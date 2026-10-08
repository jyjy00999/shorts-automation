# ====================================================
# 모듈 6: 1차 가편집 영상 렌더러 (video_renderer.py)
# MoviePy + FFmpeg를 활용해 이미지 + 음성 + 자막을
# 하나의 MP4 쇼츠 영상으로 합성합니다.
#
# ⚠️ 사전 설치 필요:
# 1. pip install moviepy
# 2. FFmpeg: https://ffmpeg.org/download.html
#    - Windows: winget install ffmpeg
#    - Mac: brew install ffmpeg
# ====================================================

import os
import math
import tempfile
from pathlib import Path
from typing import Optional
from loguru import logger

# MoviePy는 1.x와 2.x의 API가 다릅니다.
#   1.x: moviepy.editor,  .set_duration() / .resize() / .set_audio()
#   2.x: moviepy(루트),    .with_duration() / .resized() / .with_audio()
MOVIEPY_AVAILABLE = False
MOVIEPY_V2 = False
try:
    # 2.x: 루트 패키지에서 직접 import
    from moviepy import (
        ImageClip, AudioFileClip, CompositeVideoClip,
        concatenate_videoclips, TextClip, ColorClip
    )
    MOVIEPY_AVAILABLE = True
    MOVIEPY_V2 = True
except ImportError:
    try:
        # 1.x: moviepy.editor
        from moviepy.editor import (
            ImageClip, AudioFileClip, CompositeVideoClip,
            concatenate_videoclips, TextClip, ColorClip
        )
        MOVIEPY_AVAILABLE = True
    except ImportError:
        logger.warning("moviepy 미설치. 'pip install moviepy' 실행 필요")


def _with_duration(clip, seconds):
    """MoviePy 1.x/2.x 양쪽에서 클립 길이를 설정합니다."""
    return clip.with_duration(seconds) if MOVIEPY_V2 else clip.set_duration(seconds)


def _with_start(clip, seconds):
    """MoviePy 1.x/2.x 양쪽에서 시작 시점을 설정합니다."""
    return clip.with_start(seconds) if MOVIEPY_V2 else clip.set_start(seconds)


def _with_position(clip, pos):
    """MoviePy 1.x/2.x 양쪽에서 위치를 설정합니다."""
    return clip.with_position(pos) if MOVIEPY_V2 else clip.set_position(pos)


def _with_audio(clip, audio):
    """MoviePy 1.x/2.x 양쪽에서 오디오를 붙입니다."""
    return clip.with_audio(audio) if MOVIEPY_V2 else clip.set_audio(audio)


def _resized(clip, size):
    """MoviePy 1.x/2.x 양쪽에서 클립 크기를 조정합니다."""
    return clip.resized(size) if MOVIEPY_V2 else clip.resize(size)


def _apply_fades(clip, fade_in: float = 0, fade_out: float = 0):
    """MoviePy 1.x/2.x 양쪽에서 페이드 인/아웃을 적용합니다."""
    if not fade_in and not fade_out:
        return clip
    try:
        if MOVIEPY_V2:
            from moviepy import vfx
            effects = []
            if fade_in:
                effects.append(vfx.FadeIn(fade_in))
            if fade_out:
                effects.append(vfx.FadeOut(fade_out))
            return clip.with_effects(effects)
        else:
            from moviepy.video.fx.all import fadein, fadeout
            if fade_in:
                clip = fadein(clip, fade_in)
            if fade_out:
                clip = fadeout(clip, fade_out)
            return clip
    except Exception as e:
        logger.warning(f"페이드 효과 적용 실패 (효과 없이 계속): {e}")
        return clip

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ── 쇼츠 표준 해상도 ──────────────────────────────
SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920
SHORTS_FPS = 30


