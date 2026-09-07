from __future__ import annotations

import logging
import os
import threading
from typing import Any


_BALANCE_ERROR_MARKERS = (
    "insufficient balance",
    "insufficient_balance",
    "insufficient quota",
    "insufficient_quota",
    "余额不足",
)


def _is_balance_error(exc: Exception) -> bool:
    """Return true only for errors that mean the current key cannot be billed."""
    if getattr(exc, "status_code", None) == 402:
        return True

    body = getattr(exc, "body", None)
    error_text = f"{exc} {body}".lower()
    return any(marker in error_text for marker in _BALANCE_ERROR_MARKERS)


class _FallbackCompletions:
    def __init__(self, clients: list[Any]) -> None:
        self._clients = clients
        self._active_index = 0
        self._lock = threading.Lock()

    def create(self, **kwargs: Any) -> Any:
        with self._lock:
            client_index = self._active_index

        try:
            return self._clients[client_index].chat.completions.create(**kwargs)
        except Exception as exc:
            if not _is_balance_error(exc) or client_index + 1 >= len(self._clients):
                raise

            with self._lock:
                if self._active_index == client_index:
                    self._active_index += 1
                    logging.warning("DeepSeek 主 Key 余额不足，已自动切换备用 Key。")
                fallback_index = self._active_index

            return self._clients[fallback_index].chat.completions.create(**kwargs)


class _FallbackChat:
    def __init__(self, clients: list[Any]) -> None:
        self.completions = _FallbackCompletions(clients)


class _FallbackOpenAIClient:
    """Expose the OpenAI chat surface while rotating keys only on billing errors."""

    def __init__(self, clients: list[Any]) -> None:
        self.chat = _FallbackChat(clients)


def create_openai_client(
    api_key: str | None,
    base_url: str | None,
    timeout: float,
    fallback_api_key: str | None = None,
) -> Any:
    if not api_key:
        raise ValueError("缺少 OpenAI API Key。请设置 OPENAI_API_KEY 或通过 --api-key 传入。")

    try:
        from openai import DefaultHttpxClient, OpenAI
    except ImportError as exc:
        raise ImportError("未安装 openai 库，请先执行 `pip install -r requirements.txt`。") from exc

    configured_fallback = fallback_api_key or os.getenv("OPENAI_FALLBACK_API_KEY")
    keys = [api_key]
    if configured_fallback and configured_fallback != api_key:
        keys.append(configured_fallback)

    clients: list[Any] = []
    for key in keys:
        client_kwargs: dict[str, Any] = {
            "api_key": key,
            "timeout": timeout,
            # Windows may retain a stale user proxy even when proxy environment
            # variables are absent. DeepSeek is reachable directly, so avoid a
            # local proxy silently turning every LLM request into a long timeout.
            "http_client": DefaultHttpxClient(timeout=timeout, trust_env=False),
        }
        if base_url:
            client_kwargs["base_url"] = base_url
        clients.append(OpenAI(**client_kwargs))

    if len(clients) == 1:
        return clients[0]
    return _FallbackOpenAIClient(clients)

