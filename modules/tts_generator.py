# ====================================================
# 모듈 4: TTS 음성 생성기 (tts_generator.py)
# Typecast API로 대본을 자연스러운 AI 음성으로 변환합니다.
#
# ⚠️ 2026-09 기준 Typecast 신규 API(v1) 사용
#    - 엔드포인트: https://api.typecast.ai/v1
#    - 인증 헤더: X-API-KEY  (구버전의 Bearer 방식 아님)
#    - 합성 응답: 오디오 바이트 직접 반환 (구버전의 폴링 방식 아님)
# ====================================================

import io
import os
import re
from pathlib import Path
from typing import Optional
from loguru import logger

import requests


# ── Typecast API 상수 ───────────────────────────────
TYPECAST_BASE_URL = "https://api.typecast.ai/v1"
TYPECAST_SYNTHESIS_ENDPOINT = f"{TYPECAST_BASE_URL}/text-to-speech"
TYPECAST_VOICE_LIST_ENDPOINT = f"{TYPECAST_BASE_URL}/voices"

DEFAULT_MODEL = "ssfm-v30"

# 한국어 감정 라벨 → Typecast emotion_preset 매핑
EMOTION_MAP = {
    "보통": "normal",
    "기쁨": "happy",
    "슬픔": "sad",
    "화남": "angry",
    "차분함": "tonedown",
    "밝음": "toneup",
    "속삭임": "whisper",
    # 영문 입력도 그대로 통과
    "normal": "normal",
    "happy": "happy",
    "sad": "sad",
    "angry": "angry",
    "tonedown": "tonedown",
    "toneup": "toneup",
    "whisper": "whisper",
}


def _detect_language(text: str) -> str:
    """텍스트에 한글이 있으면 'kor', 없으면 'eng'를 반환합니다."""
    for ch in text:
        if 0xAC00 <= ord(ch) <= 0xD7A3 or 0x3131 <= ord(ch) <= 0x318E:
            return "kor"
    return "eng"


