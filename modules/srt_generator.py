# ====================================================
# 모듈 5: SRT 자막 파일 생성기 (srt_generator.py)
# 대본 텍스트와 오디오 길이를 기반으로
# 영상 편집 프로그램에서 바로 사용 가능한
# SRT 자막 파일을 자동 생성합니다.
# ====================================================

import re
import math
from pathlib import Path
from loguru import logger


def seconds_to_srt_time(seconds: float) -> str:
    """
    초(float)를 SRT 타임코드 형식으로 변환합니다.
    SRT 형식: HH:MM:SS,mmm (시:분:초,밀리초)

    예: 65.5초 → "00:01:05,500"
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def split_script_into_lines(
    script: str,
    max_chars_per_line: int = 18,
    max_lines_per_block: int = 2,
) -> list[str]:
    """
    대본 텍스트를 자막 블록으로 분할합니다.

    쇼츠 자막 규칙:
    - 한 줄 최대 18자 (세로형 화면 기준)
    - 한 블록 최대 2줄
    - 문장 단위로 자연스럽게 분할

    Args:
        script: 전체 대본 텍스트
        max_chars_per_line: 한 줄 최대 글자 수
        max_lines_per_block: 블록당 최대 줄 수

    Returns:
        자막 블록 리스트 (각 블록이 하나의 SRT 항목이 됨)
    """
    # 1. 구두점 기준으로 문장 분리
    # 마침표, 느낌표, 물음표, 줄바꿈, 쉼표(긴 구문의 경우) 기준
    sentences = re.split(r'(?<=[.!?~\n])\s*|(?<=,)\s+', script.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    def wrap_words(text: str) -> list[str]:
        """
        어절(띄어쓰기) 단위로 줄을 채웁니다.

        글자 단위로 자르면 '씨름했 / 는데,' 처럼 단어가 쪼개져서
        읽기 어려워집니다. 단어는 절대 끊지 않습니다.
        """
        lines = []
        cur = ""
        for word in text.split():
            # 한 단어가 줄 길이를 넘으면 어쩔 수 없이 쪼갭니다 (드묾)
            if len(word) > max_chars_per_line:
                if cur:
                    lines.append(cur)
                    cur = ""
                for i in range(0, len(word), max_chars_per_line):
                    piece = word[i:i + max_chars_per_line]
                    if len(piece) == max_chars_per_line:
                        lines.append(piece)
                    else:
                        cur = piece
                continue

            candidate = f"{cur} {word}".strip()
            if len(candidate) <= max_chars_per_line:
                cur = candidate
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    blocks = []
    current_lines = []

    for sentence in sentences:
        for line in wrap_words(sentence):
            current_lines.append(line)
            if len(current_lines) >= max_lines_per_block:
                blocks.append("\n".join(current_lines))
                current_lines = []

        # 한 줄짜리 짧은 문장은 다음 문장과 합칠 여지를 둡니다.
        # (문장마다 무조건 끊으면 '저도 그랬어요.' 같은 한 줄이
        #  독립 자막이 되어 너무 잘게 깜빡입니다)
        if len(current_lines) >= max_lines_per_block:
            blocks.append("\n".join(current_lines))
            current_lines = []

    if current_lines:
        blocks.append("\n".join(current_lines))

    # 빈 블록 제거
    blocks = [b for b in blocks if b.strip()]

    logger.info(f"대본 분할 완료: {len(sentences)}개 문장 → {len(blocks)}개 자막 블록")
    return blocks


def calculate_timings(
    blocks: list[str],
    total_duration_sec: float,
    min_display_sec: float = 1.0,
    gap_between_blocks_sec: float = 0.1,
) -> list[tuple[float, float]]:
    """
    각 자막 블록의 시작/끝 시간을 계산합니다.

    글자 수에 비례하여 시간을 배분합니다.
    (글자가 많은 블록은 더 오래 표시)

    Args:
        blocks: 자막 블록 리스트
        total_duration_sec: 전체 오디오 길이 (초)
        min_display_sec: 블록당 최소 표시 시간 (초)
        gap_between_blocks_sec: 블록 사이 간격 (초)

    Returns:
        [(start_sec, end_sec), ...] 타이밍 리스트
    """
    if not blocks:
        return []

    # 각 블록의 글자 수 계산 (줄바꿈 제외)
    char_counts = [len(b.replace('\n', '')) for b in blocks]
    total_chars = sum(char_counts)

    # 사용 가능한 총 시간 계산 (갭 시간 제외)
    total_gap = gap_between_blocks_sec * (len(blocks) - 1)
    available_time = max(total_duration_sec - total_gap, len(blocks) * min_display_sec)

    timings = []
    current_time = 0.0

    for i, (block, char_count) in enumerate(zip(blocks, char_counts)):
        # 이 블록에 배분된 시간 (글자 수 비율 기반)
        if total_chars > 0:
            allocated_time = (char_count / total_chars) * available_time
        else:
            allocated_time = available_time / len(blocks)

        # 최소 표시 시간 보장
        display_time = max(allocated_time, min_display_sec)

        start = current_time
        end = current_time + display_time

        # 마지막 블록은 오디오 끝까지
        if i == len(blocks) - 1:
            end = total_duration_sec

        timings.append((round(start, 3), round(end, 3)))
        current_time = end + gap_between_blocks_sec

    return timings


def generate_srt(
    script: str,
    total_duration_sec: float,
    output_path: str,
    max_chars_per_line: int = 18,
) -> str:
    """
    대본과 오디오 길이를 기반으로 SRT 파일을 생성합니다.

    Args:
        script: 전체 대본 텍스트
        total_duration_sec: 오디오 총 길이 (초)
        output_path: 저장할 SRT 파일 경로
        max_chars_per_line: 한 줄 최대 글자 수

    Returns:
        저장된 SRT 파일 경로
    """
    logger.info(f"SRT 생성 시작: 총 {total_duration_sec:.1f}초")

    # 1. 대본을 자막 블록으로 분할
    blocks = split_script_into_lines(script, max_chars_per_line=max_chars_per_line)

    if not blocks:
        logger.warning("자막 블록이 없습니다.")
        return output_path

    # 2. 타이밍 계산
    timings = calculate_timings(blocks, total_duration_sec)

    # 3. SRT 파일 작성
    srt_content = []
    for i, (block, (start, end)) in enumerate(zip(blocks, timings), start=1):
        srt_entry = (
            f"{i}\n"
            f"{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}\n"
            f"{block}\n"
        )
        srt_content.append(srt_entry)

    srt_text = "\n".join(srt_content)

    # 파일 저장 (UTF-8 BOM: 일부 편집 소프트웨어 호환성을 위해)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8-sig') as f:
        f.write(srt_text)

    logger.info(f"✅ SRT 파일 저장 완료: {output_path} ({len(blocks)}개 항목)")
    return output_path


def srt_to_preview(srt_path: str) -> str:
    """
    SRT 파일 내용을 읽기 쉬운 텍스트 형식으로 반환합니다.
    (Streamlit UI 미리보기용)
    """
    with open(srt_path, 'r', encoding='utf-8-sig') as f:
        return f.read()


def generate_ass_subtitles(
    script: str,
    total_duration_sec: float,
    output_path: str,
    font_size: int = 72,
    font_name: str = "Noto Sans KR",
    primary_color: str = "&H00FFFFFF",   # 흰색
    outline_color: str = "&H00000000",   # 검정 테두리
    bold: bool = True,
) -> str:
    """
    CapCut/Premiere에서 스타일 적용이 가능한 ASS 자막 파일을 생성합니다.
    (SRT보다 더 많은 스타일링 옵션 지원)

    Args:
        script: 전체 대본
        total_duration_sec: 오디오 길이
        output_path: 저장 경로 (.ass)
        font_size: 폰트 크기
        font_name: 폰트 이름
        primary_color: 텍스트 색상 (ASS BGR 형식)
        outline_color: 테두리 색상
        bold: 굵게 여부

    Returns:
        저장된 ASS 파일 경로
    """
    blocks = split_script_into_lines(script)
    timings = calculate_timings(blocks, total_duration_sec)

    bold_int = -1 if bold else 0

    # ASS 헤더
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
YCbCr Matrix: None

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary_color},&H000000FF,{outline_color},&H80000000,{bold_int},0,0,0,100,100,0,0,1,3,0,2,10,10,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def to_ass_time(sec: float) -> str:
        """초를 ASS 시간 형식으로 변환: H:MM:SS.cc"""
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = sec % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    events = []
    for block, (start, end) in zip(blocks, timings):
        # 줄바꿈을 ASS 형식으로 변환
        ass_text = block.replace('\n', '\\N')
        event = f"Dialogue: 0,{to_ass_time(start)},{to_ass_time(end)},Default,,0,0,0,,{ass_text}"
        events.append(event)

    ass_content = header + "\n".join(events)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8-sig') as f:
        f.write(ass_content)

    logger.info(f"✅ ASS 자막 파일 저장: {output_path}")
    return output_path


# ── 직접 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    test_script = """목이 너무 아프세요? 저도 그랬어요.
하루 종일 모니터 보다가 퇴근하면 어깨가 돌덩이처럼 굳잖아요.
그런데 이걸 쓰고 나서 진짜 달라졌어요!
스마트 마사지 쿠션, 3단계 강도 조절에 열선까지.
5분만 써봐도 차이 느껴져요.
지금 링크에서 오늘만 특가로 만나보세요!"""

    # SRT 파일 생성 테스트
    srt_path = generate_srt(
        script=test_script,
        total_duration_sec=52.0,
        output_path="test_subtitle.srt",
    )
    print(f"✅ SRT 생성: {srt_path}")
    print("\n📄 SRT 내용 미리보기:")
    print(srt_to_preview(srt_path))

    # ASS 파일 생성 테스트
    ass_path = generate_ass_subtitles(
        script=test_script,
        total_duration_sec=52.0,
        output_path="test_subtitle.ass",
    )
    print(f"\n✅ ASS 생성: {ass_path}")
