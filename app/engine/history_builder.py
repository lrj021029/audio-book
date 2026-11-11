"""Convert persisted dialogue turns into compact, card-aware planner context."""
import json

CARD_LABELS = {'order': '订单', 'album': '专辑', 'playback': '播放记录'}


def _first(obj, *keys):
    for key in keys:
        value = obj.get(key)
        if value not in (None, '', []):
            return value
    return None


def object_context(obj):
    """Return the small set of real business fields a planner needs to reason."""
    if not isinstance(obj, dict):
        return {}
    kind = str(obj.get('type') or 'unknown')
    if kind == 'order':
        items = obj.get('items') or []
        item_names = [
            item.get('itemName') or item.get('name')
            for item in items
            if isinstance(item, dict)
        ]
        core = {
            'order_id': _first(obj, 'orderNo', 'orderId', 'id'),
            'status': _first(obj, 'orderStatus', 'status'),
            'amount': _first(obj, 'payableAmount', 'amount'),
            'currency': _first(obj, 'currencyCode', 'currency'),
            'title': _first(obj, 'title'),
        }
        if item_names:
            core['item_names'] = [name for name in item_names if name][:3]
    elif kind == 'album':
        core = {
            'album_id': _first(obj, 'albumId', 'id'),
            'title': _first(obj, 'title', 'albumTitle'),
            'rating': _first(obj, 'rating', 'ratingScore'),
            'track_count': _first(obj, 'trackCount'),
            'author': _first(obj, 'author'),
            'narrator': _first(obj, 'narrator'),
        }
        summary = _first(obj, 'summary')
        if summary:
            core['summary'] = str(summary)[:120]
    elif kind == 'playback':
        core = {
            'album_id': _first(obj, 'albumId', 'id'),
            'title': _first(obj, 'title', 'albumTitle'),
            'track': _first(obj, 'trackTitle', 'track'),
            'position_seconds': _first(obj, 'positionSeconds'),
            'duration_seconds': _first(obj, 'durationSeconds'),
            'last_played_at': _first(obj, 'lastPlayedAt'),
        }
    else:
        core = {
            'type': kind,
            'id': _first(obj, 'id'),
            'title': _first(obj, 'title'),
            'subtitle': _first(obj, 'subtitle'),
        }
    return {key: value for key, value in core.items() if value is not None}


def render_object_context(obj):
    return json.dumps(object_context(obj), ensure_ascii=False, separators=(', ', ': '))


def render_objects_context(objects):
    return json.dumps([object_context(obj) for obj in objects or []], ensure_ascii=False)


def render_user_message(text, objects=None):
    """Render a user turn with attached business-card fields expanded for the planner."""
    parts = []
    text = (text or '').strip()
    if text:
        parts.append(text)
    for obj in objects or []:
        kind = str(obj.get('type') or 'unknown')
        label = CARD_LABELS.get(kind, '业务')
        parts.append(f'[用户发送了{label}卡片: {render_object_context(obj)}]')
    return 'USER: ' + ' '.join(parts)


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
                lines.append(render_user_message(row.get('content', ''), objects))
            elif row.get('role') == 'assistant':
                lines.append(f"ASSISTANT: {row.get('content', '')}")
        return '\n'.join(lines)
