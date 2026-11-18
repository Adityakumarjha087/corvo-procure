"""One structured-output call with graceful degradation.

Providers, in order of preference:
  1. Anthropic Claude   (ANTHROPIC_API_KEY)
  2. Google Gemini      (GEMINI_API_KEY or GOOGLE_API_KEY, free key from Google AI Studio; reads PDFs natively)
  3. Groq               (GROQ_API_KEY, free key from console.groq.com; PDFs are sent as extracted text)
Without either key every AI feature falls back to its deterministic path, so the app keeps working.
Callers pass Anthropic-style content blocks; they are translated for Gemini here.
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("ai")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_client = None


class AIError(RuntimeError):
    pass


def _gemini_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def provider() -> str | None:
    if os.getenv("AI_DISABLED", "") == "1":
        return None
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return "anthropic"
    if _gemini_key():
        return "gemini"
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    return None


def available() -> bool:
    return provider() is not None


def model_name() -> str:
    return {"gemini": GEMINI_MODEL, "groq": GROQ_MODEL}.get(provider() or "", CLAUDE_MODEL)


def structured(system: str, content, schema: dict, effort: str = "low", max_tokens: int = 8000) -> dict:
    """Ask the configured model for JSON matching ``schema``. ``content`` is a string or a list of content blocks."""
    p = provider()
    if p is None:
        raise AIError("AI is not configured (set ANTHROPIC_API_KEY, GEMINI_API_KEY or GROQ_API_KEY).")
    if p == "gemini":
        text = _gemini(system, content, schema, max_tokens)
    elif p == "groq":
        text = _groq(system, content, schema, max_tokens)
    else:
        text = _claude(system, content, schema, effort, max_tokens)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise AIError("The AI returned malformed JSON.") from e


# ---------------------------------------------------------------- Anthropic

def _get():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(timeout=120.0, max_retries=2)
    return _client


def _claude(system: str, content, schema: dict, effort: str, max_tokens: int) -> str:
    import anthropic

    kwargs = dict(
        model=CLAUDE_MODEL,
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
    return text


# ---------------------------------------------------------------- shared helpers

def _check_status(r, key_name: str) -> None:
    if r.status_code in (401, 403):
        raise AIError(f"The AI key was rejected; check {key_name}.")
    if r.status_code == 429:
        raise AIError("The AI service is rate limited; try again in a minute.")
    if r.status_code >= 400:
        raise AIError(f"AI service error ({r.status_code}).")


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    return text


def _pdf_text(b64: str) -> str:
    import base64
    import io

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(base64.standard_b64decode(b64)))
        return "\n".join((pg.extract_text() or "") for pg in reader.pages).strip()
    except Exception as e:  # noqa: BLE001 - any parse failure means we cannot read it
        raise AIError("Could not read text from the PDF.") from e


# ---------------------------------------------------------------- Groq (OpenAI-compatible)

def _groq(system: str, content, schema: dict, max_tokens: int) -> str:
    import httpx

    if isinstance(content, str):
        user = content
    else:
        chunks = []
        for b in content:
            if b.get("type") == "text":
                chunks.append(b["text"])
            elif b.get("type") == "document" and b.get("source", {}).get("media_type") == "application/pdf":
                pdf = _pdf_text(b["source"]["data"])
                if not pdf:
                    raise AIError("The PDF has no extractable text (scanned?); paste the amendment text instead.")
                chunks.append(f"<document>\n{pdf}\n</document>")
        user = "\n\n".join(chunks)
    body = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system + "\n\nReply with a single JSON object only, matching this JSON Schema:\n"
                                              + json.dumps(schema)},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_completion_tokens": max(max_tokens, 8192),
    }
    headers = {"Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '')}", "Content-Type": "application/json"}
    try:
        r = httpx.post(GROQ_URL, headers=headers, json=body, timeout=120.0)
    except httpx.HTTPError as e:
        raise AIError("Could not reach the AI service.") from e
    _check_status(r, "GROQ_API_KEY")
    choice = (r.json().get("choices") or [{}])[0]
    if choice.get("finish_reason") == "length":
        raise AIError("The AI response was cut off; try a shorter document.")
    text = (choice.get("message") or {}).get("content") or ""
    if not text.strip():
        raise AIError("The AI returned no answer.")
    return _strip_fences(text)


# ---------------------------------------------------------------- Gemini

def _gemini_parts(content) -> list[dict]:
    if isinstance(content, str):
        return [{"text": content}]
    parts = []
    for b in content:
        if b.get("type") == "text":
            parts.append({"text": b["text"]})
        elif b.get("type") in ("document", "image") and b.get("source", {}).get("type") == "base64":
            parts.append({"inline_data": {"mime_type": b["source"]["media_type"], "data": b["source"]["data"]}})
    return parts


def _gemini(system: str, content, schema: dict, max_tokens: int) -> str:
    import httpx

    base = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": _gemini_parts(content)}],
    }
    gen = {"responseMimeType": "application/json", "maxOutputTokens": max(max_tokens, 8192)}
    attempts = [
        {**base, "generationConfig": {**gen, "responseJsonSchema": schema}},
        # Older endpoints reject responseJsonSchema: put the schema in the prompt and keep JSON mode.
        {"system_instruction": {"parts": [{"text": system + "\n\nReply with JSON only, matching this JSON Schema:\n"
                                           + json.dumps(schema)}]},
         "contents": base["contents"], "generationConfig": gen},
    ]
    headers = {"x-goog-api-key": _gemini_key() or "", "Content-Type": "application/json"}
    url = GEMINI_URL.format(model=GEMINI_MODEL)
    r = None
    for i, body in enumerate(attempts):
        try:
            r = httpx.post(url, headers=headers, json=body, timeout=120.0)
        except httpx.HTTPError as e:
            raise AIError("Could not reach the AI service.") from e
        if r.status_code == 400 and i == 0:
            log.info("Gemini rejected responseJsonSchema, retrying with schema in prompt: %s", r.text[:300])
            continue
        break
    _check_status(r, "GEMINI_API_KEY")
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        raise AIError("The AI declined this request.")
    cand = cands[0]
    if cand.get("finishReason") == "MAX_TOKENS":
        raise AIError("The AI response was cut off; try a shorter document.")
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []) if not p.get("thought"))
    if not text.strip():
        raise AIError("The AI returned no answer.")
    return _strip_fences(text)
