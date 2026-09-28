from types import SimpleNamespace

from cortexa.agents.usage import UsageTotals


def test_sums_provider_usage_across_tool_rounds():
    usage = UsageTotals()
    usage.add(SimpleNamespace(usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}))
    usage.add(SimpleNamespace(usage_metadata={"input_tokens": 150, "output_tokens": 40, "total_tokens": 190}))
    assert usage.stats()["token_count"] == 310
    assert usage.stats()["input_tokens"] == 250
    assert usage.stats()["output_tokens"] == 60
    assert usage.stats()["usage_complete"]


def test_missing_usage_is_not_zero_and_partial_usage_is_flagged():
    usage = UsageTotals()
    usage.add(SimpleNamespace(content="arbitrary streamed text"))
    assert usage.stats()["token_count"] is None
    usage.add(SimpleNamespace(response_metadata={"token_usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}}))
    assert usage.stats()["token_count"] == 15
    assert not usage.stats()["usage_complete"]


def test_reported_zero_usage_is_available():
    usage = UsageTotals()
    usage.add(SimpleNamespace(usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}))
    assert usage.stats()["token_count"] == 0
    assert usage.stats()["usage_complete"]
