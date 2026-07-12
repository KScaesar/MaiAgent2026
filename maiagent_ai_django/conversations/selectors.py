from __future__ import annotations

from typing import TYPE_CHECKING

from maiagent_ai_django.api.permissions import is_admin
from maiagent_ai_django.api.permissions import is_customer_service
from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import SceneConfig

if TYPE_CHECKING:
    from maiagent_ai_django.users.models import User


def conversation_can_be_viewed_by(
    *,
    conversation: Conversation,
    user: User,
) -> bool:
    """本人／管理者／客服（僅限客服場景）三種角色可檢視同一份 Conversation。"""
    return (
        conversation.user_id == user.id
        or is_admin(user)
        or (
            is_customer_service(user)
            and conversation.scene.scene_type == SceneConfig.SceneType.CUSTOMER_SERVICE
        )
    )


def conversation_list_visible_to(*, user: User):
    """依角色回傳 Conversation 的可見範圍（權限矩陣核心邏輯）。"""
    if is_admin(user):
        return Conversation.objects.all()
    if is_customer_service(user):
        return Conversation.objects.filter(
            scene__scene_type=SceneConfig.SceneType.CUSTOMER_SERVICE,
        )
    return Conversation.objects.filter(user=user)
