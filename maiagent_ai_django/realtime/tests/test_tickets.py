"""紅燈測試：realtime.tickets（SSE 一次性 ticket）。

依據 docs/superpowers/specs/2026-07-11-spec-by-example.md 功能六 R1/R2。
"""

from __future__ import annotations

import time

from maiagent_ai_django.realtime.tickets import consume_ticket
from maiagent_ai_django.realtime.tickets import issue_ticket


class TestIssueAndConsumeTicketNormalCase:
    """[1] Happy Path：發放的 ticket 可被消費一次，取得綁定的資訊。"""

    def test_consume_returns_bound_user_and_conversation(self):
        # Given: 為某使用者與對話發放 ticket
        ticket = issue_ticket(user_id=1, conversation_id="conv-1")

        # When: 消費該 ticket
        payload = consume_ticket(ticket)

        # Then: 回傳綁定的 user_id / conversation_id
        assert payload == {"user_id": "1", "conversation_id": "conv-1"}


class TestConsumeTicketErrorCase:
    """[2] Negative：一次性使用後即失效；不存在/過期的 ticket 拒絕。"""

    def test_ticket_is_single_use(self):
        # Given: 使用者已取得 ticket 並成功消費一次
        ticket = issue_ticket(user_id=1, conversation_id="conv-1")
        consume_ticket(ticket)

        # When: 再次消費同一 ticket
        second_payload = consume_ticket(ticket)

        # Then: 第二次消費失敗（回傳 None）
        assert second_payload is None

    def test_nonexistent_ticket_returns_none(self):
        # Given / When: 消費一個從未發放過的 ticket
        payload = consume_ticket("never-issued-ticket")

        # Then: 回傳 None
        assert payload is None

    def test_expired_ticket_returns_none(self):
        # Given: 一個 TTL 極短的 ticket，且已超過 TTL
        ticket = issue_ticket(user_id=1, conversation_id="conv-1", ttl_seconds=1)
        time.sleep(1.5)

        # When: 消費已過期的 ticket
        payload = consume_ticket(ticket)

        # Then: 回傳 None
        assert payload is None
