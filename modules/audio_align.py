# ====================================================
# 모듈: 음성에 자막 맞추기 (audio_align.py)
#
# 글자 수만으로 시간을 나누면 자막이 음성과 어긋납니다.
# 사람은 문장 사이에서 쉬는데, 그 쉼은 글자가 0개이기 때문입니다.
#
# 그래서 음성 파일에서 '실제로 소리가 나는 구간'을 찾아내고,
# 글자는 소리 나는 시간에만 배분합니다.
# 쉬는 구간은 자동으로 자막 경계에 놓이게 됩니다.
# ====================================================

import os
import subprocess
from typing import List, Tuple

from loguru import logger

SAMPLE_RATE = 16000
WIN_SEC = 0.02          # 20ms 단위로 소리 크기를 봅니다
MIN_PAUSE_SEC = 0.18    # 이보다 긴 무음은 '쉼'으로 봅니다
MIN_SPEECH_SEC = 0.10   # 너무 짧은 소리는 잡음으로 보고 무시합니다


def _decode_pcm(audio_path: str):
    """어떤 오디오 형식이든 FFmpeg으로 16kHz 모노 PCM으로 읽어들입니다."""
    try:
        import numpy as np
    except ImportError:
        return None

    cmd = [
        'ffmpeg', '-v', 'error', '-i', os.path.abspath(audio_path),
        '-ac', '1', '-ar', str(SAMPLE_RATE), '-f', 's16le', '-',
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode != 0 or not r.stdout:
            logger.warning(f"오디오 디코딩 실패: {(r.stderr or b'')[-200:]}")
            return None
        return np.frombuffer(r.stdout, dtype='<i2').astype('float32')
    except Exception as e:
        logger.warning(f"오디오 디코딩 오류: {e}")
        return None


def detect_speech_segments(
    audio_path: str,
    min_pause_sec: float = MIN_PAUSE_SEC,
    min_speech_sec: float = MIN_SPEECH_SEC,
) -> List[Tuple[float, float]]:
    """소리가 나는 구간 목록을 [(시작, 끝), ...] 으로 돌려줍니다.

    못 찾으면 빈 리스트를 돌려주고, 부르는 쪽에서 예전 방식으로
    (글자 수 비례) 처리하면 됩니다.
    """
    if not audio_path or not os.path.exists(audio_path):
        return []

    try:
        import numpy as np
    except ImportError:
        logger.warning("numpy 가 없어 음성 정렬을 건너뜁니다")
        return []

    a = _decode_pcm(audio_path)
    if a is None or len(a) == 0:
        return []

    win = int(SAMPLE_RATE * WIN_SEC)
    frames = len(a) // win
    if frames < 2:
        return []

    # 창마다 소리 크기(RMS)
    rms = np.sqrt((a[:frames * win].reshape(frames, win) ** 2).mean(axis=1))
    peak = float(rms.max())
    if peak <= 0:
        return []

    # 전체에서 가장 큰 소리의 2% 를 기준으로 '소리 있음'을 판단합니다
    thr = max(peak * 0.02, 60.0)
    voiced = rms > thr
    if not voiced.any():
        return []

    # 짧은 무음은 쉼으로 치지 않고 이어 붙입니다
    min_pause_win = max(1, int(min_pause_sec / WIN_SEC))
    segments = []
    i = 0
    while i < frames:
        if not voiced[i]:
            i += 1
            continue
        j = i
        gap = 0
        while j < frames:
            if voiced[j]:
                gap = 0
            else:
                gap += 1
                if gap >= min_pause_win:
                    break
            j += 1
        end = j - gap + 1
        segments.append((i * WIN_SEC, min(end, frames) * WIN_SEC))
        i = j + 1

    # 너무 짧은 조각 제거
    segments = [(s, e) for s, e in segments if e - s >= min_speech_sec]

    if segments:
        total = sum(e - s for s, e in segments)
        logger.info(
            f"발화 구간 {len(segments)}개, 소리 {total:.1f}초 "
            f"(쉼 {frames * WIN_SEC - total:.1f}초)"
        )
    return segments


def speech_to_wall(segments: List[Tuple[float, float]], x: float) -> float:
    """'소리 나는 시간' 기준 위치 x 를 실제 영상 시각으로 바꿉니다.

    예) 쉼이 중간에 있으면, 그 쉼을 건너뛴 만큼 실제 시각은 더 뒤입니다.
    """
    if not segments:
        return x
    used = 0.0
    for s, e in segments:
        dur = e - s
        if x <= used + dur:
            return s + (x - used)
        used += dur
    return segments[-1][1]


def speech_total(segments: List[Tuple[float, float]]) -> float:
    return sum(e - s for s, e in segments)


def pause_starts(segments: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """쉬는 구간 목록 [(쉼 시작, 다음 발화 시작), ...]"""
    return [
        (segments[i][1], segments[i + 1][0])
        for i in range(len(segments) - 1)
    ]


def snap_to_pause(
    t: float,
    pauses: List[Tuple[float, float]],
    tolerance: float = 0.7,
) -> float:
    """자막이 바뀌는 시각을 근처의 '쉼'에 붙여 줍니다.

    글자 수로 계산한 시각은 조금씩 어긋나는데, 사람이 가장 잘 느끼는
    어긋남은 '문장이 끝났는데 자막이 안 바뀌는' 경우입니다.
    경계가 쉼 근처라면 그 쉼의 시작점으로 당겨 붙입니다.
    """
    if not pauses:
        return t
    best, best_d = None, tolerance
    for p_start, p_end in pauses:
        # 쉼 구간 안이면 그대로 둬도 되지만, 시작점에 맞추는 게 자연스럽습니다
        d = abs(t - p_start)
        if d < best_d:
            best, best_d = p_start, d
    return best if best is not None else t
