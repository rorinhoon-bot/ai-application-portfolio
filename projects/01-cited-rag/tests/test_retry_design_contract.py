from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = PROJECT_ROOT / "docs" / "RETRY_DESIGN.md"


def design_text() -> str:
    return DESIGN_PATH.read_text(encoding="utf-8")


def test_retry_design_is_explicitly_implemented_and_verified() -> None:
    text = design_text()

    assert "accepted；implemented；fake-verified；runtime-verified" in text
    assert "MAX_ATTEMPTS = 2" in text
    assert "最多一次重试" in text
    assert "不调用真实 MiMo" in text


def test_retry_design_has_closed_retry_allowlist() -> None:
    text = design_text()

    assert "仅允许重试：`408`、`429`、`500`、`502`、`503`、`504`" in text
    assert "不重试 `InvalidModelJsonError`、`ModelOutputError`、`InvalidCitationIdError`" in text
    assert "`httpx.ReadTimeout`、`httpx.WriteTimeout`、`httpx.ReadError`、`httpx.WriteError`：默认不重试" in text


def test_retry_design_bounds_delay_and_total_budget() -> None:
    text = design_text()

    assert "250 ms" in text
    assert "0～2 s" in text
    assert "model_timeout_seconds + 2 s" in text
    assert "HTTP-date、负数、非数字和超长值忽略" in text


def test_retry_design_preserves_billing_uncertainty() -> None:
    text = design_text()

    assert "at-least-once 发送，不是 exactly-once" in text
    assert "billing_uncertain" in text
    assert "cost_available=false" in text
    assert "Idempotency-Key" in text


def test_retry_design_requires_offline_tests_and_separate_approval() -> None:
    text = design_text()

    assert "fake-provider 合同" in text
    assert "发布前不运行真实 MiMo" in text
    assert "批准按 RETRY_DESIGN.md 第10.1节执行 V2-D3" in text
    assert "data/retry-runtime-release-report.json" in text
