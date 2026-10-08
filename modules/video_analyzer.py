# ====================================================
# 모듈 1: 참고 영상 분석기 (video_analyzer.py)
# YouTube / TikTok URL에서 자막·메타데이터를 추출하고
# 영상의 후킹 패턴을 분석합니다.
# ====================================================

import re
import json
import os
import tempfile
from typing import Optional
from loguru import logger

# ── youtube-transcript-api (YouTube 전용) ──────────
try:
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
    TRANSCRIPT_API_AVAILABLE = True
except ImportError:
    TRANSCRIPT_API_AVAILABLE = False
    logger.warning("youtube-transcript-api 미설치")

# ── yt-dlp (TikTok + YouTube 메타데이터) ──────────
try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False
    logger.warning("yt-dlp 미설치. 'pip install yt-dlp' 실행 필요")


# ══════════════════════════════════════════════════
# URL 판별 유틸리티
# ══════════════════════════════════════════════════

def detect_platform(url: str) -> str:
    """URL이 어느 플랫폼인지 판별합니다."""
    url = url.lower()
    if 'youtube.com' in url or 'youtu.be' in url:
        return 'youtube'
    if 'tiktok.com' in url:
        return 'tiktok'
    return 'unknown'


def extract_youtube_id(url: str) -> Optional[str]:
    """YouTube URL에서 영상 ID(11자리)를 추출합니다."""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
        r'[?&]v=([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def extract_tiktok_video_id(url: str) -> Optional[str]:
    """
    TikTok URL에서 영상 ID(숫자)를 추출합니다.

    지원 형식:
    - https://www.tiktok.com/@username/video/1234567890
    - https://vm.tiktok.com/ABCDE/  (단축 URL)
    """
    # 일반 영상 URL: /video/숫자
    match = re.search(r'/video/(\d{10,20})', url)
    if match:
        return match.group(1)

    # 프로필 URL이면 None 반환 (영상 ID 없음)
    # 예: https://www.tiktok.com/@username (영상이 아님)
    if re.search(r'tiktok\.com/@[\w.]+/?$', url):
        return None  # 프로필 URL — 건너뜀

    return None


# ══════════════════════════════════════════════════
# YouTube 자막 추출
# ══════════════════════════════════════════════════

def fetch_youtube_transcript(video_id: str, languages: list = ['ko', 'en']) -> list[dict]:
    """
    YouTube 영상 ID로 자막을 가져옵니다.
    한국어 → 영어 → 자동생성 자막 순으로 시도합니다.
    """
    if not TRANSCRIPT_API_AVAILABLE:
        raise ImportError("youtube-transcript-api 패키지가 없습니다.")

    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        logger.info(f"YouTube 자막 추출 성공: {video_id} ({len(transcript)}개)")
        return transcript
    except NoTranscriptFound:
        # 자동 생성 자막 시도
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            for t in transcript_list:
                if t.is_generated:
                    result = t.fetch()
                    logger.info(f"자동 생성 자막 사용: {t.language_code}")
                    return result
        except Exception as e:
            logger.warning(f"자동 생성 자막 없음: {e}")
        raise ValueError(f"YouTube 영상 {video_id} — 자막 없음")
    except TranscriptsDisabled:
        raise ValueError(f"YouTube 영상 {video_id} — 자막 비활성화")
    except Exception as e:
        raise RuntimeError(f"YouTube 자막 추출 오류: {e}")


# ══════════════════════════════════════════════════
# TikTok 자막 / 메타데이터 추출 (yt-dlp 사용)
# ══════════════════════════════════════════════════

def _build_ydl_opts(tmp_dir: str, cookie_browser: str = None) -> dict:
    """
    yt-dlp 옵션 딕셔너리를 생성합니다.
    cookie_browser: 'chrome', 'firefox', 'edge', None
    """
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['ko', 'en', 'ko-KR'],
        'subtitlesformat': 'vtt',
        'outtmpl': os.path.join(tmp_dir, '%(id)s.%(ext)s'),
        'socket_timeout': 20,
        'retries': 1,
        # TikTok 차단 우회: 실제 브라우저처럼 보이는 헤더
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
    # 브라우저 쿠키 사용 (TikTok 로그인 세션 활용)
    if cookie_browser:
        opts['cookiesfrombrowser'] = (cookie_browser,)
    return opts


