"""
Thin wrapper around the OpenAI chat completions API.

Design decisions
----------------
- Uses ``gpt-4o-mini`` by default (fast, cheap, sufficient for code review).
  Override with the ``OPENAI_MODEL`` environment variable.
- Maximum output is capped at 500 tokens to keep findings concise.
- Retries once on ``RateLimitError`` after a short sleep.
- All other exceptions are propagated so the caller can log and skip.
"""

from __future__ import annotations

import logging
import os
import time

import openai

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 500
_RETRY_SLEEP_S = 5


def call_openai(system_prompt: str, user_prompt: str) -> str:
    """Call the OpenAI chat completions API and return the response text.

    Parameters
    ----------
    system_prompt:
        The fixed system role message describing the assistant's persona.
    user_prompt:
        The user-turn message containing the assembled context and question.

    Returns
    -------
    str
        The raw text of the first choice's message content.

    Raises
    ------
    openai.OpenAIError
        Any non-rate-limit API error is re-raised after one retry attempt.
    RuntimeError
        If ``OPENAI_API_KEY`` is not set.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY environment variable is not set. "
            "Set it before running the Insight Engine."
        )

    model = os.environ.get("OPENAI_MODEL", _DEFAULT_MODEL)
    client = openai.OpenAI(api_key=api_key)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=_MAX_TOKENS,
                temperature=0.2,
            )
            return response.choices[0].message.content or ""
        except openai.RateLimitError:
            if attempt == 0:
                logger.warning(
                    "OpenAI rate limit hit — retrying in %ds", _RETRY_SLEEP_S
                )
                time.sleep(_RETRY_SLEEP_S)
            else:
                raise

    # Unreachable — loop always returns or raises
    raise RuntimeError("call_openai: unexpected code path")
