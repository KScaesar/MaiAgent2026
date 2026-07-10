"""紅燈測試：POST /api/conversations/{id}/sse-ticket/。

依據 docs/superpowers/specs/2026-07-11-spec-by-example.md 功能六 R1。
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from maiagent_ai_django.conversations.tests.factories import ConversationFactory
from maiagent_ai_django.realtime.tickets import consume_ticket
from maiagent_ai_django.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


class TestSSETicketNormalCase:
    """[1] Happy Path：對話擁有者可換得一次性 ticket，且綁定正確的對話。"""

    def test_owner_receives_ticket_bound_to_conversation(self, api_client, user):
        # Given: 使用者已取得有效對話
        conversation = ConversationFactory(user=user)
        api_client.force_authenticate(user=user)

        # When: 呼叫 POST /api/conversations/{id}/sse-ticket/
        url = reverse(
            "api:conversations:sse-ticket",
            args=[conversation.id],
        )
        response = api_client.post(url)

        # Then: 回應含 ticket，且該 ticket 綁定正確的 conversation_id
        assert response.status_code == 201
        ticket = response.data["ticket"]
        payload = consume_ticket(ticket)
        assert payload == {
            "user_id": str(user.id),
            "conversation_id": str(conversation.id),
        }


class TestSSETicketErrorCase:
    """[2] Negative（權限）：非對話擁有者無法換發 ticket。"""

    def test_non_owner_cannot_obtain_ticket(self, api_client, user):
        # Given: 對話屬於另一位使用者
        owner = UserFactory()
        conversation = ConversationFactory(user=owner)
        api_client.force_authenticate(user=user)

        # When: 呼叫 POST /api/conversations/{id}/sse-ticket/
        url = reverse(
            "api:conversations:sse-ticket",
            args=[conversation.id],
        )
        response = api_client.post(url)

        # Then: 403
        assert response.status_code == 403
