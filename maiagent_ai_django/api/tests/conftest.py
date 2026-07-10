from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from maiagent_ai_django.conversations.tests.factories import SceneConfigFactory


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def scene():
    return SceneConfigFactory()
