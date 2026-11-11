# 核心代码导读

## 关键文件

| 文件 | 职责 |
|---|---|
| [`app/main.py`](../app/main.py) | FastAPI 路由、用户/会话归属校验、同步聊天与 SSE 响应。 |
| [`app/engine/__init__.py`](../app/engine/__init__.py) | 对外暴露 `run`，转交给 `TurnExecutor`。 |
| [`app/engine/executor.py`](../app/engine/executor.py) | 轮次编排、计划校验、任务状态、YAML 流程执行、业务 Action 和持久化。 |
| [`app/engine/planner.py`](../app/engine/planner.py) | 受限 LLM 路由计划及确定性规则回退。 |
| [`app/engine/validator.py`](../app/engine/validator.py) | 校验轨道、命令、流程与槽位。 |
| [`app/engine/configuration.py`](../app/engine/configuration.py) | 加载和校验流程目录。 |
| [`app/flow_config/user_flows.yml`](../app/flow_config/user_flows.yml) | 任务流程、步骤、提示语和槽位声明。 |
| [`app/db.py`](../app/db.py) | 客服表初始化/迁移、状态读取及事务提交。 |
| [`app/audio_client.py`](../app/audio_client.py) | 调用 audio-data HTTP API。 |

业务查询与写操作在 `app/engine/business.py`，FAQ 检索在 `app/retrieval.py`，可选 LLM 能力在 `app/llm.py`。

## 输入“我要退款”的调用路径

1. `frontend/src/main.jsx::send` 创建 `turnId`，向同源 `/api/chat/stream` 发送 `{sessionId,message,objects,turnId}`；Nginx 代理到客服服务。
2. `app/main.py::chat_stream` 校验 `X-User-Id` 和会话所有权，再在 SSE 生成器内调用 `engine.run`。`POST /chat` 也调用同一个入口。
3. `app/engine/__init__.py::run` 转交 `TurnExecutor.run`。执行器读取 `chat_task_state`，规范化消息并在有附件时通过业务 API解析订单/专辑对象。
4. `TurnPlanner.plan` 根据最近对话、状态、对象及流程摘要生成计划。LLM 未配置或调用失败时使用规则回退；随后 `TurnPlanValidator` 校验计划。槽位锁定逻辑保证当前流程缺少订单号时，普通输入会作为订单号候选解析，而不是任由模型改变流程。
5. 对“我要退款”，计划会启动 `refund_request`。`FlowCatalog` 从 `app/flow_config/user_flows.yml` 驱动步骤；由于订单号缺失，执行器返回流程中 `ask_order_id` 对应的提示，不会调用退款写接口。
6. 执行器调用 `db.persist_turn`，在一个数据库事务里保存任务状态、用户消息和客服回复，两条消息共享 `turn_id`。事务提交后返回完整 JSON 结果。
7. `/chat/stream` 随后将完整回复按每 20 个 Python 字符切成 `token` 事件，最后发送包含完整结果的 `done` 事件。前端结束后重新读取历史、会话、状态和业务上下文。

## 退款后续如何执行

用户提供订单号、退款原因和全额/部分类型后，执行器按 YAML 顺序填槽。部分退款还需要 `refund_amount`。槽位齐全后，YAML 的 `action_submit_refund` 映射到 `TurnExecutor._action_submit_refund`，再由 `app/engine/business.py::execute` 及 `AudioDataClient` 调用 audio-data：

1. 在当前用户订单中匹配订单并读取详情和支付记录。
2. 根据业务接口要求组装退款请求，包括 `paymentId`、退款原因及订单项金额明细。
3. 调用 `POST /api/v1/refunds`；订单归属、支付状态及退款记录由 audio-data 执行和持久化。
4. 将业务结果作为流程回复，并与客服任务状态和本轮消息一同提交到 `listen_cs`。

客服库事务不能和 audio-data 的写入组成分布式事务。LLM 只协助生成路由计划或表达回复，不计算并执行退款副作用。

## 查询、知识和闲聊路径

- 订单及播放查询由 YAML 流程调用注册的 Python Action；专辑、会员问答等通过 `business.answer` 查询业务 API，按需用 `make_cards` 组装卡片。
- FAQ 由 `retrieval.retrieve` 先尝试 SAG CLI；CLI 不存在、失败、超时或无结果时回退到 `knowledge/` Markdown 的本地检索。命中原文可由 `llm.rag_reply` 润色，并保留来源。
- 闲聊由计划进入 `chitchat` 轨道，尝试可选 LLM 回复；不可用时使用上下文规则回退，不调用业务 API。
- 业务对象先由 `resolve_business_objects` 尽力补全详情。当前聚焦对象保存在任务状态中，也写入用户消息元数据；历史接口将它们作为 `user.objects` 和 `user.cards` 返回。

## 阅读时建议使用的调用索引

```text
main.py: chat / chat_stream / get_history / get_state
  └─ engine/__init__.py: run
       └─ executor.py: TurnExecutor.run
            ├─ planner.py: TurnPlanner.plan
            ├─ validator.py: TurnPlanValidator.validate
            ├─ configuration.py: FlowCatalog → flow_config/user_flows.yml
            ├─ business.py: answer / execute / make_cards / resolve_business_objects
            │    ├─ audio_client.py: AudioDataClient.get / post
            │    └─ retrieval.py → llm.py: rag_reply
            └─ db.py: get_state / persist_turn
```

`chat_stream` 当前先完整执行 `TurnExecutor.run`，之后才逐块发送文本，所以它不提供业务处理期间的实时 token 生成。
