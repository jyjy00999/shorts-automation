# ====================================================
# 모듈 9: 원본 자막 위치 자동 검출 (subtitle_detect.py)
#
# 영상 어디에 자막이 박혀 있든 OCR로 위치를 찾아냅니다.
# 글자를 '읽지' 않고 '찾기'만 하므로, 장식체나 저대비 자막도
# 위치는 잡힙니다.
#
# ⚠️ EasyOCR이 필요합니다: pip install easyocr
#    (없으면 detect_subtitle_bands가 None을 돌려줍니다)
# ====================================================

import os
import subprocess
import tempfile
from collections import defaultdict
from typing import Optional
from loguru import logger

_READER = None
_READER_FAILED = False

# 세로 몇 % 단위로 나눠서 투표할지
BAND_STEP = 2
# 전체 프레임 중 이 비율 이상에서 글자가 보여야 자막으로 인정.
# 0.5면 "절반 이상의 프레임에 계속 떠 있는 글자" = 자막 트랙만 남습니다.
# 더 낮추면 가끔 나오는 설명 문구까지 잡지만, 배경 글씨도 함께 걸려듭니다.
MIN_VOTE_RATIO = 0.50
# 검출 영역 위아래로 두는 여유
PAD_PCT = 2.5
# 이 간격 이내로 떨어진 띠는 하나로 묶습니다 (BAND_STEP 단위)
MERGE_GAP = 3


def _get_reader(gpu: bool = True):
    """EasyOCR 리더를 한 번만 만들어 재사용합니다."""
    global _READER, _READER_FAILED
    if _READER is not None:
        return _READER
    if _READER_FAILED:
        return None
    try:
        import easyocr
        logger.info("EasyOCR 로딩 중... (첫 실행은 모델을 받느라 오래 걸립니다)")
        _READER = easyocr.Reader(['ch_sim', 'en'], gpu=gpu, verbose=False)
        logger.info("EasyOCR 준비 완료")
        return _READER
    except Exception as e:
        _READER_FAILED = True
        logger.warning(f"EasyOCR 사용 불가 ({e}). 자막 자동 검출을 건너뜁니다.")
        return None


def _sample_frames(video_path: str, n: int = 10) -> list:
    """영상에서 고르게 n장을 뽑습니다. [(시각, 경로), ...]"""
    out_dir = tempfile.mkdtemp(prefix="subdet_")
    try:
        dur = float(subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
            capture_output=True, text=True).stdout.strip() or 0)
    except Exception:
        dur = 0.0

    if dur <= 0:
        return []

    res = []
    for i in range(n):
        t = dur * (0.05 + 0.9 * i / max(n - 1, 1))
        p = os.path.join(out_dir, f"f{i:02d}.png")
        r = subprocess.run(
            ['ffmpeg', '-y', '-v', 'error', '-ss', f'{t:.2f}',
             '-i', video_path, '-frames:v', '1', p],
            capture_output=True)
        if r.returncode == 0 and os.path.exists(p):
            res.append((t, p))
    return res