class TypecastTTS:
    """
    Typecast TTS API 클라이언트 (v1)

    사용 전 Typecast 계정 생성 및 API 키 발급 필요:
    https://typecast.ai → 로그인 → API 키 발급
    """

    def __init__(self, api_key: str, actor_id: str = None):
        """
        Args:
            api_key: Typecast API 키
            actor_id: 사용할 음성 ID (신규 API의 voice_id, 예: 'tc_xxxxxxxx')
        """
        self.api_key = (api_key or "").strip()
        self.actor_id = (actor_id or "").strip() or None
        self.headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }
        self._voice_cache = None   # list_actors() 결과 캐시

    # ── 음성 목록 ─────────────────────────────────
    def list_actors(self) -> list[dict]:
        """
        사용 가능한 음성 목록을 조회합니다.

        Returns:
            [{'actor_id', 'voice_id', 'name', 'model', 'emotions', 'language'}, ...]
            ('actor_id'는 구버전 호환용으로 voice_id와 같은 값입니다)
        """
        try:
            response = requests.get(
                TYPECAST_VOICE_LIST_ENDPOINT,
                headers=self.headers,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()

        except requests.exceptions.ConnectionError:
            raise RuntimeError("❌ Typecast 서버 연결 실패. 인터넷 연결을 확인해 주세요.")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status in (401, 403):
                raise ValueError("❌ Typecast API 키가 올바르지 않습니다.")
            raise RuntimeError(f"❌ Typecast API 오류 ({status}): {e}")

        # 응답이 리스트이거나 {'voices': [...]} 형태일 수 있음
        raw = data if isinstance(data, list) else (
            data.get("voices") or data.get("result") or []
        )

        voices = []
        for v in raw:
            vid = v.get("voice_id") or v.get("id") or ""
            if not vid:
                continue
            voices.append({
                "actor_id": vid,          # 구버전 호환
                "voice_id": vid,
                "name": v.get("voice_name") or v.get("name") or vid,
                "model": v.get("model") or DEFAULT_MODEL,
                "emotions": v.get("emotions") or [],
                "language": v.get("language") or "",
            })

        self._voice_cache = voices
        logger.info(f"Typecast 음성 {len(voices)}개 조회 완료")
        return voices

    def _model_for_voice(self, voice_id: str) -> str:
        """해당 음성이 쓰는 모델명을 찾습니다 (목록은 1회만 조회 후 캐시)."""
        if self._voice_cache is None:
            try:
                self.list_actors()
            except Exception:
                return DEFAULT_MODEL

        for v in (self._voice_cache or []):
            if v["voice_id"] == voice_id:
                return v.get("model") or DEFAULT_MODEL
        return DEFAULT_MODEL

    # ── 음성 합성 ─────────────────────────────────
    def synthesize(
        self,
        text: str,
        actor_id: str = None,
        speed: float = 1.0,
        pitch: int = 0,
        volume: int = 100,
        emotion: str = "normal",
        output_format: str = "wav",
        model: str = None,
        language: str = None,
        **_ignored,
    ) -> bytes:
        """
        텍스트를 음성으로 변환하여 오디오 바이트를 반환합니다.

        Args:
            text: 변환할 텍스트
            actor_id: 음성 ID (미입력시 self.actor_id 사용)
            speed: 말하기 속도 (0.5 ~ 2.0)
            pitch: 음높이 (-10 ~ 10)
            volume: 볼륨 (0 ~ 100)
            emotion: 감정 (한국어 라벨 또는 영문 preset)
            output_format: 'wav' 또는 'mp3'
            model: 모델명 (미지정시 음성에 맞춰 자동 선택)
            language: 'kor' / 'eng' (미지정시 텍스트로 자동 판별)

        Returns:
            오디오 파일 bytes
        """
        voice_id = (actor_id or self.actor_id or "").strip()
        if not voice_id:
            raise ValueError(
                "❌ 음성 캐릭터 ID가 설정되지 않았습니다.\n"
                "사이드바의 '🔍 음성 캐릭터 목록 불러오기'로 선택해 주세요."
            )

        body = {
            "voice_id": voice_id,
            "text": text,
            "model": model or self._model_for_voice(voice_id),
            "language": language or _detect_language(text),
            "prompt": {
                "emotion_preset": EMOTION_MAP.get(emotion, "normal"),
                "emotion_intensity": 1.0,
            },
            "output": {
                "audio_format": output_format,
                "volume": int(volume),
                "audio_tempo": float(speed),
                "audio_pitch": int(pitch),
            },
        }

        try:
            logger.info(f"Typecast 합성 요청: {len(text)}자, 음성 {voice_id}")
            response = requests.post(
                TYPECAST_SYNTHESIS_ENDPOINT,
                headers=self.headers,
                json=body,
                timeout=120,
            )
            response.raise_for_status()

        except requests.exceptions.ConnectionError:
            raise RuntimeError("❌ Typecast 서버 연결 실패. 인터넷 연결을 확인해 주세요.")
        except requests.exceptions.Timeout:
            raise TimeoutError("❌ Typecast 응답 시간 초과. 대본을 짧게 줄여 다시 시도해 주세요.")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            detail = ""
            try:
                detail = e.response.text[:300]
            except Exception:
                pass

            if status in (401, 403):
                raise ValueError("❌ Typecast API 키가 올바르지 않습니다.")
            elif status == 402:
                raise RuntimeError("❌ Typecast 크레딧이 부족합니다. typecast.ai 에서 충전해 주세요.")
            elif status == 404:
                raise ValueError(f"❌ 음성 ID를 찾을 수 없습니다: {voice_id}")
            elif status in (400, 422):
                raise ValueError(f"❌ 잘못된 요청입니다: {detail}")
            elif status == 429:
                raise RuntimeError("❌ Typecast 요청 한도 초과. 잠시 후 다시 시도해 주세요.")
            else:
                raise RuntimeError(f"❌ Typecast API 오류 ({status}): {detail}")

        # 신규 API는 오디오 바이트를 그대로 반환합니다
        content_type = response.headers.get("content-type", "")
        if "audio" not in content_type:
            raise RuntimeError(f"❌ 예상과 다른 응답 형식입니다 ({content_type}): {response.text[:200]}")

        logger.info(f"✅ TTS 합성 완료: {len(response.content)} bytes ({content_type})")
        return response.content

    # ── 긴 텍스트 합성 ────────────────────────────
    def synthesize_long_text(
        self,
        text: str,
        output_path: str,
        actor_id: str = None,
        speed: float = 1.05,    # 쇼츠는 약간 빠른 템포
        max_chars_per_chunk: int = 350,
        **kwargs
    ) -> str:
        """
        긴 텍스트를 청크로 나눠 합성 후 합칩니다.

        Args:
            text: 변환할 전체 텍스트
            output_path: 저장할 파일 경로 (.wav 또는 .mp3)
            actor_id: 음성 ID
            speed: 말하기 속도
            max_chars_per_chunk: 청크당 최대 문자 수

        Returns:
            저장된 파일 경로
        """
        # 출력 형식을 확장자에서 결정
        fmt = Path(output_path).suffix.replace('.', '').lower() or 'wav'
        kwargs.setdefault('output_format', fmt)

        chunks = self._split_text_into_chunks(text, max_chars_per_chunk)
        logger.info(f"텍스트를 {len(chunks)}개 청크로 분할")

        if len(chunks) == 1:
            audio_bytes = self.synthesize(text, actor_id=actor_id, speed=speed, **kwargs)
            with open(output_path, 'wb') as f:
                f.write(audio_bytes)
            logger.info(f"✅ 음성 파일 저장: {output_path}")
            return output_path

        # 여러 청크 합성 후 병합
        try:
            from pydub import AudioSegment
        except ImportError:
            raise ImportError("pydub 패키지가 필요합니다: pip install pydub")

        combined = AudioSegment.empty()
        for i, chunk in enumerate(chunks):
            logger.info(f"청크 {i+1}/{len(chunks)} 합성 중...")
            audio_bytes = self.synthesize(chunk, actor_id=actor_id, speed=speed, **kwargs)
            segment = AudioSegment.from_file(io.BytesIO(audio_bytes))
            combined += segment

        combined.export(output_path, format=fmt)
        logger.info(f"✅ 병합된 음성 파일 저장: {output_path} ({len(combined)/1000:.1f}초)")
        return output_path

    @staticmethod
    def _split_text_into_chunks(text: str, max_chars: int) -> list[str]:
        """텍스트를 문장 단위로 청크 분할합니다."""
        sentences = re.split(r'(?<=[.!?\n])\s*', text.strip())

        chunks = []
        current_chunk = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(current_chunk) + len(sentence) <= max_chars:
                current_chunk += (" " if current_chunk else "") + sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sentence

        if current_chunk:
            chunks.append(current_chunk)

        return chunks if chunks else [text]


def get_audio_duration(audio_path: str) -> float:
    """
    오디오 파일의 재생 길이(초)를 반환합니다.

    Args:
        audio_path: 오디오 파일 경로

    Returns:
        재생 길이 (초)
    """
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(audio_path)
        if audio and audio.info:
            return audio.info.length
    except ImportError:
        pass
    except Exception:
        pass

    # mutagen 없으면 pydub 사용
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(audio_path)
        return len(audio) / 1000.0
    except Exception:
        pass

    # 둘 다 실패 시 추정값 반환
    logger.warning("오디오 길이 계산 실패. 추정값 사용.")
    return 45.0


# ── 테스트용 더미 TTS (API 키 없을 때 사용) ──────────
def create_silent_audio(duration_sec: float, output_path: str) -> str:
    """
    테스트용 무음 WAV 파일을 생성합니다.
    (Typecast API 없이도 전체 파이프라인 테스트 가능)
    """
    try:
        from pydub import AudioSegment
        silent = AudioSegment.silent(duration=int(duration_sec * 1000))
        silent.export(output_path, format="wav")
        logger.info(f"✅ 테스트용 무음 파일 생성: {output_path} ({duration_sec}초)")
        return output_path
    except ImportError:
        # pydub도 없으면 최소한의 WAV 헤더로 생성
        import struct
        sample_rate = 44100
        num_samples = int(sample_rate * duration_sec)
        with open(output_path, 'wb') as f:
            data_size = num_samples * 2
            f.write(b'RIFF')
            f.write(struct.pack('<I', 36 + data_size))
            f.write(b'WAVE')
            f.write(b'fmt ')
            f.write(struct.pack('<IHHIIHH', 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
            f.write(b'data')
            f.write(struct.pack('<I', data_size))
            f.write(b'\x00' * data_size)
        logger.info(f"✅ 간단한 무음 WAV 생성: {output_path}")
        return output_path


# ── 직접 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("TYPECAST_API_KEY", "")
    actor_id = os.getenv("TYPECAST_ACTOR_ID", "")

    test_text = (
        "창문 닦다가 팔 아팠던 적 있죠? 저도 그랬어요.\n"
        "매주 주말마다 창문 붙잡고 씨름했는데, 솔직히 너무 힘들었어요.\n"
        "그러다 이 스마트 창문 청소 로봇을 알게 됐어요.\n"
        "지금 링크 눌러서 확인해보세요!"
    )

    if not api_key or api_key.startswith("your_"):
        print("⚠️  Typecast API 키 미설정. 테스트용 무음 파일 생성...")
        create_silent_audio(duration_sec=45, output_path="test_audio.wav")
        print("✅ test_audio.wav 생성 완료 (45초 무음)")
    else:
        tts = TypecastTTS(api_key=api_key, actor_id=actor_id)

        if not actor_id or actor_id.startswith("your_"):
            print("음성 ID가 없어 목록에서 첫 번째를 사용합니다...")
            voices = tts.list_actors()
            print(f"사용 가능한 음성 {len(voices)}개. 예시:")
            for v in voices[:5]:
                print(f"  - {v['voice_id']}  {v['name']}  ({v['model']})")
            tts.actor_id = voices[0]['voice_id']

        output = tts.synthesize_long_text(
            text=test_text,
            output_path="test_audio.wav",
        )
        print(f"✅ TTS 생성 완료: {output}")
        print(f"📊 재생 길이: {get_audio_duration(output):.1f}초")
