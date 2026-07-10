from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AiProvidersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "maiagent_ai_django.ai_providers"
    verbose_name = _("AI Providers")
