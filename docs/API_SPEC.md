# API 接口契约

客服 API 默认监听 `8001`；前端经 Nginx 同源 `/api` 代理访问。JSON 接口使用 UTF-8。会话和用户范围接口接受请求头 `X-User-Id`，缺省取 `AUDIO_DATA_USER_ID`（默认 `10001`）；无效用户号返回 400，用户无权访问或会话不存在时通常返回 404。以下示例中的 UUID 均为示意值。

## `POST /chat`

同步处理一轮对话。

请求：

```json
{
  "sessionId": "3789c710-1111-4111-8111-111111111111",
  "message": "我要退款",
  "objects": [],
  "turnId": "turn-20261111-001"
}
```

`objects` 可为空。对象包含 `type`、`id`、`title` 等业务卡片信息；订单对象还可含 `orderNo/orderId`。最新对象被写入会话 `focused_object`。后端会把卡片核心字段展开到 Planner 上下文和历史消息中，例如订单的 `order_id/status/amount`、专辑的 `title/rating/track_count`。`turnId` 可省略。

响应示例（首次进入退款流程）：

```json
{
  "turnId": "turn-20261111-001",
  "message": "请提供订单号。",
  "state": {
    "current_task": "refund_request",
    "slots": {},
    "suspended_stack": [],
    "awaiting_resume": false,
    "pending_commands": []
  },
  "intent": {"track": "slot_prompt"},
  "source": null,
  "cards": []
}
```

`intent.track` 当前记录执行分支（例如 `slot_prompt`、`task_complete`、`knowledge`、`chitchat` 或 `clarify`），不返回底层分类器的置信度字段。查询回复会填充 `source`，需要展示的专辑/播放卡片放入 `cards`。

## `POST /chat/stream`

请求 JSON 与 `/chat` 相同，响应 `Content-Type: text/event-stream`。当前实现先完整运行一轮业务逻辑，再将最终消息按每 20 个 Python 字符切块发送；这是分块传输，不代表模型逐 token 生成。

`token` 事件：

```text
event: token
data: {"turnId":"turn-20261111-001","text":"请提供订单号。"}
```

多个 `token` 的 `text` 按顺序拼接。`done` 事件返回与同步接口相同的完整结果：

```text
event: done
data: {"turnId":"turn-20261111-001","message":"请提供订单号。","state":{"current_task":"refund_request","slots":{},"suspended_stack":[],"awaiting_resume":false,"pending_commands":[],"pending_query":null,"focused_object":null},"intent":{"track":"slot_prompt"},"source":null,"cards":[]}
```

## `GET /session/{session_id}/history`

读取按轮次聚合的历史。响应：

```json
{
  "sessionId": "3789c710-1111-4111-8111-111111111111",
  "turns": [
    {
      "turn_id": "turn-20261111-001",
      "user": {"text": "我要退款", "timestamp": "2026-11-11T09:30:00", "objects": []},
      "assistant": [
        {"type": "text", "text": "请提供订单号。", "timestamp": "2026-11-11T09:30:00", "intent": {"track": "slot_prompt", "planner": "plan_validate_execute"}, "source": null}
      ],
      "intent": {"track": "slot_prompt", "planner": "plan_validate_execute"}
    }
  ]
}
```

若客服消息元数据包含卡片，`assistant` 数组还会有 `{ "type": "card", "card": { ... } }` 块。用户消息附件从 `user.objects` 和 `user.cards` 返回，前端据此重绘附件卡片。

## `GET /session/{session_id}/state`

读取流程状态：

```json
{
  "sessionId": "3789c710-1111-4111-8111-111111111111",
  "userId": 10001,
  "current_task": "refund_request",
  "slots": {"order_id": "ORD000000000001"},
  "suspended_stack": [],
  "awaiting_resume": false,
  "pending_commands": [],
  "pending_query": null,
  "focused_object": {"type":"album","id":123,"title":"人生长恨水长东"}
}
```

没有已聚焦对象时 `focused_object` 为 `null`。`pending_query` 为可空流程状态字段。`pending_commands` 保存因当前流程等待槽位而暂存的后续任务命令，例如多意图排队中的下一个 `StartFlow`；没有待执行命令时为空数组。每次附加新对象会更新当前会话的聚焦对象；知识回答不会清空聚焦对象。

## 会话与目录接口

| 方法与路径 | 请求 | 成功响应摘要 |
|---|---|---|
| `POST /session` | 无 body | `{"sessionId":"..."}`，新建会话和空任务状态。 |
| `GET /sessions` | 无 | `{"sessions":[{"id":"...","title":"...","preview":"...","created_at":"...","updated_at":"..."}]}`。 |
| `PATCH /session/{id}` | `{"title":"售后咨询"}` | `{"ok":true,"title":"售后咨询"}`。空标题返回 400。 |
| `DELETE /session/{id}` | 无 | `{"ok":true}`，删除会话及从属数据。 |
| `DELETE /session/{id}/history` | 无 | `{"ok":true}`，清空消息并重置状态。 |
| `GET /catalog/orders` | 无 | `{"items":[...]}`，当前用户订单。 |
| `GET /catalog/albums?q=...` | 可选 `q` | `{"items":[...]}`，专辑目录或搜索结果。 |
| `GET /catalog/context` | 无 | `user/orders/bookshelf/progress/albums` 业务上下文；单项服务失败时该项可返回 `{"error":"..."}`。 |
| `GET /health` | 无 | `{"status":"ok"}`。 |
| `GET /meta` | 无 | `{"userId":10001}`。 |

错误响应由 FastAPI 产生，例如 `{ "detail": "会话不存在" }`。业务 API 失败时，对话引擎通常将其转成面向客服用户的文字；详细异常记录在后端日志中。