def create_product_slideshow(
    image_paths: list[str],
    audio_path: str,
    output_path: str,
    srt_path: Optional[str] = None,
    transition_duration: float = 0.5,  # 이미지 간 전환 효과 시간
    zoom_effect: bool = True,           # 켄번스 줌 효과
) -> str:
    """
    상품 이미지들로 슬라이드쇼 형식의 쇼츠 영상을 생성합니다.

    Args:
        image_paths: 상품 이미지 파일 경로 리스트
        audio_path: TTS 음성 파일 경로
        output_path: 출력 MP4 파일 경로
        srt_path: SRT 자막 파일 경로 (선택)
        transition_duration: 이미지 간 페이드 시간 (초)
        zoom_effect: 켄번스 줌 효과 적용 여부

    Returns:
        생성된 MP4 파일 경로
    """
    if not MOVIEPY_AVAILABLE:
        raise ImportError(
            "moviepy가 설치되지 않았습니다.\n"
            "설치: pip install moviepy\n"
            "FFmpeg도 설치 필요: https://ffmpeg.org"
        )

    if not image_paths:
        raise ValueError("이미지 파일이 없습니다.")

    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"음성 파일을 찾을 수 없습니다: {audio_path}")

    logger.info(f"영상 렌더링 시작: 이미지 {len(image_paths)}장, 음성 {audio_path}")

    # ── 1. 오디오 로드 및 길이 확인 ─────────────────
    audio_clip = AudioFileClip(audio_path)
    total_duration = audio_clip.duration
    logger.info(f"오디오 길이: {total_duration:.1f}초")

    # ── 2. 이미지당 표시 시간 계산 ───────────────────
    # 각 이미지를 균등하게 배분 (마지막 이미지는 약간 더 길게)
    base_duration = total_duration / len(image_paths)
    image_durations = [base_duration] * len(image_paths)

    # ── 3. 이미지 클립 생성 ──────────────────────────
    clips = []
    for i, (img_path, duration) in enumerate(zip(image_paths, image_durations)):
        try:
            # 이미지를 쇼츠 비율(9:16)로 크롭/리사이즈
            pil_img = prepare_image_for_shorts(img_path)
            tmp_path = f"{tempfile.gettempdir()}/shorts_img_{i}.jpg"
            pil_img.save(tmp_path, quality=95)

            clip = _with_duration(ImageClip(tmp_path), duration)

            # 켄번스 효과: 서서히 줌인 (1.0 → 1.08배)
            if zoom_effect:
                clip = _resized(clip, lambda t, d=duration: 1.0 + 0.08 * (t / d))

            # 페이드 인/아웃
            fade_in = transition_duration if i > 0 else 0
            fade_out = transition_duration if i < len(image_paths) - 1 else 0
            clip = _apply_fades(clip, fade_in, fade_out)

            clips.append(clip)
            logger.info(f"이미지 {i+1}/{len(image_paths)} 처리 완료")

        except Exception as e:
            logger.error(f"이미지 {img_path} 처리 실패: {e}")
            # 실패한 이미지는 검정 화면으로 대체
            fallback = ColorClip(
                size=(SHORTS_WIDTH, SHORTS_HEIGHT),
                color=[0, 0, 0],
                duration=duration
            )
            clips.append(fallback)

    # ── 4. 클립 연결 ─────────────────────────────────
    video = concatenate_videoclips(clips, method="compose")
    video = _with_audio(video, audio_clip)

    # ── 5. 자막 추가 (SRT 파일이 있는 경우) ──────────
    if srt_path and os.path.exists(srt_path):
        try:
            subtitle_clips = parse_srt_to_textclips(srt_path)
            if subtitle_clips:
                video = CompositeVideoClip([video] + subtitle_clips)
                logger.info(f"자막 {len(subtitle_clips)}개 추가")
        except Exception as e:
            logger.warning(f"자막 추가 실패 (무자막으로 계속): {e}")

    # ── 6. MP4 렌더링 ────────────────────────────────
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"MP4 렌더링 중... (시간이 걸릴 수 있습니다)")
    video.write_videofile(
        output_path,
        fps=SHORTS_FPS,
        codec='libx264',
        audio_codec='aac',
        bitrate='4000k',           # 고화질 쇼츠 기준
        audio_bitrate='192k',
        preset='medium',           # 속도/품질 균형
        threads=4,
        logger=None,               # moviepy 내부 로그 억제
    )

    # 클린업
    audio_clip.close()
    video.close()
    for clip in clips:
        clip.close()

    logger.info(f"✅ 영상 렌더링 완료: {output_path}")
    return output_path


