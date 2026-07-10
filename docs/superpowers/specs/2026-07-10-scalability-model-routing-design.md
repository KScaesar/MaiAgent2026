# 擴充性（Scalability）— 多 AI 模型路由設計文件

**日期：** 2026-07-10
**範圍：** PRD「功能需求 - 擴充性」與附加挑戰「多 AI 模型支持」— 設計一個機制，讓每個 Scene 可設定多個候選 AI 模型，由系統依規則自動選擇並容錯，管理人員可動態調整權重
**不涵蓋：** 「回覆模板」路由（僅做模型路由）、AI 自動分類/推論對話所屬場景（場景維持 spec1 既有假設：建立 Conversation 時由外部指定）
**依賴：** [對話管理設計文件](2026-07-08-conversation-management-design.md)（spec1，`SceneConfig` 定義）、[AI 自動回覆流程設計文件](2026-07-09-ai-auto-reply-design.md)（spec2，`ai_providers` 抽象層、Celery 任務，本文件將修正其中部分設計）
**附加挑戰對照：** PRD「進階搜尋功能」已由 spec1（`search_vector`/GIN index）與 spec3（`?q=` 查詢參數）涵蓋，不在本文件重複設計；本文件對應「多 AI 模型支持」。

## 背景

spec1 設計 `SceneConfig.default_settings` 為彈性 JSONField，當時假設一個 Scene 固定對應一個模型（例如 `{"model": "gpt-4o-mini"}`）。spec2 依此假設，在 `ai_providers` 抽象層裡讓呼叫端在每次呼叫時傳入一個固定的 `model` 字串。

PRD「擴充性」需求與附加挑戰明確要求：一個 Scene 應能設定多個候選模型，依權重與優先度自動選擇，並讓管理人員動態調整規則（不需改程式碼、不需重新部署）。本文件設計這個「模型路由」機制，並回頭修正 spec2 裡與此衝突的假設。

## 核心概念澄清

「根據不同場景自動選擇不同的 AI 模型」中的「場景」延續 spec1 既有假設：**場景是建立 Conversation 時由外部（呼叫端）明確指定的固定屬性，不是每次由 AI 重新推論判斷的**。本文件要自動化的「選擇」，指的是「已知場景 → 該場景的候選模型清單 → 依規則挑一個實際呼叫」這一步，而非場景本身的判定。

## 技術選型：litellm.Router

liteLLM 套件本身區分兩個不同定位的 API：

| | `litellm.completion()`（spec2 現況） | `litellm.Router`（本文件採用） |
|---|---|---|
| 定位 | 呼叫單一模型 | 管理多個模型/deployment 的選擇與容錯 |
| `model` 參數意義 | 實際模型名稱字串 | 邏輯分組別名，實際模型清單藏在 `model_list` |
| 失敗處理 | 無內建重試，例外直接拋出 | 內建同層/跨層 failover（`enable_weighted_failover`） |

`Router` 的 `model_list` 設定支援 `order`（數字越小越優先，同 `order` 視為同一層候選）與 `weight`（同層內加權隨機選擇的相對權重），這正好對應本次需要的「分層優先度 + 層內加權隨機 + 跨層 fallback」語意，因此直接採用 `Router` 作為選模引擎，而非自行手刻演算法（避免重複實作並測試套件已提供且經過測試的邏輯）。

**已知落差（供風險評估）：** `Router` 官方文件描述的是啟動時傳入一份靜態 `model_list`，未明確支援「執行中途即時改設定」。解法見下方「Router 重建策略」。

## 資料模型：ModelRoute

```dbml
Table model_routes {
  id uuid [pk]
  scene_id uuid [ref: > scene_configs.id, not null]
  model_name varchar [not null, note: 'litellm 相容的模型名稱字串，如 gpt-4o-mini']
  order integer [not null, note: '對應 litellm.Router 的 order 參數：數字越小越優先，同 order 視為同一層']
  weight integer [not null, default: 1, note: '對應 litellm.Router 的 weight 參數：同一 order 層內的相對權重']
  is_enabled boolean [not null, default: true]
  created timestamptz [not null]
  modified timestamptz [not null]

  indexes {
    (scene_id, order, is_enabled) [name: 'idx_model_routes_scene_order']
  }
}

Ref: model_routes.scene_id > scene_configs.id
```

- `scene_id` 為必填 FK，一對多（一個 Scene 對應多筆 `ModelRoute`，一筆 `ModelRoute` 只屬於一個 Scene）。
- `is_enabled=False` 的路由永遠不會被選中，但保留紀錄方便管理人員暫時停用又快速恢復。
- 不加 `(scene_id, model_name)` 唯一性限制：允許同一模型出現在不同 order 層（YAGNI 原則下不預先禁止，目前無明確需求）。
- 模型識別直接存 litellm 相容字串，不另建模型登錄表——現階段候選模型數量有限，額外一張登錄表帶來的驗證好處不足以抵銷維護成本。

## AI 呼叫抽象層修正（修正 spec2）

