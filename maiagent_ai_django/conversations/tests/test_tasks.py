"""紅燈測試：generate_ai_reply Celery task。

依據 docs/superpowers/specs/2026-07-11-spec-by-example.md 功能二。

**設計假設（實作階段可能調整，僅為驅動介面設計的暫定假設）：**
- `maiagent_ai_django.conversations.tasks.get_provider` 是 task 內部用來取得
  `ai_providers.factory.get_provider` 的名稱（測試 patch 這個 import 位置）。
- `maiagent_ai_django.conversations.tasks.push_message_event` 是封裝
  `channel_layer.group_send` 的內部函式，簽名為
  `push_message_event(conversation_id, message_id, status, **extra)`。
- provider.generate() 回傳物件具備 `.model`（成功時的 model 名稱）與
  可透過 `["choices"][0]["message"]["content"]` 或等效方式取出回覆內容。
  本檔以 pytest-mock 動態滿足，不綁死實際的 ModelResponse 型別。
"""

from __future__ import annotations

import pytest

from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.tasks import generate_ai_reply
from maiagent_ai_django.conversations.tests.factories import ConversationFactory
from maiagent_ai_django.conversations.tests.factories import MessageFactory
from maiagent_ai_django.conversations.tests.factories import ModelRouteFactory
from maiagent_ai_django.conversations.tests.factories import SceneConfigFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def scene():
    return SceneConfigFactory()


@pytest.fixture
def conversation(user, scene):
    return ConversationFactory(user=user, scene=scene, status=Conversation.Status.OPEN)


@pytest.fixture
def pending_ai_message(conversation):
    return MessageFactory(
        conversation=conversation,
        sender_type=Message.SenderType.AI,
        status=Message.Status.PENDING,
        content="",
    )


def _fake_success_response(mocker, model_name: str, content: str):
    response = mocker.Mock()
    response.model = model_name
    response.choices = [mocker.Mock(message=mocker.Mock(content=content))]
    return response


class TestGenerateAiReplyNormalCase:
    """[1] Happy Path：AI 生成成功更新訊息並推送事件。"""

    def test_successful_generation_marks_message_completed_with_model_used(
        self,
        scene,
        pending_ai_message,
        mocker,
    ):
        # Given: AI Message status=PENDING，唯一啟用候選模型會成功回應
        ModelRouteFactory(
            scene=scene,
            model_name="gpt-4o-mini",
            order=0,
            is_enabled=True,
        )
        mock_provider = mocker.Mock()
        mock_provider.generate.return_value = _fake_success_response(
            mocker,
            "gpt-4o-mini",
            "AI 回覆內容",
        )
        mocker.patch(
            "maiagent_ai_django.conversations.tasks.get_provider",
            return_value=mock_provider,
        )
        mock_push_event = mocker.patch(
            "maiagent_ai_django.conversations.tasks.push_message_event",
        )

        # When: task 執行
        generate_ai_reply(str(pending_ai_message.id))

        # Then: Message 更新為 COMPLETED，寫入 content / model_used
        pending_ai_message.refresh_from_db()
        expected_status = Message.Status.COMPLETED
        expected_model_used = "gpt-4o-mini"
        expected_content = "AI 回覆內容"
        assert pending_ai_message.status == expected_status, (
            "生成成功時 Message.status 應更新為 COMPLETED"
        )
        assert pending_ai_message.model_used == expected_model_used, (
            "model_used 應取自 provider 回應的 model 欄位"
        )
        assert pending_ai_message.content == expected_content

        # And: 推送 Message 層級的 completed 事件
        mock_push_event.assert_called_once()


