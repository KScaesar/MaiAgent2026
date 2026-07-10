from __future__ import annotations

import os
from typing import TYPE_CHECKING

from litellm import Router

from maiagent_ai_django.ai_providers.simulator import DelayedFailureSimulator

if TYPE_CHECKING:
    from maiagent_ai_django.conversations.models import SceneConfig


class LiteLLMProvider:
    """真實呼叫 litellm.Router 的 AI Provider 實作。"""

    def __init__(self, router: Router, model_group: str) -> None:
        self.router = router
        self.model_group = model_group

    def generate(self, **kwargs):
        return self.router.completion(model=self.model_group, **kwargs)


def _build_model_list(scene: SceneConfig) -> list[dict]:
    model_group = f"scene-{scene.id}"
    return [
        {
            "model_name": model_group,
            "litellm_params": {"model": route.model_name},
            "model_info": {"id": str(route.id)},
            "order": route.order,
            "weight": route.weight,
        }
        for route in scene.model_routes.filter(is_enabled=True).order_by("order", "model_name")
    ]


def get_provider(scene: SceneConfig):
    """依 Scene 的 ModelRoute 設定組出 Router，回傳可呼叫 generate() 的 provider。

    透過 `AI_BACKEND` 環境變數切換：
    - "litellm"（預設以外的正式環境值）：真實呼叫 litellm.Router。
    - 其他（含未設定，供本機/測試環境使用）：使用 DelayedFailureSimulator 模擬。
    """
    model_group = f"scene-{scene.id}"
    router = Router(model_list=_build_model_list(scene))

    if os.environ.get("AI_BACKEND") == "litellm":
        return LiteLLMProvider(router=router, model_group=model_group)

    return DelayedFailureSimulator(router=router, model_group=model_group)