### Before（spec2 現況）

```python
# ai_providers/interfaces.py
class AIProvider(ABC):
    @abstractmethod
    async def agenerate(self, model: str, messages: list[dict], **kwargs) -> ModelResponse: ...

# ai_providers/litellm_provider.py
class LiteLLMProvider(AIProvider):
    async def agenerate(self, model: str, messages: list[dict], **kwargs) -> ModelResponse:
        return await litellm.acompletion(model=model, messages=messages, **kwargs)

# ai_providers/factory.py
def get_provider(scene_config) -> AIProvider:
    backend = settings.AI_BACKEND
    return LiteLLMProvider() if backend == "litellm" else DelayedFailureSimulator()

# conversations/tasks.py
@shared_task(autoretry_for=(Exception,), retry_kwargs={"max_retries": 3}, retry_backoff=True)
def generate_ai_reply(ai_message_id):
    ...
    model = conversation.scene.default_settings["model"]  # 單一固定字串
    provider = factory.get_provider(conversation.scene)
    response = await provider.agenerate(model=model, messages=history)
```

### After（本文件設計）

```python
# ai_providers/interfaces.py
class AIProvider(ABC):
    @abstractmethod
    async def agenerate(self, messages: list[dict], **kwargs) -> ModelResponse:
        # 不再吃 model 參數 —— 該用哪些候選模型在建構 provider 時已決定好
        ...

# ai_providers/litellm_provider.py
class LiteLLMProvider(AIProvider):
    def __init__(self, router: litellm.Router, model_group: str):
        self._router = router
        self._model_group = model_group

    async def agenerate(self, messages: list[dict], **kwargs) -> ModelResponse:
        return await self._router.acompletion(model=self._model_group, messages=messages, **kwargs)

# ai_providers/factory.py
def get_provider(scene) -> AIProvider:
    routes = scene.model_routes.filter(is_enabled=True)
    model_group = f"scene-{scene.id}"
    model_list = [
        {
            "model_name": model_group,
            "litellm_params": {"model": r.model_name},
            "order": r.order,
            "weight": r.weight,
        }
        for r in routes
    ]
    router = litellm.Router(model_list=model_list, enable_weighted_failover=True)
    backend = settings.AI_BACKEND
    return (
        LiteLLMProvider(router, model_group)
        if backend == "litellm"
        else DelayedFailureSimulator(router, model_group)
    )

# conversations/tasks.py
@shared_task
def generate_ai_reply(ai_message_id):
    ...
    provider = factory.get_provider(conversation.scene)
    try:
        response = await provider.agenerate(messages=history)
    except Exception as exc:
        ai_message.status = "failed"
        ai_message.error_message = str(exc)
        ai_message.save()
        conversation.status = "pending_human"
        conversation.save()
        return
    ai_message.status = "completed"
    ai_message.content = response.choices[0].message.content
    ai_message.model_used = response.model  # 實際成功呼叫的模型
    ai_message.save()
```

**具體差異：**

1. `AIProvider.agenerate`（及 `generate`/`stream`/`astream`）拿掉 `model` 參數——選模資訊從「呼叫時由外部傳入的字串」變成「建構 provider 時，依 `ModelRoute` DB 資料組出的 `Router` 設定」，因為現在一個 Scene 可能對應多個候選模型，一個字串裝不下這個資訊量。
2. `LiteLLMProvider` 內部改呼叫 `router.acompletion(...)`，而非直接呼叫 `litellm.acompletion(...)`。
3. **取消 Celery `autoretry`**：原本的「有限次數重試 + exponential backoff」由 `Router` 內部的跨層 failover 取代——`Router` 把所有候選模型（依 order 分層、層內加權隨機）都試過仍失敗，才會拋出例外，task 捕捉到即直接判定 `FAILED`，不再對整個流程重跑。理由：`Router` 已經是唯一的失敗容錯機制，額外疊加 Celery 重試等同把「已經試過所有模型都失敗」的流程原封不動再重來一次，多數情況下（如目標 API 本身故障）不會提高成功率，只會拉長總延遲。

### 失敗處理行為（Router 預設）

採用 `Router` 預設行為：同一層內某候選失敗，立即換同層下一個候選；同層都試過仍失敗，才 fallback 到下一個 order 層，直到所有已設定的 order 層都試過仍失敗才真正判定 `FAILED`。

> **取代先前「最多跨 2 個 order 層」的暫定決策**：討論初期曾定過「最多跨 2 層」的上限，是在決定改用 `Router` 原生機制之前的想法。改採 `Router` 開箱即用行為後，不再由程式碼另外裝一層層數上限——candidate 層數多寡完全由管理人員透過 Admin 設定 `ModelRoute` 決定，程式端統一「試到全部候選都試過」。這樣行為更簡單、可預期，且與「一失敗就換候選」的精神一致：候選層數是業務可調參數，不該被寫死的程式邏輯限制。

**不**額外設定 `retry_policy` 對同一 deployment 重試多次——一失敗就換候選，邏輯最簡單、也最貼近套件開箱即用的行為。

