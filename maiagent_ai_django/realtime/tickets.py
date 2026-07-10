from __future__ import annotations

import secrets

import redis
from django.conf import settings

DEFAULT_TICKET_TTL_SECONDS = 60


def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL)


def _ticket_key(ticket: str) -> str:
    return f"sse-ticket:{ticket}"


def issue_ticket(
    user_id,
    conversation_id,
    ttl_seconds: int = DEFAULT_TICKET_TTL_SECONDS,
) -> str:
    """發放一次性、短 TTL、綁定 user_id+conversation_id 的 SSE ticket。"""
    ticket = secrets.token_urlsafe(32)
    client = _redis_client()
    key = _ticket_key(ticket)
    with client.pipeline() as pipe:
        pipe.hset(
            key,
            mapping={"user_id": str(user_id), "conversation_id": str(conversation_id)},
        )
        pipe.expire(key, ttl_seconds)
        pipe.execute()
    return ticket


def consume_ticket(ticket: str) -> dict[str, str] | None:
    """原子性地取出並刪除 ticket（一次性使用）；不存在/已使用/過期回傳 None。"""
    client = _redis_client()
    key = _ticket_key(ticket)
    with client.pipeline() as pipe:
        pipe.hgetall(key)
        pipe.delete(key)
        result, _deleted = pipe.execute()
    if not result:
        return None
    return {field.decode(): value.decode() for field, value in result.items()}