class TestGenerateAiReplyErrorCase:
    """[2] Negative：所有候選皆失敗 → FAILED + PENDING_HUMAN。"""

    def test_all_candidates_fail_marks_message_failed_and_conversation_pending_human(
        self,
        scene,
        conversation,
        pending_ai_message,
        mocker,
    ):
        # Given: Router 所有已啟用候選皆失敗
        ModelRouteFactory(scene=scene, model_name="model-a", order=0, is_enabled=True)
        mock_provider = mocker.Mock()
        mock_provider.generate.side_effect = Exception("all enabled candidates failed")
        mocker.patch(
            "maiagent_ai_django.conversations.tasks.get_provider",
            return_value=mock_provider,
        )
        mock_push_event = mocker.patch(
            "maiagent_ai_django.conversations.tasks.push_message_event",
        )

        # When: task 執行
        generate_ai_reply(str(pending_ai_message.id))

        # Then: Message → FAILED，model_used 為 null，error_message 有值
        pending_ai_message.refresh_from_db()
        expected_status = Message.Status.FAILED
        assert pending_ai_message.status == expected_status
        assert pending_ai_message.model_used is None
        assert pending_ai_message.error_message, "失敗時 error_message 應有值"

        # And: Conversation → PENDING_HUMAN
        conversation.refresh_from_db()
        expected_conversation_status = Conversation.Status.PENDING_HUMAN
        assert conversation.status == expected_conversation_status

        # And: 仍推送 Message 層級的 failed 事件（Conversation 狀態轉換本身不推送）
        mock_push_event.assert_called_once()

    def test_task_does_not_use_celery_autoretry_on_generation_failure(
        self,
        scene,
        pending_ai_message,
        mocker,
    ):
        # Given: provider.generate 拋出例外
        ModelRouteFactory(scene=scene, model_name="model-a", order=0, is_enabled=True)
        mock_provider = mocker.Mock()
        mock_provider.generate.side_effect = Exception("systemic outage")
        mocker.patch(
            "maiagent_ai_django.conversations.tasks.get_provider",
            return_value=mock_provider,
        )
        mocker.patch("maiagent_ai_django.conversations.tasks.push_message_event")

        # When / Then: task 本身捕捉例外並正常結束，不重新拋出、不整流程重試
        generate_ai_reply(str(pending_ai_message.id))

        assert mock_provider.generate.call_count == 1, (
            "task 不應對系統性失敗做 Celery autoretry"
        )


class TestGenerateAiReplyEdgeCase:
    """[3] Edge Case：idempotency guard 與歷史查詢防禦性過濾。"""

    def test_non_pending_message_returns_without_side_effects(
        self,
        pending_ai_message,
        mocker,
    ):
        # Given: AI Message 已經是 COMPLETED（模擬重複投遞 / 多 worker 競態）
        pending_ai_message.status = Message.Status.COMPLETED
        pending_ai_message.content = "已經完成的回覆"
        pending_ai_message.model_used = "gpt-4o-mini"
        pending_ai_message.save()

        mock_get_provider = mocker.patch(
            "maiagent_ai_django.conversations.tasks.get_provider",
        )
        mock_push_event = mocker.patch(
            "maiagent_ai_django.conversations.tasks.push_message_event",
        )

        # When: task 被重複呼叫
        generate_ai_reply(str(pending_ai_message.id))

        # Then: idempotency guard 直接 return，無任何副作用
        mock_get_provider.assert_not_called()
        mock_push_event.assert_not_called()
        pending_ai_message.refresh_from_db()
        assert pending_ai_message.content == "已經完成的回覆"

    def test_history_query_excludes_pending_and_failed_messages(
        self,
        scene,
        conversation,
        pending_ai_message,
        mocker,
    ):
        # Given: 對話內混有 PENDING 與 FAILED 的舊訊息（規則被違反的情形）
        MessageFactory(
            conversation=conversation,
            sender_type=Message.SenderType.USER,
            status=Message.Status.COMPLETED,
            content="第一次提問",
        )
        MessageFactory(
            conversation=conversation,
            sender_type=Message.SenderType.AI,
            status=Message.Status.FAILED,
            content="",
        )
        MessageFactory(
            conversation=conversation,
            sender_type=Message.SenderType.USER,
            status=Message.Status.COMPLETED,
            content="第二次提問",
        )
        ModelRouteFactory(scene=scene, model_name="model-a", order=0, is_enabled=True)

        mock_provider = mocker.Mock()
        mock_provider.generate.return_value = _fake_success_response(
            mocker,
            "model-a",
            "回覆",
        )
        mocker.patch(
            "maiagent_ai_django.conversations.tasks.get_provider",
            return_value=mock_provider,
        )
        mocker.patch("maiagent_ai_django.conversations.tasks.push_message_event")

        # When: task 執行
        generate_ai_reply(str(pending_ai_message.id))

        # Then: 傳給 AI 的 messages 只包含 COMPLETED 訊息，不含 FAILED
        _, call_kwargs = mock_provider.generate.call_args
        sent_messages = call_kwargs["messages"]
        sent_contents = [m["content"] for m in sent_messages]

        assert "第一次提問" in sent_contents
        assert "第二次提問" in sent_contents
        assert "" not in sent_contents, "FAILED 的空內容訊息不應進入 LLM context"
