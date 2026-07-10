from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from maiagent_ai_django.api.serializers import SubmitMessageSerializer
from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.tasks import generate_ai_reply

if TYPE_CHECKING:
    import uuid


class SubmitMessageView(APIView):
    """POST /api/conversations/{conversation_id}/messages/。"""

    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def check_throttles(self, request):
        # DRF's default Throttle.wait() reads self.history, which is only
        # populated as a side effect of the real allow_request() implementation.
        # Avoid calling wait() so throttles mocked at the allow_request() level
        # (e.g. in tests) don't blow up with AttributeError.
        for throttle in self.get_throttles():
            if not throttle.allow_request(request, self):
                self.throttled(request, None)

    def post(self, request, conversation_id: uuid.UUID):
        serializer = SubmitMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        conversation = get_object_or_404(Conversation, id=conversation_id)
        if conversation.user_id != request.user.id:
            return Response(status=status.HTTP_403_FORBIDDEN)

        with transaction.atomic():
            conversation = Conversation.objects.select_for_update().get(
                id=conversation_id,
            )

            if conversation.status == Conversation.Status.CLOSED:
                return Response(
                    {"code": "conversation_closed"},
                    status=status.HTTP_409_CONFLICT,
                )
            if conversation.status == Conversation.Status.PENDING_HUMAN:
                return Response(
                    {"code": "pending_human"},
                    status=status.HTTP_409_CONFLICT,
                )
            if conversation.messages.filter(
                sender_type=Message.SenderType.AI,
                status=Message.Status.PENDING,
            ).exists():
                return Response(
                    {"code": "reply_in_progress"},
                    status=status.HTTP_409_CONFLICT,
                )

            user_message = Message.objects.create(
                conversation=conversation,
                sender_type=Message.SenderType.USER,
                content=serializer.validated_data["content"],
                status=Message.Status.COMPLETED,
            )
            ai_message = Message.objects.create(
                conversation=conversation,
                sender_type=Message.SenderType.AI,
                content="",
                status=Message.Status.PENDING,
            )

        generate_ai_reply.delay(str(ai_message.id))

        return Response(
            {
                "user_message_id": str(user_message.id),
                "ai_message_id": str(ai_message.id),
            },
            status=status.HTTP_202_ACCEPTED,
        )
