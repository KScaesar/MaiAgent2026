from __future__ import annotations

from celery import shared_task

from maiagent_ai_django.ai_providers.factory import get_provider
from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import Message


def push_message_event(
    conversation_id: str,
    message_id: str,
    status: str,
    **extra,
) -> None:
    """推送 Message 層級狀態變化事件。

    實際透過 Django Channels group_send 推送給前端 SSE 連線, 留待 realtime app 實作。
    """


@shared_task
def generate_ai_reply(message_id: str) -> None:
    try:
        message = Message.objects.select_related(
            "conversation__scene",
        ).get(id=message_id)
    except Message.DoesNotExist:
        return

    if message.status != Message.Status.PENDING:
        return

    conversation = message.conversation
    scene = conversation.scene

    history = conversation.messages.filter(status=Message.Status.COMPLETED).order_by(
        "created",
        "id",
    )
    llm_messages = [
        {
            "role": "user" if m.sender_type == Message.SenderType.USER else "assistant",
            "content": m.content,
        }
        for m in history
    ]

    provider = get_provider(scene)

    try:
        response = provider.generate(messages=llm_messages)
    except Exception as exc:  # noqa: BLE001
        message.status = Message.Status.FAILED
        message.error_message = str(exc)
        message.save(update_fields=["status", "error_message"])

        conversation.status = Conversation.Status.PENDING_HUMAN
        conversation.save(update_fields=["status"])

        push_message_event(str(conversation.id), str(message.id), message.status)
        return

    message.status = Message.Status.COMPLETED
    message.content = response.choices[0].message.content
    message.model_used = response.model
    message.save(update_fields=["status", "content", "model_used"])

    push_message_event(str(conversation.id), str(message.id), message.status)
