# ====================================================
# 모듈 5: SRT 자막 파일 생성기 (srt_generator.py)
# 대본 텍스트와 오디오 길이를 기반으로
# 영상 편집 프로그램에서 바로 사용 가능한
# SRT 자막 파일을 자동 생성합니다.
# ====================================================

import re
import math

# 띄어쓰기로 직접 줄을 나눌 때 허용하는 최대 줄 수
# (쇼츠 세로 화면에서 4줄을 넘으면 화면을 가립니다)
MAX_FORCED_LINES = 4
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


def split_into_sentences(text: str) -> list[str]:
    """한 덩어리 글을 문장 단위로 나눕니다 (마침표·물음표·느낌표 기준)."""
    parts = re.split(r'(?<=[.!?~])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def resplit_script_by_sentence(script: str) -> str:
    """대본을 '문장마다 한 줄'로 다시 정리합니다.

    AI가 여러 문장을 한 문단으로 붙여 놓았을 때,
    '대본 한 줄 = 자막 한 장면' 을 쓰려면 먼저 줄을 나눠야 합니다.
    """
    out = []
    for line in str(script).strip().splitlines():
        line = line.strip()
        if not line:
            continue
        out.extend(split_into_sentences(line))
    return "\n".join(out)


def split_script_into_lines(
    script: str,
    max_chars_per_line: int = 18,
    max_lines_per_block: int = 2,
    respect_line_breaks: bool = True,
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
        respect_line_breaks: True면 대본의 줄바꿈을 그대로 지킵니다.
            즉 **대본 한 줄 = 자막 한 장면**이 되고, 서로 다른 줄의
            내용이 한 자막에 섞이지 않습니다.
            (한 줄이 너무 길면 그 줄 안에서만 문장 단위로 더 나눕니다)

    자막 한 장면 안에서 줄을 어디서 바꿀지 직접 정하고 싶으면
    **띄어쓰기를 2칸 이상** 넣으세요. 그 자리에서 줄이 바뀝니다.
    그냥 두면 한 줄 글자 수에 맞춰 어절(띄어쓰기) 단위로 자동 줄바꿈합니다.

    Returns:
        자막 블록 리스트 (각 블록이 하나의 SRT 항목이 됨)
    """
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

    def wrap_segment(text: str) -> list[str]:
        """띄어쓰기 2칸 이상은 '여기서 줄 바꿔라'는 뜻으로 받아들입니다.

        그 지점에서 먼저 끊고, 각 조각은 글자 수에 맞춰 어절 단위로
        다시 접습니다. (단어가 중간에서 쪼개지는 일은 없습니다)
        """
        lines = []
        for chunk in re.split(r'[ \t　]{2,}', text):
            chunk = chunk.strip()
            if chunk:
                lines.extend(wrap_words(chunk))
        return lines

    # ── 1) 큰 덩어리 나누기 ──────────────────────
    # 줄바꿈을 지키면 '대본 한 줄'이 곧 한 덩어리가 됩니다.
    if respect_line_breaks:
        segments = [l.strip() for l in script.strip().splitlines() if l.strip()]
    else:
        # 예전 방식: 줄바꿈을 무시하고 전체를 문장·쉼표로 다시 쪼갭니다
        segments = [script.strip()]

    if not segments:
        return []

    # ── 2) 덩어리마다 자막 블록 만들기 ────────────
    blocks = []
    for seg in segments:
        wrapped = wrap_segment(seg)

        # 띄어쓰기 2칸 이상으로 직접 줄을 나눠 놓았다면 그 뜻을 존중합니다.
        # ('최대 줄 수'는 자동 줄바꿈에만 적용되는 한도입니다)
        forced = len([c for c in re.split(r'[ \t　]{2,}', seg) if c.strip()])
        limit = max_lines_per_block
        if forced > 1:
            limit = max(max_lines_per_block, min(forced, MAX_FORCED_LINES))

        # 한 장면에 들어갈 만큼 짧으면 → 그대로 한 블록
        if len(wrapped) <= limit:
            blocks.append("\n".join(wrapped))
            continue

        # 너무 길면 이 줄 안에서만 문장 단위로 더 나눕니다
        # (다른 줄의 내용과는 절대 섞이지 않습니다)
        sentences = split_into_sentences(seg)
        if len(sentences) <= 1:
            # 문장이 하나뿐인데 길면 어쩔 수 없이 줄 수로 자릅니다
            for i in range(0, len(wrapped), max_lines_per_block):
                blocks.append("\n".join(wrapped[i:i + max_lines_per_block]))
            continue

        cur_lines = []
        for sentence in sentences:
            s_lines = wrap_segment(sentence)
            # 넣으면 넘칠 때는 지금까지 모은 걸 먼저 내보냅니다
            if cur_lines and len(cur_lines) + len(s_lines) > max_lines_per_block:
                blocks.append("\n".join(cur_lines))
                cur_lines = []
            cur_lines.extend(s_lines)
            while len(cur_lines) > max_lines_per_block:
                blocks.append("\n".join(cur_lines[:max_lines_per_block]))
                cur_lines = cur_lines[max_lines_per_block:]
        if cur_lines:
            blocks.append("\n".join(cur_lines))

    # 빈 블록 제거
    blocks = [b for b in blocks if b.strip()]

    logger.info(
        f"대본 분할 완료: {len(segments)}개 줄 → {len(blocks)}개 자막 블록 "
        f"(줄바꿈 지킴={respect_line_breaks})"
    )
    return blocks


def speech_weight(block: str) -> float:
    """이 자막을 소리 내어 읽는 데 걸리는 '몫'을 어림합니다.

    - 공백은 발음되지 않으므로 글자 수에서 뺍니다
    - 쉼표·마침표 뒤에는 TTS가 잠깐 쉬므로 그만큼 몫을 더해 줍니다
      (이걸 빼먹으면 문장이 끝나는 자막마다 조금씩 빨라집니다)
    """
    t = block.replace('\n', '')
    w = float(len(t.replace(' ', '')))
    w += t.count(',') * 1.5
    w += sum(t.count(c) for c in '.!?~') * 3.0
    return max(w, 1.0)


def calculate_timings(
    blocks: list[str],
    total_duration_sec: float,
    min_display_sec: float = 0.8,
    gap_between_blocks_sec: float = 0.08,
    lead_sec: float = 0.10,
) -> list[tuple[float, float]]:
    """
    각 자막 블록의 시작/끝 시간을 계산합니다.

    ⚠️ 싱크가 밀리지 않게 하는 것이 핵심입니다.
    예전 방식은 짧은 블록에 '최소 표시 시간'을 적용하면서
    그만큼을 뒤쪽에서 빼앗지 않아, 뒤로 갈수록 자막이 늦어졌습니다
    (30초 영상에서 1초 넘게 밀림).

    지금은 '최소 시간에 걸리는 블록'을 먼저 고정해 두고
    남은 시간만 나머지에 비례 배분합니다. 그래서 길이의 합이
    오디오 길이와 정확히 일치하고, 밀림이 생기지 않습니다.

    Args:
        blocks: 자막 블록 리스트
        total_duration_sec: 전체 오디오 길이 (초)
        min_display_sec: 블록당 최소 표시 시간 (초)
        gap_between_blocks_sec: 자막이 바뀔 때 눈에 보이는 짧은 틈.
            다음 자막의 '시작'은 밀지 않고 앞 자막의 '끝'만 당깁니다.
        lead_sec: 자막을 소리보다 이만큼 먼저 띄웁니다.
            (읽을 시간을 주면 훨씬 자연스럽습니다)

    Returns:
        [(start_sec, end_sec), ...] 타이밍 리스트
    """
    n = len(blocks)
    if n == 0:
        return []

    total = max(float(total_duration_sec), 0.1)

    # 최소 시간조차 못 채울 만큼 자막이 많으면 그냥 균등 분배
    if n * min_display_sec >= total:
        d = total / n
        return [(round(i * d, 3), round((i + 1) * d, 3)) for i in range(n)]

    weights = [speech_weight(b) for b in blocks]

    # ── 최소 시간에 걸리는 블록을 고정하고 나머지를 비례 배분 ──
    #    (고정된 블록이 생기면 남은 시간이 줄어드니 반복합니다)
    fixed: set[int] = set()
    while len(fixed) < n:
        rem_time = total - min_display_sec * len(fixed)
        rem_w = sum(w for i, w in enumerate(weights) if i not in fixed)
        if rem_w <= 0:
            break
        newly = {
            i for i in range(n)
            if i not in fixed
            and weights[i] / rem_w * rem_time < min_display_sec
        }
        if not newly:
            break
        fixed |= newly

    rem_time = total - min_display_sec * len(fixed)
    rem_w = sum(w for i, w in enumerate(weights) if i not in fixed)

    durations = [
        min_display_sec if i in fixed
        else (weights[i] / rem_w * rem_time if rem_w > 0 else 0.0)
        for i in range(n)
    ]

    # ── 누적해서 시작 시각 만들기 (길이의 합 = 오디오 길이) ──
    starts = []
    cursor = 0.0
    for d in durations:
        starts.append(max(0.0, cursor - lead_sec))
        cursor += d

    # ── 끝 시각: 다음 자막 시작을 넘지 않게 ────────
    #    (겹치면 두 자막이 같이 떠서 깜빡입니다)
    timings = []
    for i in range(n):
        start = starts[i]
        if i == n - 1:
            end = total                       # 마지막은 오디오 끝까지
        else:
            nxt = starts[i + 1]
            # 자막이 바뀌는 게 보이도록 짧은 틈을 둡니다
            end = max(start + 0.25, nxt - gap_between_blocks_sec)
            end = min(end, nxt)               # 절대 겹치지 않게
        timings.append((round(start, 3), round(end, 3)))

    return timings


def generate_srt(
    script: str,
    total_duration_sec: float,
    output_path: str,
    max_chars_per_line: int = 18,
    max_lines_per_block: int = 2,
    respect_line_breaks: bool = True,
) -> str:
    """
    대본과 오디오 길이를 기반으로 SRT 파일을 생성합니다.

    Args:
        script: 전체 대본 텍스트
        total_duration_sec: 오디오 총 길이 (초)
        output_path: 저장할 SRT 파일 경로
        max_chars_per_line: 한 줄 최대 글자 수
        max_lines_per_block: 한 자막에 들어갈 최대 줄 수
        respect_line_breaks: 대본 한 줄 = 자막 한 장면

    Returns:
        저장된 SRT 파일 경로
    """
    logger.info(f"SRT 생성 시작: 총 {total_duration_sec:.1f}초")

    # 1. 대본을 자막 블록으로 분할
    blocks = split_script_into_lines(
        script,
        max_chars_per_line=max_chars_per_line,
        max_lines_per_block=max_lines_per_block,
        respect_line_breaks=respect_line_breaks,
    )

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
