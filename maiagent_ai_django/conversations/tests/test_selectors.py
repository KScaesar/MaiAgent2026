"""單元測試：conversations/selectors.py。

對應重構後新增的 selector 層，補上 API 測試（黑箱）未直接涵蓋的函式層級案例。
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group

from maiagent_ai_django.conversations.models import SceneConfig
from maiagent_ai_django.conversations.selectors import conversation_can_be_viewed_by
from maiagent_ai_django.conversations.selectors import conversation_list_visible_to
from maiagent_ai_django.conversations.tests.factories import ConversationFactory
from maiagent_ai_django.conversations.tests.factories import SceneConfigFactory
from maiagent_ai_django.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


class TestConversationCanBeViewedByNormalCase:
    """[1] Happy Path：擁有者／管理者／客服（客服場景）皆可檢視。"""

    def test_owner_can_view_own_conversation(self, user):
        conversation = ConversationFactory(user=user)

        assert conversation_can_be_viewed_by(conversation=conversation, user=user)

    def test_admin_can_view_any_conversation(self, user):
        admin_group, _ = Group.objects.get_or_create(name="admin")
        user.groups.add(admin_group)
        conversation = ConversationFactory(user=UserFactory())

        assert conversation_can_be_viewed_by(conversation=conversation, user=user)

    def test_customer_service_can_view_conversation_in_customer_service_scene(
        self,
        user,
    ):
        cs_group, _ = Group.objects.get_or_create(name="customer_service")
        user.groups.add(cs_group)
        cs_scene = SceneConfigFactory(scene_type=SceneConfig.SceneType.CUSTOMER_SERVICE)
        conversation = ConversationFactory(user=UserFactory(), scene=cs_scene)

        assert conversation_can_be_viewed_by(conversation=conversation, user=user)


class TestConversationCanBeViewedByErrorCase:
    """[2] Negative：非本人、非管理者、非對應場景客服，皆不可檢視。"""

    def test_regular_user_cannot_view_others_conversation(self, user):
        conversation = ConversationFactory(user=UserFactory())

        assert not conversation_can_be_viewed_by(conversation=conversation, user=user)

    def test_customer_service_cannot_view_conversation_outside_their_scene(self, user):
        cs_group, _ = Group.objects.get_or_create(name="customer_service")
        user.groups.add(cs_group)
        km_scene = SceneConfigFactory(
            scene_type=SceneConfig.SceneType.KNOWLEDGE_MANAGEMENT,
        )
        conversation = ConversationFactory(user=UserFactory(), scene=km_scene)

        assert not conversation_can_be_viewed_by(conversation=conversation, user=user)


class TestConversationListVisibleToNormalCase:
    """[3] Happy Path：依角色回傳的可見範圍。"""

    def test_regular_user_sees_only_own_conversations(self, user):
        own = ConversationFactory(user=user)
        ConversationFactory(user=UserFactory())

        visible = conversation_list_visible_to(user=user)

        assert set(visible.values_list("id", flat=True)) == {own.id}

    def test_admin_sees_all_conversations(self, user):
        admin_group, _ = Group.objects.get_or_create(name="admin")
        user.groups.add(admin_group)
        conv_a = ConversationFactory(user=user)
        conv_b = ConversationFactory(user=UserFactory())

        visible = conversation_list_visible_to(user=user)

        assert set(visible.values_list("id", flat=True)) == {conv_a.id, conv_b.id}

    def test_customer_service_sees_only_customer_service_scene_conversations(
        self,
        user,
    ):
        cs_group, _ = Group.objects.get_or_create(name="customer_service")
        user.groups.add(cs_group)
        cs_scene = SceneConfigFactory(scene_type=SceneConfig.SceneType.CUSTOMER_SERVICE)
        km_scene = SceneConfigFactory(
            scene_type=SceneConfig.SceneType.KNOWLEDGE_MANAGEMENT,
        )
        cs_conversation = ConversationFactory(user=UserFactory(), scene=cs_scene)
        ConversationFactory(user=UserFactory(), scene=km_scene)

        visible = conversation_list_visible_to(user=user)

        assert set(visible.values_list("id", flat=True)) == {cs_conversation.id}
