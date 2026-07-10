from __future__ import annotations

from django.urls import path

from maiagent_ai_django.realtime.consumers import ConversationEventsConsumer

http_urlpatterns = [
    path(
        "sse/conversations/<uuid:conversation_id>/",
        ConversationEventsConsumer.as_asgi(),
    ),
]
