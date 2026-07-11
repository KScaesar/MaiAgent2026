from __future__ import annotations

from django.contrib import admin

from maiagent_ai_django.api.permissions import is_admin
from maiagent_ai_django.api.permissions import is_customer_service
from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.models import ModelRoute
from maiagent_ai_django.conversations.models import SceneConfig

MESSAGE_IMMUTABLE_FIELDS = ("content", "metadata", "error_message", "model_used")


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    can_delete = False
    fields = ("sender_type", "content", "status", "model_used", "created")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("user", "scene", "status", "created")
    list_filter = ("scene", "status")
    inlines = [MessageInline]

    def get_readonly_fields(self, request, obj=None):
        if is_admin(request.user):
            return ()
        if is_customer_service(request.user):
            return tuple(
                field.name
                for field in Conversation._meta.get_fields()  # noqa: SLF001
                if field.concrete and field.name not in {"status", "id"}
            )
        return super().get_readonly_fields(request, obj)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender_type", "status", "created")
    search_fields = ("content",)
    readonly_fields = MESSAGE_IMMUTABLE_FIELDS

    def get_readonly_fields(self, request, obj=None):
        return MESSAGE_IMMUTABLE_FIELDS


class ModelRouteInline(admin.TabularInline):
    model = ModelRoute
    extra = 0
    fields = ("model_name", "order", "weight", "is_enabled")


@admin.register(SceneConfig)
class SceneConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "scene_type", "is_active")
    list_filter = ("scene_type", "is_active")
    inlines = [ModelRouteInline]
