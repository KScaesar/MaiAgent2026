from __future__ import annotations

from rest_framework import serializers


class SubmitMessageSerializer(serializers.Serializer):
    content = serializers.CharField(allow_blank=False)
