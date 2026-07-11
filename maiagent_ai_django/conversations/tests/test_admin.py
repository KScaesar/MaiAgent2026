"""紅燈測試：conversations Django Admin。

依據 docs/superpowers/specs/2026-07-11-spec-by-example.md 功能四（Admin 相關情境）
與 2026-07-10-final-design.md「Django Admin 管理介面」章節：
- MessageAdmin：content/metadata/error_message/model_used 唯讀（訊息不可變）。
- ConversationAdmin：客服人員（customer_service Group）只能改 status，其餘欄位唯讀；
  管理者可自由調整 status。
"""

from __future__ import annotations

from http import HTTPStatus

import pytest
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.urls import reverse

from maiagent_ai_django.conversations.admin import ConversationAdmin
from maiagent_ai_django.conversations.admin import MessageAdmin
from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.tests.factories import ConversationFactory
from maiagent_ai_django.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


class TestMessageAdminNormalCase:
    """[1] Happy Path：訊息內容欄位一律唯讀。"""

    def test_content_related_fields_are_readonly_for_any_staff(self, rf, admin_user):
        # Given: 一個管理者角色的 request
        request = rf.get("/admin/")
        request.user = admin_user

        # When: 取得 MessageAdmin 的唯讀欄位
        readonly_fields = MessageAdmin(Message, None).get_readonly_fields(request)

        # Then: content/metadata/error_message/model_used 皆唯讀（稽核完整性）
        assert "content" in readonly_fields
        assert "error_message" in readonly_fields
        assert "model_used" in readonly_fields


class TestConversationAdminNormalCase:
    """[2] Happy Path：客服人員可將對話狀態改回 OPEN。"""

    def test_customer_service_can_change_conversation_status_via_admin(self, client):
        # Given: 客服人員屬於 customer_service Group，且有 change_conversation 權限
        cs_user = UserFactory(is_staff=True)
        cs_group, _ = Group.objects.get_or_create(name="customer_service")
        change_perm = Permission.objects.get(
            codename="change_conversation",
            content_type__app_label="conversations",
        )
        view_perm = Permission.objects.get(
            codename="view_conversation",
            content_type__app_label="conversations",
        )
        cs_group.permissions.add(change_perm, view_perm)
        cs_user.groups.add(cs_group)
        cs_user.set_password("pass1234")
        cs_user.save()
        client.force_login(cs_user)

        conversation = ConversationFactory(status=Conversation.Status.PENDING_HUMAN)

        # When: 客服人員在 Django Admin 將狀態改為 OPEN
        url = reverse("admin:conversations_conversation_change", args=[conversation.id])
        response = client.post(
            url,
            {
                "status": Conversation.Status.OPEN,
                "_save": "Save",
            },
        )

        # Then: 成功（redirect 表示 admin 表單處理成功）
        conversation.refresh_from_db()
        assert response.status_code == HTTPStatus.FOUND, response.content
        assert conversation.status == Conversation.Status.OPEN


class TestConversationAdminEdgeCase:
    """[3] Edge Case：客服人員不可修改對話擁有者/場景（僅能調整 status）。"""

    def test_customer_service_readonly_fields_exclude_status(self, rf):
        # Given: 客服人員角色的 request
        cs_user = UserFactory(is_staff=True)
        cs_group, _ = Group.objects.get_or_create(name="customer_service")
        cs_user.groups.add(cs_group)
        request = rf.get("/admin/")
        request.user = cs_user

        # When: 取得 ConversationAdmin 對客服人員顯示的唯讀欄位
        readonly_fields = ConversationAdmin(Conversation, None).get_readonly_fields(
            request,
        )

        # Then: user/scene 唯讀，但 status 不在唯讀清單內（可編輯）
        assert "user" in readonly_fields
        assert "scene" in readonly_fields
        assert "status" not in readonly_fields

    def test_admin_has_no_extra_readonly_restriction_on_user_and_scene(self, rf):
        # Given: 管理者角色的 request
        admin_user = UserFactory(is_staff=True, is_superuser=True)
        request = rf.get("/admin/")
        request.user = admin_user

        # When: 取得 ConversationAdmin 對管理者顯示的唯讀欄位
        readonly_fields = ConversationAdmin(Conversation, None).get_readonly_fields(
            request,
        )

        # Then: 管理者可自由調整 user/scene/status，皆不在唯讀清單內
        assert "user" not in readonly_fields
        assert "scene" not in readonly_fields
        assert "status" not in readonly_fields
