from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


class DelayedFailureSimulator:
    """模擬 AI Provider 呼叫的延遲與失敗，透過 litellm 相容的 mock_response 機制。

    絕不觸發真實外部 API：所有呼叫都經由傳入的 router（litellm.Router 或測試替身）
    的 completion(mock_response=...) 完成。
    """

    def __init__(
        self,
        router,
        model_group: str,
        failure_rate: float = 0.1,
        fail_models: Iterable[str] = frozenset(),
        delay_range: tuple[float, float] = (1, 3),
    ) -> None:
        self.router = router
        self.model_group = model_group
        self.failure_rate = failure_rate
        self.fail_models = set(fail_models)
        self.delay_range = delay_range

    def generate(self, **kwargs):
        low, high = self.delay_range
        time.sleep(random.uniform(low, high))  # noqa: S311

        should_fail = random.random() < self.failure_rate  # noqa: S311
        mock_response = (
            "Exception: DelayedFailureSimulator simulated global failure"
            if should_fail
            else "This is a mocked AI response"
        )

        response = self.router.completion(
            model=self.model_group,
            mock_response=mock_response,
            **kwargs,
        )

        if should_fail:
            msg = "DelayedFailureSimulator: simulated global failure"
            raise RuntimeError(msg)

        return response