def prepare_image_for_shorts(image_path: str) -> 'Image.Image':
    """
    이미지를 쇼츠 비율(1080x1920, 9:16)로 변환합니다.
    - 원본 비율 유지하며 중앙 크롭
    - 여백은 배경색으로 채움 (블러 처리)

    Args:
        image_path: 원본 이미지 경로

    Returns:
        변환된 PIL Image 객체
    """
    if not PIL_AVAILABLE:
        raise ImportError("Pillow가 설치되지 않았습니다: pip install Pillow")

    img = Image.open(image_path).convert('RGB')
    orig_w, orig_h = img.size
    target_ratio = SHORTS_WIDTH / SHORTS_HEIGHT  # 9:16 = 0.5625

    # 새 캔버스 생성 (쇼츠 크기)
    canvas = Image.new('RGB', (SHORTS_WIDTH, SHORTS_HEIGHT), (0, 0, 0))

    # 이미지 스케일링 (전체가 보이도록 letterbox 방식)
    img_ratio = orig_w / orig_h

    if img_ratio > target_ratio:
        # 원본이 더 넓음: 너비 맞춤
        new_w = SHORTS_WIDTH
        new_h = int(SHORTS_WIDTH / img_ratio)
    else:
        # 원본이 더 좁음: 높이 맞춤
        new_h = SHORTS_HEIGHT
        new_w = int(SHORTS_HEIGHT * img_ratio)

    img_resized = img.resize((new_w, new_h), Image.LANCZOS)

    # 중앙에 배치
    paste_x = (SHORTS_WIDTH - new_w) // 2
    paste_y = (SHORTS_HEIGHT - new_h) // 2

    # 배경: 블러 처리된 이미지 (시네마틱 효과)
    try:
        from PIL import ImageFilter
        bg = img.resize((SHORTS_WIDTH, SHORTS_HEIGHT), Image.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=40))
        # 배경 어둡게 (가독성)
        from PIL import ImageEnhance
        bg = ImageEnhance.Brightness(bg).enhance(0.4)
        canvas.paste(bg, (0, 0))
    except Exception:
        pass  # 블러 실패시 검정 배경 유지

    canvas.paste(img_resized, (paste_x, paste_y))

    return canvas


def zoom_frame(frame, t: float, duration: float, zoom_start: float, zoom_end: float):
    """켄번스 줌 효과를 프레임에 적용합니다."""
    import numpy as np
    zoom = zoom_start + (zoom_end - zoom_start) * (t / duration)
    h, w = frame.shape[:2]
    new_h, new_w = int(h * zoom), int(w * zoom)
    # 리사이즈
    from PIL import Image
    pil = Image.fromarray(frame)
    pil = pil.resize((new_w, new_h), Image.LANCZOS)
    # 중앙 크롭
    x = (new_w - w) // 2
    y = (new_h - h) // 2
    pil = pil.crop((x, y, x + w, y + h))
    return np.array(pil)