def fetch_tiktok_info(url: str) -> dict:
    """
    yt-dlp로 TikTok 영상 메타데이터와 자막을 가져옵니다.
    Chrome → Edge → Firefox → 쿠키 없음 순으로 자동 시도합니다.

    Returns:
        {
          'title': str,
          'description': str,
          'duration': float,
          'transcript': list[dict],
          'has_transcript': bool,
        }
    """
    if not YTDLP_AVAILABLE:
        raise ImportError("yt-dlp 패키지가 없습니다: pip install yt-dlp")

    tmp_dir = tempfile.mkdtemp()

    # 시도 순서: 쿠키 없음(빠름) → Chrome → Edge → Firefox
    # 쿠키 없이도 User-Agent + api_hostname 설정으로 대부분 접근 가능
    browsers_to_try = [None, 'chrome', 'edge', 'firefox']
    last_error = None

    for browser in browsers_to_try:
        try:
            opts = _build_ydl_opts(tmp_dir, cookie_browser=browser)
            label = f"쿠키({browser})" if browser else "쿠키없음"
            logger.info(f"TikTok 시도: {label} | {url[:60]}")

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

            # 성공하면 브레이크
            logger.info(f"TikTok 접근 성공 ({label})")
            break

        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            # 확실히 재시도 의미 없는 에러면 즉시 중단
            if 'private' in err_str or 'removed' in err_str or 'not found' in err_str:
                raise ValueError("TikTok 영상이 비공개이거나 삭제되었습니다.")
            logger.warning(f"TikTok 실패 ({label}): {str(e)[:80]}")
            info = None
            continue

    if info is None:
        # 모든 방법 실패 → 사용자 친화적 메시지
        raise RuntimeError(
            "TikTok 접근 차단됨. 해결 방법:\n"
            "① Chrome에서 TikTok(tiktok.com)에 로그인 후 재시도\n"
            "② 또는 해당 URL을 제외하고 다른 영상 URL을 사용하세요"
        )

    title = info.get('title', '')
    description = info.get('description', '')
    duration = float(info.get('duration') or 45)
    logger.info(f"TikTok 메타데이터: '{title}' ({duration:.0f}초)")

    # 자막 파일 찾기
    transcript = []
    has_transcript = False

    for fname in os.listdir(tmp_dir):
        if fname.endswith('.vtt') or fname.endswith('.srt'):
            vtt_path = os.path.join(tmp_dir, fname)
            transcript = parse_vtt_to_transcript(vtt_path)
            if transcript:
                has_transcript = True
                logger.info(f"TikTok 자막 파싱 성공: {len(transcript)}개")
            break

    # 자막 없으면 제목+설명을 텍스트로 사용
    if not has_transcript:
        combined_text = f"{title}. {description}".strip()
        if combined_text:
            transcript = [{'text': combined_text, 'start': 0.0, 'duration': duration}]
            logger.info("TikTok 자막 없음 → 제목+설명 텍스트 사용")

    # 임시 파일 정리
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        'title': title,
        'description': description,
        'duration': duration,
        'transcript': transcript,
        'has_transcript': has_transcript,
    }


