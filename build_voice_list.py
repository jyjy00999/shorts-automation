# ====================================================
# 음성 목록 생성 스크립트 (build_voice_list.py)
#
# Typecast API에는 성별 정보가 없어서, 로마자 한국 이름의
# 끝음절 패턴으로 남/녀를 추정해 assets/voices_ko.json 을 만듭니다.
#
# 실행: python build_voice_list.py
# ====================================================

import os
import re
import json
import requests
from dotenv import load_dotenv

load_dotenv()

VOICES_URL = "https://api.typecast.ai/v1/voices"
OUT_PATH = os.path.join("assets", "voices_ko.json")

# ── 끝음절 → 성별 ────────────────────────────────
# 'a', 'na', 'il', 'young' 처럼 서양 이름과 자주 겹치는 접미사는
# 오분류(Abigail·April→남성, Angela·Dana→여성)를 일으켜서 제외했습니다.
# 한국 이름에서만 뚜렷하게 나타나는 끝음절만 남깁니다.
# 하나의 맵으로 두고 긴 접미사부터 검사합니다.
# 여성 목록을 먼저 돌고 남성을 도는 방식이면 'Sungtae'가 짧은 'ae'(여)에
# 먼저 걸려서 'tae'(남)가 밀립니다. 그래서 길이순 단일 검사로 바꿨습니다.
SUFFIX_GENDER = {
    # ── 여성 ──
    "sook": "F", "sug": "F",                       # 숙
    "hee": "F", "hui": "F",                        # 희
    "hye": "F",                                    # 혜
    "kyung": "F", "kyoung": "F", "gyeong": "F",    # 경
    "yeon": "F", "yeun": "F",                      # 연
    "seon": "F",                                   # 선
    "eun": "F",                                    # 은
    "mi": "F",                                     # 미
    "ji": "F",                                     # 지
    "hwa": "F",                                    # 화
    "sil": "F",                                    # 실
    "chae": "F",                                   # 채

    # ── 남성 ──
    "hoon": "M", "hun": "M",                       # 훈
    "joon": "M", "jun": "M",                       # 준
    "seok": "M", "suk": "M", "sok": "M",           # 석
    "cheol": "M", "chul": "M",                     # 철
    "hyuk": "M",                                   # 혁
    "woo": "M", "wu": "M",                         # 우
    "ook": "M", "uk": "M",                         # 욱
    "geon": "M",                                   # 건
    "hwan": "M",                                   # 환
    "seung": "M",                                  # 승
    "sang": "M",                                   # 상
    "dong": "M",                                   # 동
    "tae": "M",                                    # 태
    "jae": "M",                                    # 재
    "bae": "M",                                    # 배
    "dae": "M",                                    # 대
    "wan": "M",                                    # 완
    "kyu": "M",                                    # 규
    "ho": "M",                                     # 호
}

# 휴리스틱으로는 갈리지 않는 이름을 직접 지정합니다.
KNOWN = {
    # 여성
    "kyungae": "F", "eunkyung": "F", "jiseon": "F", "hyejin": "F",
    "seohyeon": "F", "okji": "F", "jungsook": "F", "daeun": "F",
    "hyoeun": "F", "moonjung": "F", "gowoon": "F", "rayeon": "F",
    "mongsil": "F", "jiwoo": "F", "sohee": "F", "yuna": "F",
    # 남성
    "junwoo": "M", "hyunjun": "M", "doyoon": "M", "daejin": "M",
    "sanghyun": "M", "juwan": "M", "byunghun": "M", "minuk": "M",
    "kangil": "M", "wonwoo": "M", "seheon": "M", "cheolhoon": "M",
    "jaesun": "M", "leehyun": "M", "woony": "M", "seojin": "M",
}

# 한국 이름이 아닌 것이 분명한 이름은 제외합니다.
NON_KOREAN = {
    # 그리스/로마 신화
    "poseidon", "hades", "demeter", "hera", "artemis", "zeus",
    "aphrodite", "apollo", "athena", "hermes", "ares", "hestia",
    # 서양 이름
    "krista", "amara", "silas", "ray", "callum", "lorenzo", "donatella",
    "antonio", "lena", "mateo", "pierre", "manon", "fabio", "alessandra",
    "alena", "anja", "elise", "wade", "nia", "walter", "tessa", "doug",
    "janet", "echo", "angela", "abigail", "april", "camila", "ella",
    "dana", "aaron", "aiden", "alex", "amber", "annie", "agatha", "ael",
    "olivia", "emma", "sophia", "james", "william", "henry", "grace",
    "lucas", "noah", "ethan", "mason", "logan", "jacob", "daniel",
    "chloe", "zoe", "lily", "maya", "nora", "ruby", "iris", "luna",
    # 기타 (의성어/애칭)
    "daidai", "bboddo", "booqoo", "arang",
}


def guess_gender(name: str):
    """이름으로 성별을 추정합니다. 판단이 안 되면 None."""
    low = name.lower()

    if low in KNOWN:
        return KNOWN[low]
    if low in NON_KOREAN:
        return None

    # 끝음절 검사 — 긴 접미사부터 한 번에 (여/남을 따로 돌지 않습니다)
    for suf in sorted(SUFFIX_GENDER, key=len, reverse=True):
        if low.endswith(suf):
            return SUFFIX_GENDER[suf]
    return None


def main():
    api_key = os.getenv("TYPECAST_API_KEY", "").strip()
    if not api_key or api_key.startswith("your_"):
        raise SystemExit("TYPECAST_API_KEY가 .env에 없습니다.")

    print("음성 목록 조회 중...")
    resp = requests.get(VOICES_URL, headers={"X-API-KEY": api_key}, timeout=30)
    resp.raise_for_status()
    voices = resp.json()
    print(f"  전체 {len(voices)}개")

    # 한 단어 영문 이름만 (로마자 한국 이름 후보)
    candidates = [v for v in voices if re.fullmatch(r"[A-Za-z]+", v.get("voice_name", ""))]

    # 이름 중복 제거 — 최신 모델(ssfm-v30) 우선
    by_name = {}
    for v in candidates:
        nm = v["voice_name"]
        prev = by_name.get(nm)
        if prev is None or (v.get("model") == "ssfm-v30" and prev.get("model") != "ssfm-v30"):
            by_name[nm] = v

    female, male, unknown = [], [], []
    for nm, v in sorted(by_name.items()):
        entry = {
            "voice_id": v["voice_id"],
            "name": nm,
            "model": v.get("model", "ssfm-v30"),
            "emotions": v.get("emotions", []),
        }
        g = guess_gender(nm)
        if g == "F":
            female.append(entry)
        elif g == "M":
            male.append(entry)
        else:
            unknown.append(entry)

    os.makedirs("assets", exist_ok=True)
    data = {
        "female": female,
        "male": male,
        "unknown": unknown,
        "note": "성별은 Typecast API가 제공하지 않아 이름으로 추정한 값입니다. 미리듣기로 확인하세요.",
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n여성 {len(female)}개 / 남성 {len(male)}개 / 미분류 {len(unknown)}개")
    print(f"저장: {OUT_PATH}")
    print("\n여성 샘플:", ", ".join(x["name"] for x in female[:15]))
    print("남성 샘플:", ", ".join(x["name"] for x in male[:15]))
    print("미분류 샘플:", ", ".join(x["name"] for x in unknown[:15]))


if __name__ == "__main__":
    main()
