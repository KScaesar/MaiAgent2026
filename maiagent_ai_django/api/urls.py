from __future__ import annotations

from django.urls import path

from maiagent_ai_django.api.views import ConversationDetailView
from maiagent_ai_django.api.views import ConversationListView
from maiagent_ai_django.api.views import ConversationMessagesView
from maiagent_ai_django.api.views import MessageDetailView
from maiagent_ai_django.api.views import SceneDetailView
from maiagent_ai_django.api.views import SceneListCreateView
from maiagent_ai_django.api.views import SSETicketView

app_name = "conversations"

urlpatterns = [
    path(
        "conversations/",
        ConversationListView.as_view(),
        name="conversation-list",
    ),
    path(
        "conversations/<uuid:conversation_id>/",
        ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
    path(
        "conversations/<uuid:conversation_id>/messages/",
        ConversationMessagesView.as_view(),
        name="submit-message",
    ),
    path(
        "conversations/<uuid:conversation_id>/sse-ticket/",
        SSETicketView.as_view(),
        name="sse-ticket",
    ),
    path(
        "messages/<uuid:message_id>/",
        MessageDetailView.as_view(),
        name="message-detail",
    ),
    path(
        "scenes/",
        SceneListCreateView.as_view(),
        name="scene-list",
    ),
    path(
        "scenes/<uuid:scene_id>/",
        SceneDetailView.as_view(),
        name="scene-detail",
    ),
]
