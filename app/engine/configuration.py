"""Load and validate the YAML flow catalog used by planning and execution."""
from pathlib import Path
import yaml


CONFIG_PATH = Path(__file__).parent.parent / 'flow_config' / 'user_flows.yml'


class FlowCatalog:
    def __init__(self, path=CONFIG_PATH):
        self.path = Path(path)
        self.reload()

    def reload(self):
        self.data = yaml.safe_load(self.path.read_text(encoding='utf-8'))
        self.slots = self.data['slots']
        self.flows = self.data['flows']
        self._validate_catalog()

    def _validate_catalog(self):
        for flow_id, flow in self.flows.items():
            ids = [step['id'] for step in flow['steps']]
            if len(ids) != len(set(ids)) or 'start' not in ids:
                raise ValueError(f'流程 {flow_id} 的 step id 重复或缺少 start')
            known = set(ids)
            for step in flow['steps']:
                if step['type'] == 'collect' and step['slot_name'] not in self.slots:
                    raise ValueError(f'流程 {flow_id} 使用未定义槽位 {step["slot_name"]}')
                target = step.get('next')
                targets = target.values() if isinstance(target, dict) else ([target] if isinstance(target, str) else [])
                if any(item not in known for item in targets):
                    raise ValueError(f'流程 {flow_id} 的步骤 {step["id"]} 指向不存在的步骤')
                if step['type'] == 'action' and not step.get('action'):
                    raise ValueError(f'流程 {flow_id} 的 action 步骤缺少 action 名称')

    def flow_summaries(self):
        return {key: {'name': item['name'], 'description': item['description']} for key, item in self.flows.items()}

    def knowledge_intents(self):
        return ['book_query', 'membership_query', 'faq']

    def step(self, flow_id, step_id):
        return next(step for step in self.flows[flow_id]['steps'] if step['id'] == step_id)

    def first_step(self, flow_id):
        return self.step(flow_id, 'start')
