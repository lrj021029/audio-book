# 核心代码导读

## 关键文件

| 文件 | 职责 |
|---|---|
| [`app/main.py`](../app/main.py) | FastAPI 应用、请求模型、会话/历史/状态路由、同步聊天与 SSE 响应。 |
| [`app/engine.py`](../app/engine.py) | 对话控制器：意图路由、任务槽位收集、挂起栈、查询、业务 Action 调用及消息持久化。 |
| [`app/db.py`](../app/db.py) | 建表和迁移、会话/消息/任务状态的 MySQL 访问。 |

辅助关键模块：`app/intents.py` 负责规则路由；`app/llm.py::plan_turn` 生成并校验受限路由计划，`chitchat_reply` 负责闲聊生成；`app/audio_client.py` 封装 audio-data HTTP API；`app/retrieval.py` 负责 FAQ 检索。

## 输入“我要退款”的调用路径

1. 前端 `frontend/src/main.jsx::send` 创建 `turnId`，将 `{sessionId,message,objects,turnId}` 发到 `/api/chat/stream`。Nginx 把请求代理到客服 FastAPI。
2. `app/main.py::chat_stream` 校验用户和会话 (`owned`)，再构造 SSE 生成器。同步接口 `POST /chat` 则进入 `chat`；两者最后都会调用同一个 `engine.run`。
3. `app/engine.py::run` 清理文本、生成/接收 `turn_id`，先调用 `db.add_message(..., role='user', ...)` 持久化用户消息。
4. `classify_intent` 在 `app/intents.py` 匹配“退款”；`plan_turn` 可生成受限轨道计划，校验失败则回退规则结果。`run` 读取 `db.get_state`，发现当前无进行中任务后进入 Task Track。
5. `FLOW['refund_request']` 指定所需槽位。`extract_slot` 尝试从当前文本和附加订单对象取值；“我要退款”没有订单号，因此 `collect` 返回首个缺失槽位的提示（请提供订单号）。
6. 本轮还不会调用退款写接口，因为槽位不齐全。`db.put_state` 保存 `current_task=refund_request` 和已有 `slots`，再以同一 `turn_id` 将客服回复写入 `chat_message`。
7. `run` 返回含 `message/state/intent/source/cards` 的结果。SSE 实现将消息按 20 字符切块发为一个或多个 `token` 事件，最后发完整 `done` 事件。前端逐步显示文本，并在结束后重新读取历史、会话、状态和业务上下文。

## 退款流程后续如何执行

用户之后提供订单号、原因、全额/部分类型，`extract_slot` 依当前缺失项填槽。部分退款还要求金额。必填项齐全后，`advance_task` 调用 `execute('refund_request', slots, user_id)`：

1. `AudioDataClient.get` 通过 `GET /api/v1/orders` 在当前用户订单中匹配订单，再读订单详情。
2. 校验订单归属和成功支付记录，组装退款明细。
3. `AudioDataClient.post` 调用 `POST /api/v1/refunds`，由 audio-data 执行业务校验和退款记录写入。
4. 将退款单号与状态组成回复，清理已完成任务状态（若存在挂起任务则恢复它），把最终状态和回复一起写回客服库。

这里 Python 的 `execute` 是实际 Action；意图分类只决定走哪条分支。LLM 不决定订单、退款金额或写接口参数。

## 查询、知识和闲聊路径

- “查订单/会员/播放记录/专辑”由规则分类到 Query，再由 `answer` 调用相应 audio-data API；专辑和播放查询还可能由 `make_cards` 组装结果卡片。
- FAQ 先经 `retrieve` 调 SAG 或本地 Markdown 回退检索，再由 `rag_reply` 可选改写命中原文。原文与来源也会保留在回复里。
- 闲聊由受约束的 `plan_turn` 路由到 Chitchat，再调用 LLM 生成自然语言回复；不可用时使用情境化规则回退，不访问业务 API。“我非常开心”由规则识别为情绪闲聊，未知输入使用简短澄清。
- 引擎在意图规划前规范化附加对象并更新 focused object。没有明确动作时按对象类型/标题确认收到；历史 API 返回 `user.cards`，React 在用户消息中渲染附件卡片。订单对象还可填退款/工单订单号槽位。

## 阅读时建议使用的函数索引

```text
main.py: chat / chat_stream / get_history / get_state
  └─ engine.py: run
       ├─ intents.py: classify_intent / order_no
       ├─ engine.py: extract_slot / collect / advance_task / execute
       ├─ engine.py: answer / make_cards
       │    ├─ audio_client.py: AudioDataClient.get / post
       │    └─ retrieval.py: retrieve → llm.py: rag_reply
       └─ db.py: add_message / get_state / put_state
```

注意 `chat_stream` 当前先同步完成 `run`，随后才生成分块事件；所以它提供流式传输体验，但不让后台业务执行与 token 输出并行。
