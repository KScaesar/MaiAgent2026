from __future__ import annotations

from django.urls import path

from maiagent_ai_django.api.views import SubmitMessageView

app_name = "conversations"

urlpatterns = [
    path(
        "conversations/<uuid:conversation_id>/messages/",
        SubmitMessageView.as_view(),
        name="submit-message",
    ),
]
