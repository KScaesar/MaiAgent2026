from __future__ import annotations

import json
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.exceptions import StopConsumer
from channels.generic.http import AsyncHttpConsumer

from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.realtime.tickets import consume_ticket


def group_name_for(conversation_id) -> str:
    return f"conv_{conversation_id}"


def _serialize_message_event(message: Message) -> dict:
    payload = {"message_id": str(message.id), "status": message.status}
    if message.status == Message.Status.COMPLETED:
        payload["content"] = message.content
    elif message.status == Message.Status.FAILED:
        payload["error_message"] = message.error_message
    return payload


def build_initial_snapshot(conversation_id) -> dict | None:
    message = (
        Message.objects.filter(
            conversation_id=conversation_id,
            sender_type=Message.SenderType.AI,
        )
        .order_by("-created", "-id")
        .first()
    )
    if message is None:
        return None
    return _serialize_message_event(message)


class ConversationEventsConsumer(AsyncHttpConsumer):
    """GET /sse/conversations/{conversation_id}/?ticket=...。

    連線順序固定：驗證 ticket -> group_add -> 查 DB 送初始快照 -> 進入等待迴圈，
    避免漏接。

    NOTE: `AsyncHttpConsumer.http_request` 預設在 `handle()` 返回後一律呼叫
    `disconnect()` + `raise StopConsumer()`（單次請求/回應語意），這與 SSE
    需要在 `handle()` 返回後仍保持連線開啟、持續接收 `group_send` 事件矛盾。
    這裡覆寫 `http_request`：只有在 ticket 驗證失敗（維持一次性回應）時才
    立即結束連線；驗證成功後交由框架的 dispatch 迴圈把後續
    `channel_layer.group_send` 事件路由給 `conversation_message()`，直到
    用戶端斷線（`http_disconnect`）為止。
    """

    group_name: str | None = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._keep_alive = False

    async def http_request(self, message: dict) -> None:
        if "body" in message:
            self.body.append(message["body"])
        if not message.get("more_body"):
            try:
                await self.handle(b"".join(self.body))
            finally:
                if not self._keep_alive:
                    await self.disconnect()
                    raise StopConsumer

    async def handle(self, body: bytes) -> None:
        conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        query_params = parse_qs(self.scope["query_string"].decode())
        ticket = query_params.get("ticket", [None])[0]

        ticket_payload = (
            await database_sync_to_async(consume_ticket)(ticket) if ticket else None
        )
        if not ticket_payload or ticket_payload.get("conversation_id") != str(conversation_id):
            await self.send_response(
                403,
                b"invalid or expired ticket",
                headers=[(b"Content-Type", b"text/plain")],
            )
            return

        self.group_name = group_name_for(conversation_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        self._keep_alive = True

        await self.send_headers(
            headers=[
                (b"Content-Type", b"text/event-stream"),
                (b"Cache-Control", b"no-cache"),
            ],
        )

        snapshot = await database_sync_to_async(build_initial_snapshot)(conversation_id)
        if snapshot is not None:
            await self._send_event(snapshot)

    async def conversation_message(self, event: dict) -> None:
        await self._send_event(event["payload"])

    async def _send_event(self, payload: dict) -> None:
        data = f"data: {json.dumps(payload)}\n\n".encode()
        await self.send_body(data, more_body=True)

    async def disconnect(self) -> None:
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
