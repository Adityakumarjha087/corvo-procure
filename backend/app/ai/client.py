"""Thin wrapper over the Anthropic SDK: one structured-output call with graceful degradation.

Every AI feature has a deterministic fallback, so the app keeps working without a key.
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("ai")
MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
_client = None


class AIError(RuntimeError):
    pass


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")) and os.getenv("AI_DISABLED", "") != "1"


def _get():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(timeout=120.0, max_retries=2)
    return _client


def structured(system: str, content, schema: dict, effort: str = "low", max_tokens: int = 8000) -> dict:
    """Ask Claude for JSON matching ``schema``. ``content`` is a string or a list of content blocks."""
    if not available():
        raise AIError("AI is not configured (set ANTHROPIC_API_KEY).")
    import anthropic

    kwargs = dict(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    )
    try:
        try:
            # Server-side refusal fallback (recommended for Opus 5.5); fall back to a plain call if unsupported.
            resp = _get().beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        except (TypeError, anthropic.BadRequestError) as e:
            log.info("fallbacks unavailable, plain call: %s", e)
            resp = _get().messages.create(**kwargs)
    except anthropic.AuthenticationError as e:
        raise AIError("The AI key was rejected; check ANTHROPIC_API_KEY.") from e
    except anthropic.RateLimitError as e:
        raise AIError("The AI service is rate limited; try again in a minute.") from e
    except anthropic.APIConnectionError as e:
        raise AIError("Could not reach the AI service.") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"AI service error ({e.status_code}).") from e
    if resp.stop_reason == "refusal":
        raise AIError("The AI declined this request.")
    if resp.stop_reason == "max_tokens":
        raise AIError("The AI response was cut off; try a shorter document.")
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
    if not text:
        raise AIError("The AI returned no answer.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise AIError("The AI returned malformed JSON.") from e
