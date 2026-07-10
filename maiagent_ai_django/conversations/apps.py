from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ConversationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "maiagent_ai_django.conversations"
    verbose_name = _("Conversations")

    def ready(self) -> None:
        from maiagent_ai_django.conversations import signals  # noqa: F401