def detect_subtitle_bands(
    video_path: str,
    frames: int = 12,
    gpu: bool = True,
    min_vote_ratio: float = None,
) -> Optional[list]:
    """
    영상에 박힌 자막의 위치를 찾습니다.

    여러 프레임에서 반복해서 글자가 나오는 가로 띠만 자막으로 봅니다.
    (배경 간판이나 제품 라벨처럼 스쳐가는 글자는 걸러집니다)

    Returns:
        [{'x','y','w','h','votes','frames'}, ...]  — 모두 0~100 퍼센트
        EasyOCR을 못 쓰면 None, 자막이 없으면 빈 리스트
    """
    reader = _get_reader(gpu)
    if reader is None:
        return None

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None

    samples = _sample_frames(video_path, frames)
    if not samples:
        return []

    votes = defaultdict(int)
    x_ranges = defaultdict(list)

    for _t, p in samples:
        try:
            img = np.asarray(Image.open(p).convert('RGB'))
        except Exception:
            continue
        h, w = img.shape[:2]

        try:
            # detect()는 위치만 반환합니다 — 읽기를 건너뛰어 빠르고,
            # 읽기 어려운 장식체 자막도 위치는 잡힙니다.
            horiz, free = reader.detect(img)
        except Exception as e:
            logger.warning(f"검출 실패 ({os.path.basename(p)}): {str(e)[:80]}")
            continue

        boxes = []
        for grp in (horiz or []):
            for b in grp:
                if len(b) == 4:                 # [x0, x1, y0, y1]
                    boxes.append((b[2], b[3], b[0], b[1]))
        for grp in (free or []):
            for poly in grp:
                pts = np.array(poly, dtype=float)
                boxes.append((pts[:, 1].min(), pts[:, 1].max(),
                              pts[:, 0].min(), pts[:, 0].max()))

        counted = set()
        for (y0, y1, x0, x1) in boxes:
            yp0, yp1 = y0 / h * 100, y1 / h * 100
            for band in range(int(yp0 // BAND_STEP), int(yp1 // BAND_STEP) + 1):
                if band not in counted:
                    votes[band] += 1
                    counted.add(band)
                x_ranges[band].append((x0 / w * 100, x1 / w * 100))

    if not votes:
        return []

    ratio = MIN_VOTE_RATIO if min_vote_ratio is None else min_vote_ratio
    need = max(2, int(len(samples) * ratio))
    hot = sorted(b for b, c in votes.items() if c >= need)
    if not hot:
        return []

    # 가까이 있는 띠끼리 묶습니다
    # (같은 자막인데 시점마다 높이가 조금씩 달라 띠가 갈리는 경우가 많습니다)
    groups, cur = [], [hot[0]]
    for b in hot[1:]:
        if b - cur[-1] <= MERGE_GAP:
            cur.append(b)
        else:
            groups.append(cur)
            cur = [b]
    groups.append(cur)

    result = []
    for g in groups:
        xs = [x for b in g for x in x_ranges[b]]
        y0 = max(0.0, g[0] * BAND_STEP - PAD_PCT)
        y1 = min(100.0, (g[-1] + 1) * BAND_STEP + PAD_PCT)
        x0 = max(0.0, min(x[0] for x in xs) - PAD_PCT) if xs else 0.0
        x1 = min(100.0, max(x[1] for x in xs) + PAD_PCT) if xs else 100.0

        result.append({
            'x': round(x0, 1),
            'y': round(y0, 1),
            'w': round(x1 - x0, 1),
            'h': round(y1 - y0, 1),
            'votes': max(votes[b] for b in g),
            'frames': len(samples),
        })

    logger.info(f"{os.path.basename(video_path)}: 자막 영역 {len(result)}개 검출")
    for r in result:
        logger.info(f"  y {r['y']}~{r['y']+r['h']}% "
                    f"x {r['x']}~{r['x']+r['w']}% ({r['votes']}/{r['frames']})")
    return result


def detect_for_videos(
    video_paths: list,
    frames: int = 12,
    gpu: bool = True,
    min_vote_ratio: float = None,
) -> dict:
    """여러 영상을 한 번에 검출합니다. {경로: [영역, ...]}"""
    out = {}
    for v in video_paths:
        if not os.path.exists(v):
            continue
        try:
            bands = detect_subtitle_bands(
                v, frames=frames, gpu=gpu, min_vote_ratio=min_vote_ratio)
            if bands:
                out[v] = bands
        except Exception as e:
            logger.warning(f"검출 건너뜀 {os.path.basename(v)}: {e}")
    return out


if __name__ == "__main__":
    import sys
    import glob

    target = sys.argv[1] if len(sys.argv) > 1 else "outputs/source_videos"
    vids = ([target] if target.endswith('.mp4')
            else sorted(glob.glob(os.path.join(target, "*.mp4"))))

    for v in vids:
        bands = detect_subtitle_bands(v)
        print(f"\n=== {os.path.basename(v)[:30]} ===")
        if bands is None:
            print("  EasyOCR 없음")
        elif not bands:
            print("  자막 없음")
        else:
            for b in bands:
                print(f"  x={b['x']}% y={b['y']}% w={b['w']}% h={b['h']}%  "
                      f"({b['votes']}/{b['frames']} 프레임)")
