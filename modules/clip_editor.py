# ====================================================
# 모듈 7: 참고 영상 컷편집기 (clip_editor.py)
#
# 벤치마킹 영상들을 내려받아 장면 단위로 쪼갠 뒤,
# 생성된 음성·자막 타이밍에 맞춰 이어붙입니다.
#
# 흐름:
#   1) yt-dlp 로 참고 영상 다운로드
#   2) ffmpeg 장면 전환 감지로 컷 지점 추출
#   3) SRT 자막 블록마다 클립 하나씩 배정
#   4) 클립을 잘라 9:16로 맞추고 이어붙인 뒤 음성/자막 입히기
#
# ⚠️ 저작권: 남의 영상을 잘라 쓰면 침해가 될 수 있습니다.
#    본인이 찍었거나 사용 허락을 받은 영상에만 쓰세요.
# ====================================================

import os
import re
import json
import math
import random
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from loguru import logger

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920
SHORTS_FPS = 30

# 장면 하나를 클립으로 쓰기 위한 최소 길이(초)
MIN_SCENE_SEC = 0.8

# ── 컷 길이 ───────────────────────────────────────
# 쇼츠는 화면이 계속 바뀌어야 끝까지 봅니다.
# 자막 한 줄이 MAX보다 길면 그 안에서도 컷을 나눠 화면을 바꿉니다.
DEFAULT_MAX_CUT_SEC = 2.6
MIN_CUT_SEC = 0.9

CUT_SPEED_PRESETS = {
    "아주 빠르게": 1.4,
    "빠르게": 1.9,
    "보통": 2.6,
    "느리게": 3.6,
}

# 장면이 이보다 길면 여러 토막으로 쪼개서 후보로 씁니다
# (한 번에 다 보여 주는 대신 여러 컷에 나눠 쓰려고)
SCENE_SPLIT_SEC = 2.2


def _ydl_opts(out_dir: str) -> dict:
    """참고 영상 다운로드용 yt-dlp 옵션."""
    return {
        'quiet': True,
        'no_warnings': True,
        'outtmpl': os.path.join(out_dir, '%(id)s.%(ext)s'),
        'format': 'mp4/bestvideo[ext=mp4]+bestaudio/best',
        'merge_output_format': 'mp4',
        'socket_timeout': 30,
        'retries': 2,
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/126.0.0.0 Safari/537.36'
            ),
            'Referer': 'https://www.tiktok.com/',
        },
        'extractor_args': {
            'tiktok': {'api_hostname': ['api16-normal-c-useast1a.tiktokv.com']},
        },
    }


def download_reference_videos(urls: list[str], out_dir: str = "outputs/reference") -> list[dict]:
    """
    참고 영상들을 내려받습니다.

    Returns:
        [{'path', 'url', 'duration', 'width', 'height', 'title'}, ...]
        실패한 URL은 결과에서 빠집니다.
    """
    if not YTDLP_AVAILABLE:
        raise ImportError("yt-dlp가 필요합니다: pip install yt-dlp")

    os.makedirs(out_dir, exist_ok=True)
    results = []

    for url in urls:
        url = url.strip()
        if not url:
            continue
        try:
            logger.info(f"참고 영상 다운로드: {url[:70]}")
            with yt_dlp.YoutubeDL(_ydl_opts(out_dir)) as ydl:
                info = ydl.extract_info(url, download=True)

            vid = info.get('id', '')
            # 실제 저장된 파일 찾기 (확장자가 바뀔 수 있음)
            path = None
            for ext in ('mp4', 'webm', 'mkv'):
                cand = os.path.join(out_dir, f"{vid}.{ext}")
                if os.path.exists(cand):
                    path = cand
                    break
            if not path:
                logger.warning(f"다운로드 파일을 찾지 못함: {vid}")
                continue

            results.append({
                'path': path,
                'url': url,
                'duration': float(info.get('duration') or 0),
                'width': info.get('width') or 0,
                'height': info.get('height') or 0,
                'title': (info.get('title') or '')[:80],
            })
            logger.info(f"  ✅ {os.path.basename(path)} ({info.get('duration')}초)")

        except Exception as e:
            logger.warning(f"  ❌ 다운로드 실패 {url[:50]}: {str(e)[:120]}")
            continue

    return results