### Router 重建策略

不維持一個 process 常駐的 `Router` 物件，而是**每次 Celery task 執行時，即時從 `ModelRoute` 資料表撈出當下設定、動態建構一個新的 `Router` 實例**（`Router` 是輕量記憶體物件，建構成本低）。管理人員在 Django Admin 改權重後，下一次 task 執行就會讀到最新設定，天然滿足「即時生效」需求，不需要自己維護一份 process 內的 cache 失效機制。

**已知代價：** 每次任務多一次 DB 查詢與物件建構；流量大時可考慮短 TTL cache（例如同一 Scene 60 秒內共用同一個 Router 實例），本次設計不做這個最佳化，列入未來擴充。

## Message 新增欄位

`Message` 新增 `model_used`（CharField，nullable）：只有 AI Message 且成功回覆時才有值，取自 `ModelResponse.model`，記錄實際成功呼叫的模型名稱，供日後分析各模型使用比例、成功率，亦是管理人員調整 `ModelRoute` 權重時的參考依據。

## Admin 管理介面

`ModelRoute` 註冊為 `SceneConfig` 的 `TabularInline`：管理人員在 Admin 編輯某個 Scene 頁面時，下方直接顯示候選模型清單（`model_name`、`order`、`weight`、`is_enabled`），編輯儲存即可調整路由規則。

**不額外開 DRF API**：spec3「更新場景設定」API 服務的是前端/其他系統程式化呼叫的情境；`ModelRoute` 目前只設定「管理人員在後台手動操作」這個情境，Django Admin 內建的 inline 編輯機制已足夠，不需要額外寫 serializer/view。

## 已排除方案

- **自行手刻加權隨機 + 分層 + fallback 演算法**——排除，`litellm.Router` 已提供且測試過相同邏輯，自己刻只是重複造輪子，多寫多測沒有額外好處。
- **同一模型重試到上限才 fallback 換下一個**——排除，改採 `Router` 預設「一失敗就換同層下一個候選」，邏輯更簡單且是套件開箱即用行為，不需要額外設定 `retry_policy`。
- **保留 Celery autoretry 疊加在 Router fallback 之上**——排除，`Router` 已經是跨模型的失敗容錯機制，疊加整流程重試只會拉長延遲，對系統性故障（如 API 本身掛掉）沒有幫助。
- **新增 AIModel 登錄表，ModelRoute 用 FK 引用**——排除，現階段候選模型數量有限，多一張表管理的好處不足以抵銷複雜度，直接存 litellm 相容字串即可。
- **回覆模板路由**——排除，PRD 附加挑戰雖提及，但本次聚焦「模型路由」，模板路由涉及 prompt 策略設計，範圍不同，留待未來需求。
- **ModelRoute 調整也開放 DRF API**——排除，目前只有「管理人員後台手動操作」這個情境，Admin inline 已足夠，不需要多一層程式化介面。
- **AI 自動推論場景**——排除，延續 spec1 假設，場景是外部指定的固定屬性，不在本次重新設計。

## 未來擴充 / 已知邊界條件

| 項目 | 現況 | 說明 |
|---|---|---|
| Router 效能最佳化 | 每次 task 即時重建 Router | 流量大時可加短 TTL cache，減少重複查 DB/建構物件 |
| `model_group` 命名 | `f"scene-{scene.id}"`，一對一綁定 Scene | 若未來需要多個 Scene 共用同一組路由設定，需重新設計對應關係 |
| 回覆模板路由 | 未設計 | PRD 附加挑戰提及，範圍與模型路由不同，留待未來需求 |
| ModelRoute 程式化調整 | 僅 Django Admin inline | 若未來有前端/其他系統需要程式化調整權重，需在 spec3 的場景設定 API 上擴充 |
| Router `enable_weighted_failover` 邊界行為 | 依官方文件描述設計，未實際驗證所有 edge case | 例如同層只剩一個候選時的行為，需在實作階段以整合測試驗證 |

## 測試考量

- `factory.get_provider`：驗證依 DB 裡的 `ModelRoute` 資料正確組出 `model_list`（order/weight 對應正確）。
- Failover 行為：用 `DelayedFailureSimulator` 讓特定候選必定失敗，驗證確實 fallback 到下一個候選、且 `model_used` 記錄的是最終成功呼叫的模型。
- 全部候選失敗：驗證 Celery task 捕捉例外後正確轉 `Message.status=failed`、`Conversation.status=pending_human`，且不會觸發整流程重試。
- Admin inline：新增/停用/改權重後，下次任務執行確實讀到最新設定（驗證「即時生效」假設）。
- `Message.model_used`：驗證只有成功的 AI Message 才有值，`FAILED` 狀態的訊息此欄位為 `null`。

## 延伸閱讀

- liteLLM Router: https://docs.litellm.ai/docs/routing
- liteLLM Proxy Reliability (fallback/retry 相關概念): https://docs.litellm.ai/docs/proxy/reliability
