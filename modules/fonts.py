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


# ── 자막 스타일 기본값 ────────────────────────────
# 앱(사이드바/④탭)에서 조절하면 set_subtitle_style() 로 여기에 반영되고,
# 영상을 만드는 쪽(clip_editor / video_renderer)은 이 값을 그대로 씁니다.
#
# 단위 주의: libass 는 SRT 를 PlayResY=288 기준으로 그린 뒤 영상 높이에 맞춰
# 늘립니다. 그래서 FontSize·MarginV 는 '288칸 중 몇 칸' 이라는 뜻입니다.
PLAY_RES_Y = 288

DEFAULT_FONT_SIZE = 20     # 288 기준 → 1920 영상에서 약 133px
DEFAULT_MARGIN_V = 70      # 288 기준 → 아래에서 약 24% 위

_style = {"font_size": DEFAULT_FONT_SIZE, "margin_v": DEFAULT_MARGIN_V}


def set_subtitle_style(font_size: int = None, margin_v: int = None):
    """영상을 만들기 직전에 앱이 고른 자막 크기·위치를 적용합니다."""
    if font_size:
        _style["font_size"] = int(font_size)
    if margin_v is not None:
        _style["margin_v"] = int(margin_v)
    logger.info(f"자막 스타일: 크기 {_style['font_size']}, 위치 {_style['margin_v']}")


def get_subtitle_style() -> dict:
    return dict(_style)


def max_chars_for_font(font_size: int) -> int:
    """이 글씨 크기로 9:16 화면 한 줄에 들어가는 한글 글자 수.

    실제로 1080×1920 에 렌더링해서 재 본 값입니다.
      크기 12 → 17자 / 16 → 12자 / 20 → 10자 / 26 → 8자 / 30 → 7자
    이 수치를 넘기면 글자가 화면 밖으로 잘려 나갑니다.
    """
    return max(4, int(207 / max(int(font_size), 1)))


def pct_to_margin(pct: float) -> int:
    """'아래에서 N%' 를 libass MarginV 값으로 바꿉니다."""
    return max(0, min(PLAY_RES_Y - 10, int(round(pct / 100.0 * PLAY_RES_Y))))


def margin_to_pct(margin_v: int) -> float:
    """libass MarginV 값을 '아래에서 N%' 로 바꿉니다."""
    return round(margin_v / PLAY_RES_Y * 100.0, 1)


def subtitle_filter(
    srt_path: str,
    font_size: int = None,
    margin_v: int = None,
    outline: int = 3,
    extra_style: str = "",
) -> str:
    """SRT를 영상에 새겨 넣는 FFmpeg 필터 문자열을 만듭니다.

    찾은 한글 폰트를 FontName 과 fontsdir 양쪽으로 넘겨서,
    fontconfig 가 없는 환경에서도 libass 가 폰트를 찾게 합니다.

    외곽선(Outline)을 3으로 둔 이유: 한글은 획이 많아서 2로 하면
    글자 사이에서 테두리가 끊겨 지저분해 보입니다.

    font_size / margin_v 를 안 주면 앱에서 고른 값(_style)을 씁니다.
    """
    if font_size is None:
        font_size = _style["font_size"]
    if margin_v is None:
        margin_v = _style["margin_v"]

    esc_srt = _escape_for_filter(srt_path)

    found = find_korean_font()
    font_name = found[1] if found else "Arial"

    style = (
        f'FontName={font_name},FontSize={font_size},'
        'PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,'
        f'Outline={outline},Shadow=1,Bold=1,Alignment=2,'
        f'MarginV={margin_v},Spacing=0.5,'
        # WrapStyle=2 : libass 가 멋대로 줄을 더 쪼개지 않습니다.
        # 우리가 넣은 줄바꿈이 그대로 최종 결과가 됩니다.
        'WrapStyle=2'
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


def render_subtitle_preview(
    text: str,
    out_path: str,
    font_size: int = None,
    margin_v: int = None,
    bg_video: str = "",
    bg_seek: float = 1.0,
    width: int = 540,
    height: int = 960,
) -> str:
    """자막이 화면 어디에 어떤 크기로 올라가는지 미리보기 PNG를 만듭니다.

    영상에 실제로 자막을 입힐 때와 '똑같은 필터'를 쓰기 때문에
    여기서 보이는 그대로 결과물에 나옵니다.

    Args:
        text: 미리볼 자막 (줄바꿈으로 여러 줄)
        bg_video: 배경으로 쓸 영상 (없으면 회색 배경)
        bg_seek: 배경 영상에서 몇 초 지점을 쓸지
    """
    import subprocess
    import tempfile

    out_path = os.path.abspath(out_path)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    # 미리보기용 임시 SRT (10초짜리 한 블록)
    lines = [l.strip() for l in str(text).strip().splitlines() if l.strip()][:3]
    if not lines:
        lines = ["자막 미리보기"]

    tmp_srt = os.path.join(tempfile.gettempdir(), "subtitle_preview.srt")
    with open(tmp_srt, "w", encoding="utf-8") as f:
        f.write("1\n00:00:00,000 --> 00:00:10,000\n" + "\n".join(lines) + "\n")

    vf = subtitle_filter(tmp_srt, font_size=font_size, margin_v=margin_v)

    if bg_video and os.path.exists(bg_video):
        # 올린 영상의 한 장면 위에 얹어 봅니다 (가장 정확한 미리보기)
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", str(bg_seek), "-i", os.path.abspath(bg_video),
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                   f"crop={width}:{height},{vf}",
            "-frames:v", "1", out_path,
        ]
    else:
        # 영상이 없으면 눈금 있는 회색 배경 위에 그립니다
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c=0x3a3a44:s={width}x{height}:d=1",
            "-vf", vf, "-frames:v", "1", out_path,
        ]

    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"자막 미리보기 실패:\n{(r.stderr or '')[-300:]}")
    return out_path


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
