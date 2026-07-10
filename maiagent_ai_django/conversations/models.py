from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel


class SceneConfig(TimeStampedModel):
    class SceneType(models.TextChoices):
        CUSTOMER_SERVICE = "customer_service", _("Customer Service")
        KNOWLEDGE_MANAGEMENT = "knowledge_management", _("Knowledge Management")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    scene_type = models.CharField(max_length=32, choices=SceneType.choices)
    default_settings = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Conversation(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        CLOSED = "closed", _("Closed")
        PENDING_HUMAN = "pending_human", _("Pending Human")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    scene = models.ForeignKey(
        SceneConfig,
        on_delete=models.PROTECT,
        related_name="conversations",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.OPEN,
    )
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self) -> str:
        return f"Conversation({self.id})"


class Message(TimeStampedModel):
    class SenderType(models.TextChoices):
        USER = "user", _("User")
        AI = "ai", _("AI")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender_type = models.CharField(max_length=16, choices=SenderType.choices)
    content = models.TextField(blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    model_used = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
    error_message = models.TextField(null=True, blank=True)  # noqa: DJ001
    search_vector = SearchVectorField(null=True, blank=True)

    class Meta:
        ordering = ["created", "id"]
        indexes = [
            models.Index(fields=["conversation", "created"]),
            GinIndex(fields=["search_vector"]),
        ]

    def __str__(self) -> str:
        return f"Message({self.id})"


class ModelRoute(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scene = models.ForeignKey(
        SceneConfig,
        on_delete=models.CASCADE,
        related_name="model_routes",
    )
    model_name = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)
    weight = models.PositiveIntegerField(default=1)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "model_name"]

    def __str__(self) -> str:
        return f"{self.scene_id}:{self.model_name}"
