# ====================================================
# 모듈: 한글 자막 폰트 찾기 (fonts.py)
#
# 자막이 □□□(두부)로 나오는 건 거의 항상 폰트 문제입니다.
# - 윈도우(내 PC)  : 맑은 고딕이 있어서 잘 나옵니다
# - 리눅스(클라우드): 한글 폰트가 아예 없어서 전부 네모가 됩니다
#
# 그래서 하드코딩 대신 '지금 이 컴퓨터에 실제로 있는' 한글 폰트를
# 찾아서 씁니다. (packages.txt 의 fonts-nanum 이 깔아 줍니다)
# ====================================================

import os
from pathlib import Path
from typing import Optional

from loguru import logger


# (폰트 파일 경로, libass에 넘길 글꼴 이름) — 앞에서부터 찾습니다
FONT_CANDIDATES = [
    # ── 윈도우 ──────────────────────────────────
    (r"C:\Windows\Fonts\malgunbd.ttf", "Malgun Gothic"),
    (r"C:\Windows\Fonts\malgun.ttf", "Malgun Gothic"),
    (r"C:\Windows\Fonts\NanumGothic.ttf", "NanumGothic"),
    (r"C:\Windows\Fonts\gulim.ttc", "Gulim"),
    (r"C:\Windows\Fonts\batang.ttc", "Batang"),

    # ── 리눅스 (Streamlit Cloud 등) ──────────────
    ("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "NanumGothic"),
    ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "NanumGothic"),
    ("/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf", "NanumBarunGothic"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "Noto Sans CJK KR"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK KR"),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK KR"),
    ("/usr/share/fonts/opentype/noto/NotoSansKR-Regular.otf", "Noto Sans KR"),

    # ── 맥 ──────────────────────────────────────
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc", "Apple SD Gothic Neo"),
]

# 프로젝트 안에 직접 넣어 둔 폰트가 있으면 그걸 가장 먼저 씁니다
BUNDLED_FONT_DIR = Path(__file__).parent.parent / "assets" / "fonts"

_cache = None


def find_korean_font() -> Optional[tuple]:
    """이 컴퓨터에서 쓸 수 있는 한글 폰트를 찾습니다.

    Returns:
        (폰트파일경로, 글꼴이름) 또는 못 찾으면 None
    """
    global _cache
    if _cache is not None:
        return _cache or None

    # 1) 프로젝트에 직접 넣어 둔 폰트 (assets/fonts/*.ttf)
    if BUNDLED_FONT_DIR.is_dir():
        for ext in ("*.ttf", "*.otf", "*.ttc"):
            for f in sorted(BUNDLED_FONT_DIR.glob(ext)):
                name = f.stem.replace("-Bold", "").replace("-Regular", "")
                logger.info(f"번들 한글 폰트 사용: {f}")
                _cache = (str(f), name)
                return _cache

    # 2) 시스템에 깔려 있는 폰트
    for path, family in FONT_CANDIDATES:
        if os.path.exists(path):
            logger.info(f"한글 폰트 발견: {path} ({family})")
            _cache = (path, family)
            return _cache

    # 3) 리눅스에서 이름으로 한 번 더 뒤져 봅니다
    for root in ("/usr/share/fonts", "/usr/local/share/fonts",
                 os.path.expanduser("~/.fonts")):
        if not os.path.isdir(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            for fn in sorted(filenames):
                low = fn.lower()
                if not low.endswith((".ttf", ".otf", ".ttc")):
                    continue
                if any(k in low for k in ("nanum", "noto", "cjk", "gothic", "korean")):
                    full = os.path.join(dirpath, fn)
                    family = os.path.splitext(fn)[0]
                    logger.info(f"한글 폰트 발견(탐색): {full}")
                    _cache = (full, family)
                    return _cache

    logger.warning(
        "⚠️ 한글 폰트를 못 찾았습니다. 자막이 □□□ 로 나올 수 있습니다. "
        "(리눅스라면 packages.txt 에 fonts-nanum 을 넣어 주세요)"
    )
    _cache = ()
    return None


def _escape_for_filter(path: str) -> str:
    """FFmpeg 필터 인자용으로 경로를 escape 합니다 (C:\\ 의 콜론 처리)."""
    return os.path.abspath(path).replace('\\', '/').replace(':', r'\:')


def subtitle_filter(
    srt_path: str,
    font_size: int = 20,
    margin_v: int = 70,
    outline: int = 3,
    extra_style: str = "",
) -> str:
    """SRT를 영상에 새겨 넣는 FFmpeg 필터 문자열을 만듭니다.

    찾은 한글 폰트를 FontName 과 fontsdir 양쪽으로 넘겨서,
    fontconfig 가 없는 환경에서도 libass 가 폰트를 찾게 합니다.

    외곽선(Outline)을 3으로 둔 이유: 한글은 획이 많아서 2로 하면
    글자 사이에서 테두리가 끊겨 지저분해 보입니다.
    """
    esc_srt = _escape_for_filter(srt_path)

    found = find_korean_font()
    font_name = found[1] if found else "Arial"

    style = (
        f'FontName={font_name},FontSize={font_size},'
        'PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,'
        f'Outline={outline},Shadow=1,Bold=1,Alignment=2,'
        f'MarginV={margin_v},Spacing=0.5'
    )
    if extra_style:
        style += ',' + extra_style

    filt = f"subtitles='{esc_srt}'"
    if found:
        # libass 가 이 폴더의 폰트를 직접 읽게 합니다
        esc_dir = _escape_for_filter(os.path.dirname(found[0]))
        filt += f":fontsdir='{esc_dir}'"
    filt += f":force_style='{style}'"
    return filt


def font_status() -> dict:
    """앱에서 '한글 폰트 준비됨?' 을 보여 줄 때 씁니다."""
    found = find_korean_font()
    if found:
        return {"ok": True, "path": found[0], "name": found[1]}
    return {
        "ok": False,
        "path": "",
        "name": "",
        "hint": (
            "한글 폰트가 없어 자막이 □□□ 로 나옵니다.\n"
            "• 클라우드: packages.txt 에 `fonts-nanum` 추가 후 재배포\n"
            "• 내 PC: assets/fonts/ 폴더에 한글 ttf 파일을 넣어 주세요"
        ),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(font_status(), ensure_ascii=False, indent=2))
    print(subtitle_filter("test.srt"))
