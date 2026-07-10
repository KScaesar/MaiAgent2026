"""紅燈測試：GET /api/conversations/{id}/ 與 GET /api/conversations/。

依據 docs/superpowers/specs/2026-07-11-spec-by-example.md 功能四、功能五。
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.models import SceneConfig
from maiagent_ai_django.conversations.tests.factories import ConversationFactory
from maiagent_ai_django.conversations.tests.factories import MessageFactory
from maiagent_ai_django.conversations.tests.factories import SceneConfigFactory
from maiagent_ai_django.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


class TestConversationDetailNormalCase:
    """[1] Happy Path：擁有者可存取自己的對話。"""

    def test_owner_can_retrieve_own_conversation(self, api_client, user):
        # Given: 對話 "conv-1" 屬於 user
        conversation = ConversationFactory(user=user)
        api_client.force_authenticate(user=user)

        # When: 呼叫 GET /api/conversations/{id}/
        url = reverse("api:conversations:conversation-detail", args=[conversation.id])
        response = api_client.get(url)

        # Then: 回應 200
        assert response.status_code == 200
        assert response.data["id"] == str(conversation.id)


class TestConversationDetailErrorCase:
    """[2] Negative：存取他人對話回 403。"""

    def test_accessing_other_users_conversation_is_forbidden(self, api_client, user):
        # Given: 對話 "conv-9" 屬於使用者 A（非 user）
        owner = UserFactory()
        conversation = ConversationFactory(user=owner)
        api_client.force_authenticate(user=user)

        # When: 使用者 B（user）呼叫 GET /api/conversations/conv-9/
        url = reverse("api:conversations:conversation-detail", args=[conversation.id])
        response = api_client.get(url)

        # Then: 回應為 403
        assert response.status_code == 403


class TestConversationListCustomerServiceNormalCase:
    """[3] Happy Path：客服人員可檢視所屬場景的全部對話。"""

    def test_customer_service_sees_all_conversations_in_scene(self, api_client, user):
        # Given: 客服人員屬於 customer_service Group
        cs_group, _ = Group.objects.get_or_create(name="customer_service")
        user.groups.add(cs_group)
        cs_scene = SceneConfigFactory(scene_type=SceneConfig.SceneType.CUSTOMER_SERVICE)
        other_user = UserFactory()
        conv_a = ConversationFactory(user=user, scene=cs_scene)
        conv_b = ConversationFactory(user=other_user, scene=cs_scene)
        api_client.force_authenticate(user=user)

        # When: 客服人員呼叫 GET /api/conversations/?scene=cs-scene-1
        url = reverse("api:conversations:conversation-list")
        response = api_client.get(url, {"scene": str(cs_scene.id)})

        # Then: 回應 200，清單包含所有使用者在該場景下的對話
        assert response.status_code == 200
        actual_ids = {item["id"] for item in response.data["results"]}
        assert actual_ids == {str(conv_a.id), str(conv_b.id)}


class TestConversationListRegularUserNormalCase:
    """[4] Happy Path：一般使用者只看得到自己的對話。"""

    def test_regular_user_sees_only_own_conversations(self, api_client, user):
        # Given: user 與其他人各自都有對話
        own = ConversationFactory(user=user)
        other_user = UserFactory()
        ConversationFactory(user=other_user)
        api_client.force_authenticate(user=user)

        # When: 呼叫 GET /api/conversations/
        url = reverse("api:conversations:conversation-list")
        response = api_client.get(url)

        # Then: 只回傳自己的對話
        actual_ids = {item["id"] for item in response.data["results"]}
        assert actual_ids == {str(own.id)}


class TestConversationSearchNormalCase:
    """[5] Happy Path：依關鍵字搜尋命中歷史對話。"""

    def test_search_hits_conversation_by_message_content(self, api_client, user):
        # Given: 使用者的對話 "conv-11" 內有一則訊息 content 為 "請協助退貨"
        conversation = ConversationFactory(user=user)
        MessageFactory(conversation=conversation, content="請協助退貨")
        api_client.force_authenticate(user=user)

        # When: 使用者呼叫 GET /api/conversations/?q=退貨
        url = reverse("api:conversations:conversation-list")
        response = api_client.get(url, {"q": "退貨"})

        # Then: 回應 200，清單包含 "conv-11"
        assert response.status_code == 200
        actual_ids = {item["id"] for item in response.data["results"]}
        assert str(conversation.id) in actual_ids


class TestConversationSearchEdgeCase:
    """[6] Edge Case：關鍵字不存在於任何訊息。"""

    def test_search_with_no_matches_returns_empty_list(self, api_client, user):
        # Given: 使用者的對話內沒有符合關鍵字的訊息
        conversation = ConversationFactory(user=user)
        MessageFactory(conversation=conversation, content="其他內容")
        api_client.force_authenticate(user=user)

        # When: 以不存在的詞搜尋
        url = reverse("api:conversations:conversation-list")
        response = api_client.get(url, {"q": "不存在的詞"})

        # Then: 回傳空清單，200
        assert response.status_code == 200
        assert response.data["results"] == []


class TestConversationSearchErrorCase:
    """[7] Negative（權限）：搜尋結果不含他人對話。"""

    def test_search_does_not_leak_other_users_conversations(self, api_client, user):
        # Given: 使用者 A 的對話含關鍵字 "退貨"，使用者 B（user）搜尋同一關鍵字
        owner = UserFactory()
        owner_conversation = ConversationFactory(user=owner)
        MessageFactory(conversation=owner_conversation, content="請協助退貨")
        api_client.force_authenticate(user=user)

        # When: 使用者 B 呼叫 GET /api/conversations/?q=退貨
        url = reverse("api:conversations:conversation-list")
        response = api_client.get(url, {"q": "退貨"})

        # Then: 回應 200，清單為空（不因關鍵字命中他人資料而洩漏）
        assert response.status_code == 200
        assert response.data["results"] == []


class TestMessageStatusEnsuresSearchVectorIsFilled:
    """[8] Edge Case：訊息儲存後自動填入 search_vector。"""

    def test_saving_message_populates_search_vector(self, user):
        conversation = ConversationFactory(user=user)
        message = MessageFactory(conversation=conversation, content="退貨流程說明")

        message.refresh_from_db()

        assert message.search_vector is not None, (
            "Message 儲存後應自動填入 search_vector 供全文檢索使用"
        )
        assert Message.objects.filter(
            id=message.id,
            search_vector__isnull=False,
        ).exists()
