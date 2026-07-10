from __future__ import annotations

from django.contrib.postgres.search import SearchVector
from django.db.models.signals import post_save
from django.dispatch import receiver

from maiagent_ai_django.conversations.models import Message


@receiver(post_save, sender=Message)
def populate_search_vector(sender, instance: Message, **kwargs) -> None:
    Message.all_objects.filter(pk=instance.pk).update(
        search_vector=SearchVector("content"),
    )
