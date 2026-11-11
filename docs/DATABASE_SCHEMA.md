# 数据字典与表结构

客服状态库由 `app/db.py::DDL` 创建，数据库名从 `LISTEN_CS_DSN` 读取，compose 默认 `listen_cs`。以下仅列客服系统创建的三张表；业务表属于 `audio_data` 服务管理范围，不由客服服务创建。

## `chat_session` — 会话主表

| 字段 | 类型 | 约束/默认值 | 作用 |
|---|---|---|---|
| `id` | `VARCHAR(36)` | 主键 | UUID 会话 ID。 |
| `user_id` | `BIGINT` | 可空（初始化后旧记录回填） | 所属业务用户 ID；接口按用户校验会话所有权。 |
| `title` | `VARCHAR(120)` | 非空，默认“新会话” | 工作台显示标题；首条用户消息写入后自动取其前 36 字符。 |
| `created_at` | `DATETIME` | 当前时间 | 创建时间。 |
| `updated_at` | `DATETIME` | 当前时间，更新时自动刷新 | 最近活动时间，用于会话列表排序。 |

索引：`idx_chat_session_user_updated(user_id, updated_at)`，用于按用户列出最近会话。

## `chat_message` — 轮次消息表

| 字段 | 类型 | 约束/默认值 | 作用 |
|---|---|---|---|
| `id` | `BIGINT` | 自增主键 | 消息行 ID，也用于稳定排序。 |
| `session_id` | `VARCHAR(36)` | 外键到 `chat_session.id` | 所属会话。 |
| `turn_id` | `VARCHAR(36)` | 非空；迁移时回填 | 关联同一轮用户输入及客服回复的轮次键。 |
| `role` | `VARCHAR(16)` | 无显式枚举约束 | 消息角色，当前写入 `user` 或 `assistant`。 |
| `content` | `MEDIUMTEXT` | 非空 | 消息文本。 |
| `metadata_json` | `JSON` | 可空 | 用户对象列表，或客服的意图、来源、状态快照与卡片数据。 |
| `created_at` | `DATETIME` | 当前时间 | 消息写入时间。 |

索引：`idx_chat_message_session(session_id,id)` 支持会话顺序读取；`idx_chat_message_turn(session_id,turn_id,id)` 支持按轮次关联。外键 `fk_chat_message_session` 指向会话。

### `turn_id` 如何绑定问答

`POST /chat` 和 `/chat/stream` 的请求可带 `turnId`。前端 `send` 会先生成 UUID 并放进请求；如果未传，`engine.run` 自行生成 UUID。`run` 用同一 `turn_id` 先后插入 `role=user` 和 `role=assistant` 两行。历史接口按 `session_id` 和 `turn_id` 聚合，因此前端即使有多轮对话，也能将一条用户输入与对应回复、卡片放在同一轮，而无需依赖相邻消息猜测。

旧数据迁移时，`initialize` 按会话和消息 ID 顺序处理空值或 `legacy-` ID：用户消息开启一个 legacy 轮次，后续客服消息关联到该轮；没有前置用户消息的消息则使用自身行 ID。

## `chat_task_state` — 当前任务快照

| 字段 | 类型 | 约束/默认值 | 作用 |
|---|---|---|---|
| `session_id` | `VARCHAR(36)` | 主键、外键 | 一会话一份状态，引用 `chat_session.id`。 |
| `current_task` | `VARCHAR(64)` | 可空 | 当前流程 ID，如 `refund_request` 或 `ticket_submit`。 |
| `slots_json` | `JSON` | 非空 | 当前任务已收集的槽位。 |
| `suspended_stack_json` | `JSON` | 非空 | 被中断任务及槽位快照的 LIFO 数组。 |
| `awaiting_resume` | `TINYINT(1)` | 非空，默认 `0` | 是否等待用户确认恢复挂起任务。 |
| `focused_object_json` | `JSON` | 可空 | 当前会话最近一次聚焦的专辑/订单等业务对象。 |
| `pending_query` | `VARCHAR(64)` | 可空 | 可选的待处理查询状态；当前接口会读取该字段。 |
| `pending_commands_json` | `JSON` | 可空 | 当前流程等待槽位时暂存的后续任务命令队列，例如多意图中的下一个 `StartFlow`。 |
| `updated_at` | `DATETIME` | 当前时间，更新时自动刷新 | 最近状态更新时刻。 |

`create_session` 同时创建初始状态（`current_task=NULL`、`slots_json={}`、`suspended_stack_json=[]`、`focused_object_json=NULL`、`pending_query=NULL`、`pending_commands_json=NULL`）。`persist_turn` 在单个 MySQL 事务里锁定任务状态行，并同时更新流程状态、待执行命令队列、写入同一 `turn_id` 下的用户与客服消息及更新会话时间。清空历史会同时清空状态、挂起栈、待执行队列和聚焦对象；删除会话会删除消息、状态和会话。

## 数据责任

`listen_cs` 保存会话、消息和对话流程状态。订单、会员、播放、专辑、退款、工单等业务事实由 `audio_data` 数据库保存，客服服务经 `audio-data` HTTP API 访问，不在 `listen_cs` 创建业务副本。
