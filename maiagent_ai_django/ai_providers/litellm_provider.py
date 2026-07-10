from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from litellm import Router


class LiteLLMProvider:
    """真實呼叫 litellm.Router 的 AI Provider 實作。"""

    def __init__(self, router: Router, model_group: str) -> None:
        self.router = router
        self.model_group = model_group

    def generate(self, **kwargs):
        return self.router.completion(model=self.model_group, **kwargs)
