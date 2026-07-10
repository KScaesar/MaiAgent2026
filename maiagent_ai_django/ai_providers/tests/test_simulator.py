"""紅燈測試：DelayedFailureSimulator。

依據 docs/superpowers/specs/2026-07-11-spec-by-example.md 功能三。

**設計假設（驅動介面設計的暫定簽名）：**
    DelayedFailureSimulator(
        router,
        model_group: str,
        failure_rate: float = 0.1,
        fail_models: set[str] = frozenset(),
        delay_range: tuple[float, float] = (1, 3),
    )
"""

from __future__ import annotations

import pytest

from maiagent_ai_django.ai_providers.simulator import DelayedFailureSimulator


class FakeRouter:
    """測試用假 Router：只記錄呼叫參數，絕不接觸真實網路。"""

    def __init__(self, response=None, raise_error: Exception | None = None):
        self.calls: list[dict] = []
        self._response = response
        self._raise_error = raise_error

    def completion(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise_error is not None:
            raise self._raise_error
        return self._response


class TestDelayedFailureSimulatorNormalCase:
    """[1] Happy Path：不觸發真實外部 API，回傳結構與 Router 呼叫一致。"""

    def test_generate_returns_router_response_via_mock_response_param(self, mocker):
        # Given: fail_models 為空、全域失敗機率為 0
        mocker.patch("time.sleep")
        fake_response = object()
        router = FakeRouter(response=fake_response)
        simulator = DelayedFailureSimulator(
            router=router,
            model_group="scene-1",
            failure_rate=0.0,
            fail_models=set(),
            delay_range=(0, 0),
        )

        # When: 呼叫 generate()
        actual_response = simulator.generate(messages=[{"role": "user", "content": "hi"}])

        # Then: 回傳值就是 router.completion() 的回傳值
        assert actual_response is fake_response

        # And: 呼叫帶有 mock_response 參數，絕不觸發真實外部 API
        assert len(router.calls) == 1, "應恰好呼叫 router.completion 一次"
        assert "mock_response" in router.calls[0], (
            "呼叫必須帶 mock_response，保證不會真的打外部 API"
        )


class TestDelayedFailureSimulatorEdgeCase:
    """[2] Edge Case：延遲範圍、同層單一候選必敗。"""

    def test_delay_falls_within_configured_range(self, mocker):
        # Given: 延遲範圍設為 1~3 秒
        mock_sleep = mocker.patch("time.sleep")
        router = FakeRouter(response=object())
        simulator = DelayedFailureSimulator(
            router=router,
            model_group="scene-1",
            failure_rate=0.0,
            fail_models=set(),
            delay_range=(1, 3),
        )

        # When: 呼叫 generate()
        simulator.generate(messages=[{"role": "user", "content": "hi"}])

        # Then: time.sleep 恰好被呼叫一次，且延遲秒數落在設定範圍內
        mock_sleep.assert_called_once()
        (actual_delay_seconds,), _ = mock_sleep.call_args
        assert 1 <= actual_delay_seconds <= 3, (
            f"延遲秒數 {actual_delay_seconds} 應落在設定範圍 1~3 秒內"
        )

    def test_only_candidate_in_fail_models_results_in_call_failure(self, mocker):
        # Given: 同一層（同 order）只有一個候選，且該候選被指定為必敗
        mocker.patch("time.sleep")
        router = FakeRouter(raise_error=Exception("candidate failed"))
        simulator = DelayedFailureSimulator(
            router=router,
            model_group="scene-1",
            failure_rate=0.0,
            fail_models={"model-a"},
            delay_range=(0, 0),
        )

        # When / Then: 呼叫應拋出例外（無其他同層候選可切換）
        with pytest.raises(Exception, match="candidate failed"):
            simulator.generate(messages=[{"role": "user", "content": "hi"}])


class TestDelayedFailureSimulatorErrorCase:
    """[3] Negative：全域失敗機率生效。"""

    def test_global_failure_rate_100_percent_always_raises(self, mocker):
        # Given: 全域失敗機率設為 100%
        mocker.patch("time.sleep")
        router = FakeRouter(raise_error=Exception("simulated failure"))
        simulator = DelayedFailureSimulator(
            router=router,
            model_group="scene-1",
            failure_rate=1.0,
            fail_models=set(),
            delay_range=(0, 0),
        )

        # When / Then: 呼叫恆定拋出例外
        with pytest.raises(Exception, match="simulated failure"):
            simulator.generate(messages=[{"role": "user", "content": "hi"}])

    def test_failure_rate_statistics_approximate_configured_probability(self, mocker):
        # Given: 全域失敗機率設為 50%
        mocker.patch("time.sleep")
        router = FakeRouter(response=object())
        simulator = DelayedFailureSimulator(
            router=router,
            model_group="scene-1",
            failure_rate=0.5,
            fail_models=set(),
            delay_range=(0, 0),
        )

        # When: 觀察大量呼叫下的失敗次數
        attempts = 2000
        failures = 0
        for _ in range(attempts):
            try:
                simulator.generate(messages=[{"role": "user", "content": "hi"}])
            except Exception:  # noqa: BLE001, PERF203
                failures += 1

        # Then: 失敗比例應接近設定機率（容許統計誤差）
        observed_failure_rate = failures / attempts
        assert 0.4 <= observed_failure_rate <= 0.6, (
            f"觀察到的失敗率 {observed_failure_rate} 應接近設定值 0.5"
        )
