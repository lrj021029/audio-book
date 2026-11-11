"""Plan-Validate-Execute conversation engine public entry point."""
from .executor import TurnExecutor

_executor = TurnExecutor()


def run(session_id, text, objects=None, user_id=None, turn_id=None):
    return _executor.run(session_id, text, objects, user_id, turn_id)


__all__ = ['run', 'TurnExecutor']
