import json
import pymysql
from pymysql.cursors import DictCursor
from .config import AUDIO_DATA_USER_ID, mysql_config

DDL = [
    """CREATE TABLE IF NOT EXISTS chat_session (
        id VARCHAR(36) PRIMARY KEY,
        user_id BIGINT NULL,
        title VARCHAR(120) NOT NULL DEFAULT '新会话',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        KEY idx_chat_session_user_updated(user_id, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS chat_message (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        session_id VARCHAR(36) NOT NULL,
        turn_id VARCHAR(36) NULL,
        role VARCHAR(16) NOT NULL,
        content MEDIUMTEXT NOT NULL,
        metadata_json JSON NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_chat_message_session(session_id,id),
        CONSTRAINT fk_chat_message_session FOREIGN KEY(session_id) REFERENCES chat_session(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS chat_task_state (
        session_id VARCHAR(36) PRIMARY KEY,
        current_task VARCHAR(64) NULL,
        slots_json JSON NOT NULL,
        suspended_stack_json JSON NOT NULL,
        awaiting_resume TINYINT(1) NOT NULL DEFAULT 0,
        focused_object_json JSON NULL,
        pending_query VARCHAR(64) NULL,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_task_state_session FOREIGN KEY(session_id) REFERENCES chat_session(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


def connect():
    return pymysql.connect(**mysql_config(), cursorclass=DictCursor)


def initialize():
    cfg = mysql_config()
    database = cfg.pop('database')
    c = pymysql.connect(**cfg, cursorclass=DictCursor)
    try:
        with c.cursor() as cur:
            cur.execute(f'CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
        c.select_db(database)
        with c.cursor() as cur:
            for sql in DDL:
                cur.execute(sql)
            _ensure_column(cur, 'chat_task_state', 'awaiting_resume', 'TINYINT(1) NOT NULL DEFAULT 0')
            _ensure_column(cur, 'chat_task_state', 'focused_object_json', 'JSON NULL')
            _ensure_column(cur, 'chat_task_state', 'pending_query', 'VARCHAR(64) NULL')
            _ensure_column(cur, 'chat_session', 'user_id', 'BIGINT NULL')
            _ensure_column(cur, 'chat_session', 'title', "VARCHAR(120) NOT NULL DEFAULT '新会话'")
            _ensure_column(cur, 'chat_message', 'turn_id', 'VARCHAR(36) NULL')
            cur.execute('SELECT id,session_id,role,turn_id FROM chat_message ORDER BY session_id,id')
            current_session = None
            current_turn = None
            for row in cur.fetchall():
                if row['session_id'] != current_session:
                    current_session = row['session_id']
                    current_turn = None
                if row['turn_id'] is None or str(row['turn_id']).startswith('legacy-'):
                    if row['role'] == 'user':
                        current_turn = row['id']
                    turn_key = current_turn if current_turn is not None else row['id']
                    new_turn_id = f'legacy-{turn_key}'
                    if row['turn_id'] != new_turn_id:
                        cur.execute('UPDATE chat_message SET turn_id=%s WHERE id=%s', (new_turn_id, row['id']))
            cur.execute("SELECT IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='chat_message' AND COLUMN_NAME='turn_id'")
            if cur.fetchone()['IS_NULLABLE'] == 'YES':
                cur.execute('ALTER TABLE chat_message MODIFY turn_id VARCHAR(36) NOT NULL')
            cur.execute("SELECT COUNT(*) AS n FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='chat_message' AND INDEX_NAME='idx_chat_message_turn'")
            if not cur.fetchone()['n']:
                cur.execute('CREATE INDEX idx_chat_message_turn ON chat_message(session_id,turn_id,id)')
            cur.execute('UPDATE chat_session SET user_id=%s WHERE user_id IS NULL', (int(AUDIO_DATA_USER_ID),))
    finally:
        c.close()


def _ensure_column(cur, table, column, definition):
    cur.execute(
        'SELECT COUNT(*) AS n FROM information_schema.COLUMNS '
        'WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s',
        (table, column),
    )
    if not cur.fetchone()['n']:
        cur.execute(f'ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}')


def create_session(session_id, user_id, title='新会话'):
    c = connect()
    try:
        with c.cursor() as cur:
            cur.execute('INSERT INTO chat_session(id,user_id,title) VALUES(%s,%s,%s)', (session_id, user_id, title))
            cur.execute(
                'INSERT INTO chat_task_state(session_id,current_task,slots_json,suspended_stack_json,awaiting_resume,focused_object_json,pending_query) '
                'VALUES(%s,NULL,%s,%s,0,NULL,NULL)',
                (session_id, '{}', '[]'),
            )
    finally:
        c.close()


def list_sessions(user_id):
    c = connect()
    try:
        with c.cursor() as cur:
            cur.execute(
                """SELECT s.id,s.title,s.user_id,s.created_at,s.updated_at,
                    (SELECT m.content FROM chat_message m WHERE m.session_id=s.id ORDER BY m.id DESC LIMIT 1) AS preview
                    FROM chat_session s WHERE s.user_id=%s ORDER BY s.updated_at DESC,s.created_at DESC""",
                (user_id,),
            )
            return cur.fetchall()
    finally:
        c.close()


def get_session(session_id, user_id):
    c = connect()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT id,title,user_id FROM chat_session WHERE id=%s AND user_id=%s', (session_id, user_id))
            return cur.fetchone()
    finally:
        c.close()


def rename_session(session_id, user_id, title):
    c = connect()
    try:
        with c.cursor() as cur:
            return cur.execute('UPDATE chat_session SET title=%s WHERE id=%s AND user_id=%s', (title, session_id, user_id)) > 0
    finally:
        c.close()


def delete_session(session_id, user_id):
    c = connect()
    try:
        c.begin()
        with c.cursor() as cur:
            cur.execute('DELETE m FROM chat_message m JOIN chat_session s ON s.id=m.session_id WHERE s.id=%s AND s.user_id=%s', (session_id, user_id))
            cur.execute('DELETE st FROM chat_task_state st JOIN chat_session s ON s.id=st.session_id WHERE s.id=%s AND s.user_id=%s', (session_id, user_id))
            deleted = cur.execute('DELETE FROM chat_session WHERE id=%s AND user_id=%s', (session_id, user_id))
        c.commit()
        return deleted > 0
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def clear_history(session_id, user_id):
    c = connect()
    try:
        c.begin()
        with c.cursor() as cur:
            cur.execute('DELETE m FROM chat_message m JOIN chat_session s ON s.id=m.session_id WHERE s.id=%s AND s.user_id=%s', (session_id, user_id))
            cur.execute(
                """UPDATE chat_task_state st JOIN chat_session s ON s.id=st.session_id
                   SET st.current_task=NULL,st.slots_json='{}',st.suspended_stack_json='[]',st.awaiting_resume=0,st.focused_object_json=NULL,st.pending_query=NULL
                   WHERE s.id=%s AND s.user_id=%s""",
                (session_id, user_id),
            )
            cur.execute('UPDATE chat_session SET title=\'新会话\' WHERE id=%s AND user_id=%s', (session_id, user_id))
            cur.execute('SELECT ROW_COUNT() AS n')
            exists = cur.fetchone()['n'] > 0 or get_session(session_id, user_id) is not None
        c.commit()
        return exists
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def add_message(session_id, role, content, metadata=None, turn_id=None):
    c = connect()
    try:
        with c.cursor() as cur:
            cur.execute(
                'INSERT INTO chat_message(session_id,turn_id,role,content,metadata_json) VALUES(%s,%s,%s,%s,%s)',
                (session_id, turn_id, role, content, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            if role == 'user':
                cur.execute(
                    "UPDATE chat_session SET title=IF(title='新会话',LEFT(%s,36),title),updated_at=NOW() WHERE id=%s",
                    (content.strip() or '新会话', session_id),
                )
            else:
                cur.execute('UPDATE chat_session SET updated_at=NOW() WHERE id=%s', (session_id,))
    finally:
        c.close()


def history(session_id, user_id):
    c = connect()
    try:
        with c.cursor() as cur:
            cur.execute(
                'SELECT m.id,m.turn_id,m.role,m.content,m.metadata_json,m.created_at FROM chat_message m '
                'JOIN chat_session s ON s.id=m.session_id WHERE m.session_id=%s AND s.user_id=%s ORDER BY m.id',
                (session_id, user_id),
            )
            return cur.fetchall()
    finally:
        c.close()


def get_state(session_id, user_id):
    c = connect()
    try:
        with c.cursor() as cur:
            cur.execute(
                'SELECT st.current_task,st.slots_json,st.suspended_stack_json,st.awaiting_resume,st.focused_object_json,st.pending_query '
                'FROM chat_task_state st JOIN chat_session s ON s.id=st.session_id '
                'WHERE st.session_id=%s AND s.user_id=%s',
                (session_id, user_id),
            )
            return cur.fetchone()
    finally:
        c.close()


def persist_turn(session_id, turn_id, user_text, user_metadata, assistant_text, assistant_metadata,
                 task, slots, stack, awaiting_resume, focused_object, pending_query=None):
    """Persist both messages and the resulting dialogue state as one transaction."""
    c = connect()
    try:
        c.begin()
        with c.cursor() as cur:
            cur.execute('SELECT session_id FROM chat_task_state WHERE session_id=%s FOR UPDATE', (session_id,))
            if cur.fetchone() is None:
                raise RuntimeError('会话任务状态不存在，无法提交本轮对话')
            cur.execute(
                'UPDATE chat_task_state SET current_task=%s,slots_json=%s,suspended_stack_json=%s,'
                'awaiting_resume=%s,focused_object_json=%s,pending_query=%s WHERE session_id=%s',
                (task, json.dumps(slots, ensure_ascii=False), json.dumps(stack, ensure_ascii=False),
                 int(awaiting_resume), json.dumps(focused_object, ensure_ascii=False) if focused_object else None,
                 pending_query, session_id),
            )
            cur.execute(
                'INSERT INTO chat_message(session_id,turn_id,role,content,metadata_json) VALUES(%s,%s,%s,%s,%s)',
                (session_id, turn_id, 'user', user_text, json.dumps(user_metadata or {}, ensure_ascii=False)),
            )
            cur.execute(
                'INSERT INTO chat_message(session_id,turn_id,role,content,metadata_json) VALUES(%s,%s,%s,%s,%s)',
                (session_id, turn_id, 'assistant', assistant_text, json.dumps(assistant_metadata or {}, ensure_ascii=False)),
            )
            cur.execute(
                "UPDATE chat_session SET title=IF(title='新会话',LEFT(%s,36),title),updated_at=NOW() WHERE id=%s",
                (user_text.strip() or '新会话', session_id),
            )
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def put_state(session_id, task, slots, stack, awaiting_resume=False, focused_object=None):
    c = connect()
    try:
        with c.cursor() as cur:
            cur.execute(
                'UPDATE chat_task_state SET current_task=%s,slots_json=%s,suspended_stack_json=%s,awaiting_resume=%s,focused_object_json=%s WHERE session_id=%s',
                (task, json.dumps(slots, ensure_ascii=False), json.dumps(stack, ensure_ascii=False), int(awaiting_resume), json.dumps(focused_object, ensure_ascii=False) if focused_object else None, session_id),
            )
    finally:
        c.close()
