"""Minimal client for the System One endpoint (TypeSafe Jev, or OpenRouter reselling it)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=5)  # a voice reply that waits longer is worse than "try again"


class JevError(Exception):
    """The request failed or the reply was unusable; nothing should be executed."""


class JevAuthError(JevError):
    """The API key was rejected."""


class JevClient:
    """POST {base_url}/v1/systemone with state and typed questions."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str, api_key: str, model: str) -> None:
        self._session = session
        self._url = base_url.rstrip("/") + "/v1/systemone"
        self._headers = {"Authorization": f"Bearer {api_key}"}  # never logged
        self.model = model

    async def ask(self, state: Any, questions: dict[str, dict]) -> dict[str, dict]:
        """Return the answers keyed by question id, or raise JevError."""
        start = time.monotonic()
        try:
            async with self._session.post(
                self._url,
                json={"model": self.model, "state": state, "questions": questions},
                headers=self._headers,
                timeout=TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    raise JevAuthError(f"HTTP {resp.status}")
                if resp.status != 200:
                    raise JevError(f"HTTP {resp.status}: {(await resp.text())[:200]}")
                body = await resp.json(content_type=None)
        except TimeoutError as err:
            raise JevError("timeout") from err
        except (aiohttp.ClientError, ValueError) as err:
            raise JevError(type(err).__name__) from err
        ms = (time.monotonic() - start) * 1000
        answers = body.get("answers") if isinstance(body, dict) else None
        if not isinstance(answers, dict) or set(answers) != set(questions):
            raise JevError("reply is missing answers")
        _LOGGER.info(
            "Jev call %.0f ms, %d questions, %s input tokens, model %s",
            ms, len(questions), body.get("usage", {}).get("input_tokens"), body.get("model"),
        )
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Jev answers: %s", json.dumps(answers, ensure_ascii=False))
        return answers
