from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
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
from maiagent_ai_django.api.serializers import ConversationCreateSerializer
from maiagent_ai_django.api.serializers import ConversationSerializer
from maiagent_ai_django.api.serializers import MessageSerializer
from maiagent_ai_django.api.serializers import SceneConfigAdminSerializer
from maiagent_ai_django.api.serializers import SceneConfigPublicSerializer
from maiagent_ai_django.api.serializers import SubmitMessageSerializer
from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.models import SceneConfig
from maiagent_ai_django.conversations.selectors import conversation_can_be_viewed_by
from maiagent_ai_django.conversations.selectors import conversation_list_visible_to
from maiagent_ai_django.conversations.services import MessageSubmitError
from maiagent_ai_django.conversations.services import message_submit
from maiagent_ai_django.realtime.tickets import issue_ticket

if TYPE_CHECKING:
    import uuid

    from maiagent_ai_django.users.models import User


class ConversationMessagesView(APIView):
    """GET / POST /api/conversations/{conversation_id}/messages/。"""

    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]
    pagination_class = None  # set on the class, see get() below

    def get(self, request, conversation_id: uuid.UUID):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        if not conversation_can_be_viewed_by(
            conversation=conversation,
            user=cast("User", request.user),
        ):
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
                # djangorestframework-stubs types `wait` as `float`, but DRF itself
                # accepts `None` (Throttled(wait=None) is valid) when unknown.
                self.throttled(request, None)  # type: ignore[arg-type]

    def post(self, request, conversation_id: uuid.UUID):
        serializer = SubmitMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        conversation = get_object_or_404(Conversation, id=conversation_id)
        if conversation.user_id != request.user.id:
            return Response(status=status.HTTP_403_FORBIDDEN)

        try:
            result = message_submit(
                conversation_id=conversation_id,
                content=serializer.validated_data["content"],
            )
        except MessageSubmitError as exc:
            return Response({"code": exc.code}, status=status.HTTP_409_CONFLICT)

        return Response(
            {
                "user_message_id": str(result.user_message_id),
                "ai_message_id": str(result.ai_message_id),
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ConversationCursorPagination(CursorPagination):
    ordering = "-created"
    page_size = 20


class ConversationListView(ListCreateAPIView):
    """GET / POST /api/conversations/。"""

    permission_classes = [IsAuthenticated]
    pagination_class = ConversationCursorPagination

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ConversationCreateSerializer
        return ConversationSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def get_queryset(self):
        queryset = conversation_list_visible_to(user=cast("User", self.request.user))

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
        if not conversation_can_be_viewed_by(
            conversation=conversation,
            user=cast("User", self.request.user),
        ):
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
        if not conversation_can_be_viewed_by(
            conversation=message.conversation,
            user=cast("User", self.request.user),
        ):
            raise PermissionDenied
        return message


class SSETicketView(APIView):
    """POST /api/conversations/{conversation_id}/sse-ticket/。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: uuid.UUID):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        user = cast("User", request.user)
        if not conversation_can_be_viewed_by(conversation=conversation, user=user):
            return Response(status=status.HTTP_403_FORBIDDEN)

        ticket = issue_ticket(user_id=user.id, conversation_id=conversation.id)
        return Response({"ticket": ticket}, status=status.HTTP_201_CREATED)
