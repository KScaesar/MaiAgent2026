from __future__ import annotations

from rest_framework.permissions import BasePermission


def is_admin(user) -> bool:
    return user.is_superuser or user.groups.filter(name="admin").exists()


def is_customer_service(user) -> bool:
    return user.groups.filter(name="customer_service").exists()


class IsAdmin(BasePermission):
    """僅管理者（is_superuser 或 admin Group）可通過。"""

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user and request.user.is_authenticated and is_admin(request.user),
        )