def parse_vtt_to_transcript(vtt_path: str) -> list[dict]:
    """
    .vtt 자막 파일을 transcript 형식 [{text, start, duration}]으로 파싱합니다.
    """
    transcript = []
    try:
        with open(vtt_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # VTT 타임코드 패턴: HH:MM:SS.mmm --> HH:MM:SS.mmm
        blocks = re.split(r'\n\n+', content.strip())
        for block in blocks:
            lines = block.strip().split('\n')
            # 타임코드 줄 찾기
            time_line = None
            text_lines = []
            for line in lines:
                if '-->' in line:
                    time_line = line
                elif time_line and line and not line.startswith('WEBVTT') and not line.isdigit():
                    # HTML 태그 제거
                    clean = re.sub(r'<[^>]+>', '', line).strip()
                    if clean:
                        text_lines.append(clean)

            if time_line and text_lines:
                # 시작 시간 파싱
                start_str = time_line.split('-->')[0].strip()
                start_sec = vtt_time_to_seconds(start_str)
                end_str = time_line.split('-->')[1].strip().split()[0]
                end_sec = vtt_time_to_seconds(end_str)

                transcript.append({
                    'text': ' '.join(text_lines),
                    'start': start_sec,
                    'duration': max(end_sec - start_sec, 0.5),
                })

    except Exception as e:
        logger.warning(f"VTT 파싱 오류: {e}")

    return transcript


def vtt_time_to_seconds(time_str: str) -> float:
    """VTT 타임코드를 초로 변환: '00:01:23.456' → 83.456"""
    time_str = time_str.strip()
    try:
        parts = time_str.replace(',', '.').split(':')
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(parts[-1])
    except Exception:
        return 0.0


# ══════════════════════════════════════════════════
# 공통 분석 로직
# ══════════════════════════════════════════════════

def transcript_to_text(transcript: list[dict]) -> str:
    """transcript 리스트를 하나의 텍스트 문자열로 합칩니다."""
    return " ".join([item['text'].strip() for item in transcript if item.get('text')])


def analyze_hook_structure(transcript_text: str, full_transcript: list[dict]) -> dict:
    """
    자막 텍스트에서 쇼츠 후킹 패턴을 분석합니다.
    """
    # 첫 15초: 오프닝 후크
    opening_texts = [
        item['text'] for item in full_transcript
        if item.get('start', 0) <= 15
    ]
    opening_hook = " ".join(opening_texts) or transcript_text[:100]

    # 마지막 10초: CTA
    total_duration = 45.0
    if full_transcript:
        last = full_transcript[-1]
        total_duration = last.get('start', 0) + last.get('duration', 2)

    closing_texts = [
        item['text'] for item in full_transcript
        if item.get('start', 0) >= total_duration - 10
    ]
    closing_cta = " ".join(closing_texts)

    # 후킹 패턴 감지 (한·영 혼합)
    txt = transcript_text.lower()
    hook_patterns = {
        "질문형":  bool(re.search(r'아시나요|있으세요|해보셨나요|이거\s*아세요|you need|did you know|have you', txt)),
        "숫자형":  bool(re.search(r'\d+가지|\d+개|\d+%|\d+원|\d+ reasons|\d+ ways', txt)),
        "공감형":  bool(re.search(r'고민|힘드|불편|지치|스트레스|struggle|tired of|hate when', txt)),
        "긴급형":  bool(re.search(r'한정|품절|마감|오늘만|지금|limited|last chance|only.*left', txt)),
        "비교형":  bool(re.search(r'vs|비교|다르|차이|before.*after|전후|versus', txt)),
        "비밀형":  bool(re.search(r'비밀|몰랐|알려드릴|secret|nobody tells|they don\'t want', txt)),
    }

    return {
        "opening_hook": opening_hook,
        "closing_cta": closing_cta,
        "full_text": transcript_text,
        "total_duration_sec": round(total_duration, 1),
        "hook_patterns": hook_patterns,
        "word_count": len(transcript_text.split()),
    }


# ══════════════════════════════════════════════════
# 메인 진입점: 여러 URL 일괄 분석
# ══════════════════════════════════════════════════

def analyze_reference_videos(urls: list[str]) -> dict:
    """
    YouTube / TikTok URL을 자동 판별하여 분석합니다.

    Args:
        urls: YouTube 또는 TikTok 영상 URL 리스트

    Returns:
        종합 분석 결과 딕셔너리
    """
    results = []
    errors = []

    for url in urls:
        url = url.strip()
        if not url:
            continue

        platform = detect_platform(url)

        # ── 미지원 플랫폼 ──────────────────────────
        if platform == 'unknown':
            errors.append(f"⚠️ 지원하지 않는 URL입니다 (YouTube·TikTok만 가능): {url}")
            continue

        try:
            if platform == 'youtube':
                # ── YouTube ───────────────────────
                video_id = extract_youtube_id(url)
                if not video_id:
                    errors.append(f"⚠️ YouTube 영상 ID를 찾을 수 없습니다: {url}")
                    continue

                logger.info(f"YouTube 분석 중: {video_id}")
                transcript = fetch_youtube_transcript(video_id)
                text = transcript_to_text(transcript)
                analysis = analyze_hook_structure(text, transcript)
                analysis['platform'] = 'youtube'
                analysis['video_id'] = video_id
                analysis['url'] = url
                results.append(analysis)
                logger.info(f"✅ YouTube 완료: {url}")

            elif platform == 'tiktok':
                # ── TikTok ───────────────────────
                video_id = extract_tiktok_video_id(url)

                if video_id is None:
                    # 프로필 URL이면 안내 메시지
                    if re.search(r'tiktok\.com/@[\w.]+/?$', url):
                        errors.append(
                            f"⚠️ 프로필 URL은 분석할 수 없습니다. "
                            f"특정 영상의 URL을 입력해 주세요: {url}"
                        )
                    else:
                        errors.append(f"⚠️ TikTok 영상 URL 형식이 맞지 않습니다: {url}")
                    continue

                logger.info(f"TikTok 분석 중: {video_id}")
                info = fetch_tiktok_info(url)
                transcript = info['transcript']

                if not transcript:
                    errors.append(f"⚠️ TikTok 자막/텍스트를 가져올 수 없습니다: {url}")
                    continue

                text = transcript_to_text(transcript)
                analysis = analyze_hook_structure(text, transcript)
                analysis['platform'] = 'tiktok'
                analysis['video_id'] = video_id
                analysis['url'] = url
                analysis['title'] = info.get('title', '')
                analysis['has_transcript'] = info.get('has_transcript', False)

                # 메타데이터만 있는 경우 표시
                if not info.get('has_transcript'):
                    analysis['note'] = '자막 없음 — 제목+설명 텍스트 기반 분석'

                results.append(analysis)
                logger.info(f"✅ TikTok 완료: {url}")

        except (ValueError, RuntimeError) as e:
            errors.append(f"❌ {url}\n   → {str(e)}")
            logger.error(f"{url} 분석 실패: {e}")
        except Exception as e:
            errors.append(f"❌ {url}\n   → 예상치 못한 오류: {str(e)}")
            logger.exception(f"{url} 처리 중 예외 발생")

    # ── 결과 종합 ──────────────────────────────────
    if results:
        pattern_counts: dict[str, int] = {}
        for r in results:
            for pattern, used in r.get('hook_patterns', {}).items():
                if used:
                    pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

        # 절반 이상의 영상에서 사용된 패턴 = 주요 패턴
        threshold = max(len(results) // 2, 1)
        dominant_patterns = [p for p, c in pattern_counts.items() if c >= threshold]

        avg_duration = sum(r.get('total_duration_sec', 45) for r in results) / len(results)
        sample_hooks = [r['opening_hook'] for r in results[:3] if r.get('opening_hook')]
        sample_ctas  = [r['closing_cta']  for r in results[:3] if r.get('closing_cta')]

        return {
            "success": True,
            "analyzed_count": len(results),
            "errors": errors,
            "individual_results": results,
            "summary": {
                "dominant_patterns": dominant_patterns,
                "avg_duration_sec": round(avg_duration, 1),
                "sample_hooks": sample_hooks,
                "sample_ctas": sample_ctas,
                "all_texts": [r['full_text'] for r in results],
            }
        }
    else:
        return {
            "success": False,
            "analyzed_count": 0,
            "errors": errors,
            "individual_results": [],
            "summary": {}
        }


# ── 직접 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    test_urls = [
        # TikTok 영상 URL 테스트
        "https://www.tiktok.com/@trustedtryouts/video/7596741593009278230",
        # YouTube 쇼츠 테스트 (실제 URL로 교체)
        # "https://youtube.com/shorts/dQw4w9WgXcQ",
    ]
    result = analyze_reference_videos(test_urls)
    print(f"\n분석 성공: {result['analyzed_count']}개")
    print(f"오류: {len(result['errors'])}개")
    for e in result['errors']:
        print(f"  {e}")
    if result['summary']:
        print(f"주요 패턴: {result['summary']['dominant_patterns']}")
        print(f"평균 길이: {result['summary']['avg_duration_sec']}초")
