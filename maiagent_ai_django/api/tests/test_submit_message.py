"""紅燈測試：POST /api/conversations/{id}/messages/。

依據 docs/superpowers/specs/2026-07-11-spec-by-example.md 功能一。

**設計假設（驅動介面設計的暫定細節）：**
- 成功回應 body 含 `user_message_id`、`ai_message_id` 兩個鍵。
- 409 回應 body 含機器可判別的 `code` 鍵（值為 `conversation_closed` /
  `pending_human` / `reply_in_progress`）。
- 觸發 Celery task 的呼叫點為
  `maiagent_ai_django.conversations.tasks.generate_ai_reply.delay`。
"""

from __future__ import annotations

import threading

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.tests.factories import ConversationFactory
from maiagent_ai_django.conversations.tests.factories import MessageFactory

pytestmark = pytest.mark.django_db


def _submit_message(api_client: APIClient, conversation: Conversation, content: str = "你好"):
    return api_client.post(
        f"/api/conversations/{conversation.id}/messages/",
        data={"content": content},
        format="json",
    )


class TestSubmitMessageNormalCase:
    """[1] Happy Path：Example #1、#8。"""

    def test_open_conversation_without_pending_reply_creates_messages_and_triggers_task(
        self,
        api_client,
        user,
        scene,
        mocker,
    ):
        # Given: 對話狀態 OPEN，且無 PENDING AI Message
        conversation = ConversationFactory(
            user=user,
            scene=scene,
            status=Conversation.Status.OPEN,
        )
        api_client.force_authenticate(user=user)
        mock_delay = mocker.patch(
            "maiagent_ai_django.conversations.tasks.generate_ai_reply.delay",
        )

        # When: 使用者提交查詢
        response = _submit_message(api_client, conversation, content="你好")

        # Then: 回應 202，並回傳 user_message_id / ai_message_id
        expected_status_code = status.HTTP_202_ACCEPTED
        assert response.status_code == expected_status_code, (
            "提交合法查詢應回傳 202 Accepted"
        )
        assert "user_message_id" in response.data
        assert "ai_message_id" in response.data

        # And: 同一 transaction 建立 USER(COMPLETED) + AI(PENDING) 兩筆 Message
        user_message = Message.objects.get(id=response.data["user_message_id"])
        ai_message = Message.objects.get(id=response.data["ai_message_id"])

        assert user_message.sender_type == Message.SenderType.USER
        assert user_message.status == Message.Status.COMPLETED
        assert user_message.content == "你好"

        assert ai_message.sender_type == Message.SenderType.AI
        assert ai_message.status == Message.Status.PENDING
        assert ai_message.content == ""

        # And: 觸發 generate_ai_reply task
        mock_delay.assert_called_once_with(str(ai_message.id))

    def test_conversation_reopened_from_pending_human_accepts_submission_again(
        self,
        api_client,
        user,
        scene,
        mocker,
    ):
        # Given: 對話原本 PENDING_HUMAN，客服已在 Admin 將狀態改回 OPEN
        conversation = ConversationFactory(
            user=user,
            scene=scene,
            status=Conversation.Status.PENDING_HUMAN,
        )
        conversation.status = Conversation.Status.OPEN
        conversation.save(update_fields=["status"])
        api_client.force_authenticate(user=user)
        mocker.patch("maiagent_ai_django.conversations.tasks.generate_ai_reply.delay")

        # When: 使用者再次提交查詢
        response = _submit_message(api_client, conversation)

        # Then: 恢復正常流程，回應 202
        expected_status_code = status.HTTP_202_ACCEPTED
        assert response.status_code == expected_status_code


