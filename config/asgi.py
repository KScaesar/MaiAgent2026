"""ASGI config for MaiAgent AI Django project.

WSGI + ASGI 並存：一般 REST API 走既有 WSGI（Gunicorn）；本檔僅供
`/sse/...` 長連線端點（Django Channels）使用，其餘路徑委派回 Django 原生
ASGI application。
"""

import os
import sys
from pathlib import Path

from channels.routing import ProtocolTypeRouter
from channels.routing import URLRouter
from django.core.asgi import get_asgi_application
from django.urls import re_path

BASE_DIR = Path(__file__).resolve(strict=True).parent.parent
sys.path.append(str(BASE_DIR / "maiagent_ai_django"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

django_asgi_app = get_asgi_application()

from maiagent_ai_django.realtime.routing import http_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": URLRouter(
            [
                *http_urlpatterns,
                re_path(r"", django_asgi_app),
            ],
        ),
    },
)
