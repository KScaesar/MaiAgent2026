"""紅燈測試：ai_providers.factory.get_provider。

依據 docs/superpowers/specs/2026-07-10-final-design.md「AI 呼叫抽象層」章節：
- get_provider(scene) 依 scene.model_routes（is_enabled=True）組出 litellm.Router 的
  model_list（order/weight 對應 ModelRoute 欄位）。
- AI_BACKEND 環境變數為 "litellm" 時回傳 LiteLLMProvider，其餘（含未設定）回傳
  DelayedFailureSimulator。
"""

from __future__ import annotations

import pytest

from maiagent_ai_django.ai_providers.factory import get_provider
from maiagent_ai_django.ai_providers.factory import _build_model_list
from maiagent_ai_django.ai_providers.litellm_provider import LiteLLMProvider
from maiagent_ai_django.ai_providers.simulator import DelayedFailureSimulator
from maiagent_ai_django.conversations.tests.factories import ModelRouteFactory
from maiagent_ai_django.conversations.tests.factories import SceneConfigFactory

pytestmark = pytest.mark.django_db


class TestBuildModelListNormalCase:
    """[1] Happy Path：依 ModelRoute 組出符合 litellm 慣例的 model_list。"""

    def test_enabled_routes_are_mapped_with_order_and_weight(self):
        # Given: 一個 Scene 有兩層候選（order 0 / order 1），皆啟用
        scene = SceneConfigFactory()
        ModelRouteFactory(scene=scene, model_name="model-a", order=0, weight=2, is_enabled=True)
        ModelRouteFactory(scene=scene, model_name="model-b", order=1, weight=1, is_enabled=True)

        # When: 組出 model_list
        model_list = _build_model_list(scene)

        # Then: 每個候選都對應到 litellm_params.model / order / weight
        expected_model_group = f"scene-{scene.id}"
        actual_by_model = {
            entry["litellm_params"]["model"]: entry for entry in model_list
        }
        assert len(model_list) == 2, "應包含全部兩個啟用中的候選"
        assert actual_by_model["model-a"]["order"] == 0
        assert actual_by_model["model-a"]["weight"] == 2
        assert actual_by_model["model-a"]["model_name"] == expected_model_group
        assert actual_by_model["model-b"]["order"] == 1
        assert actual_by_model["model-b"]["weight"] == 1


class TestBuildModelListEdgeCase:
    """[2] Edge Case：停用中的候選應被排除。"""

    def test_disabled_routes_are_excluded(self):
        # Given: 其中一個候選 is_enabled=False
        scene = SceneConfigFactory()
        ModelRouteFactory(scene=scene, model_name="model-a", order=0, is_enabled=True)
        ModelRouteFactory(scene=scene, model_name="model-b", order=1, is_enabled=False)

        # When: 組出 model_list
        model_list = _build_model_list(scene)

        # Then: 只包含啟用中的候選
        actual_model_names = [entry["litellm_params"]["model"] for entry in model_list]
        assert actual_model_names == ["model-a"]

    def test_no_enabled_routes_results_in_empty_model_list(self):
        # Given: Scene 沒有任何啟用中的候選
        scene = SceneConfigFactory()
        ModelRouteFactory(scene=scene, model_name="model-a", order=0, is_enabled=False)

        # When: 組出 model_list
        model_list = _build_model_list(scene)

        # Then: 回傳空陣列（Router 無可用候選）
        assert model_list == []


class TestGetProviderNormalCase:
    """[3] Happy Path：依 AI_BACKEND 環境變數選擇 provider 實作。"""

    def test_ai_backend_litellm_returns_lite_llm_provider(self, monkeypatch):
        # Given: AI_BACKEND 設定為 "litellm"
        monkeypatch.setenv("AI_BACKEND", "litellm")
        scene = SceneConfigFactory()
        ModelRouteFactory(scene=scene, model_name="gpt-4o-mini", order=0)

        # When: 取得 provider
        provider = get_provider(scene)

        # Then: 回傳 LiteLLMProvider
        assert isinstance(provider, LiteLLMProvider)

    def test_ai_backend_unset_defaults_to_simulator(self, monkeypatch):
        # Given: AI_BACKEND 未設定（模擬本機/測試環境）
        monkeypatch.delenv("AI_BACKEND", raising=False)
        scene = SceneConfigFactory()
        ModelRouteFactory(scene=scene, model_name="gpt-4o-mini", order=0)

        # When: 取得 provider
        provider = get_provider(scene)

        # Then: 回傳 DelayedFailureSimulator
        assert isinstance(provider, DelayedFailureSimulator)


class TestGetProviderEdgeCase:
    """[4] Edge Case：非 "litellm" 的其他任意值也應 fallback 到 simulator。"""

    def test_ai_backend_arbitrary_value_falls_back_to_simulator(self, monkeypatch):
        # Given: AI_BACKEND 設定為未知值
        monkeypatch.setenv("AI_BACKEND", "something-else")
        scene = SceneConfigFactory()
        ModelRouteFactory(scene=scene, model_name="gpt-4o-mini", order=0)

        # When: 取得 provider
        provider = get_provider(scene)

        # Then: 回傳 DelayedFailureSimulator（安全預設值）
        assert isinstance(provider, DelayedFailureSimulator)