class TestSubmitMessageErrorCase:
    """[2] Negative：三種 409、403、429。"""

    @pytest.mark.parametrize(
        ("conversation_status", "expected_code"),
        [
            pytest.param(
                Conversation.Status.CLOSED,
                "conversation_closed",
                id="closed-conversation-returns-conversation_closed",
            ),
            pytest.param(
                Conversation.Status.PENDING_HUMAN,
                "pending_human",
                id="pending-human-conversation-returns-pending_human",
            ),
        ],
    )
    def test_conversation_in_terminal_state_rejects_submission(
        self,
        api_client,
        user,
        scene,
        conversation_status,
        expected_code,
        mocker,
    ):
        # Given: 對話狀態為 CLOSED 或 PENDING_HUMAN
        conversation = ConversationFactory(
            user=user,
            scene=scene,
            status=conversation_status,
        )
        api_client.force_authenticate(user=user)
        mock_delay = mocker.patch(
            "maiagent_ai_django.conversations.tasks.generate_ai_reply.delay",
        )

        # When: 使用者提交查詢
        response = _submit_message(api_client, conversation)

        # Then: 409，且不建立任何 Message、不觸發 task
        expected_status_code = status.HTTP_409_CONFLICT
        assert response.status_code == expected_status_code
        assert response.data["code"] == expected_code
        assert not Message.objects.filter(conversation=conversation).exists()
        mock_delay.assert_not_called()

    def test_existing_pending_ai_message_rejects_further_submission(
        self,
        api_client,
        user,
        scene,
        mocker,
    ):
        # Given: 對話狀態 OPEN，但已有一則 AI Message status=PENDING
        conversation = ConversationFactory(
            user=user,
            scene=scene,
            status=Conversation.Status.OPEN,
        )
        MessageFactory(
            conversation=conversation,
            sender_type=Message.SenderType.AI,
            status=Message.Status.PENDING,
            content="",
        )
        api_client.force_authenticate(user=user)
        mocker.patch("maiagent_ai_django.conversations.tasks.generate_ai_reply.delay")

        # When: 使用者再次提交查詢
        response = _submit_message(api_client, conversation)

        # Then: 409 reply_in_progress，不建立新 Message
        expected_status_code = status.HTTP_409_CONFLICT
        assert response.status_code == expected_status_code
        assert response.data["code"] == "reply_in_progress"
        assert Message.objects.filter(conversation=conversation).count() == 1

    def test_submitting_to_other_users_conversation_is_forbidden(
        self,
        api_client,
        user,
        scene,
        django_user_model,
    ):
        # Given: 對話屬於使用者 owner，非目前登入的使用者
        owner = django_user_model.objects.create_user(
            email="owner@example.com",
            password="password123",  # noqa: S106
        )
        conversation = ConversationFactory(
            user=owner,
            scene=scene,
            status=Conversation.Status.OPEN,
        )
        api_client.force_authenticate(user=user)

        # When: 非對話擁有者提交查詢
        response = _submit_message(api_client, conversation)

        # Then: 403
        expected_status_code = status.HTTP_403_FORBIDDEN
        assert response.status_code == expected_status_code

    def test_exceeding_rate_limit_returns_429(
        self,
        api_client,
        user,
        scene,
        mocker,
    ):
        # Given: 使用者已達提交頻率上限（以 mock 模擬 throttle 判定為超限）
        conversation = ConversationFactory(
            user=user,
            scene=scene,
            status=Conversation.Status.OPEN,
        )
        api_client.force_authenticate(user=user)
        mocker.patch("maiagent_ai_django.conversations.tasks.generate_ai_reply.delay")
        mocker.patch(
            "rest_framework.throttling.UserRateThrottle.allow_request",
            return_value=False,
        )

        # When: 使用者再次提交查詢
        response = _submit_message(api_client, conversation, content="超過限制的請求")

        # Then: 429
        expected_status_code = status.HTTP_429_TOO_MANY_REQUESTS
        assert response.status_code == expected_status_code


class TestSubmitMessageEdgeCase:
    """[3] Edge Case：Example #5（併發提交同一對話）。"""

    @pytest.mark.django_db(transaction=True)
    def test_concurrent_submissions_to_same_conversation_only_one_succeeds(
        self,
        user,
        scene,
        mocker,
    ):
        # Given: 對話狀態 OPEN，無 PENDING AI Message
        conversation = ConversationFactory(
            user=user,
            scene=scene,
            status=Conversation.Status.OPEN,
        )
        mocker.patch("maiagent_ai_django.conversations.tasks.generate_ai_reply.delay")

        response_status_codes: list[int] = []
        barrier = threading.Barrier(2)

        def _submit_from_new_connection():
            barrier.wait()
            client = APIClient()
            client.force_authenticate(user=user)
            response = _submit_message(client, conversation)
            response_status_codes.append(response.status_code)

        threads = [threading.Thread(target=_submit_from_new_connection) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Then: 恰好一個請求成功（202），另一個因狀態已變為 reply_in_progress 而 409
        expected_success_count = 1
        expected_conflict_count = 1
        assert response_status_codes.count(status.HTTP_202_ACCEPTED) == expected_success_count, (
            "併發提交同一對話應恰好只有一個請求成功建立訊息"
        )
        assert response_status_codes.count(status.HTTP_409_CONFLICT) == expected_conflict_count
