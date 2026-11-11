"""Convert persisted dialogue turns into compact, card-aware planner context."""
import json


class HistoryBuilder:
    def __init__(self, database, max_turns=20):
        self.database = database
        self.max_turns = max_turns

    def build(self, session_id, user_id):
        rows = self.database.history(session_id, user_id)[-self.max_turns * 2:]
        lines = []
        for row in rows:
            metadata = row.get('metadata_json') or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (TypeError, ValueError):
                    metadata = {}
            if row.get('role') == 'user':
                objects = metadata.get('objects') or []
                labels = [self._object_label(item) for item in objects]
                suffix = f" [附加了业务对象: {'；'.join(labels)}]" if labels else ''
                lines.append(f"USER: {row.get('content', '')}{suffix}")
            elif row.get('role') == 'assistant':
                lines.append(f"ASSISTANT: {row.get('content', '')}")
        return '\n'.join(lines)

    @staticmethod
    def _object_label(obj):
        kind = obj.get('type', '业务对象')
        title = obj.get('title') or obj.get('orderNo') or obj.get('id') or '未命名对象'
        return f'{kind} {title}'
