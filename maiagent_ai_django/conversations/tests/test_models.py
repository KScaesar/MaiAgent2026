"""紅燈測試：conversations models。

依據 docs/superpowers/specs/2026-07-10-final-design.md 資料模型設計決策：
- Message 排序：Meta.ordering = ["created", "id"]。
- ModelRoute 排序：Meta.ordering = ["order", "model_name"]。
- 軟刪除：`is_deleted`/`deleted_at`，預設 Manager 排除已刪除紀錄；
  `all_objects` 可查詢包含已刪除的全部紀錄。
"""

from __future__ import annotations

import pytest

from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.models import ModelRoute
from maiagent_ai_django.conversations.models import SceneConfig
from maiagent_ai_django.conversations.tests.factories import ConversationFactory
from maiagent_ai_django.conversations.tests.factories import MessageFactory
from maiagent_ai_django.conversations.tests.factories import ModelRouteFactory
from maiagent_ai_django.conversations.tests.factories import SceneConfigFactory

pytestmark = pytest.mark.django_db


class TestSceneConfigNormalCase:
    """[1] Happy Path：預設值與字串表示。"""

    def test_defaults_are_active_with_empty_settings(self):
        # Given / When: 建立一個未指定 is_active/default_settings 的 SceneConfig
        scene = SceneConfigFactory()

        # Then: 預設為啟用中，且 default_settings 預設為空 dict
        assert scene.is_active is True
        assert scene.default_settings == {}

    def test_str_returns_name(self):
        # Given: 一個具名的 SceneConfig
        scene = SceneConfigFactory(name="customer-service-scene")

        # When / Then: __str__ 回傳名稱
        assert str(scene) == "customer-service-scene"


class TestConversationNormalCase:
    """[2] Happy Path：預設狀態與排序。"""

    def test_default_status_is_open_and_not_deleted(self, user):
        # Given / When: 建立一個未指定 status 的 Conversation
        conversation = ConversationFactory(user=user)

        # Then: 預設狀態為 OPEN，未被軟刪除
        assert conversation.status == Conversation.Status.OPEN
        assert conversation.is_deleted is False
        assert conversation.deleted_at is None

    def test_default_manager_orders_by_created_descending(self, user):
        # Given: 依序建立三筆 Conversation
        first = ConversationFactory(user=user)
        second = ConversationFactory(user=user)
        third = ConversationFactory(user=user)

        # When: 用預設 Manager 取出全部
        actual_ids = list(Conversation.objects.values_list("id", flat=True))

        # Then: 依 created 由新到舊排序
        assert actual_ids == [third.id, second.id, first.id]


class TestConversationEdgeCase:
    """[3] Edge Case：軟刪除排除。"""

    def test_soft_deleted_conversation_excluded_from_default_manager(self, user):
        # Given: 一筆已軟刪除的 Conversation 與一筆正常的 Conversation
        deleted = ConversationFactory(user=user, is_deleted=True)
        active = ConversationFactory(user=user, is_deleted=False)

        # When: 用預設 Manager 查詢
        actual_ids = set(Conversation.objects.values_list("id", flat=True))

        # Then: 已刪除的紀錄被排除，未刪除的仍可查到
        assert deleted.id not in actual_ids
        assert active.id in actual_ids

    def test_all_objects_manager_includes_soft_deleted(self, user):
        # Given: 一筆已軟刪除的 Conversation
        deleted = ConversationFactory(user=user, is_deleted=True)

        # When: 用 all_objects 查詢
        actual_ids = set(Conversation.all_objects.values_list("id", flat=True))

        # Then: 已刪除的紀錄仍可查到
        assert deleted.id in actual_ids


class TestMessageNormalCase:
    """[4] Happy Path：預設狀態與排序。"""

    def test_default_status_is_pending(self):
        # Given / When: 建立一個未指定 status 的 Message（factory 覆寫為 COMPLETED，直接用 model 驗證預設值）
        message = Message(sender_type=Message.SenderType.USER, content="hi")

        # Then: model 欄位預設值為 PENDING
        assert message.status == Message.Status.PENDING

    def test_default_manager_orders_by_created_then_id(self, user):
        # Given: 同一對話下建立三則訊息
        conversation = ConversationFactory(user=user)
        first = MessageFactory(conversation=conversation)
        second = MessageFactory(conversation=conversation)
        third = MessageFactory(conversation=conversation)

        # When: 用預設 Manager 取出全部
        actual_ids = list(
            Message.objects.filter(conversation=conversation).values_list("id", flat=True),
        )

        # Then: 依 created 由舊到新排序（id 為 tie-breaker）
        assert actual_ids == [first.id, second.id, third.id]


class TestMessageEdgeCase:
    """[5] Edge Case：軟刪除排除。"""

    def test_soft_deleted_message_excluded_from_default_manager(self, user):
        # Given: 一筆已軟刪除的 Message
        conversation = ConversationFactory(user=user)
        deleted = MessageFactory(conversation=conversation, is_deleted=True)
        active = MessageFactory(conversation=conversation, is_deleted=False)

        # When: 用預設 Manager 查詢
        actual_ids = set(Message.objects.values_list("id", flat=True))

        # Then: 已刪除的紀錄被排除
        assert deleted.id not in actual_ids
        assert active.id in actual_ids


class TestModelRouteNormalCase:
    """[6] Happy Path：預設值與排序。"""

    def test_defaults_are_enabled_with_weight_one(self):
        # Given / When: 建立一個未指定 weight/is_enabled 的 ModelRoute
        route = ModelRouteFactory()

        # Then: 預設啟用中，weight 為 1
        assert route.is_enabled is True
        assert route.weight == 1

    def test_default_manager_orders_by_order_then_model_name(self):
        # Given: 同一 Scene 下建立三個候選，order 值刻意打亂
        scene = SceneConfigFactory()
        second = ModelRouteFactory(scene=scene, model_name="model-b", order=1)
        first = ModelRouteFactory(scene=scene, model_name="model-a", order=0)
        third = ModelRouteFactory(scene=scene, model_name="model-c", order=1)

        # When: 取出全部
        actual_names = list(
            ModelRoute.objects.filter(scene=scene).values_list("model_name", flat=True),
        )

        # Then: 先依 order 排序，同 order 依 model_name 排序
        assert actual_names == [first.model_name, second.model_name, third.model_name]
