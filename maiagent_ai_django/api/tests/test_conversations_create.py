"""紅燈測試：POST /api/conversations/。

依據 docs/superpowers/specs/2026-07-10-final-design.md「Endpoint 清單」與
docs/superpowers/specs/2026-07-11-spec-by-example.md 功能七。

**設計假設（驅動介面設計的暫定細節）：**
- 成功回應 201，body 為序列化後的 Conversation（含 `id`、`scene`、`status`、
  `created`、`modified`），`status` 恆為 `open`。
- `user` 一律取自 `request.user`，不接受 client 指定（即使帶了也會被忽略）。
- `scene` 不存在時回 400（DRF `PrimaryKeyRelatedField` 預設驗證行為）。
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status

from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _create_conversation(api_client, scene_id):
    url = reverse("api:conversations:conversation-list")
    return api_client.post(url, data={"scene": str(scene_id)}, format="json")


class TestCreateConversationNormalCase:
    """[1] Happy Path：功能七 Example #1、#2。"""

    def test_authenticated_user_creates_conversation(self, api_client, user, scene):
        # Given: 已登入使用者、有效的 scene
        api_client.force_authenticate(user=user)

        # When: 呼叫 POST /api/conversations/ 指定 scene
        response = _create_conversation(api_client, scene.id)

        # Then: 201，回傳新建的 Conversation
        assert response.status_code == status.HTTP_201_CREATED
        conversation = Conversation.objects.get(id=response.data["id"])
        assert conversation.user_id == user.id
        assert conversation.scene_id == scene.id
        assert conversation.status == Conversation.Status.OPEN

    def test_client_supplied_user_is_ignored(self, api_client, user, scene):
        # Given: 已登入使用者，body 內夾帶其他 user id 意圖冒充
        api_client.force_authenticate(user=user)
        other_user = UserFactory()

        # When: 提交 POST body 帶入 user 欄位
        url = reverse("api:conversations:conversation-list")
        response = api_client.post(
            url,
            data={"scene": str(scene.id), "user": other_user.id},
            format="json",
        )

        # Then: 忽略 client 帶入的 user，Conversation 歸屬目前登入者
        assert response.status_code == status.HTTP_201_CREATED
        conversation = Conversation.objects.get(id=response.data["id"])
        assert conversation.user_id == user.id


class TestCreateConversationErrorCase:
    """[2] Negative：功能七 Example #3、#4。"""

    def test_anonymous_user_cannot_create_conversation(self, api_client, scene):
        # Given: 未登入
        # When: 呼叫 POST /api/conversations/
        response = _create_conversation(api_client, scene.id)

        # Then: 403（SessionAuthentication 未帶 WWW-Authenticate 挑戰，DRF 慣例回 403）
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_nonexistent_scene_returns_400(self, api_client, user):
        # Given: 已登入使用者，但 scene id 不存在
        api_client.force_authenticate(user=user)
        missing_scene_id = "00000000-0000-0000-0000-000000000000"

        # When: 呼叫 POST /api/conversations/ 指定不存在的 scene
        response = _create_conversation(api_client, missing_scene_id)

        # Then: 400
        assert response.status_code == status.HTTP_400_BAD_REQUEST
