# ====================================================
# 모듈: AI 공급자 선택기 (ai_provider.py)
#
# 같은 일(이미지 보기 / 글쓰기)을 Claude(유료) 또는
# Gemini(무료 할당량)로 처리할 수 있게 해 줍니다.
#
# Gemini는 REST로 직접 부릅니다.
#   - 추가 설치가 필요 없습니다 (requests만 씁니다)
#   - SDK 버전이 바뀌어도 깨지지 않습니다
# ====================================================

import json
import os
import re
from typing import Optional

import requests
from loguru import logger


# ── 공급자 ────────────────────────────────────────
PROVIDER_CLAUDE = "claude"
PROVIDER_GEMINI = "gemini"

PROVIDER_LABELS = {
    PROVIDER_GEMINI: "🆓 Google Gemini (무료 할당량)",
    PROVIDER_CLAUDE: "💳 Anthropic Claude (유료·고품질)",
}

# ── Gemini 설정 ───────────────────────────────────
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# 무료 할당량에서 쓸 수 있는 모델들.
# 앞에서부터 시도하고, 한도 초과(429)나 없는 모델(404)이면 다음 걸로 넘어갑니다.
GEMINI_FALLBACK_CHAIN = [
    "gemini-3.5-flash-lite",   # 무료 하루 요청수가 가장 넉넉합니다
    "gemini-3.8-flash",        # 품질이 더 좋지만 무료 한도가 빡빡합니다
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",        # 구버전 (아직 살아있는 계정용)
]

GEMINI_TIMEOUT = 180


class ProviderError(RuntimeError):
    """공급자 호출 실패 (사용자에게 그대로 보여 줄 메시지를 담습니다)."""


# ══════════════════════════════════════════════════
# Gemini 호출
# ══════════════════════════════════════════════════

def _gemini_call(
    api_key: str,
    model: str,
    prompt: str,
    system: str = "",
    images: Optional[list] = None,
    max_tokens: int = 8000,
    temperature: float = 0.9,
) -> tuple:
    """Gemini 한 번 호출. (raw_text, usage_dict) 반환. 실패하면 예외."""

    parts = []

    # 이미지 먼저, 그 다음 지시문 (Claude 쪽 구성과 동일하게 맞췄습니다)
    for b64_data, media_type in (images or []):
        parts.append({
            "inline_data": {
                "mime_type": media_type,
                "data": b64_data,
            }
        })
    parts.append({"text": prompt})

    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": temperature,
            # Gemini 3.x 는 '생각'에도 출력 토큰을 씁니다.
            # 넉넉히 주지 않으면 생각만 하다 끝나 빈 응답이 옵니다.
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    url = f"{GEMINI_BASE}/{model}:generateContent"
    resp = requests.post(
        url,
        params={"key": api_key},
        json=body,
        timeout=GEMINI_TIMEOUT,
    )

    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except Exception:
            detail = resp.text[:300]
        raise ProviderError(f"[{resp.status_code}] {detail}")

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        blocked = data.get("promptFeedback", {}).get("blockReason")
        if blocked:
            raise ProviderError(f"Gemini 안전필터에 걸렸습니다 ({blocked})")
        raise ProviderError("Gemini가 빈 응답을 보냈습니다")

    text_parts = [
        p.get("text", "")
        for p in candidates[0].get("content", {}).get("parts", [])
        if p.get("text")
    ]
    raw_text = "".join(text_parts).strip()

    if not raw_text:
        finish = candidates[0].get("finishReason", "")
        if finish == "MAX_TOKENS":
            raise ProviderError("Gemini 응답이 길이 제한에 걸렸습니다")
        raise ProviderError(f"Gemini 응답이 비어 있습니다 (사유: {finish or '알 수 없음'})")

    um = data.get("usageMetadata", {})
    usage = {
        "input_tokens": um.get("promptTokenCount", 0),
        "output_tokens": um.get("candidatesTokenCount", 0),
        "model": data.get("modelVersion", model),
    }
    return raw_text, usage


