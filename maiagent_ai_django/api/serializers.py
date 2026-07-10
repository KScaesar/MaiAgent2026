from __future__ import annotations

from rest_framework import serializers

from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.models import SceneConfig


class SubmitMessageSerializer(serializers.Serializer):
    content = serializers.CharField(allow_blank=False)


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "user", "scene", "status", "created", "modified"]
        read_only_fields = fields


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "conversation",
            "sender_type",
            "content",
            "status",
            "model_used",
            "error_message",
            "created",
            "modified",
        ]
        read_only_fields = fields


class SceneConfigPublicSerializer(serializers.ModelSerializer):
    """一般使用者可見欄位：不曝露 default_settings 等內部設定。"""

    class Meta:
        model = SceneConfig
        fields = ["id", "name", "scene_type"]
        read_only_fields = fields


class SceneConfigAdminSerializer(serializers.ModelSerializer):
    """管理者可見/可寫的完整欄位。"""

    class Meta:
        model = SceneConfig
        fields = [
            "id",
            "name",
            "scene_type",
            "default_settings",
            "is_active",
            "created",
            "modified",
        ]
        read_only_fields = ["id", "created", "modified"]
