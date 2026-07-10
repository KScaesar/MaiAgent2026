from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class RealtimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "maiagent_ai_django.realtime"
    verbose_name = _("Realtime")
