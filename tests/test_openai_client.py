from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest

from csbaoyan_daily.infra.openai_client import _is_balance_error, create_openai_client


@dataclass
class _Response:
    key: str


class _FakeCompletions:
    def __init__(self, key: str, outcomes: dict[str, list[object]]) -> None:
        self.key = key
        self.outcomes = outcomes

    def create(self, **_kwargs: object) -> object:
        outcome = self.outcomes[self.key].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeOpenAI:
    outcomes: dict[str, list[object]] = {}

    def __init__(self, api_key: str, **_kwargs: object) -> None:
        completions = _FakeCompletions(api_key, self.outcomes)
        self.chat = type("Chat", (), {"completions": completions})()


class _BillingError(Exception):
    status_code = 402


def _make_client(outcomes: dict[str, list[object]]):
    _FakeOpenAI.outcomes = outcomes
    with (
        patch("openai.OpenAI", _FakeOpenAI),
        patch("openai.DefaultHttpxClient", lambda **kwargs: kwargs),
    ):
        return create_openai_client("primary", "https://example.invalid", 12, "fallback")


def test_balance_error_switches_to_fallback_and_stays_there() -> None:
    client = _make_client(
        {
            "primary": [_BillingError("Insufficient Balance")],
            "fallback": [_Response("fallback"), _Response("fallback")],
        }
    )

    assert client.chat.completions.create().key == "fallback"
    assert client.chat.completions.create().key == "fallback"


def test_timeout_does_not_consume_fallback_key() -> None:
    client = _make_client(
        {
            "primary": [TimeoutError("network timeout")],
            "fallback": [_Response("fallback")],
        }
    )

    with pytest.raises(TimeoutError):
        client.chat.completions.create()


def test_balance_detection_accepts_provider_error_code() -> None:
    error = RuntimeError("provider error")
    error.body = {"error": {"code": "insufficient_balance"}}  # type: ignore[attr-defined]

    assert _is_balance_error(error)
