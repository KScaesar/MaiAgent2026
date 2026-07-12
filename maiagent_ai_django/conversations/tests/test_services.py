"""單元測試：conversations/services.py。

對應重構後新增的 service 層，補上 API 測試（黑箱）未直接涵蓋的函式層級案例。
API 層的行為案例（202/409 對應關係、併發鎖定）見
`maiagent_ai_django/api/tests/test_submit_message.py`。
"""

from __future__ import annotations

import pytest

from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.services import MessageSubmitError
from maiagent_ai_django.conversations.services import message_submit
from maiagent_ai_django.conversations.tests.factories import ConversationFactory
from maiagent_ai_django.conversations.tests.factories import MessageFactory
from maiagent_ai_django.conversations.tests.factories import SceneConfigFactory

pytestmark = pytest.mark.django_db


class TestMessageSubmitNormalCase:
    """[1] Happy Path：建立 USER(COMPLETED) + AI(PENDING) 並派送任務。"""

    def test_creates_user_and_ai_messages_and_triggers_task(self, user, mocker):
        conversation = ConversationFactory(
            user=user,
            scene=SceneConfigFactory(),
            status=Conversation.Status.OPEN,
        )
        mock_delay = mocker.patch(
            "maiagent_ai_django.conversations.tasks.generate_ai_reply.delay",
        )

        result = message_submit(conversation_id=conversation.id, content="你好")

        user_message = Message.objects.get(id=result.user_message_id)
        ai_message = Message.objects.get(id=result.ai_message_id)
        assert user_message.sender_type == Message.SenderType.USER
        assert user_message.status == Message.Status.COMPLETED
        assert user_message.content == "你好"
        assert ai_message.sender_type == Message.SenderType.AI
        assert ai_message.status == Message.Status.PENDING
        mock_delay.assert_called_once_with(str(ai_message.id))


class TestMessageSubmitErrorCase:
    """[2] Negative：三種衝突狀態各自對應的 `code`。"""

    @pytest.mark.parametrize(
        ("conversation_status", "expected_code"),
        [
            pytest.param(
                Conversation.Status.CLOSED,
                "conversation_closed",
                id="closed-conversation",
            ),
            pytest.param(
                Conversation.Status.PENDING_HUMAN,
                "pending_human",
                id="pending-human-conversation",
            ),
        ],
    )
    def test_terminal_state_raises_with_expected_code(
        self,
        user,
        mocker,
        conversation_status,
        expected_code,
    ):
        conversation = ConversationFactory(
            user=user,
            scene=SceneConfigFactory(),
            status=conversation_status,
        )
        mock_delay = mocker.patch(
            "maiagent_ai_django.conversations.tasks.generate_ai_reply.delay",
        )

        with pytest.raises(MessageSubmitError) as exc_info:
            message_submit(conversation_id=conversation.id, content="你好")

        assert exc_info.value.code == expected_code
        assert not Message.objects.filter(conversation=conversation).exists()
        mock_delay.assert_not_called()

    def test_existing_pending_ai_message_raises_reply_in_progress(
        self,
        user,
        mocker,
    ):
        conversation = ConversationFactory(
            user=user,
            scene=SceneConfigFactory(),
            status=Conversation.Status.OPEN,
        )
        MessageFactory(
            conversation=conversation,
            sender_type=Message.SenderType.AI,
            status=Message.Status.PENDING,
            content="",
        )
        mocker.patch("maiagent_ai_django.conversations.tasks.generate_ai_reply.delay")

        with pytest.raises(MessageSubmitError) as exc_info:
            message_submit(conversation_id=conversation.id, content="你好")

        assert exc_info.value.code == "reply_in_progress"
        assert Message.objects.filter(conversation=conversation).count() == 1
