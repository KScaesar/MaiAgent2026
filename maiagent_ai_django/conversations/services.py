from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.tasks import generate_ai_reply

if TYPE_CHECKING:
    import uuid


class MessageSubmitError(Exception):
    """對話目前狀態不允許提交新訊息（見 `code` 對應的具體原因）。"""

    def __init__(self, *, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class MessageSubmitResult:
    user_message_id: uuid.UUID
    ai_message_id: uuid.UUID


def message_submit(
    *,
    conversation_id: uuid.UUID,
    content: str,
) -> MessageSubmitResult:
    """提交使用者訊息，建立待生成的 AI 回覆並派送 Celery 任務。

    在 `closed`／`pending_human`／已有進行中 AI 回覆 三種情況下會拒絕提交，
    以 `MessageSubmitError` 表達（呼叫端負責轉換成對應的 HTTP 狀態碼）。
    """
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(id=conversation_id)

        if conversation.status == Conversation.Status.CLOSED:
            raise MessageSubmitError(code="conversation_closed")
        if conversation.status == Conversation.Status.PENDING_HUMAN:
            raise MessageSubmitError(code="pending_human")
        if conversation.messages.filter(
            sender_type=Message.SenderType.AI,
            status=Message.Status.PENDING,
        ).exists():
            raise MessageSubmitError(code="reply_in_progress")

        user_message = Message.objects.create(
            conversation=conversation,
            sender_type=Message.SenderType.USER,
            content=content,
            status=Message.Status.COMPLETED,
        )
        ai_message = Message.objects.create(
            conversation=conversation,
            sender_type=Message.SenderType.AI,
            content="",
            status=Message.Status.PENDING,
        )

    generate_ai_reply.delay(str(ai_message.id))

    return MessageSubmitResult(
        user_message_id=user_message.id,
        ai_message_id=ai_message.id,
    )
