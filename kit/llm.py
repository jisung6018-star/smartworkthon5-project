"""AI 호출 부품 — Claude(기본) 또는 Gemini(무료 키) 중 있는 키로 같은 함수를 씁니다.

    from kit.llm import ask, ask_json, chat, ask_many

    ask("이 메일을 3줄로 요약해줘", text=본문)
    ask("영수증 내용을 표로 정리해줘", files=["samples/receipt.png"])
    ask_json("발주 내용을 뽑아줘", {"거래처": "str", "납기": "date?",
              "품목": [{"품명": "str", "수량": "int", "단가": "int?"}],
              "긴급도": "높음|보통|낮음"}, text=본문)

간단 스키마 규칙: "str" "int" "float" "bool" "date"(문자열),
    뒤에 ? = 값이 없으면 null,  "A|B|C" = 셋 중 하나,  "int: 설명" = 설명 붙이기,
    [ {...} ] = 목록,  { ... } = 하위 객체. 표준 JSON Schema(dict)도 그대로 받습니다.

공급자 선택: .env 의 LLM_PROVIDER=claude|gemini|mock (비우면 있는 키로 자동, mock=키 없이 흐름 테스트).
응답 캐시(LLM_CACHE=1 기본): 같은 입력은 저장된 답 재사용 → 시연 안정성. 비용: usage_text(per=건수).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable

from . import config  # noqa: F401  (.env 로드)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip()  # 비우면 최신 flash 자동 선택

DEFAULT_SYSTEM = (
    "당신은 한국 중소기업의 실무를 돕는 AI 업무 비서입니다. "
    "한국어로 간결하고 정확하게 답합니다. "
    "주어진 자료에 없는 내용은 지어내지 말고 '확인 필요'라고 표시합니다. "
    "금액·수량·날짜는 자료에 적힌 값을 그대로 옮깁니다."
)

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp"}
AUDIO_TYPES = {".mp3": "audio/mp3", ".wav": "audio/wav", ".m4a": "audio/mp4", ".ogg": "audio/ogg",
               ".flac": "audio/flac", ".aac": "audio/aac"}  # 회의 녹음 → Gemini 만 직접 처리


class LLMError(RuntimeError):
    pass


# ───────────────────────── 공급자 ─────────────────────────
def provider() -> str:
    p = os.getenv("LLM_PROVIDER", "").strip().lower()
    if p:
        return p
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return "claude"
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    raise LLMError("AI API 키가 없습니다. .env 에 ANTHROPIC_API_KEY 또는 GEMINI_API_KEY 를 넣으세요 (README 1단계).")


def status() -> str:
    """화면 표시용: 지금 어떤 AI를 쓰는지."""
    try:
        p = provider()
    except LLMError:
        return "API 키 없음"
    if p == "mock":
        return "Mock (가짜 응답 · 흐름 테스트용)"
    return f"Claude ({CLAUDE_MODEL})" if p == "claude" else f"Gemini ({GEMINI_MODEL or '자동 선택'})"


_claude_client = None
_gemini_client = None
_gemini_resolved: str | None = None


def _claude():
    global _claude_client
    if _claude_client is None:
        import anthropic
        _claude_client = anthropic.Anthropic()
    return _claude_client


def _gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    return _gemini_client


def gemini_model() -> str:
    """GEMINI_MODEL 이 비어 있으면 사용 가능한 최신 정식 flash 모델을 고릅니다."""
    global _gemini_resolved
    if GEMINI_MODEL:
        return GEMINI_MODEL
    if _gemini_resolved:
        return _gemini_resolved
    names = []
    for m in _gemini().models.list():
        name = (m.name or "").removeprefix("models/")
        actions = getattr(m, "supported_actions", None) or []
        if actions and "generateContent" not in actions:
            continue
        if "flash" not in name or any(x in name for x in ("lite", "image", "tts", "audio", "live", "embed")):
            continue
        names.append(name)
    if not names:
        raise LLMError("Gemini flash 모델을 찾지 못했습니다. .env 에 GEMINI_MODEL 을 직접 지정하세요.")

    def rank(n: str):
        mm = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        stable = not any(x in n for x in ("preview", "exp"))
        return (float(mm.group(1)) if mm else 0.0, stable, -len(n))

    _gemini_resolved = max(names, key=rank)
    return _gemini_resolved


# ───────────────────────── 입력 정리 ─────────────────────────
def _image_bytes(p: Path) -> tuple[bytes, str]:
    """큰 이미지는 긴 변 1600px로 줄여서 보냅니다 (속도·비용·용량 제한 대비)."""
    data = p.read_bytes()
    mime = IMAGE_TYPES[p.suffix.lower()]
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        if max(im.size) > 1600 or len(data) > 4_000_000:
            im.thumbnail((1600, 1600))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=88)
            return buf.getvalue(), "image/jpeg"
    except Exception:
        pass
    return data, mime


def _load(f) -> tuple[str, Any, str]:
    p = Path(f)
    ext = p.suffix.lower()
    if ext in IMAGE_TYPES:
        data, mime = _image_bytes(p)
        return "image", data, mime
    if ext == ".pdf":
        return "pdf", p.read_bytes(), "application/pdf"
    if ext in AUDIO_TYPES:
        return "audio", p.read_bytes(), AUDIO_TYPES[ext]
    from .files_in import read_text  # 나머지는 텍스트로 변환해서 전달
    return "text", f"[파일: {p.name}]\n{read_text(p)}", "text/plain"


def _b64(b: bytes) -> str:
    return base64.standard_b64encode(b).decode()


# ───────────────────────── 스키마 ─────────────────────────
_PRIM = {"str": "string", "string": "string", "text": "string", "date": "string", "datetime": "string",
         "int": "integer", "integer": "integer", "float": "number", "number": "number", "num": "number",
         "bool": "boolean", "boolean": "boolean"}


def _strict(s: dict) -> dict:
    """표준 JSON Schema 를 구조화 출력 규칙(additionalProperties:false, 전부 required)에 맞춥니다."""
    s = dict(s)
    if s.get("type") == "object" and "properties" in s:
        s["properties"] = {k: _strict(v) for k, v in s["properties"].items()}
        s["required"] = list(s["properties"])
        s["additionalProperties"] = False
    if s.get("type") == "array" and isinstance(s.get("items"), dict):
        s["items"] = _strict(s["items"])
    for key in ("anyOf", "oneOf"):
        if key in s:
            s[key] = [_strict(x) for x in s[key]]
    return s


def to_json_schema(spec) -> dict:
    """간단 스키마(또는 JSON Schema)를 strict JSON Schema 로 바꿉니다."""
    if isinstance(spec, dict):
        if spec.get("type") == "object" and "properties" in spec:
            return _strict(spec)
        props = {k: to_json_schema(v) for k, v in spec.items()}
        return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
    if isinstance(spec, list):
        return {"type": "array", "items": to_json_schema(spec[0] if spec else "str")}
    if isinstance(spec, str):
        t, _, desc = spec.partition(":")
        t, desc = t.strip(), desc.strip()
        optional = t.endswith("?")
        t = t.rstrip("?").strip()
        if "|" in t:
            base: dict = {"type": "string", "enum": [x.strip() for x in t.split("|") if x.strip()]}
        elif t.lower() in _PRIM:
            base = {"type": _PRIM[t.lower()]}
        else:  # "거래처 이름" 처럼 설명만 쓴 경우 → 문자열
            base, desc = {"type": "string"}, (desc or t)
        if t.lower() == "date":
            desc = f"{desc} (YYYY-MM-DD 형식)" if desc else "YYYY-MM-DD 형식"
        if desc:
            base["description"] = desc
        return {"anyOf": [base, {"type": "null"}]} if optional else base
    if spec in (str, int, float, bool):
        return to_json_schema(spec.__name__)
    raise TypeError(f"스키마를 이해하지 못했습니다: {spec!r}")


def parse_json(text: str) -> Any:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", t, re.S)
        if m:
            return json.loads(m.group(1))
        raise LLMError(f"JSON 해석 실패:\n{text[:500]}")


# ───────────────────────── 사용량·비용 ─────────────────────────
# USD / 1M 토큰 (입력, 출력). Gemini 는 무료 한도 안이면 실제 0원 — 유료 기준 추정치.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50),
          "claude-fable-5-2": (8.0, 40.0), "claude-opus-5": (5.0, 25.0), "claude-sonnet-5": (2.0, 10.0)}
USD_KRW = float(os.getenv("USD_KRW", "1400"))  # 환율 가정 — 발표 때 '가정'이라고 밝히기
_lock = threading.Lock()
USAGE = {"calls": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0}


def _price(model: str) -> tuple[float, float]:
    if model in PRICES:
        return PRICES[model]
    if model.startswith("gemini"):
        return float(os.getenv("GEMINI_PRICE_IN", "0.3")), float(os.getenv("GEMINI_PRICE_OUT", "2.5"))
    return float(os.getenv("PRICE_IN", "4")), float(os.getenv("PRICE_OUT", "20"))


def _record(model: str, inp: int = 0, out: int = 0, cache_read: int = 0, cache_write: int = 0) -> None:
    pin, pout = _price(model)
    usd = (inp * pin + cache_write * pin * 1.25 + cache_read * pin * 0.1 + out * pout) / 1e6
    with _lock:
        USAGE["calls"] += 1
        USAGE["input_tokens"] += inp + cache_read + cache_write
        USAGE["output_tokens"] += out
        USAGE["usd"] += usd


def usage(per: int | None = None) -> dict:
    """누적 사용량. per=처리 건수 를 주면 건당 비용도 계산."""
    with _lock:
        u = dict(USAGE)
    u["krw"] = round(u["usd"] * USD_KRW)
    if per:
        u["krw_per_item"] = round(u["usd"] * USD_KRW / per, 1)
    return u


def usage_text(per: int | None = None) -> str:
    u = usage(per)
    s = (f"AI 호출 {u['calls']}회(캐시 재사용 {u['cache_hits']}회) · 토큰 입력 {u['input_tokens']:,} / 출력 "
         f"{u['output_tokens']:,} · 약 {u['krw']:,}원")
    if per:
        s += f" (건당 약 {u['krw_per_item']:,}원, 환율 {USD_KRW:,.0f}원 가정)"
    return s


def reset_usage() -> None:
    with _lock:
        USAGE.update(calls=0, cache_hits=0, input_tokens=0, output_tokens=0, usd=0.0)


# ───────────────────────── 응답 캐시 ─────────────────────────
# 같은 입력(프롬프트·자료·파일·스키마·모델)이면 저장된 답을 즉시 재사용 → 시연 중 네트워크·한도 장애 대비.
# 끄기: .env 에 LLM_CACHE=0   /  비우기: llm.cache_clear()
CACHE_DIR = config.OUT / ".llm_cache"


def _cache_on() -> bool:
    return os.getenv("LLM_CACHE", "1") != "0"


def _key(*parts) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(json.dumps(part, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
    return h.hexdigest()[:40]


def _file_sig(files) -> list:
    sig = []
    for f in files or []:
        p = Path(f)
        sig.append([p.name, hashlib.sha256(p.read_bytes()).hexdigest()])
    return sig


def _cached(key: str) -> str | None:
    if not _cache_on():
        return None
    f = CACHE_DIR / f"{key}.json"
    if f.exists():
        with _lock:
            USAGE["cache_hits"] += 1
        return json.loads(f.read_text(encoding="utf-8"))["text"]
    return None


def _store(key: str, text: str, meta: dict) -> None:
    if _cache_on() and text:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{key}.json").write_text(json.dumps({"text": text, **meta}, ensure_ascii=False),
                                               encoding="utf-8")


def cache_clear() -> int:
    n = 0
    if CACHE_DIR.exists():
        for f in CACHE_DIR.glob("*.json"):
            f.unlink()
            n += 1
    return n


# ───────────────────────── mock (키 없이 흐름 테스트) ─────────────────────────
def _mock_value(s: dict, name: str = ""):
    if "anyOf" in s:
        return _mock_value(s["anyOf"][0], name)
    if "enum" in s:
        return s["enum"][0]
    t = s.get("type")
    if t == "object":
        return {k: _mock_value(v, k) for k, v in s.get("properties", {}).items()}
    if t == "array":
        return [_mock_value(s.get("items", {}), name) for _ in range(2)]
    if t == "integer":
        return 3
    if t == "number":
        return 1.5
    if t == "boolean":
        return False
    if "YYYY" in s.get("description", ""):
        from datetime import date
        return date.today().isoformat()
    return f"(샘플 {name})"


def _mock(prompt: str, schema: dict | None) -> str:
    time.sleep(0.2)
    if schema:
        return json.dumps(_mock_value(schema), ensure_ascii=False)
    return f"(mock 응답 — 실제 AI 아님) {prompt[:60]}"


# ───────────────────────── 실제 호출 ─────────────────────────
def _call_claude(messages, system, schema, effort, max_tokens) -> str:
    import anthropic
    kw: dict = dict(model=CLAUDE_MODEL, max_tokens=max_tokens, messages=messages)
    if system:
        kw["system"] = system
    oc: dict = {"effort": effort}
    if schema:
        oc["format"] = {"type": "json_schema", "schema": schema}
    kw["output_config"] = oc
    client = _claude()
    try:
        if os.getenv("CLAUDE_FALLBACKS", "1") != "0":
            # 안전 분류기가 거절하면 서버가 다른 모델로 자동 재시도 (server-side fallback)
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        else:
            resp = client.messages.create(**kw)
    except anthropic.AuthenticationError as e:
        raise LLMError("Claude API 키가 잘못됐습니다 (.env 의 ANTHROPIC_API_KEY 확인).") from e
    except anthropic.RateLimitError as e:
        raise LLMError("Claude 사용량 한도(429). 잠시 후 재시도하거나 LLM_PROVIDER=gemini 로 전환하세요.") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("네트워크 오류. 와이파이/핫스팟을 확인하세요.") from e
    u = resp.usage
    _record(CLAUDE_MODEL, getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0,
            getattr(u, "cache_read_input_tokens", 0) or 0, getattr(u, "cache_creation_input_tokens", 0) or 0)
    if resp.stop_reason == "refusal":
        raise LLMError("모델이 요청을 거절했습니다(refusal). 표현을 바꿔 다시 시도하세요.")
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    if resp.stop_reason == "max_tokens":
        if schema:
            raise LLMError("응답이 max_tokens 에서 잘렸습니다. max_tokens 를 늘리거나 자료를 나눠 보내세요.")
        text += "\n\n[⚠ 응답이 길이 제한으로 잘렸습니다]"
    return text


def _call_gemini(contents, system, schema, max_tokens) -> str:
    from google.genai import types
    cfg: dict = dict(max_output_tokens=max_tokens)
    if system:
        cfg["system_instruction"] = system
    if schema:
        cfg["response_mime_type"] = "application/json"
        cfg["response_json_schema"] = schema
    model = gemini_model()
    resp = _gemini().models.generate_content(model=model, contents=contents, config=types.GenerateContentConfig(**cfg))
    um = getattr(resp, "usage_metadata", None)
    if um:
        _record(model, um.prompt_token_count or 0,
                (um.candidates_token_count or 0) + (getattr(um, "thoughts_token_count", 0) or 0))
    return resp.text or ""


def _build(prompt: str, text: str | None, files: Iterable | None, prov: str):
    items = [_load(f) for f in (files or [])]
    if prov == "claude":
        blocks = []
        for kind, data, mime in items:
            if kind == "image":
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": _b64(data)}})
            elif kind == "pdf":
                blocks.append({"type": "document", "source": {"type": "base64", "media_type": mime, "data": _b64(data)}})
            elif kind == "audio":
                raise LLMError("Claude 는 음성 파일을 직접 못 읽습니다 → .env 에 GEMINI_API_KEY 를 넣고 "
                               "LLM_PROVIDER=gemini 로 받아쓰기(transcribe) 후 텍스트로 넘기세요.")
            else:
                blocks.append({"type": "text", "text": data})
        if text:
            blocks.append({"type": "text", "text": f"<자료>\n{text}\n</자료>"})
        blocks.append({"type": "text", "text": prompt})
        return [{"role": "user", "content": blocks}]
    from google.genai import types
    parts: list = []
    for kind, data, mime in items:
        parts.append(types.Part.from_bytes(data=data, mime_type=mime) if kind in ("image", "pdf", "audio") else data)
    if text:
        parts.append(f"<자료>\n{text}\n</자료>")
    parts.append(prompt)
    return parts


def _model_name(prov: str) -> str:
    return CLAUDE_MODEL if prov == "claude" else (GEMINI_MODEL or "gemini-auto") if prov == "gemini" else prov


def _with_retry(fn, retries: int = 2) -> str:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except LLMError:
            raise
        except Exception as e:  # 일시 오류는 짧게 재시도
            msg = str(e)
            if "API key not valid" in msg or "PERMISSION_DENIED" in msg:
                raise LLMError("Gemini API 키가 잘못됐습니다 (.env 의 GEMINI_API_KEY 확인).") from e
            if "NOT_FOUND" in msg and "models/" in msg:
                raise LLMError(f"Gemini 모델 이름 오류: {msg[:120]} → .env 의 GEMINI_MODEL 을 비우거나 고치세요.") from e
            last = e
            time.sleep(1.5 * (attempt + 1) * (4 if "429" in msg or "RESOURCE_EXHAUSTED" in msg else 1))
    raise LLMError(f"AI 호출 실패: {last}")


def _run(prompt, text, files, system, schema, effort, max_tokens, prov: str | None = None) -> str:
    prov = prov or provider()
    system = DEFAULT_SYSTEM if system is None else system
    key = _key(prov, _model_name(prov), system, prompt, text, _file_sig(files), schema, effort, max_tokens)
    hit = _cached(key)
    if hit is not None:
        return hit
    if prov == "mock":
        out = _mock(prompt, schema)
    elif prov in ("claude", "gemini"):
        payload = _build(prompt, text, files, prov)
        if prov == "claude":
            out = _with_retry(lambda: _call_claude(payload, system, schema, effort, max_tokens))
        else:
            out = _with_retry(lambda: _call_gemini(payload, system, schema, max_tokens))
    else:
        raise LLMError(f"모르는 LLM_PROVIDER: {prov} (claude|gemini|mock)")
    if prov != "mock":
        _store(key, out, {"provider": prov, "prompt": prompt[:200]})
    return out


# ───────────────────────── 공개 함수 ─────────────────────────
def ask(prompt: str, text: str | None = None, files: Iterable | None = None, system: str | None = None,
        effort: str = "medium", max_tokens: int = 16000, provider: str | None = None) -> str:
    """자유 형식 답변. text=참고 자료 문자열, files=PDF·이미지·기타 파일 경로 목록. provider 로 모델 회사를 지정할 수 있음."""
    return _run(prompt, text, files, system, None, effort, max_tokens, prov=provider)


def ask_json(prompt: str, schema, text: str | None = None, files: Iterable | None = None,
             system: str | None = None, effort: str = "medium", max_tokens: int = 16000, provider: str | None = None) -> Any:
    """스키마에 맞는 JSON(dict/list)을 돌려줍니다. 목록 스키마([...])도 됩니다."""
    js = to_json_schema(schema)
    wrapped = js.get("type") != "object"
    if wrapped:  # 최상위는 객체여야 하므로 감쌌다가 풉니다
        js = {"type": "object", "properties": {"result": js}, "required": ["result"], "additionalProperties": False}
    data = parse_json(_run(prompt, text, files, system, js, effort, max_tokens, prov=provider))
    return data["result"] if wrapped else data


def chat(history: list[dict], message: str, system: str | None = None, docs: str | None = None,
         effort: str = "low", max_tokens: int = 8000) -> str:
    """대화형(챗봇). history=[{"role":"user"|"assistant","content":str}, ...] (이번 메시지 제외).
    docs 에 사내 규정·매뉴얼 등을 넣으면 그 자료 근거로만 답합니다."""
    prov = provider()
    sys_text = system or DEFAULT_SYSTEM
    if docs:
        sys_text += ("\n\n아래 <자료>에 근거해서만 답하고, 답 끝에 근거 조항/항목을 [근거: ...] 로 표시하세요. "
                     "자료에 없으면 '자료에 없는 내용이라 담당 부서 확인이 필요합니다'라고 답하세요.\n"
                     f"<자료>\n{docs}\n</자료>")
    key = _key("chat", prov, _model_name(prov), sys_text, history, message, effort)
    hit = _cached(key)
    if hit is not None:
        return hit
    if prov == "mock":
        return _mock(message, None)
    if prov == "claude":
        msgs = [{"role": h["role"], "content": h["content"]} for h in history] + [{"role": "user", "content": message}]
        # 긴 자료는 프롬프트 캐시로 두 번째 질문부터 빠르고 싸게
        system_blocks = [{"type": "text", "text": sys_text, "cache_control": {"type": "ephemeral"}}]
        out = _with_retry(lambda: _call_claude(msgs, system_blocks, None, effort, max_tokens))
    else:
        from google.genai import types
        contents = [types.Content(role="model" if h["role"] == "assistant" else "user",
                                  parts=[types.Part.from_text(text=h["content"])]) for h in history]
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))
        out = _with_retry(lambda: _call_gemini(contents, sys_text, None, max_tokens))
    _store(key, out, {"provider": prov, "prompt": message[:200]})
    return out


def transcribe(audio_path, speakers: bool = True) -> str:
    """회의 녹음 → 받아쓰기 텍스트. Gemini 키 필요."""
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")) and provider() != "mock":
        raise LLMError("음성 받아쓰기는 Gemini 키가 필요합니다 (.env 의 GEMINI_API_KEY).")
    how = "화자를 [화자1] [화자2] 처럼 구분하고 " if speakers else ""
    return _run(f"이 음성을 한국어로 빠짐없이 받아쓰세요. {how}요약하지 마세요.", None, [audio_path], "", None,
                "medium", 32000, prov="mock" if provider() == "mock" else "gemini")


def ask_many(items: list, fn: Callable[[Any], Any], workers: int = 4, label: str = "처리") -> list:
    """여러 건을 동시에 처리. 실패한 건은 결과 자리에 Exception 객체가 들어갑니다.
        results = ask_many(files, lambda f: ask_json(PROMPT, SCHEMA, files=[f]))"""
    results: list = [None] * len(items)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, it): i for i, it in enumerate(items)}
        for n, fut in enumerate(as_completed(futs), 1):
            i = futs[fut]
            try:
                results[i] = fut.result()
                mark = "✓"
            except Exception as e:  # noqa: BLE001
                results[i] = e
                mark = f"✗ {e}"
            print(f"  [{label} {n}/{len(items)}] {mark}  ({time.time() - t0:.1f}s)")
    return results