def detect_scenes(video_path: str, threshold: float = 0.25) -> list[tuple]:
    """
    ffmpeg 장면 전환 감지로 컷 구간을 찾습니다.

    Returns:
        [(start_sec, end_sec), ...]
    """
    if not shutil.which('ffmpeg'):
        raise RuntimeError("FFmpeg가 설치되어 있지 않습니다.")

    duration = get_video_duration(video_path)

    cmd = [
        'ffmpeg', '-i', video_path,
        '-vf', f"select='gt(scene,{threshold})',showinfo",
        '-f', 'null', '-',
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')

    # showinfo 출력에서 pts_time 추출
    times = []
    for m in re.finditer(r'pts_time:([0-9.]+)', proc.stderr or ''):
        try:
            times.append(float(m.group(1)))
        except ValueError:
            pass

    # 컷 지점을 구간으로 변환 (0초 시작, 마지막은 영상 끝)
    points = [0.0] + sorted(set(times)) + [duration]
    scenes = []
    for i in range(len(points) - 1):
        s, e = points[i], points[i + 1]
        if e - s >= MIN_SCENE_SEC:
            scenes.append((round(s, 3), round(e, 3)))

    # 장면 전환이 거의 없는 영상(한 번에 쭉 찍은 영상)이면
    # 일정 간격으로 쪼개서 컷 후보를 만듭니다.
    if len(scenes) < 2 and duration > 3:
        step = SCENE_SPLIT_SEC
        scenes = []
        t = 0.0
        while t + MIN_SCENE_SEC < duration:
            scenes.append((round(t, 3), round(min(t + step, duration), 3)))
            t += step

    # 긴 장면은 토막으로 나눠 둡니다.
    # 한 장면을 10초 내내 보여 주면 "편집 안 한 영상"처럼 보이니,
    # 같은 장면 안에서도 다른 구간을 골라 쓸 수 있게 후보를 늘립니다.
    scenes = split_long_scenes(scenes)

    logger.info(f"{os.path.basename(video_path)}: 컷 후보 {len(scenes)}개")
    return scenes


def split_long_scenes(scenes: list[tuple], piece_sec: float = SCENE_SPLIT_SEC) -> list[tuple]:
    """긴 장면을 piece_sec 정도의 토막으로 나눕니다."""
    out = []
    for (s, e) in scenes:
        length = e - s
        if length <= piece_sec * 1.6:
            out.append((round(s, 3), round(e, 3)))
            continue
        n = max(2, int(round(length / piece_sec)))
        step = length / n
        for k in range(n):
            a = s + step * k
            b = s + step * (k + 1) if k < n - 1 else e
            if b - a >= MIN_SCENE_SEC:
                out.append((round(a, 3), round(b, 3)))
    return out


def get_video_duration(video_path: str) -> float:
    """ffprobe로 영상 길이(초)를 구합니다."""
    if not shutil.which('ffprobe'):
        return 0.0
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        video_path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except (TypeError, ValueError):
        return 0.0


def extract_frames(
    video_path: str,
    count: int = 3,
    out_dir: str = None,
    prefix: str = "frame",
) -> list[str]:
    """
    영상에서 고르게 퍼진 프레임을 뽑아 JPG로 저장합니다.
    (상품 이미지 없이 영상만 있을 때 이미지 분석용으로 씁니다)

    Args:
        video_path: 원본 영상
        count: 뽑을 장 수
        out_dir: 저장 폴더 (기본: 임시 폴더)
        prefix: 파일명 접두사

    Returns:
        저장된 이미지 경로 리스트
    """
    if not shutil.which('ffmpeg'):
        raise RuntimeError("FFmpeg가 설치되어 있지 않습니다.")

    duration = get_video_duration(video_path)
    if duration <= 0:
        logger.warning(f"영상 길이를 읽지 못함: {video_path}")
        return []

    out_dir = out_dir or tempfile.mkdtemp(prefix="frames_")
    os.makedirs(out_dir, exist_ok=True)

    paths = []
    # 맨 앞/뒤는 검은 화면인 경우가 많아 10~90% 구간에서 뽑습니다
    for i in range(count):
        ratio = 0.1 + (0.8 * i / max(count - 1, 1))
        t = duration * ratio
        out = os.path.join(out_dir, f"{prefix}_{i:02d}.jpg")

        r = subprocess.run(
            ['ffmpeg', '-y', '-v', 'error',
             '-ss', f'{t:.3f}', '-i', video_path,
             '-frames:v', '1', '-q:v', '2', out],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
            paths.append(out)
        else:
            logger.warning(f"프레임 추출 실패 ({t:.1f}s): {(r.stderr or '')[-150:]}")

    logger.info(f"{os.path.basename(video_path)}에서 프레임 {len(paths)}장 추출")
    return paths


def extract_frames_from_videos(
    video_paths: list[str],
    per_video: int = 3,
    max_total: int = 9,
    out_dir: str = "outputs/frames",
) -> list[str]:
    """여러 영상에서 프레임을 뽑아 모읍니다."""
    os.makedirs(out_dir, exist_ok=True)
    collected = []

    for i, vp in enumerate(video_paths):
        if len(collected) >= max_total:
            break
        try:
            collected += extract_frames(
                vp, count=per_video, out_dir=out_dir, prefix=f"v{i}"
            )
        except Exception as e:
            logger.warning(f"프레임 추출 건너뜀 {vp}: {e}")

    return collected[:max_total]


def get_video_size(video_path: str) -> tuple:
    """영상 해상도 (가로, 세로)를 구합니다."""
    if not shutil.which('ffprobe'):
        return (0, 0)
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height',
         '-of', 'csv=p=0', video_path],
        capture_output=True, text=True
    ).stdout.strip()
    try:
        w, h = out.split(',')[:2]
        return (int(w), int(h))
    except Exception:
        return (0, 0)


def delogo_filter(box: dict, vid_w: int, vid_h: int) -> Optional[str]:
    """
    자막 영역을 지우는 delogo 필터 문자열을 만듭니다.

    Args:
        box: {'x','y','w','h'} — 0~100 사이의 퍼센트 값
        vid_w, vid_h: 영상 해상도

    Returns:
        'delogo=x=..:y=..:w=..:h=..' 또는 None
    """
    if not box or not vid_w or not vid_h:
        return None

    x = int(vid_w * box.get('x', 0) / 100)
    y = int(vid_h * box.get('y', 0) / 100)
    w = int(vid_w * box.get('w', 0) / 100)
    h = int(vid_h * box.get('h', 0) / 100)

    # delogo는 상자가 화면 안에 완전히 들어가야 하고 가장자리 1px 여백이 필요합니다
    x = max(1, min(x, vid_w - 3))
    y = max(1, min(y, vid_h - 3))
    w = max(2, min(w, vid_w - x - 1))
    h = max(2, min(h, vid_h - y - 1))

    if w < 2 or h < 2:
        return None
    return f"delogo=x={x}:y={y}:w={w}:h={h}"


