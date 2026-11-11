"""Strict structural and state-aware validation for TurnPlan JSON."""


class TurnPlanValidationError(ValueError):
    pass


class TurnPlanValidator:
    COMMAND_FIELDS = {
        'StartFlow': {'type', 'flow_id'}, 'SetSlots': {'type', 'slots'},
        'PauseTask': {'type'}, 'ResumeTask': {'type', 'task_id'}, 'CancelTask': {'type'},
    }

    def __init__(self, catalog): self.catalog = catalog

    def validate(self, plan, state):
        if not isinstance(plan, dict): raise TurnPlanValidationError('TurnPlan 必须是 JSON 对象')
        if set(plan) != {'track', 'task_commands', 'knowledge_intents', 'chitchat_reply'}:
            raise TurnPlanValidationError('TurnPlan 字段不完整或包含未定义字段')
        track, commands, intents, reply = (plan['track'], plan['task_commands'], plan['knowledge_intents'], plan['chitchat_reply'])
        if track not in {'task', 'knowledge', 'chitchat'}:
            raise TurnPlanValidationError('必须且只能选择 task、knowledge、chitchat 之一')
        if not isinstance(commands, list) or not isinstance(intents, list) or not isinstance(reply, str):
            raise TurnPlanValidationError('TurnPlan 的轨道载荷类型错误')
        if track == 'task':
            if not commands or intents or reply: raise TurnPlanValidationError('task 轨道只能包含 task_commands')
            for command in commands: self._validate_command(command, state)
            kinds = [command['type'] for command in commands]
            if kinds.count('PauseTask') > 1 or kinds.count('StartFlow') > 1 or kinds.count('ResumeTask') > 1:
                raise TurnPlanValidationError('任务指令重复，不能安全执行')
            if 'PauseTask' in kinds and (kinds[0] != 'PauseTask' or 'StartFlow' not in kinds[1:]):
                raise TurnPlanValidationError('挂起任务后必须启动明确的新流程')
            if 'ResumeTask' in kinds and (len(kinds) != 1 or kinds[0] != 'ResumeTask'):
                raise TurnPlanValidationError('恢复任务不能与其他任务指令混用')
            if 'CancelTask' in kinds and (len(kinds) != 1 or kinds[0] != 'CancelTask'):
                raise TurnPlanValidationError('取消任务不能与其他任务指令混用')
        elif track == 'knowledge':
            if commands or len(intents) != 1 or reply: raise TurnPlanValidationError('knowledge 轨道必须且只能包含一个知识意图')
            if intents[0] not in self.catalog.knowledge_intents(): raise TurnPlanValidationError(f'未知知识意图: {intents[0]}')
        else:
            if commands or intents or not reply.strip(): raise TurnPlanValidationError('chitchat 轨道必须包含自然语言回复且不得包含业务命令')
        return plan

    def _validate_command(self, command, state):
        if not isinstance(command, dict) or command.get('type') not in self.COMMAND_FIELDS:
            raise TurnPlanValidationError('存在未知任务指令')
        kind = command['type']
        if set(command) != self.COMMAND_FIELDS[kind]: raise TurnPlanValidationError(f'{kind} 指令字段不合法')
        if kind == 'StartFlow' and command['flow_id'] not in self.catalog.flows:
            raise TurnPlanValidationError(f'流程不存在: {command["flow_id"]}')
        if kind == 'SetSlots':
            values = command['slots']
            if not isinstance(values, dict) or not values: raise TurnPlanValidationError('SetSlots 必须包含非空槽位对象')
            for name, value in values.items():
                if name not in self.catalog.slots: raise TurnPlanValidationError(f'槽位未定义: {name}')
                if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                    raise TurnPlanValidationError(f'槽位 {name} 的值必须为文本或数字')
        if kind == 'ResumeTask':
            pending = {item.get('task') for item in state.get('suspended_stack', [])}
            if command['task_id'] not in pending: raise TurnPlanValidationError('ResumeTask 指向的任务不在挂起栈中')
        if kind == 'PauseTask' and not state.get('current_task'):
            raise TurnPlanValidationError('没有活动任务可挂起')
