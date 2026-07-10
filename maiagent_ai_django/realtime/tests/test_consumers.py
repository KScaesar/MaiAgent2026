"""紅燈測試：ConversationEventsConsumer（SSE）。

依據 docs/superpowers/specs/2026-07-11-spec-by-example.md 功能六。

以 asgiref.sync.async_to_sync 包裝 channels 的 async 測試工具，
維持與專案其他測試相同的同步 pytest 風格（專案未安裝 pytest-asyncio）。
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import ApplicationCommunicator

from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.tests.factories import ConversationFactory
from maiagent_ai_django.conversations.tests.factories import MessageFactory
from maiagent_ai_django.realtime.consumers import ConversationEventsConsumer
from maiagent_ai_django.realtime.tickets import issue_ticket

pytestmark = pytest.mark.django_db


def _http_scope(conversation_id, ticket: str | None):
    query_string = f"ticket={ticket}".encode() if ticket else b""
    return {
        "type": "http",
        "method": "GET",
        "path": f"/sse/conversations/{conversation_id}/",
        "query_string": query_string,
        "headers": [],
        "url_route": {"kwargs": {"conversation_id": conversation_id}},
    }


class TestConversationEventsConsumerErrorCase:
    """[1] Negative：ticket 不存在/已使用/過期一律拒絕連線。"""

    def test_missing_ticket_is_rejected(self, user):
        # Given: 對話存在，但連線時未帶 ticket
        conversation = ConversationFactory(user=user)
        communicator = ApplicationCommunicator(
            ConversationEventsConsumer.as_asgi(),
            _http_scope(conversation.id, ticket=None),
        )

        async def scenario():
            await communicator.send_input({"type": "http.request", "body": b""})
            start = await communicator.receive_output(timeout=2)
            body = await communicator.receive_output(timeout=2)
            return start, body

        # When: 建立連線
        start, body = async_to_sync(scenario)()

        # Then: 連線被拒絕（403）
        assert start["status"] == 403
        assert b"invalid" in body["body"]

    def test_reused_ticket_is_rejected(self, user):
        # Given: ticket 已被使用過一次
        conversation = ConversationFactory(user=user)
        ticket = issue_ticket(user_id=user.id, conversation_id=conversation.id)

        first = ApplicationCommunicator(
            ConversationEventsConsumer.as_asgi(),
            _http_scope(conversation.id, ticket=ticket),
        )

        async def connect_once(communicator):
            await communicator.send_input({"type": "http.request", "body": b""})
            start = await communicator.receive_output(timeout=2)
            assert start["status"] == 200

        async_to_sync(connect_once)(first)

        # When: 同一使用者再次用同一 ticket 連線
        second = ApplicationCommunicator(
            ConversationEventsConsumer.as_asgi(),
            _http_scope(conversation.id, ticket=ticket),
        )

        async def scenario():
            await second.send_input({"type": "http.request", "body": b""})
            start = await second.receive_output(timeout=2)
            return start

        start = async_to_sync(scenario)()

        # Then: 第二次連線被拒絕
        assert start["status"] == 403


class TestConversationEventsConsumerNormalCase:
    """[2] Happy Path：連線建立後送出初始快照，並轉發後續 group_send 事件。"""

    def test_connect_sends_initial_snapshot_then_forwards_group_send_event(self, user):
        # Given: 對話內已有一則 COMPLETED 的 AI 訊息（連線前任務已完成）
        conversation = ConversationFactory(user=user)
        existing_ai_message = MessageFactory(
            conversation=conversation,
            sender_type=Message.SenderType.AI,
            status=Message.Status.COMPLETED,
            content="先前已完成的回覆",
        )
        ticket = issue_ticket(user_id=user.id, conversation_id=conversation.id)
        communicator = ApplicationCommunicator(
            ConversationEventsConsumer.as_asgi(),
            _http_scope(conversation.id, ticket=ticket),
        )

        async def scenario():
            await communicator.send_input({"type": "http.request", "body": b""})
            start = await communicator.receive_output(timeout=2)
            snapshot_chunk = await communicator.receive_output(timeout=2)

            # When: 另一個 task 完成後透過 channel_layer 推送事件
            channel_layer = get_channel_layer()
            await channel_layer.group_send(
                f"conv_{conversation.id}",
                {
                    "type": "conversation.message",
                    "payload": {
                        "message_id": "msg-new",
                        "status": "completed",
                        "content": "剛完成的回覆",
                    },
                },
            )
            pushed_chunk = await communicator.receive_output(timeout=2)
            return start, snapshot_chunk, pushed_chunk

        start, snapshot_chunk, pushed_chunk = async_to_sync(scenario)()

        # Then: 連線成功，先收到初始快照（反映已存在的 COMPLETED 訊息）
        assert start["status"] == 200
        snapshot_body = json.loads(
            snapshot_chunk["body"].decode().removeprefix("data: ").removesuffix("\n\n"),
        )
        assert snapshot_body == {
            "message_id": str(existing_ai_message.id),
            "status": "completed",
            "content": "先前已完成的回覆",
        }

        # And: 之後收到 group_send 轉發的事件
        pushed_body = json.loads(
            pushed_chunk["body"].decode().removeprefix("data: ").removesuffix("\n\n"),
        )
        assert pushed_body == {
            "message_id": "msg-new",
            "status": "completed",
            "content": "剛完成的回覆",
        }