def preview_delogo(
    video_path: str,
    box: Optional[dict] = None,
    at_sec: float = None,
    out_path: str = None,
    width: int = 360,
) -> Optional[str]:
    """
    자막 제거 결과를 한 장 미리보기로 만듭니다.

    Args:
        box: {'x','y','w','h'} 퍼센트. None이면 원본 그대로
        at_sec: 몇 초 지점 (None이면 영상 중간)

    Returns:
        생성된 PNG 경로
    """
    if not os.path.exists(video_path):
        return None

    dur = get_video_duration(video_path)
    t = at_sec if at_sec is not None else max(dur * 0.4, 0.5)

    vw, vh = get_video_size(video_path)
    filters = []
    dl = delogo_filter(box, vw, vh) if box else None
    if dl:
        filters.append(dl)
    filters.append(f"scale={width}:-1")

    out_path = out_path or os.path.join(
        tempfile.mkdtemp(prefix="dlprev_"), "preview.png"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    r = subprocess.run(
        ['ffmpeg', '-y', '-v', 'error', '-ss', f'{t:.2f}', '-i', video_path,
         '-frames:v', '1', '-vf', ','.join(filters), out_path],
        capture_output=True, text=True, encoding='utf-8', errors='replace'
    )
    if r.returncode != 0 or not os.path.exists(out_path):
        logger.warning(f"미리보기 실패: {(r.stderr or '')[-200:]}")
        return None
    return out_path


def extract_scene_thumbnails(
    sources: list[dict],
    out_dir: str = None,
    max_scenes: int = 12,      # 24 → 12 (Vision 요금 절반)
    thumb_width: int = 384,    # 480 → 384 (토큰 약 1/1.6)
) -> list[dict]:
    """
    각 장면의 대표 프레임(가운데 지점)을 뽑습니다.
    AI가 장면 내용을 보고 자막과 매칭할 때 씁니다.

    Returns:
        [{'src', 'start', 'end', 'thumb'}, ...]
    """
    out_dir = out_dir or tempfile.mkdtemp(prefix="thumbs_")
    os.makedirs(out_dir, exist_ok=True)

    # 모든 장면을 모읍니다
    all_scenes = []
    for s in sources:
        for (st_, en) in (s.get('scenes') or []):
            all_scenes.append({'src': s['path'], 'start': st_, 'end': en})

    if not all_scenes:
        return []

    # 너무 많으면 고르게 솎아냅니다 (Vision 비용/토큰 절약)
    if len(all_scenes) > max_scenes:
        step = len(all_scenes) / max_scenes
        all_scenes = [all_scenes[int(i * step)] for i in range(max_scenes)]

    result = []
    for i, sc in enumerate(all_scenes):
        mid = (sc['start'] + sc['end']) / 2
        thumb = os.path.join(out_dir, f"scene_{i:03d}.jpg")
        r = subprocess.run(
            ['ffmpeg', '-y', '-v', 'error',
             '-ss', f"{mid:.3f}", '-i', sc['src'],
             '-frames:v', '1', '-vf', f'scale={thumb_width}:-1', '-q:v', '4', thumb],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        if r.returncode == 0 and os.path.exists(thumb):
            result.append({**sc, 'thumb': thumb})

    logger.info(f"장면 썸네일 {len(result)}개 추출")
    return result


def guess_text_score(image_path: str) -> tuple:
    """
    이미지에 자막 글자가 있을 가능성을 점수로 매깁니다 (무료, API 불필요).

    흰 글자에 검은 테두리가 있으면 한 행에서 밝음↔어두움 전환이 많이 생깁니다.
    ⚠️ 완벽하지 않습니다 — 저대비 회색 자막은 놓칩니다. 추천용으로만 쓰세요.

    Returns:
        (점수, 세로위치%) — 점수 3 이상이면 자막 가능성 높음
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return 0.0, 0.0

    try:
        arr = np.asarray(Image.open(image_path).convert('L'), dtype=np.int16)
    except Exception:
        return 0.0, 0.0

    h, w = arr.shape
    if h < 10 or w < 10:
        return 0.0, 0.0

    bright = arr > 195
    dark = arr < 95
    flip = (bright[:, :-1] & dark[:, 1:]) | (dark[:, :-1] & bright[:, 1:])
    per_row = flip.sum(axis=1) / w * 100
    smooth = np.convolve(per_row, np.ones(3) / 3, mode='same')

    i = int(np.argmax(smooth))
    return float(smooth[i]), round(i / h * 100, 1)


TEXT_SCORE_THRESHOLD = 3.0


def find_text_scenes_free(scenes: list[dict]) -> set:
    """API 없이 자막 있을 법한 장면 번호를 추립니다 (추천용)."""
    flagged = set()
    for i, sc in enumerate(scenes):
        score, _pos = guess_text_score(sc.get('thumb', ''))
        if score >= TEXT_SCORE_THRESHOLD:
            flagged.add(i)
    logger.info(f"무료 검출: {len(scenes)}개 중 {len(flagged)}개에 자막 의심")
    return flagged


def _encode_thumbs(scenes: list[dict]) -> list[tuple]:
    """장면 썸네일들을 (base64, mime) 리스트로 만듭니다."""
    try:
        from modules.image_analyzer import image_to_base64
    except ImportError as e:
        logger.warning(f"썸네일 인코딩 불가: {e}")
        return []

    out = []
    for sc in scenes:
        try:
            out.append(image_to_base64(sc['thumb']))
        except Exception as e:
            logger.warning(f"썸네일 인코딩 실패: {e}")
    return out


def _pick_vision_provider(provider: str, api_key: str, gemini_key) -> str:
    """어떤 AI로 사진을 볼지 정합니다 (지정값 → 있는 키 순)."""
    p = (provider or "").strip().lower()
    if p in ("gemini", "claude"):
        return p
    # 지정이 없으면 가진 키로 판단합니다
    if gemini_key:
        return "gemini"
    return "claude" if api_key else "gemini"


def _ai_vision_json(
    prompt: str,
    images: list[tuple],
    label: str,
    api_key: str = "",
    gemini_key=None,
    provider: str = "",
    model: str = "claude-sonnet-5",
    max_tokens: int = 1500,
) -> Optional[dict]:
    """
    사진 여러 장을 보여 주고 JSON 답을 받습니다.

    Gemini(무료)와 Claude(유료) 둘 다 씁니다.
    실패하면 None을 돌려줍니다 (부르는 쪽에서 순서대로 배치로 대체).
    """
    if not images:
        return None

    which = _pick_vision_provider(provider, api_key, gemini_key)
    system = "당신은 쇼핑 쇼츠 편집자입니다. 항상 JSON 형식으로만 응답합니다."

    # ── Gemini (무료 할당량) ──────────────────────
    if which == "gemini":
        if not gemini_key:
            logger.warning(f"{label}: Gemini 키가 없어 건너뜁니다")
            return None
        try:
            from modules.ai_provider import extract_json, gemini_generate
            raw, _usage = gemini_generate(
                api_key=gemini_key,
                prompt=prompt,
                system=system,
                images=images,
                max_tokens=max_tokens,
                temperature=0.3,
            )
            logger.info(f"✅ {label} 완료 (Gemini)")
            return extract_json(raw)
        except Exception as e:
            logger.warning(f"{label} 실패 (Gemini) → 순서대로 배치: {str(e)[:200]}")
            return None

    # ── Claude (유료) ─────────────────────────────
    if not api_key:
        logger.warning(f"{label}: Anthropic 키가 없어 건너뜁니다")
        return None
    try:
        import anthropic
        from modules.ai_provider import extract_json

        content = [
            {"type": "image",
             "source": {"type": "base64", "media_type": mt, "data": b64}}
            for b64, mt in images
        ]
        content.append({"type": "text", "text": prompt})

        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": content}],
        )

        try:
            from modules.cost_tracker import record
            record(label, model, resp.usage)
        except Exception:
            pass

        logger.info(f"✅ {label} 완료 (Claude)")
        return extract_json(resp.content[0].text)

    except Exception as e:
        msg = str(e)
        if "credit balance" in msg or "billing" in msg.lower():
            logger.warning(f"{label}: Anthropic 크레딧 부족 → 순서대로 배치")
        else:
            logger.warning(f"{label} 실패 → 순서대로 배치: {msg[:200]}")
        return None


def find_text_scenes_ai(
    scenes: list[dict],
    api_key: str = "",
    model: str = "claude-sonnet-5",
    provider: str = "",
    gemini_key=None,
) -> Optional[set]:
    """
    AI로 자막(한국어 외 글자)이 박힌 장면을 찾습니다. Gemini/Claude 둘 다 됩니다.

    Returns:
        자막 있는 장면 번호 집합. 실패하면 None.
    """
    if not scenes:
        return None

    images = _encode_thumbs(scenes)
    if not images:
        return None

    prompt = f"""위 사진 {len(images)}장은 영상에서 뽑은 장면입니다.
사진 번호는 0부터 {len(images)-1}까지입니다.

각 사진에 **영상에 박혀 있는 자막이나 설명 문구**가 있는지 봐주세요.
- 중국어·영어 자막, 치수 표시, 화살표와 함께 있는 설명 글자 → 있음
- 제품에 원래 인쇄된 작은 로고나 라벨 → 없음으로 칩니다
- 간판, 상자에 적힌 글씨 같은 배경 속 글자 → 없음으로 칩니다

JSON만 출력하세요:
```json
{{"with_text": [0, 3, 7]}}
```"""

    data = _ai_vision_json(
        prompt=prompt, images=images, label="자막 검출",
        api_key=api_key, gemini_key=gemini_key, provider=provider,
        model=model, max_tokens=900,
    )
    if data is None:
        return None

    try:
        found = {
            int(i) for i in (data.get('with_text') or [])
            if 0 <= int(i) < len(scenes)
        }
    except (TypeError, ValueError):
        logger.warning("자막 검출 응답을 읽지 못했습니다")
        return None

    logger.info(f"AI 자막 검출: 장면 {len(scenes)}개 중 {len(found)}개에 자막")
    return found


def match_scenes_with_ai(
    scenes: list[dict],
    srt_blocks: list[dict],
    api_key: str = "",
    model: str = "claude-sonnet-5",
    provider: str = "",
    gemini_key=None,
) -> Optional[list[int]]:
    """
    AI가 장면 사진을 보고 자막마다 가장 어울리는 장면을 고릅니다.
    Gemini(무료)와 Claude(유료) 둘 다 됩니다.

    Returns:
        자막 순서대로의 장면 인덱스 리스트. 실패하면 None.
    """
    if not scenes or not srt_blocks:
        return None

    images = _encode_thumbs(scenes)
    if not images:
        return None

    lines = "\n".join(
        f"{i}: {b['text'].replace(chr(10), ' ')}" for i, b in enumerate(srt_blocks)
    )

    prompt = f"""위에 쇼핑 쇼츠에 쓸 장면 사진 {len(images)}장이 순서대로 있습니다.
사진 번호는 0부터 {len(images)-1}까지입니다.

아래는 이 영상에 깔릴 내레이션 자막입니다.

{lines}

각 자막이 나올 때 화면에 띄우면 가장 잘 어울리는 사진을 하나씩 골라 주세요.

기준:
- 자막이 말하는 내용과 사진에 보이는 것이 맞아야 합니다
  (예: "유리에 붙이면 알아서 움직여요" → 제품이 유리창에 붙어 있는 사진)
- 후크·공감 부분은 문제 상황이나 사람의 모습이 좋습니다
- 혜택 설명은 제품이 실제로 작동하는 모습이 좋습니다
- **같은 사진을 연달아 쓰지 마세요.** 바로 앞 자막과 다른 사진을 고르세요
- 사진이 자막보다 적으면 어쩔 수 없이 다시 쓰되, 최소 2컷은 띄워서 쓰세요
- 모든 자막에 반드시 사진을 하나씩 배정하세요

JSON만 출력하세요:
```json
{{"matches": [{{"sub": 0, "scene": 3}}, {{"sub": 1, "scene": 7}}]}}
```"""

    logger.info(f"AI 장면 매칭 요청: 장면 {len(images)}개, 자막 {len(srt_blocks)}줄")
    data = _ai_vision_json(
        prompt=prompt, images=images, label="장면 매칭",
        api_key=api_key, gemini_key=gemini_key, provider=provider,
        model=model, max_tokens=2000,
    )
    if data is None:
        return None

    try:
        by_sub = {}
        for x in (data.get('matches') or []):
            by_sub[int(x['sub'])] = int(x['scene'])
    except (TypeError, ValueError, KeyError):
        logger.warning("장면 매칭 응답을 읽지 못했습니다 → 순서대로 배치")
        return None

    if not by_sub:
        return None

    result = []
    for i in range(len(srt_blocks)):
        idx = by_sub.get(i, i % len(scenes))
        result.append(max(0, min(idx, len(scenes) - 1)))

    logger.info(f"✅ AI 매칭 완료: {result}")
    return result


def parse_srt_blocks(srt_path: str) -> list[dict]:
    """
    SRT를 읽어 자막 블록 목록을 반환합니다.

    Returns:
        [{'index', 'start', 'end', 'dur', 'text'}, ...]
    """
    with open(srt_path, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    pattern = (
        r'(\d+)\s*\n'
        r'(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*'
        r'(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*\n'
        r'([\s\S]*?)(?=\n\s*\n|\Z)'
    )

    blocks = []
    for m in re.finditer(pattern, content):
        idx = int(m.group(1))
        start = int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4)) + int(m.group(5)) / 1000
        end = int(m.group(6)) * 3600 + int(m.group(7)) * 60 + int(m.group(8)) + int(m.group(9)) / 1000
        blocks.append({
            'index': idx,
            'start': round(start, 3),
            'end': round(end, 3),
            'dur': round(end - start, 3),
            'text': m.group(10).strip(),
        })
    return blocks


def _cut_lengths(dur: float, max_cut: float, min_cut: float = MIN_CUT_SEC) -> list[float]:
    """
    자막 한 줄이 차지하는 시간을 여러 컷으로 나눕니다.

    예) 자막이 5.2초인데 최대 컷이 2.6초면 → [2.6, 2.6]
        자막 한 줄 동안에도 화면이 한 번 바뀝니다.
    """
    dur = max(float(dur), 0.2)
    if dur <= max_cut + 0.25:
        return [round(dur, 3)]

    n = int(math.ceil(dur / max_cut))
    # 너무 잘게 쪼개서 화면이 깜빡이지 않도록 최소 길이를 지킵니다
    while n > 1 and dur / n < min_cut:
        n -= 1
    if n <= 1:
        return [round(dur, 3)]

    base = dur / n
    parts = [round(base, 3) for _ in range(n - 1)]
    parts.append(round(dur - sum(parts), 3))
    return parts


class _SceneBank:
    """
    컷에 쓸 장면 후보를 모아 두고 하나씩 꺼내 줍니다.

    - 아직 안 쓴 장면을 먼저 꺼냅니다 (전부 돌고 나서 재사용)
    - 직전 컷과 같은 장면·같은 영상은 되도록 피합니다
    - 같은 장면을 또 쓸 때는 시작점을 옮겨 다른 그림이 나오게 합니다
    """

    def __init__(self, pools: list[dict], seed: int = 20240501):
        # 영상을 번갈아 담습니다 (한 영상만 쭉 쓰지 않게)
        self.items = []
        if pools:
            longest = max(len(p['scenes']) for p in pools)
            for k in range(longest):
                for p in pools:
                    if k < len(p['scenes']):
                        s, e = p['scenes'][k]
                        self.items.append({'src': p['path'], 'start': s, 'end': e})

        self.used = [0] * len(self.items)
        self.last = -1
        self.rng = random.Random(seed)

    def __len__(self):
        return len(self.items)

    def _score(self, i: int, need: float, avoid_src: str):
        it = self.items[i]
        length = it['end'] - it['start']
        return (
            self.used[i],                                    # 적게 쓴 장면 먼저
            0 if length >= need else 1,                      # 길이가 되는 것 먼저
            1 if i == self.last else 0,                      # 직전 컷과 같은 장면은 피함
            1 if (avoid_src and it['src'] == avoid_src) else 0,  # 직전과 같은 영상도 피함
            -length,
        )

    def take(self, need: float, avoid_src: str = "") -> Optional[dict]:
        """컷 하나에 쓸 장면을 꺼냅니다. {'src','start'} 또는 None."""
        if not self.items:
            return None

        order = sorted(
            range(len(self.items)),
            key=lambda i: self._score(i, need, avoid_src),
        )
        best = self._score(order[0], need, avoid_src)[:4]
        # 조건이 똑같이 좋은 후보들 중에서 골라, 매번 같은 순서로 나오지 않게 합니다
        tied = [i for i in order if self._score(i, need, avoid_src)[:4] == best]
        idx = self.rng.choice(tied[:4]) if tied else order[0]

        it = self.items[idx]
        self.used[idx] += 1
        self.last = idx

        avail = it['end'] - it['start']
        if avail > need + 0.15:
            start = it['start'] + self.rng.uniform(0, avail - need)
        else:
            start = max(0.0, it['end'] - need)

        return {'src': it['src'], 'start': round(start, 3)}


def _fix_repeated_cuts(plan: list[dict], src_limit: dict, gap: float = 0.4) -> int:
    """
    연달아 같은 그림이 나오는 컷을 찾아 시작점을 옮깁니다.

    컷이 바뀌었는데 화면이 그대로면 "편집 안 한 영상"처럼 보입니다.
    같은 영상의 거의 같은 지점이 이어지면 뒤 컷을 다른 구간으로 밀어 줍니다.

    Returns:
        고친 컷 개수
    """
    fixed = 0
    for j in range(1, len(plan)):
        a, b = plan[j - 1], plan[j]
        if a.get('type') != 'video' or b.get('type') != 'video':
            continue
        if a['src'] != b['src']:
            continue
        if abs(a['src_start'] - b['src_start']) >= gap:
            continue

        shift = a['dur'] + b['dur']
        limit = max(0.0, src_limit.get(b['src'], 0.0) - b['dur'])

        if b['src_start'] + shift <= limit:
            b['src_start'] = round(b['src_start'] + shift, 3)
            fixed += 1
        elif b['src_start'] - shift >= 0:
            b['src_start'] = round(b['src_start'] - shift, 3)
            fixed += 1
        elif limit > gap:
            # 영상이 짧아 밀 자리가 없으면 쓸 수 있는 범위의 반대쪽 끝으로
            b['src_start'] = round(limit if b['src_start'] < limit / 2 else 0.0, 3)
            fixed += 1

    if fixed:
        logger.info(f"같은 그림이 이어지던 컷 {fixed}개를 다른 구간으로 옮겼습니다")
    return fixed


def build_clip_plan(
    srt_blocks: list[dict],
    sources: list[dict],
    total_duration: float = 0.0,
    image_paths: Optional[list[str]] = None,
    image_every: int = 3,
    ai_scenes: Optional[list[dict]] = None,
    ai_matches: Optional[list[int]] = None,
    exclude_ranges: Optional[list] = None,
    max_cut_sec: float = DEFAULT_MAX_CUT_SEC,
) -> list[dict]:
    """
    대본(자막) 타이밍에 맞춰 컷을 배치합니다.

    - 자막 한 줄 = 최소 한 컷. 줄이 길면 그 안에서도 컷을 나눕니다
      (max_cut_sec 초보다 긴 자막은 2컷 이상으로 쪼갭니다)
    - AI가 자막 내용에 맞는 장면을 골라 줬으면 그 장면을 첫 컷으로 씁니다
    - 안 쓴 장면을 먼저 쓰고, 직전 컷과 같은 영상·장면은 피합니다
    - total_duration을 주면 마지막 컷을 늘려 음성 끝까지 화면이 남습니다

    Returns:
        [{'type','src','src_start','dur','sub_index','text'}, ...]
    """
    images = [p for p in (image_paths or []) if p and os.path.exists(p)]

    # 자막이 박힌 구간은 빼고 장면 목록을 만듭니다
    banned = exclude_ranges or []

    def _is_banned(path, s, e):
        for (bp, bs, be) in banned:
            if os.path.abspath(bp) == os.path.abspath(path):
                # 구간이 절반 이상 겹치면 제외
                ov = min(e, be) - max(s, bs)
                if ov > 0 and ov >= (e - s) * 0.5:
                    return True
        return False

    # 영상별 장면 목록 준비
    pools = []
    for s in sources:
        scenes = [
            (a, b) for (a, b) in (s.get('scenes') or [])
            if not _is_banned(s['path'], a, b)
        ]
        if scenes:
            pools.append({'path': s['path'], 'scenes': list(scenes), 'used': set()})

    if banned:
        _total = sum(len(s.get('scenes') or []) for s in sources)
        _left = sum(len(p['scenes']) for p in pools)
        logger.info(f"자막 구간 제외: 장면 {_total}개 중 {_left}개 사용 가능")

    if not pools and not images:
        raise RuntimeError(
            "사용할 수 있는 영상이나 이미지가 없습니다. 참고 영상 또는 상품 이미지를 넣어 주세요."
        )

    bank = _SceneBank(pools)
    use_ai = bool(ai_scenes and ai_matches and len(ai_matches) >= len(srt_blocks))

    max_cut = max(float(max_cut_sec or DEFAULT_MAX_CUT_SEC), MIN_CUT_SEC)

    plan = []
    img_cursor = 0
    prev_src = ""
    prev_ai_idx = -1
    ai_repeat_shift = 0.0

    for i, blk in enumerate(srt_blocks):
        need = max(blk['dur'], 0.4)

        # 이미지를 넣을 자리인지 판단
        # - 영상이 없으면 전부 이미지
        # - 이미지가 있으면 image_every 번째마다 한 장씩
        use_image = False
        if images:
            if not pools:
                use_image = True
            elif image_every > 0 and (i + 1) % image_every == 0:
                use_image = True

        # 자막 한 줄을 몇 컷으로 보여 줄지 (길면 여러 컷)
        lengths = _cut_lengths(need, max_cut)

        for k, seg_dur in enumerate(lengths):
            if use_image:
                # 이미지는 쪼개도 같은 그림이니, 컷마다 다른 이미지를 씁니다
                plan.append({
                    'type': 'image',
                    'src': images[img_cursor % len(images)],
                    'src_start': 0.0,
                    'dur': round(seg_dur, 3),
                    'sub_index': blk['index'],
                    'text': blk['text'],
                })
                img_cursor += 1
                prev_src = ""
                continue

            # 자막의 첫 컷은 AI가 내용에 맞게 고른 장면을 씁니다
            if use_ai and k == 0:
                ai_idx = ai_matches[i]
                sc = ai_scenes[ai_idx]
                avail = sc['end'] - sc['start']

                if ai_idx == prev_ai_idx:
                    # AI가 직전과 같은 장면을 또 골랐으면
                    # 적어도 같은 장면의 다른 구간을 보여 줍니다
                    ai_repeat_shift += max(seg_dur, 0.8)
                else:
                    ai_repeat_shift = 0.0

                start = sc['start'] + ai_repeat_shift
                if start + seg_dur > sc['end']:
                    start = max(0.0, sc['end'] - seg_dur) if avail >= seg_dur else sc['start']
                    ai_repeat_shift = 0.0

                plan.append({
                    'type': 'video',
                    'src': sc['src'],
                    'src_start': round(max(start, 0.0), 3),
                    'dur': round(seg_dur, 3),
                    'sub_index': blk['index'],
                    'text': blk['text'],
                    'matched_by': 'ai',
                })
                prev_src = sc['src']
                prev_ai_idx = ai_idx
                continue

            # 나머지 컷은 안 쓴 장면 중에서 꺼내 씁니다
            got = bank.take(seg_dur, avoid_src=prev_src)
            if got is None:
                # 쓸 영상이 없으면 이미지로 메웁니다
                if images:
                    plan.append({
                        'type': 'image',
                        'src': images[img_cursor % len(images)],
                        'src_start': 0.0,
                        'dur': round(seg_dur, 3),
                        'sub_index': blk['index'],
                        'text': blk['text'],
                    })
                    img_cursor += 1
                continue

            plan.append({
                'type': 'video',
                'src': got['src'],
                'src_start': got['start'],
                'dur': round(seg_dur, 3),
                'sub_index': blk['index'],
                'text': blk['text'],
                'matched_by': 'ai' if use_ai else 'auto',
            })
            prev_src = got['src']

    # 같은 그림이 연달아 나오면(컷이 바뀐 티가 안 나면) 시작점을 옮깁니다
    _src_limit = {}
    for p in pools:
        for (s, e) in p['scenes']:
            _src_limit[p['path']] = max(_src_limit.get(p['path'], 0.0), e)
    for sc in (ai_scenes or []):
        _src_limit[sc['src']] = max(_src_limit.get(sc['src'], 0.0), sc['end'])
    _fix_repeated_cuts(plan, _src_limit)

    # 자막이 음성보다 먼저 끝나면 마지막 클립을 늘려서
    # 말이 남았는데 화면이 꺼지는 일이 없게 합니다.
    if plan and total_duration > 0:
        planned = sum(c['dur'] for c in plan)
        gap = total_duration - planned
        if gap > 0.05:
            plan[-1]['dur'] = round(plan[-1]['dur'] + gap, 3)
            logger.info(f"마지막 컷을 {gap:.2f}초 늘려 음성 길이에 맞춤")

    logger.info(
        f"컷 배치 완료: 자막 {len(srt_blocks)}줄 → 컷 {len(plan)}개 "
        f"(최대 컷 길이 {max_cut:.1f}초, {'AI 매칭' if use_ai else '자동 배치'})"
    )
    return plan


def render_cut_video(
    plan: list[dict],
    audio_path: str,
    output_path: str,
    srt_path: Optional[str] = None,
    delogo_boxes: Optional[dict] = None,
    bottom_trim: Optional[dict] = None,
    progress_cb=None,
) -> str:
    """
    클립 계획대로 잘라 이어붙이고 음성·자막을 입힙니다.

    Args:
        plan: build_clip_plan() 결과
        audio_path: 생성된 TTS 음성
        output_path: 출력 MP4 경로
        srt_path: 자막 SRT (있으면 영상에 새겨 넣음)
        progress_cb: 진행률 콜백 fn(현재, 전체, 설명)

    Returns:
        생성된 MP4 경로
    """
    if not shutil.which('ffmpeg'):
        raise RuntimeError("FFmpeg가 설치되어 있지 않습니다.")

    tmp_dir = tempfile.mkdtemp(prefix="cutedit_")
    seg_paths = []

    # 영상: 9:16 꽉 채우기 (여백 대신 가운데를 잘라냅니다)
    vf_video = (
        f'scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:force_original_aspect_ratio=increase,'
        f'crop={SHORTS_WIDTH}:{SHORTS_HEIGHT},'
        f'setsar=1,fps={SHORTS_FPS},format=yuv420p'
    )

    # 이미지: 상품이 잘리면 안 되므로 통째로 넣고,
    #         남는 여백은 같은 이미지를 흐리게 깔아 채웁니다.
    vf_image = (
        f'[0:v]scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:force_original_aspect_ratio=increase,'
        f'crop={SHORTS_WIDTH}:{SHORTS_HEIGHT},gblur=sigma=25[bg];'
        f'[0:v]scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:force_original_aspect_ratio=decrease[fg];'
        f'[bg][fg]overlay=(W-w)/2:(H-h)/2,'
        f'setsar=1,fps={SHORTS_FPS},format=yuv420p'
    )

    try:
        # ── 1) 클립별로 잘라내기 ──────────────────
        for i, c in enumerate(plan):
            seg = os.path.join(tmp_dir, f"seg_{i:03d}.mp4")

            if c.get('type') == 'image':
                cmd = [
                    'ffmpeg', '-y', '-v', 'error',
                    '-loop', '1',
                    '-t', f"{c['dur']:.3f}",
                    '-i', c['src'],
                    '-filter_complex', vf_image,
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                    '-pix_fmt', 'yuv420p',
                    seg,
                ]
            else:
                # 중국어 자막 등이 박혀 있으면 먼저 지우고 크롭합니다
                # (크롭 전에 지워야 좌표가 원본 기준으로 맞습니다)
                chain = []
                box = (delogo_boxes or {}).get(c['src'])
                if box:
                    vw, vh = get_video_size(c['src'])
                    dl = delogo_filter(box, vw, vh)
                    if dl:
                        chain.append(dl)
                chain.append(vf_video)

                # 화면 맨 아래에 박힌 자막을 잘라내고 다시 채웁니다
                # (delogo보다 확실하지만 그만큼 화면이 확대됩니다)
                tp = (bottom_trim or {}).get(c['src'], 0)
                if tp > 0:
                    keep = int(SHORTS_HEIGHT * (100 - tp) / 100) // 2 * 2
                    chain.append(
                        f"crop={SHORTS_WIDTH}:{keep}:0:0,"
                        f"scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}"
                    )

                cmd = [
                    'ffmpeg', '-y', '-v', 'error',
                    '-ss', f"{c['src_start']:.3f}",
                    '-i', c['src'],
                    '-t', f"{c['dur']:.3f}",
                    '-vf', ','.join(chain),
                    '-an',                   # 원본 소리는 버립니다 (TTS를 씁니다)
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                    seg,
                ]

            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding='utf-8', errors='replace')
            if r.returncode != 0 or not os.path.exists(seg):
                logger.warning(f"클립 {i} 생성 실패: {(r.stderr or '')[-200:]}")
                continue
            seg_paths.append(seg)

            if progress_cb:
                progress_cb(i + 1, len(plan), f"클립 {i+1}/{len(plan)} 자르는 중")

        if not seg_paths:
            raise RuntimeError("잘라낸 클립이 하나도 없습니다.")

        # ── 2) 이어붙이기 ─────────────────────────
        concat_file = os.path.join(tmp_dir, "concat.txt")
        with open(concat_file, 'w', encoding='utf-8') as f:
            for p in seg_paths:
                f.write(f"file '{p.replace(os.sep, '/')}'\n")

        merged = os.path.join(tmp_dir, "merged.mp4")
        r = subprocess.run(
            ['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0',
             '-i', concat_file, '-c', 'copy', merged],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        if r.returncode != 0:
            raise RuntimeError(f"클립 병합 실패:\n{(r.stderr or '')[-500:]}")

        if progress_cb:
            progress_cb(len(plan), len(plan), "음성·자막 입히는 중")

        # ── 3) 음성 + 자막 입히기 ─────────────────
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        cmd = ['ffmpeg', '-y', '-v', 'error', '-i', merged,
               '-i', os.path.abspath(audio_path)]

        if srt_path and os.path.exists(srt_path):
            from modules.fonts import subtitle_filter
            cmd += ['-vf', subtitle_filter(srt_path)]

        cmd += [
            '-map', '0:v:0', '-map', '1:a:0',
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-shortest',
            output_path,
        ]

        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        if r.returncode != 0:
            raise RuntimeError(f"최종 렌더링 실패:\n{(r.stderr or '')[-500:]}")

        logger.info(f"✅ 컷편집 영상 완성: {output_path}")
        return output_path

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def auto_cut_edit(
    audio_path: str,
    srt_path: str,
    output_path: str,
    reference_urls: Optional[list[str]] = None,
    local_videos: Optional[list[str]] = None,
    image_paths: Optional[list[str]] = None,
    image_every: int = 3,
    ref_dir: str = "outputs/reference",
    anthropic_key: str = "",
    provider: str = "",
    gemini_key=None,
    max_cut_sec: float = DEFAULT_MAX_CUT_SEC,
    smart_match: bool = True,
    delogo_boxes: Optional[dict] = None,
    bottom_trim: Optional[dict] = None,
    skip_text_scenes: bool = False,
    manual_exclude: Optional[list] = None,
    progress_cb=None,
) -> dict:
    """
    영상(URL 또는 로컬 파일) + 이미지를 자막 타이밍에 맞춰 컷편집합니다.

    Args:
        audio_path: 생성된 TTS 음성
        srt_path: 자막 SRT
        output_path: 출력 MP4
        reference_urls: 내려받을 영상 URL (선택)
        local_videos: 이미 가지고 있는 영상 파일 경로 (선택)
        image_paths: 사이에 끼워 넣을 이미지 (선택)
        image_every: 몇 번째 컷마다 이미지를 넣을지 (3이면 3번째마다)
        provider: "gemini"(무료) 또는 "claude"(유료) — 장면을 고를 AI
        gemini_key: Gemini API 키 (하나 또는 여러 개)
        max_cut_sec: 한 컷의 최대 길이(초). 이보다 긴 자막은 여러 컷으로 쪼갭니다

    Returns:
        {'video_path', 'sources', 'plan', 'clip_count', 'image_count'}
    """
    sources = []

    # ── 로컬 영상 파일 ────────────────────────────
    for p in (local_videos or []):
        if p and os.path.exists(p):
            sources.append({
                'path': os.path.abspath(p),
                'url': '',
                'duration': get_video_duration(p),
                'title': os.path.basename(p),
            })
        else:
            logger.warning(f"로컬 영상을 찾을 수 없음: {p}")

    # ── URL 다운로드 ──────────────────────────────
    urls = [u for u in (reference_urls or []) if u.strip()]
    if urls:
        if progress_cb:
            progress_cb(0, 4, "참고 영상 다운로드 중")
        sources += download_reference_videos(urls, ref_dir)

    images = [p for p in (image_paths or []) if p and os.path.exists(p)]

    if not sources and not images:
        raise RuntimeError(
            "쓸 수 있는 소재가 없습니다. 영상 파일이나 URL, 또는 이미지를 넣어 주세요. "
            "(TikTok은 프로필이 아니라 개별 영상 URL이어야 합니다)"
        )

    if progress_cb:
        progress_cb(1, 4, "장면 전환 분석 중")

    for s in sources:
        try:
            s['scenes'] = detect_scenes(s['path'])
        except Exception as e:
            logger.warning(f"장면 감지 실패 {s['path']}: {e}")
            s['scenes'] = []

    if progress_cb:
        progress_cb(2, 4, "자막에 맞춰 컷 배치 중")

    # 사진을 볼 AI에 실제로 키가 있는지 미리 확인합니다
    # (없으면 썸네일 뽑는 헛수고를 하지 않습니다)
    _vision = _pick_vision_provider(provider, anthropic_key, gemini_key)
    vision_ok = bool(gemini_key) if _vision == "gemini" else bool(anthropic_key)
    if not vision_ok:
        logger.info(f"사진 보는 AI({_vision}) 키가 없어 자동 배치로 진행합니다")

    blocks = parse_srt_blocks(srt_path)
    if not blocks:
        raise RuntimeError("자막(SRT)을 읽지 못했습니다.")

    # ── 원본 자막이 박힌 장면 걸러내기 ────────────
    exclude_ranges = []
    text_info = {'method': None, 'flagged': 0, 'total': 0}

    if skip_text_scenes and sources:
        if progress_cb:
            progress_cb(2, 4, "자막 박힌 장면 찾는 중")
        try:
            _scenes = extract_scene_thumbnails(sources, max_scenes=40)
            text_info['total'] = len(_scenes)

            flagged = None
            if vision_ok:
                flagged = find_text_scenes_ai(
                    _scenes, api_key=anthropic_key,
                    provider=provider, gemini_key=gemini_key,
                )
                if flagged is not None:
                    text_info['method'] = 'ai'

            if flagged is None:
                flagged = find_text_scenes_free(_scenes)
                text_info['method'] = 'free'

            text_info['flagged'] = len(flagged)
            exclude_ranges = [
                (_scenes[i]['src'], _scenes[i]['start'], _scenes[i]['end'])
                for i in flagged
            ]
        except Exception as e:
            logger.warning(f"자막 장면 검출 실패: {e}")

    # 사용자가 직접 지정한 제외 구간을 더합니다
    if manual_exclude:
        exclude_ranges += list(manual_exclude)

    # ── 자막 내용에 맞는 장면 고르기 (AI) ─────────
    ai_scenes, ai_matches = None, None
    if smart_match and sources and vision_ok:
        if progress_cb:
            progress_cb(2, 4, "자막에 맞는 장면 고르는 중 (AI)")
        try:
            ai_scenes = extract_scene_thumbnails(sources)
            # 자막 있는 장면은 후보에서 빼고 고르게 합니다
            if ai_scenes and exclude_ranges:
                ai_scenes = [
                    sc for sc in ai_scenes
                    if not any(
                        os.path.abspath(sc['src']) == os.path.abspath(bp)
                        and min(sc['end'], be) - max(sc['start'], bs) > 0
                        for (bp, bs, be) in exclude_ranges
                    )
                ]
            if ai_scenes:
                ai_matches = match_scenes_with_ai(
                    ai_scenes, blocks, api_key=anthropic_key,
                    provider=provider, gemini_key=gemini_key,
                )
        except Exception as e:
            logger.warning(f"AI 매칭 준비 실패: {e}")
            ai_scenes, ai_matches = None, None

    # 음성 길이를 넘겨 마지막 클립이 끝까지 남도록 합니다
    audio_sec = get_video_duration(audio_path)   # ffprobe는 오디오에도 동작
    plan = build_clip_plan(
        blocks, sources,
        total_duration=audio_sec,
        image_paths=images,
        image_every=image_every,
        ai_scenes=ai_scenes,
        ai_matches=ai_matches,
        exclude_ranges=exclude_ranges,
        max_cut_sec=max_cut_sec,
    )

    if progress_cb:
        progress_cb(3, 4, "영상 편집 중")

    def _inner(cur, total, msg):
        if progress_cb:
            progress_cb(3, 4, msg)

    video_path = render_cut_video(
        plan=plan,
        audio_path=audio_path,
        output_path=output_path,
        srt_path=srt_path,
        delogo_boxes=delogo_boxes,
        bottom_trim=bottom_trim,
        progress_cb=_inner,
    )

    if progress_cb:
        progress_cb(4, 4, "완료")

    return {
        'video_path': video_path,
        'sources': sources,
        'plan': plan,
        'clip_count': len(plan),
        'image_count': sum(1 for c in plan if c.get('type') == 'image'),
        'ai_matched': bool(ai_matches),
        'text_filter': text_info,
        'sub_count': len(blocks),
        'max_cut_sec': max_cut_sec,
        'scene_count': sum(len(s.get('scenes') or []) for s in sources),
    }


# ── 직접 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    import sys
    import glob as _glob

    # 사용법:
    #   python modules/clip_editor.py <음성.wav> <자막.srt> [영상폴더] [이미지폴더]
    audio = sys.argv[1] if len(sys.argv) > 1 else ""
    srt = sys.argv[2] if len(sys.argv) > 2 else ""
    vid_dir = sys.argv[3] if len(sys.argv) > 3 else ""
    img_dir = sys.argv[4] if len(sys.argv) > 4 else ""

    if not audio or not srt:
        print("사용법: python modules/clip_editor.py <음성.wav> <자막.srt> [영상폴더] [이미지폴더]")
        raise SystemExit(1)

    local_videos = []
    if vid_dir:
        for ext in ('mp4', 'mov', 'webm', 'mkv'):
            local_videos += _glob.glob(os.path.join(vid_dir, f'*.{ext}'))

    images = []
    if img_dir:
        for ext in ('jpg', 'jpeg', 'png', 'webp'):
            images += _glob.glob(os.path.join(img_dir, f'*.{ext}'))

    print(f"영상 {len(local_videos)}개 / 이미지 {len(images)}개")

    def prog(cur, total, msg):
        print(f"[{cur}/{total}] {msg}")

    result = auto_cut_edit(
        audio_path=audio,
        srt_path=srt,
        output_path="outputs/_cut_test.mp4",
        local_videos=local_videos,
        image_paths=images,
        progress_cb=prog,
    )
    print(f"\n완성: {result['video_path']}")
    print(f"클립 {result['clip_count']}개 (이미지 {result['image_count']}개)")
    t = 0.0
    for c in result['plan']:
        kind = '🖼️' if c.get('type') == 'image' else '🎬'
        print(f"  {t:5.1f}s {kind} {os.path.basename(c['src'])[:24]:<26} "
              f"+{c['dur']:.1f}s | {c['text'][:24]}")
        t += c['dur']
