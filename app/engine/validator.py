"""State-aware validation and normalization for TurnPlan JSON."""
import logging

log = logging.getLogger('listen_cs.engine.validator')

MULTIPLE_TRACKS = 'MULTIPLE_TRACKS'


class TurnPlanValidationError(ValueError):
    pass


class TurnPlanValidator:
    COMMAND_FIELDS = {
        'StartFlow': {'type', 'flow_id'},
        'SetSlots': {'type', 'slots'},
        'PauseTask': {'type'},
        'ResumeTask': {'type', 'task_id'},
        'AbandonTask': {'type'},
        'CancelTask': {'type'},
    }
    OPTIONAL_FIELDS = {'AbandonTask': {'task_id'}}

    def __init__(self, catalog):
        self.catalog = catalog

    def validate(self, plan, state):
        if not isinstance(plan, dict):
            raise TurnPlanValidationError('TurnPlan 必须是 JSON 对象')
        allowed_fields = {'track', 'task_commands', 'knowledge_intents', 'chitchat_reply'}
        extra = set(plan) - allowed_fields
        if extra:
            log.warning('忽略 TurnPlan 未定义字段: %s', ', '.join(sorted(extra)))
        plan = {
            'track': plan.get('track'),
            'task_commands': plan.get('task_commands') if plan.get('task_commands') is not None else [],
            'knowledge_intents': plan.get('knowledge_intents') if plan.get('knowledge_intents') is not None else [],
            'chitchat_reply': plan.get('chitchat_reply') if plan.get('chitchat_reply') is not None else '',
        }
        track, commands, intents, reply = (
            plan['track'], plan['task_commands'], plan['knowledge_intents'], plan['chitchat_reply'])
        if track not in {'task', 'knowledge', 'chitchat'}:
            raise TurnPlanValidationError('必须且只能选择 task、knowledge、chitchat 之一')
        if not isinstance(commands, list) or not isinstance(intents, list) or not isinstance(reply, str):
            raise TurnPlanValidationError('TurnPlan 的轨道载荷类型错误')

        if track == 'task':
            if intents or reply:
                raise TurnPlanValidationError(f'{MULTIPLE_TRACKS}: task 轨道不能混入知识意图或闲聊回复')
            normalized = self._normalize_task_commands(commands, state)
            if not normalized and not state.get('current_task'):
                # All commands were safely discarded and there is no active flow
                # to continue. Degrade to chitchat instead of a clarification.
                return {'track': 'chitchat', 'task_commands': [], 'knowledge_intents': [], 'chitchat_reply': ''}
            return {'track': 'task', 'task_commands': normalized,
                    'knowledge_intents': [], 'chitchat_reply': ''}
        if track == 'knowledge':
            if commands:
                raise TurnPlanValidationError(f'{MULTIPLE_TRACKS}: knowledge 轨道不能包含任务命令')
            if len(intents) != 1 or reply:
                raise TurnPlanValidationError('knowledge 轨道必须且只能包含一个知识意图')
            if intents[0] not in self.catalog.knowledge_intents():
                raise TurnPlanValidationError(f'未知知识意图: {intents[0]}')
            return {'track': 'knowledge', 'task_commands': [],
                    'knowledge_intents': [intents[0]], 'chitchat_reply': ''}
        if commands or intents:
            raise TurnPlanValidationError(f'{MULTIPLE_TRACKS}: chitchat 轨道不能包含任务命令或知识意图')
        return {'track': 'chitchat', 'task_commands': [], 'knowledge_intents': [], 'chitchat_reply': reply}

    def _validate_command(self, command):
        if not isinstance(command, dict) or command.get('type') not in self.COMMAND_FIELDS:
            raise TurnPlanValidationError('存在未知任务指令')
        kind = command['type']
        required = self.COMMAND_FIELDS[kind]
        allowed = required | self.OPTIONAL_FIELDS.get(kind, set())
        if not required <= set(command) <= allowed:
            raise TurnPlanValidationError(f'{kind} 指令字段不合法')
        if kind == 'StartFlow' and command['flow_id'] not in self.catalog.flows:
            raise TurnPlanValidationError(f'流程不存在: {command["flow_id"]}')
        if kind == 'SetSlots' and command.get('slots') is not None and not isinstance(command['slots'], dict):
            raise TurnPlanValidationError('SetSlots 的 slots 必须是对象')
        if kind == 'AbandonTask' and 'task_id' in command and not isinstance(command['task_id'], str):
            raise TurnPlanValidationError('AbandonTask 的 task_id 必须是文本')

    def _normalize_task_commands(self, commands, state):
        for command in commands:
            self._validate_command(command)

        normalized = []
        current_task = state.get('current_task')
        active = bool(current_task)
        initial_active = active
        queue_allowed = not initial_active
        stack = state.get('suspended_stack') or []
        pending_tasks = {item.get('task') for item in stack}

        for command in commands:
            kind = command['type']
            if kind == 'PauseTask':
                if not active:
                    log.warning('忽略 PauseTask：当前没有活动任务')
                    continue
                normalized.append(command)
                active, current_task = False, None
                queue_allowed = True
                continue

            if kind == 'StartFlow':
                flow_id = command['flow_id']
                if active and flow_id != current_task:
                    if not queue_allowed:
                        raise TurnPlanValidationError(
                            f'{MULTIPLE_TRACKS}: 当前任务 {current_task} 尚未挂起，不能同时启动 {flow_id}')
                    # Consecutive StartFlow commands form an ordered queue.
                if not active:
                    active, current_task = True, flow_id
                    queue_allowed = True
                normalized.append(command)
                continue

            if kind == 'SetSlots':
                if not active:
                    log.warning('忽略 SetSlots：当前没有活动任务')
                    continue
                raw_values = command.get('slots')
                if not isinstance(raw_values, dict):
                    log.warning('忽略 SetSlots：slots 不是对象')
                    continue
                values = {}
                for name, value in raw_values.items():
                    if name not in self.catalog.slots:
                        log.warning('忽略未定义槽位: %s', name)
                        continue
                    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                        log.warning('忽略非法槽位值: %s=%r', name, value)
                        continue
                    values[name] = value
                if values:
                    normalized.append({'type': 'SetSlots', 'slots': values})
                else:
                    log.warning('忽略 SetSlots：没有可用槽位')
                continue

            if kind == 'ResumeTask':
                if any(item['type'] in {'StartFlow', 'PauseTask', 'CancelTask', 'AbandonTask'}
                       for item in normalized):
                    raise TurnPlanValidationError(
                        f'{MULTIPLE_TRACKS}: ResumeTask 不能与启动、挂起、放弃或取消命令混用')
                if command['task_id'] not in pending_tasks:
                    log.warning('忽略 ResumeTask：任务不在挂起栈中: %s', command['task_id'])
                    continue
                normalized.append(command)
                active, current_task = True, command['task_id']
                queue_allowed = False
                continue

            if kind == 'AbandonTask':
                if any(item['type'] in {'StartFlow', 'PauseTask', 'ResumeTask', 'CancelTask'}
                       for item in normalized):
                    raise TurnPlanValidationError(
                        f'{MULTIPLE_TRACKS}: AbandonTask 不能与启动、挂起、恢复或取消命令混用')
                task_id = command.get('task_id')
                if not stack:
                    log.warning('忽略 AbandonTask：挂起栈为空')
                    continue
                if task_id and task_id not in pending_tasks:
                    log.warning('忽略 AbandonTask：任务不在挂起栈中: %s', task_id)
                    continue
                normalized.append(command)
                continue

            if kind == 'CancelTask':
                if any(item['type'] in {'StartFlow', 'PauseTask', 'ResumeTask', 'AbandonTask'}
                       for item in normalized):
                    raise TurnPlanValidationError(
                        f'{MULTIPLE_TRACKS}: CancelTask 不能与其他任务命令混用')
                normalized.append(command)
                active, current_task = False, None
                queue_allowed = True

        kinds = [item['type'] for item in normalized]
        if kinds.count('ResumeTask') > 1 or kinds.count('AbandonTask') > 1 or kinds.count('CancelTask') > 1:
            raise TurnPlanValidationError(f'{MULTIPLE_TRACKS}: 同类控制命令不能重复')
        if 'PauseTask' in kinds and 'StartFlow' not in kinds:
            raise TurnPlanValidationError(f'{MULTIPLE_TRACKS}: 挂起任务后必须启动明确的新流程')
        return normalized
