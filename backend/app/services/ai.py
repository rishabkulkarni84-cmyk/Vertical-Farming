"""Provider-agnostic AI adapter (Google Gemini, Anthropic Claude, OpenAI) over plain HTTPS.

Keys are stored server-side and never sent to the browser. Every AI output is labelled source_type = MODEL
and treated as an estimate the user can correct. When web search is enabled and the provider supports it,
answers are grounded in live web results and the cited sources are returned.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

PROVIDERS = {
    "gemini": {"label": "Google Gemini", "default_model": "gemini-flash-latest"},
    "anthropic": {"label": "Anthropic Claude", "default_model": "claude-sonnet-5-5"},
    "openai": {"label": "OpenAI", "default_model": "gpt-5"},
}
TIMEOUT_S = 90


class AIError(Exception):
    pass


@dataclass
class AIResult:
    text: str
    sources: list[dict] = field(default_factory=list)
    model: str = ""
    provider: str = ""


def _post(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
    return _send(req)


def _get(url: str, headers: dict) -> dict:
    return _send(urllib.request.Request(url, headers=headers, method="GET"))


def _send(req: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            j = json.loads(e.read().decode())
            detail = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else str(j.get("error") or j)
        except Exception:
            pass
        if e.code in (401, 403):
            raise AIError(f"The AI provider rejected the API key ({e.code}). Check the key in Settings. {detail}".strip()) from None
        if e.code == 404:
            raise AIError(f"Model not found for this key ({detail or 'check the model name in Settings'}).") from None
        if e.code == 429:
            raise AIError("The AI provider's rate limit or quota was reached. Try again later or check billing.") from None
        raise AIError(f"AI provider error {e.code}: {detail or e.reason}") from None
    except urllib.error.URLError as e:
        raise AIError(f"Could not reach the AI provider: {e.reason}. Check your internet connection.") from None
    except TimeoutError:
        raise AIError("The AI provider took too long to respond.") from None


# ------------------------------------------------------------------ list models (connection test)

def list_models(provider: str, key: str) -> list[str]:
    if provider == "gemini":
        d = _get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", {"x-goog-api-key": key})
        return sorted(m["name"].removeprefix("models/") for m in d.get("models", [])
                      if "generateContent" in m.get("supportedGenerationMethods", []) and "gemini" in m.get("name", ""))
    if provider == "anthropic":
        d = _get("https://api.anthropic.com/v1/models?limit=100", {"x-api-key": key, "anthropic-version": "2023-06-01"})
        return [m["id"] for m in d.get("data", [])]
    if provider == "openai":
        d = _get("https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"})
        ids = [m["id"] for m in d.get("data", [])]
        return sorted(i for i in ids if i.startswith(("gpt-", "o")) and not any(x in i for x in ("audio", "realtime", "tts", "transcribe", "embedding", "image", "search")))
    raise AIError(f"Unknown provider '{provider}'")


# ------------------------------------------------------------------ generation

def generate(provider: str, key: str, model: str, prompt: str, image: bytes | None = None, mime: str | None = None,
             web_search: bool = False, max_tokens: int = 4000) -> AIResult:
    model = model or PROVIDERS[provider]["default_model"]
    if provider == "gemini":
        parts: list[dict] = [{"text": prompt}]
        if image:
            parts.insert(0, {"inline_data": {"mime_type": mime, "data": base64.b64encode(image).decode()}})
        body: dict = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens}}
        if web_search:
            body["tools"] = [{"google_search": {}}]
        d = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", body, {"x-goog-api-key": key})
        cands = d.get("candidates") or []
        if not cands:
            raise AIError("The AI returned no answer" + (f" ({d['promptFeedback'].get('blockReason')})" if d.get("promptFeedback") else "."))
        text = "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))
        srcs = []
        for ch in (cands[0].get("groundingMetadata") or {}).get("groundingChunks", []) or []:
            w = ch.get("web") or {}
            if w.get("uri"):
                srcs.append({"title": w.get("title") or w["uri"], "url": w["uri"]})
        return AIResult(text, _dedupe(srcs), model, provider)

    if provider == "anthropic":
        content: list[dict] = [{"type": "text", "text": prompt}]
        if image:
            content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(image).decode()}})
        body = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}
        if web_search:
            body["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
        d = _post("https://api.anthropic.com/v1/messages", body, {"x-api-key": key, "anthropic-version": "2023-06-01"})
        text, srcs = "", []
        for b in d.get("content", []):
            if b.get("type") == "text":
                text += b.get("text", "")
                for c in b.get("citations") or []:
                    if c.get("url"):
                        srcs.append({"title": c.get("title") or c["url"], "url": c["url"]})
            elif b.get("type") == "web_search_tool_result" and isinstance(b.get("content"), list):
                for r in b["content"]:
                    if r.get("url"):
                        srcs.append({"title": r.get("title") or r["url"], "url": r["url"]})
        return AIResult(text, _dedupe(srcs), model, provider)

    if provider == "openai":
        content = [{"type": "input_text", "text": prompt}]
        if image:
            content.append({"type": "input_image", "image_url": f"data:{mime};base64,{base64.b64encode(image).decode()}"})
        body = {"model": model, "input": [{"role": "user", "content": content}], "max_output_tokens": max_tokens}
        if web_search:
            body["tools"] = [{"type": "web_search"}]
        d = _post("https://api.openai.com/v1/responses", body, {"Authorization": f"Bearer {key}"})
        text, srcs = d.get("output_text") or "", []
        for item in d.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        if not d.get("output_text"):
                            text += c.get("text", "")
                        for a in c.get("annotations") or []:
                            if a.get("url"):
                                srcs.append({"title": a.get("title") or a["url"], "url": a["url"]})
        return AIResult(text, _dedupe(srcs), model, provider)

    raise AIError(f"Unknown provider '{provider}'")


def _dedupe(srcs: list[dict]) -> list[dict]:
    seen, out = set(), []
    for s in srcs:
        if s["url"] not in seen:
            seen.add(s["url"])
            out.append(s)
    return out[:12]


def extract_json(text: str) -> dict:
    """Parse the first JSON object in a model reply (tolerates code fences and surrounding prose)."""
    t = re.sub(r"```(?:json)?", "", text).strip()
    start = t.find("{")
    if start < 0:
        raise AIError("The AI reply did not contain the expected data. Try again.")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except json.JSONDecodeError as e:
                    raise AIError(f"The AI reply was not valid data ({e.msg}). Try again.") from None
    raise AIError("The AI reply was cut off. Try again.")


# ------------------------------------------------------------------ prompts

ROOM_PROMPT = """You are helping plan an indoor vertical farm. Look at this photo of a room and estimate what you can see.
{known}
Return ONLY a JSON object with this shape (metres; use null when you cannot tell):
{{
  "room": {{"length_m": number|null, "width_m": number|null, "height_m": number|null, "confidence": "low"|"medium"|"high",
            "basis": "what in the photo you used for scale, e.g. door height ~2.0 m"}},
  "light": {{"natural_light": "none"|"low"|"medium"|"high", "notes": string}},
  "floor": string|null,
  "power_outlets_visible": boolean|null,
  "water_source_visible": boolean|null,
  "objects": [{{"kind": "DOOR"|"WINDOW"|"PILLAR"|"FURNITURE"|"EQUIPMENT"|"FIXED", "label": string,
               "wall": "N"|"S"|"E"|"W"|"NONE",
               "x_frac": number, "y_frac": number, "w_m": number, "d_m": number, "height_m": number|null, "confidence": "low"|"medium"|"high"}}],
  "warnings": [string],
  "summary": string
}}
Coordinate convention for objects: imagine a top-down floor plan, origin at the top-left corner; x_frac (0..1) runs along the room LENGTH,
y_frac (0..1) along the WIDTH; the wall the camera faces is "N" (y_frac≈0). x_frac/y_frac are the object's top-left corner as fractions.
Only list objects you can actually see. Do not invent hidden objects. Single photos cannot give exact sizes: be honest about confidence."""

CROP_PROMPT = """You are an agronomy and market advisor for small indoor vertical farms.
Context:
- Location: {location} (lat {lat}, lon {lon}); today's date: {date}; current season (computed): {season}.
- Budget for setup: {budget} {currency}. The budget planner fits about {plants} plant sites on {levels} levels in this room.
- Growing method: {method}. Room temperature: {temp}. Grower experience: {experience}.
- Crops this system can physically grow (rule engine passed them): {candidates}.
{search_line}
Recommend the best 5 crops from that list for MAXIMUM PROFIT right now at this location, considering season, local demand and current
wholesale/retail prices, cycle length and beginner-friendliness. Also say which crops are currently in demand or trending locally and why.
Return ONLY JSON:
{{
  "season_summary": string,
  "recommendations": [{{"slug": one of the candidate slugs, "rank": int, "why": string, "demand_trend": "rising"|"steady"|"falling"|"unknown",
                        "price_per_kg_low": number|null, "price_per_kg_high": number|null, "price_basis": string,
                        "best_selling_channel": string, "risk": string}}],
  "trending_notes": [string],
  "avoid": [{{"slug": string, "reason": string}}],
  "disclaimer": string
}}
Prices must be per kg in {currency}. If you could not verify a price, set it to null rather than guessing."""
