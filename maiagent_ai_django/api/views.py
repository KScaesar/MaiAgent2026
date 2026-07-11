from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import ListAPIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from maiagent_ai_django.api.permissions import IsAdmin
from maiagent_ai_django.api.permissions import is_admin
from maiagent_ai_django.api.permissions import is_customer_service
from maiagent_ai_django.api.serializers import ConversationSerializer
from maiagent_ai_django.api.serializers import MessageSerializer
from maiagent_ai_django.api.serializers import SceneConfigAdminSerializer
from maiagent_ai_django.api.serializers import SceneConfigPublicSerializer
from maiagent_ai_django.api.serializers import SubmitMessageSerializer
from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.models import SceneConfig
from maiagent_ai_django.conversations.tasks import generate_ai_reply
from maiagent_ai_django.realtime.tickets import issue_ticket

if TYPE_CHECKING:
    import uuid


class ConversationMessagesView(APIView):
    """GET / POST /api/conversations/{conversation_id}/messages/。"""

    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]
    pagination_class = None  # set on the class, see get() below

    def get(self, request, conversation_id: uuid.UUID):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        user = request.user
        allowed = (
            conversation.user_id == user.id
            or is_admin(user)
            or (
                is_customer_service(user)
                and conversation.scene.scene_type
                == SceneConfig.SceneType.CUSTOMER_SERVICE
            )
        )
        if not allowed:
            return Response(status=status.HTTP_403_FORBIDDEN)

        paginator = ConversationCursorPagination()
        queryset = conversation.messages.all()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = MessageSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

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


class ConversationCursorPagination(CursorPagination):
    ordering = "-created"
    page_size = 20


def _conversation_queryset_for(user):
    """依角色回傳 Conversation 的可見範圍（權限矩陣核心邏輯）。"""
    if is_admin(user):
        return Conversation.objects.all()
    if is_customer_service(user):
        return Conversation.objects.filter(
            scene__scene_type=SceneConfig.SceneType.CUSTOMER_SERVICE,
        )
    return Conversation.objects.filter(user=user)


class ConversationListView(ListAPIView):
    """GET /api/conversations/。"""

    permission_classes = [IsAuthenticated]
    serializer_class = ConversationSerializer
    pagination_class = ConversationCursorPagination

    def get_queryset(self):
        queryset = _conversation_queryset_for(self.request.user)

        scene_id = self.request.query_params.get("scene")
        if scene_id:
            queryset = queryset.filter(scene_id=scene_id)

        conversation_status = self.request.query_params.get("status")
        if conversation_status:
            queryset = queryset.filter(status=conversation_status)

        query = self.request.query_params.get("q")
        if query:
            # NOTE: 中文全文檢索（simple config）對無空白 CJK 長字串會整段變成
            # 單一 lexeme，to_tsquery 無法命中子字串（已於 2026-07-10 final design
            # 「Open Questions」#3 標註為待驗證項目，實測確認需要 CJK 分詞擴充套件）。
            # 在該擴充套件到位前，改用 icontains 保證子字串搜尋行為符合預期。
            queryset = queryset.filter(messages__content__icontains=query).distinct()

        return queryset


class ConversationDetailView(RetrieveAPIView):
    """GET /api/conversations/{id}/。"""

    permission_classes = [IsAuthenticated]
    serializer_class = ConversationSerializer
    queryset = Conversation.objects.all()
    lookup_url_kwarg = "conversation_id"

    def get_object(self):
        conversation = get_object_or_404(
            Conversation,
            id=self.kwargs["conversation_id"],
        )
        user = self.request.user
        allowed = (
            conversation.user_id == user.id
            or is_admin(user)
            or (
                is_customer_service(user)
                and conversation.scene.scene_type
                == SceneConfig.SceneType.CUSTOMER_SERVICE
            )
        )
        if not allowed:
            raise PermissionDenied
        return conversation


class SceneListCreateView(ListCreateAPIView):
    """GET / POST /api/scenes/。"""

    permission_classes = [IsAuthenticated]
    queryset = SceneConfig.objects.all()
    pagination_class = ConversationCursorPagination

    def get_serializer_class(self):
        if is_admin(self.request.user):
            return SceneConfigAdminSerializer
        return SceneConfigPublicSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsAdmin()]
        return [IsAuthenticated()]


class SceneDetailView(RetrieveUpdateAPIView):
    """GET / PATCH /api/scenes/{id}/。"""

    queryset = SceneConfig.objects.all()
    serializer_class = SceneConfigAdminSerializer
    lookup_url_kwarg = "scene_id"

    def get_permissions(self):
        if self.request.method in {"PATCH", "PUT"}:
            return [IsAuthenticated(), IsAdmin()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.request.method in {"PATCH", "PUT"} or is_admin(self.request.user):
            return SceneConfigAdminSerializer
        return SceneConfigPublicSerializer


class MessageDetailView(RetrieveAPIView):
    """GET /api/messages/{id}/（SSE 初始快照 / 輪詢 fallback）。"""

    permission_classes = [IsAuthenticated]
    serializer_class = MessageSerializer
    queryset = Message.objects.all()
    lookup_url_kwarg = "message_id"

    def get_object(self):
        message = get_object_or_404(Message, id=self.kwargs["message_id"])
        conversation = message.conversation
        user = self.request.user
        allowed = (
            conversation.user_id == user.id
            or is_admin(user)
            or (
                is_customer_service(user)
                and conversation.scene.scene_type
                == SceneConfig.SceneType.CUSTOMER_SERVICE
            )
        )
        if not allowed:
            raise PermissionDenied
        return message


class SSETicketView(APIView):
    """POST /api/conversations/{conversation_id}/sse-ticket/。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: uuid.UUID):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        user = request.user
        allowed = (
            conversation.user_id == user.id
            or is_admin(user)
            or (
                is_customer_service(user)
                and conversation.scene.scene_type
                == SceneConfig.SceneType.CUSTOMER_SERVICE
            )
        )
        if not allowed:
            return Response(status=status.HTTP_403_FORBIDDEN)

        ticket = issue_ticket(user_id=user.id, conversation_id=conversation.id)
        return Response({"ticket": ticket}, status=status.HTTP_201_CREATED)
