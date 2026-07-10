"""紅燈測試：GET/POST /api/scenes/。

依據 docs/superpowers/specs/2026-07-11-spec-by-example.md 功能四。
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from maiagent_ai_django.conversations.models import SceneConfig
from maiagent_ai_django.conversations.tests.factories import SceneConfigFactory

pytestmark = pytest.mark.django_db


class TestScenesListNormalCase:
    """[1] Happy Path：一般使用者只看得到有限欄位。"""

    def test_regular_user_scenes_list_omits_default_settings(self, api_client, user):
        # Given: 使用者為一般使用者（無特殊 Group）
        SceneConfigFactory(default_settings={"foo": "bar"})
        api_client.force_authenticate(user=user)

        # When: 呼叫 GET /api/scenes/
        url = reverse("api:conversations:scene-list")
        response = api_client.get(url)

        # Then: 回應 200，只含 id/name/scene_type，不含 default_settings
        assert response.status_code == 200
        scene_payload = response.data["results"][0]
        assert set(scene_payload.keys()) == {"id", "name", "scene_type"}

    def test_admin_scenes_list_includes_default_settings(self, api_client, user):
        # Given: 使用者為管理者
        user.is_superuser = True
        user.save()
        SceneConfigFactory(default_settings={"foo": "bar"})
        api_client.force_authenticate(user=user)

        # When: 呼叫 GET /api/scenes/
        url = reverse("api:conversations:scene-list")
        response = api_client.get(url)

        # Then: 回應 200，欄位含完整 default_settings
        assert response.status_code == 200
        scene_payload = response.data["results"][0]
        assert scene_payload["default_settings"] == {"foo": "bar"}


class TestScenesCreateNormalCase:
    """[2] Happy Path：管理者建立新場景設定。"""

    def test_admin_can_create_scene(self, api_client, user):
        # Given: 使用者為管理者
        user.is_superuser = True
        user.save()
        api_client.force_authenticate(user=user)

        # When: POST /api/scenes/
        url = reverse("api:conversations:scene-list")
        response = api_client.post(
            url,
            {
                "name": "new-scene",
                "scene_type": SceneConfig.SceneType.CUSTOMER_SERVICE,
            },
        )

        # Then: 201
        assert response.status_code == 201
        assert SceneConfig.objects.filter(name="new-scene").exists()

    def test_admin_group_member_can_create_scene(self, api_client, user):
        # Given: 使用者屬於 admin Group（非 is_superuser）
        admin_group, _ = Group.objects.get_or_create(name="admin")
        user.groups.add(admin_group)
        api_client.force_authenticate(user=user)

        # When: POST /api/scenes/
        url = reverse("api:conversations:scene-list")
        response = api_client.post(
            url,
            {
                "name": "another-scene",
                "scene_type": SceneConfig.SceneType.KNOWLEDGE_MANAGEMENT,
            },
        )

        # Then: 201
        assert response.status_code == 201


class TestScenesCreateErrorCase:
    """[3] Negative（權限）：一般使用者無法建立場景設定。"""

    def test_regular_user_cannot_create_scene(self, api_client, user):
        # Given: 使用者為一般使用者
        api_client.force_authenticate(user=user)

        # When: 嘗試 POST /api/scenes/
        url = reverse("api:conversations:scene-list")
        response = api_client.post(
            url,
            {"name": "nope", "scene_type": SceneConfig.SceneType.CUSTOMER_SERVICE},
        )

        # Then: 403
        assert response.status_code == 403
