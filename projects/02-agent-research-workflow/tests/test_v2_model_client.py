"""Provider adapter tests use an in-process HTTP double; no network is opened."""

from __future__ import annotations

import json
import urllib.request

import pytest

from agent_research.v2.model_client import (
    DeepSeekV4FlashClient,
    DeepSeekV4FlashPriceCard,
    ModelClientError,
    ModelResponseContractError,
    _task_contract,
)


def _price_card() -> DeepSeekV4FlashPriceCard:
    return DeepSeekV4FlashPriceCard(
        price_page_url="https://api.example.invalid/pricing",
        price_page_checked_at="2026-09-14T00:00:00Z",
        fx_safety_ceiling_cny_per_usd=10,
        input_cache_hit_minor_per_million=14,
        input_cache_miss_minor_per_million=440,
        output_minor_per_million=1320,
    )


def test_live_model_is_disabled_by_default() -> None:
    client = DeepSeekV4FlashClient(api_key="unused", live=False)
    with pytest.raises(ModelClientError, match="LIVE_MODEL_DISABLED"):
        client.generate(task="review", payload={})


def test_model_configuration_hash_excludes_secret_and_tracks_output_limit() -> None:
    first = DeepSeekV4FlashClient(api_key="first-secret", live=False)
    same = DeepSeekV4FlashClient(api_key="second-secret", live=False)
    changed = DeepSeekV4FlashClient(api_key="first-secret", max_output_tokens=2_999, live=False)
    assert first.config_hash == same.config_hash
    assert first.config_hash != changed.config_hash


def test_draft_and_review_prompts_limit_unknown_to_supplied_read_evidence() -> None:
    for task in ("draft", "review"):
        contract = _task_contract(task)
        assert "this run's supplied read evidence" in contract
        assert "whole frozen snapshot" in contract


def test_draft_prompt_names_the_only_allowed_decision_status_values() -> None:
    contract = _task_contract("draft")
    assert "exactly one of recommended, conditional, or insufficient_evidence" in contract


def test_live_model_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ModelClientError, match="DEEPSEEK_API_KEY_REQUIRED"):
        DeepSeekV4FlashClient(live=True, price_card=_price_card())


@pytest.mark.parametrize("limitations,error", [
    ([], "MODEL_REPORT_NEXT_STEP_REQUIRED"),
    (["下一步验证：用本地测试输入检查输出校验，记录拒绝非法数据的结果。"], "MODEL_REPORT_CONDITIONS_REQUIRED"),
    (["下一步验证：用本地测试输入检查输出校验，记录拒绝非法数据的结果。", "前置条件：团队已经采用类型化输出契约且不要求性能保证。"], None),
])
def test_live_draft_requires_reviewable_next_step_and_conditions(monkeypatch, limitations, error):
    report = {"executive_summary": "条件比较", "decision_status": "conditional", "recommendation": "candidate-a",
              "evidence_cells": [{"candidate_id": "candidate-a", "dimension_id": "state",
                                  "status": "unknown", "claim": "本次已读证据不足"}], "limitations": limitations}
    envelope = {"choices": [{"message": {"content": json.dumps(report)}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps(envelope).encode()
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: Response())
    client = DeepSeekV4FlashClient(api_key="test-key", live=True, price_card=_price_card())
    if error:
        with pytest.raises(ModelResponseContractError, match=error) as caught:
            client.generate(task="draft", payload={})
        assert caught.value.usage.input_tokens == 7
    else:
        result = client.generate(task="draft", payload={})
        assert result.limitations == tuple(limitations)


def test_live_model_requires_a_reviewed_price_card() -> None:
    with pytest.raises(ModelClientError, match="DEEPSEEK_PRICE_CARD_REQUIRED"):
        DeepSeekV4FlashClient(api_key="test-key", live=True)


def test_live_adapter_parses_openai_compatible_json_without_real_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "id": "chatcmpl-test",
        "choices": [{"message": {"content": json.dumps({"review_completed": True, "review_findings": []})}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(request: urllib.request.Request, *, timeout: float):
        assert request.full_url == "https://api.example.invalid/chat/completions"
        assert timeout == 60.0
        body = json.loads(request.data.decode("utf-8"))
        assert body["model"] == "deepseek-flash"
        assert body["max_tokens"] == 3_000
        assert body["response_format"] == {"type": "json_object"}
        assert "Task review" in body["messages"][0]["content"]
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = DeepSeekV4FlashClient(
        api_key="test-key",
        base_url="https://api.example.invalid",
        price_card=_price_card(),
        live=True,
    )
    result = client.generate(task="review", payload={"report": {}})
    assert result.provider == "deepseek"
    assert result.model_id == "deepseek-flash"
    assert result.usage.input_tokens == 7
    assert result.usage.output_tokens == 3
    assert result.usage.cost_status.value == "known"
    assert result.usage.cost_minor_units == 1


def test_usage_parser_keeps_reasoning_token_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "id": "chatcmpl-reasoning",
        "choices": [{"message": {"content": json.dumps({"review_completed": True, "review_findings": []})}}],
        "usage": {
            "prompt_tokens": 7,
            "completion_tokens": 3,
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, *, timeout: FakeResponse())
    result = DeepSeekV4FlashClient(
        api_key="test-key",
        base_url="https://api.example.invalid",
        price_card=_price_card(),
        live=True,
    ).generate(
        task="review", payload={}
    )
    assert result.usage.reasoning_tokens == 2


def test_price_card_uses_cache_miss_rate_and_rounds_up() -> None:
    assert _price_card().estimate_cost_minor_units(input_tokens=1_000_000, output_tokens=0) == 440
    assert _price_card().estimate_cost_minor_units(input_tokens=1, output_tokens=0) == 1


def test_provider_prompt_rejects_unsupported_model_task() -> None:
    client = DeepSeekV4FlashClient(api_key="test-key", price_card=_price_card(), live=True)
    with pytest.raises(ModelClientError, match="MODEL_TASK_UNSUPPORTED"):
        client.generate(task="unsupported", payload={})


def test_invalid_model_result_exposes_only_schema_field_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "id": "0123456789",
        "choices": [{"message": {"content": json.dumps({"tool_calls": []})}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, *, timeout: FakeResponse())
    client = DeepSeekV4FlashClient(api_key="test-key", price_card=_price_card(), live=True)
    with pytest.raises(ModelResponseContractError, match="MODEL_RESULT_CONTRACT_INVALID") as error:
        client.generate(task="plan", payload={})
    assert error.value.usage.cost_status.value == "known"
    assert error.value.usage.cost_minor_units == 1


def test_numeric_provider_response_id_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "id": "0123456789",
        "choices": [{"message": {"content": json.dumps({"review_completed": True, "review_findings": []})}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, *, timeout: FakeResponse())
    result = DeepSeekV4FlashClient(
        api_key="test-key",
        price_card=_price_card(),
        live=True,
    ).generate(task="review", payload={})
    assert result.response_id == "0123456789"
