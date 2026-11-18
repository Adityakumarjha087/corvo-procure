"""AI provider selection and request/response translation (HTTP is faked; no keys or network needed)."""
import base64
import io
import json

import pytest

from app.ai import client


class FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._p, self.text = status, payload, json.dumps(payload)

    def json(self):
        return self._p


@pytest.fixture
def no_keys(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "AI_DISABLED"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_provider_order(no_keys):
    assert client.provider() is None and not client.available()
    no_keys.setenv("GROQ_API_KEY", "g")
    assert client.provider() == "groq"
    no_keys.setenv("GEMINI_API_KEY", "x")
    assert client.provider() == "gemini"
    no_keys.setenv("ANTHROPIC_API_KEY", "a")
    assert client.provider() == "anthropic"
    no_keys.setenv("AI_DISABLED", "1")
    assert client.provider() is None


def test_no_key_raises(no_keys):
    with pytest.raises(client.AIError):
        client.structured("sys", "hi", {"type": "object"})


def test_gemini_translates_blocks_and_parses(no_keys):
    no_keys.setenv("GEMINI_API_KEY", "x")
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, body=json)
        return FakeResp(200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "thinking...", "thought": True}, {"text": '```json\n{"ok": true}\n```'}]}}]})

    no_keys.setattr("httpx.post", fake_post)
    out = client.structured("SYS", [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "QUJD"}},
                                    {"type": "text", "text": "read it"}], {"type": "object"})
    assert out == {"ok": True}
    parts = seen["body"]["contents"][0]["parts"]
    assert parts[0] == {"inline_data": {"mime_type": "application/pdf", "data": "QUJD"}}
    assert parts[1] == {"text": "read it"}
    assert seen["body"]["generationConfig"]["responseJsonSchema"] == {"type": "object"}
    assert seen["headers"]["x-goog-api-key"] == "x"


def test_gemini_retries_without_schema_on_400(no_keys):
    no_keys.setenv("GEMINI_API_KEY", "x")
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json)
        if len(calls) == 1:
            return FakeResp(400, {"error": "unknown field responseJsonSchema"})
        return FakeResp(200, {"candidates": [{"content": {"parts": [{"text": '{"a": 1}'}]}}]})

    no_keys.setattr("httpx.post", fake_post)
    assert client.structured("SYS", "hi", {"type": "object"}) == {"a": 1}
    assert "responseJsonSchema" not in calls[1]["generationConfig"]
    assert "JSON Schema" in calls[1]["system_instruction"]["parts"][0]["text"]


@pytest.mark.parametrize("status,msg", [(401, "rejected"), (429, "rate limited"), (500, r"error \(500\)")])
def test_errors_become_aierror(no_keys, status, msg):
    no_keys.setenv("GROQ_API_KEY", "g")
    no_keys.setattr("httpx.post", lambda *a, **k: FakeResp(status, {}))
    with pytest.raises(client.AIError, match=msg):
        client.structured("SYS", "hi", {"type": "object"})


def _pdf_with_text(text: str) -> str:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    w = PdfWriter()
    page = w.add_blank_page(300, 200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = w._add_object(stream)
    buf = io.BytesIO()
    w.write(buf)
    return base64.standard_b64encode(buf.getvalue()).decode()


def test_groq_sends_pdf_as_text(no_keys):
    no_keys.setenv("GROQ_API_KEY", "g")
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, body=json)
        return FakeResp(200, {"choices": [{"finish_reason": "stop", "message": {"content": '{"operations": []}'}}]})

    no_keys.setattr("httpx.post", fake_post)
    pdf = _pdf_with_text("Spot limit raised to 300000")
    out = client.structured("SYS", [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf}},
                                    {"type": "text", "text": "Return the edit operations."}], {"type": "object"})
    assert out == {"operations": []}
    user = seen["body"]["messages"][1]["content"]
    assert "Spot limit raised to 300000" in user and "Return the edit operations." in user
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["headers"]["Authorization"] == "Bearer g"
    assert "groq.com" in seen["url"]