def normalize_keys(api_key) -> list:
    """키 하나(str) 또는 여러 개(list)를 정리된 리스트로 만듭니다.

    빈 값과 중복을 걸러내고, 넣은 순서는 그대로 지킵니다.
    """
    if isinstance(api_key, str):
        raw = [api_key]
    else:
        raw = list(api_key or [])

    seen, out = set(), []
    for k in raw:
        k = (k or "").strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def gemini_generate(
    api_key,                      # str 또는 list[str] (여러 개면 순서대로 돌려씁니다)
    prompt: str,
    system: str = "",
    images: Optional[list] = None,
    model: str = "",
    max_tokens: int = 8000,
    temperature: float = 0.9,
) -> tuple:
    """
    Gemini 호출.

    모델 × 키를 순서대로 시도합니다.
    같은 모델에서 키 1번이 하루 한도(429)에 걸리면 키 2번, 3번… 으로 넘어가고,
    모든 키가 막히면 그 다음 모델로 내려갑니다.

    Args:
        api_key: API 키 하나 또는 여러 개
        images: [(base64_string, 'image/jpeg'), ...] 형태의 리스트

    Returns:
        (raw_text, usage_dict)  — usage_dict['key_index'] 에 몇 번째 키를 썼는지 담깁니다
    """
    keys = normalize_keys(api_key)
    if not keys:
        raise ProviderError(
            "Gemini API 키가 없습니다.\n"
            "→ aistudio.google.com/apikey 에서 무료로 발급받아 사이드바에 넣어 주세요."
        )

    chain = ([model] if model else []) + [m for m in GEMINI_FALLBACK_CHAIN if m != model]

    last_err = None
    bad_keys = set()        # 키 자체가 틀린 경우 (다음 모델에서 또 시도하지 않게)
    exhausted = set()       # 하루 한도를 다 쓴 키

    for m in chain:
        for idx, key in enumerate(keys):
            if idx in bad_keys or idx in exhausted:
                continue
            try:
                logger.info(
                    f"Gemini 호출: {m} / 키 {idx+1}번 (이미지 {len(images or [])}장)"
                )
                raw_text, usage = _gemini_call(
                    api_key=key, model=m, prompt=prompt, system=system,
                    images=images, max_tokens=max_tokens, temperature=temperature,
                )
                usage["key_index"] = idx
                return raw_text, usage

            except ProviderError as e:
                msg = str(e)
                last_err = e

                if "API key not valid" in msg or "[401]" in msg:
                    logger.warning(f"키 {idx+1}번이 올바르지 않습니다 → 건너뜁니다")
                    bad_keys.add(idx)
                    continue
                if "[429]" in msg:
                    logger.warning(f"키 {idx+1}번 한도 초과 → 다음 키")
                    exhausted.add(idx)
                    continue
                if any(c in msg for c in ("[404]", "[403]")):
                    # 이 모델을 못 쓰는 것뿐이니 키는 살려 두고 다음 모델로
                    logger.warning(f"{m} 사용 불가 → 다음 모델: {msg[:100]}")
                    break
                logger.warning(f"{m}/키 {idx+1}번 실패 → 계속: {msg[:100]}")
                continue

    # ── 전부 실패 ────────────────────────────────
    if len(bad_keys) == len(keys):
        raise ProviderError(
            "❌ 넣으신 Gemini 키가 모두 올바르지 않습니다.\n"
            "→ aistudio.google.com/apikey 에서 다시 확인해 주세요."
        )
    if exhausted:
        raise ProviderError(
            f"❌ Gemini 무료 하루 한도를 다 썼습니다 (키 {len(exhausted)}개 모두 소진).\n\n"
            "• 사이드바에 키를 더 추가하면 그만큼 더 쓸 수 있습니다\n"
            "  (구글 계정이나 프로젝트가 다르면 한도도 따로 잡힙니다)\n"
            "• 또는 내일 다시 쓰거나, Claude(유료)로 바꿔 주세요"
        )
    raise ProviderError(
        "❌ Gemini 호출에 모두 실패했습니다.\n"
        f"마지막 오류: {last_err}"
    )


# ══════════════════════════════════════════════════
# 공통 유틸
# ══════════════════════════════════════════════════

def extract_json(raw_text: str) -> dict:
    """모델 응답에서 JSON을 꺼냅니다 (```json 블록 / 앞뒤 잡소리 모두 처리)."""
    # 1) 마크다운 코드블록
    m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_text)
    candidate = m.group(1) if m else raw_text

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 2) 첫 { 부터 마지막 } 까지
    start, end = candidate.find('{'), candidate.rfind('}')
    if start != -1 and end > start:
        return json.loads(candidate[start:end + 1])

    raise json.JSONDecodeError("JSON을 찾지 못했습니다", raw_text, 0)


def resolve_provider(provider: str = "") -> str:
    """지정값 → 환경변수 → 기본값(gemini) 순으로 공급자를 정합니다."""
    p = (provider or os.getenv("AI_PROVIDER", "") or PROVIDER_GEMINI).strip().lower()
    return p if p in (PROVIDER_CLAUDE, PROVIDER_GEMINI) else PROVIDER_GEMINI