def parse_srt_to_textclips(srt_path: str) -> list:
    """
    SRT 파일을 파싱하여 MoviePy TextClip 리스트로 변환합니다.

    ⚠️ TextClip은 ImageMagick 설치 필요
       (없으면 자막 없이 렌더링)
    """
    import re

    with open(srt_path, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    # SRT 파싱: 번호, 시간, 텍스트
    pattern = r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n([\s\S]*?)(?=\n\n|\Z)'
    matches = re.findall(pattern, content)

    text_clips = []
    for match in matches:
        _, start_str, end_str, text = match
        start = srt_time_to_seconds(start_str)
        end = srt_time_to_seconds(end_str)
        duration = end - start
        text = text.strip()

        try:
            if MOVIEPY_V2:
                # 2.x: fontsize -> font_size, 첫 인자는 font(경로), 텍스트는 키워드
                txt_clip = TextClip(
                    text=text,
                    font_size=72,
                    color='white',
                    stroke_color='black',
                    stroke_width=3,
                    method='caption',
                    size=(SHORTS_WIDTH - 100, None),
                    text_align='center',
                )
            else:
                txt_clip = TextClip(
                    text,
                    fontsize=72,
                    color='white',
                    font='NanumGothic-Bold',
                    stroke_color='black',
                    stroke_width=3,
                    method='caption',
                    size=(SHORTS_WIDTH - 100, None),
                    align='center',
                )

            txt_clip = _with_duration(txt_clip, duration)
            txt_clip = _with_start(txt_clip, start)
            txt_clip = _with_position(txt_clip, ('center', int(SHORTS_HEIGHT * 0.78)))
            text_clips.append(txt_clip)
        except Exception as e:
            logger.warning(f"TextClip 생성 실패 ({e}). FFmpeg 자막 방식으로 대체됩니다.")
            break

    return text_clips


def srt_time_to_seconds(time_str: str) -> float:
    """SRT 시간 문자열을 초로 변환합니다. 예: '00:01:05,500' → 65.5"""
    h, m, rest = time_str.split(':')
    s, ms = rest.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def render_with_ffmpeg_direct(
    image_paths: list[str],
    audio_path: str,
    output_path: str,
    srt_path: Optional[str] = None,
) -> str:
    """
    FFmpeg를 직접 CLI로 호출하여 영상을 렌더링합니다.
    (MoviePy 없이도 작동하는 대안)

    이 함수는 FFmpeg가 PATH에 설치되어 있어야 합니다.
    """
    import subprocess
    import shutil

    if not shutil.which('ffmpeg'):
        raise RuntimeError(
            "FFmpeg가 설치되어 있지 않습니다.\n"
            "Windows: winget install ffmpeg\n"
            "Mac: brew install ffmpeg"
        )

    # 오디오 길이에 맞춰 이미지당 표시 시간 계산
    audio_clip_info = get_audio_info_ffprobe(audio_path)
    total_duration = audio_clip_info.get('duration', 45.0)
    per_img_duration = total_duration / max(len(image_paths), 1)

    # 이미지를 9:16 캔버스로 미리 변환
    prepared_images = []
    for i, img_path in enumerate(image_paths):
        if PIL_AVAILABLE:
            pil_img = prepare_image_for_shorts(img_path)
            prepared_path = os.path.join(tempfile.gettempdir(), f"ffmpeg_img_{i}.jpg")
            pil_img.save(prepared_path, quality=95)
        else:
            prepared_path = img_path
        prepared_images.append(os.path.abspath(prepared_path))

    # ── 입력 구성 ────────────────────────────────────
    # concat demuxer는 필터와 섞이면 길이가 어긋나는 경우가 있어,
    # 이미지마다 -loop/-t 로 입력을 만들고 filter_complex로 이어붙입니다.
    cmd = ['ffmpeg', '-y']
    for img in prepared_images:
        cmd += ['-loop', '1', '-t', f'{per_img_duration:.3f}', '-i', img]
    cmd += ['-i', os.path.abspath(audio_path)]

    audio_idx = len(prepared_images)   # 오디오 입력 인덱스

    # ── 필터 그래프 ─────────────────────────────────
    scale_pad = (
        f'scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:force_original_aspect_ratio=decrease,'
        f'pad={SHORTS_WIDTH}:{SHORTS_HEIGHT}:(ow-iw)/2:(oh-ih)/2,'
        f'setsar=1,fps={SHORTS_FPS},format=yuv420p'
    )

    parts = []
    for i in range(len(prepared_images)):
        parts.append(f'[{i}:v]{scale_pad}[v{i}]')

    concat_inputs = ''.join(f'[v{i}]' for i in range(len(prepared_images)))
    parts.append(f'{concat_inputs}concat=n={len(prepared_images)}:v=1:a=0[vcat]')

    last_label = 'vcat'
    if srt_path and os.path.exists(srt_path):
        # Windows 경로를 subtitles 필터용으로 이스케이프
        #   C:\a\b.srt  ->  C\:/a/b.srt
        esc = os.path.abspath(srt_path).replace('\\', '/').replace(':', r'\:')
        style = (
            'FontName=Malgun Gothic,FontSize=18,'
            'PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,'
            'Outline=2,Shadow=0,Bold=1,Alignment=2,MarginV=60'
        )
        parts.append(f"[vcat]subtitles='{esc}':force_style='{style}'[vout]")
        last_label = 'vout'

    cmd += [
        '-filter_complex', ';'.join(parts),
        '-map', f'[{last_label}]',
        '-map', f'{audio_idx}:a:0',
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
        '-c:a', 'aac', '-b:a', '192k',
        '-pix_fmt', 'yuv420p',
        '-shortest',
        output_path,
    ]

    logger.info("FFmpeg 명령 실행 중...")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')

    if result.returncode != 0:
        tail = (result.stderr or '')[-1200:]
        raise RuntimeError(f"FFmpeg 오류:\n{tail}")

    logger.info(f"✅ FFmpeg 렌더링 완료: {output_path}")
    return output_path


def get_audio_info_ffprobe(audio_path: str) -> dict:
    """ffprobe로 오디오 정보를 가져옵니다."""
    import subprocess, json, shutil

    if not shutil.which('ffprobe'):
        return {'duration': 45.0}

    cmd = [
        'ffprobe', '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        info = json.loads(result.stdout)
        return {'duration': float(info.get('format', {}).get('duration', 45.0))}
    return {'duration': 45.0}


# ── 직접 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    print("영상 렌더러 테스트")
    print(f"MoviePy 사용 가능: {MOVIEPY_AVAILABLE}")
    print(f"Pillow 사용 가능: {PIL_AVAILABLE}")

    # 실제 테스트는 이미지와 오디오 파일이 필요합니다
    # create_product_slideshow(
    #     image_paths=["product1.jpg", "product2.jpg"],
    #     audio_path="tts_output.wav",
    #     output_path="outputs/final_shorts.mp4",
    #     srt_path="outputs/subtitle.srt",
    # )
