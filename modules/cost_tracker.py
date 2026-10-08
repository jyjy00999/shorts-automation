# ====================================================
# 모듈 8: API 사용량·비용 추적 (cost_tracker.py)
#
# Anthropic 응답의 usage 값을 누적해서 실제 쓴 금액을 보여줍니다.
# 기록은 outputs/api_usage.json 에 남습니다.
# ====================================================

import os
import json
from datetime import datetime
from pathlib import Path
from loguru import logger

USAGE_PATH = Path("outputs") / "api_usage.json"

# 1M 토큰당 요금 (USD) — 2026-06 기준
PRICING = {
    "claude-opus-5":   {"in": 5.00, "out": 25.00},
    "claude-sonnet-5": {"in": 2.00, "out": 10.00},
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00},
}

USD_TO_KRW = 1450


def _price(model: str) -> dict:
    for key, val in PRICING.items():
        if model.startswith(key):
            return val
    return PRICING["claude-sonnet-5"]   # 모르는 모델은 Sonnet 기준으로 추정


def calc_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    """USD 단위 비용을 계산합니다."""
    p = _price(model)
    return in_tokens / 1e6 * p["in"] + out_tokens / 1e6 * p["out"]


def record(step: str, model: str, usage) -> dict:
    """
    API 호출 1건의 사용량을 기록합니다.

    Args:
        step: 어떤 작업인지 ('이미지 분석', '대본 생성', '장면 매칭')
        model: 모델 ID
        usage: 응답의 usage 객체 또는 dict

    Returns:
        {'step','model','in','out','usd','krw','at'}
    """
    if usage is None:
        return {}

    if isinstance(usage, dict):
        in_tok = usage.get("input_tokens", 0) or 0
        out_tok = usage.get("output_tokens", 0) or 0
    else:
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0

    usd = calc_cost(model, in_tok, out_tok)
    entry = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "step": step,
        "model": model,
        "in": in_tok,
        "out": out_tok,
        "usd": round(usd, 6),
        "krw": round(usd * USD_TO_KRW),
    }

    try:
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = []
        if USAGE_PATH.exists():
            with open(USAGE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        data.append(entry)
        with open(USAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception as e:
        logger.warning(f"사용량 기록 실패: {e}")

    logger.info(f"💰 {step}: {in_tok:,}+{out_tok:,} 토큰 = {entry['krw']}원")
    return entry


def summary(days: int = None) -> dict:
    """
    누적 사용량을 요약합니다.

    Args:
        days: 최근 며칠만 집계 (None이면 전체)

    Returns:
        {'calls','usd','krw','by_step','today_krw'}
    """
    if not USAGE_PATH.exists():
        return {"calls": 0, "usd": 0.0, "krw": 0, "by_step": {}, "today_krw": 0}

    try:
        with open(USAGE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"calls": 0, "usd": 0.0, "krw": 0, "by_step": {}, "today_krw": 0}

    if days:
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        data = [d for d in data if d.get("at", "") >= cutoff]

    today = datetime.now().strftime("%Y-%m-%d")
    by_step = {}
    total_usd = 0.0
    today_krw = 0

    for d in data:
        total_usd += d.get("usd", 0)
        s = d.get("step", "기타")
        by_step[s] = by_step.get(s, 0) + d.get("krw", 0)
        if d.get("at", "").startswith(today):
            today_krw += d.get("krw", 0)

    return {
        "calls": len(data),
        "usd": round(total_usd, 4),
        "krw": round(total_usd * USD_TO_KRW),
        "by_step": by_step,
        "today_krw": today_krw,
    }


def estimate_run(n_images: int = 4, n_scenes: int = 12, smart_match: bool = True) -> dict:
    """
    실행 전에 예상 비용을 계산합니다 (Sonnet 5 기준).

    Returns:
        {'krw','usd','detail'}
    """
    def img_tokens(w, h):
        return (w * h) / 750

    detail = {}

    # ① 이미지 분석 (768px 정사각 기준)
    t_in = img_tokens(768, 768) * n_images + 500
    detail["이미지 분석"] = calc_cost("claude-sonnet-5", t_in, 1500)

    # ② 대본 생성
    detail["대본 생성"] = calc_cost("claude-sonnet-5", 2000, 2500)

    # ③ 장면 매칭 (384px 폭 9:16 기준)
    if smart_match and n_scenes:
        t_in = img_tokens(384, 683) * n_scenes + 800
        detail["장면 매칭"] = calc_cost("claude-sonnet-5", t_in, 400)

    usd = sum(detail.values())
    return {
        "usd": round(usd, 4),
        "krw": round(usd * USD_TO_KRW),
        "detail": {k: round(v * USD_TO_KRW) for k, v in detail.items()},
    }


def reset():
    """기록을 초기화합니다."""
    try:
        if USAGE_PATH.exists():
            USAGE_PATH.unlink()
    except Exception as e:
        logger.warning(f"기록 초기화 실패: {e}")


if __name__ == "__main__":
    est = estimate_run()
    print("예상 비용 (1회):")
    for k, v in est["detail"].items():
        print(f"  {k:12} {v:>5,}원")
    print(f"  {'합계':12} {est['krw']:>5,}원  (${est['usd']})")
    print()
    s = summary()
    print(f"누적: {s['calls']}회 호출, {s['krw']:,}원 (오늘 {s['today_krw']:,}원)")
