# 🛍️ 쇼핑 쇼츠 영상 자동화 앱

> 상품 이미지 + 참고 영상 URL → AI가 대본·음성·자막·에셋 완전 자동 생성

---

## 🏗️ 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                    웹 UI (Streamlit)                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ ① 입력   │→ │ ② 분석   │→ │ ③ 대본   │→ │ ④ 생성   │       │
│  │ URL/이미지│  │ Vision AI│  │ Claude   │  │ TTS/SRT  │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
         │               │              │              │
         ▼               ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────────┐
│ YouTube      │ │ Claude       │ │ Claude   │ │ Typecast     │
│ Transcript   │ │ Vision API   │ │ Sonnet 5 │ │ TTS API      │
│ API          │ │ (이미지 분석)│ │ (대본 생성)│ │ (음성 변환)  │
└──────────────┘ └──────────────┘ └──────────┘ └──────────────┘
                                                       │
                                              ┌────────────────┐
                                              │  최종 출력물   │
                                              │  ① voice.wav   │
                                              │  ② images/     │
                                              │  ③ subtitle.srt│
                                              │  ④ shorts.mp4  │
                                              │  ⑤ package.zip │
                                              └────────────────┘
```

## 📦 기술 스택

| 영역 | 기술 |
|------|------|
| **프론트엔드** | Streamlit |
| **이미지 분석** | Anthropic Claude Sonnet 5 (Vision) |
| **대본 생성** | Anthropic Claude Sonnet 5 |
| **자막 추출** | youtube-transcript-api |
| **TTS 음성** | Typecast API |
| **영상 렌더링** | MoviePy + FFmpeg |
| **이미지 처리** | Pillow |

---

## 🚀 설치 및 실행

### 1단계: 패키지 설치

```bash
pip install -r requirements.txt
```

### 2단계: FFmpeg 설치 (영상 렌더링용)

**Windows:**
```bash
winget install ffmpeg
```

**Mac:**
```bash
brew install ffmpeg
```

### 3단계: 환경변수 설정

```bash
# .env.example을 복사하여 .env 생성
copy .env.example .env
```

`.env` 파일을 열고 실제 API 키 입력:
```
ANTHROPIC_API_KEY=sk-ant-...
TYPECAST_API_KEY=...
TYPECAST_ACTOR_ID=...
```

### 4단계: 앱 실행

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속

---

## 📁 프로젝트 구조

```
Shorts Video Automation/
├── app.py                    # 메인 Streamlit 앱
├── requirements.txt          # 의존성 패키지
├── .env.example             # 환경변수 템플릿
├── README.md
├── modules/
│   ├── video_analyzer.py    # YouTube 자막 추출 + 패턴 분석
│   ├── image_analyzer.py    # Claude Vision 이미지 분석
│   ├── script_generator.py  # 쇼핑 쇼츠 대본 생성
│   ├── tts_generator.py     # Typecast TTS 음성 생성
│   ├── srt_generator.py     # SRT/ASS 자막 파일 생성
│   ├── video_renderer.py    # MoviePy MP4 렌더링
│   └── asset_packager.py    # ZIP 패키징
├── outputs/                 # 생성된 결과물 (자동 생성)
└── assets/                  # 공통 에셋 (폰트 등)
```

---

## 🔑 API 키 발급 방법

### Anthropic (Claude) API
1. https://console.anthropic.com 접속
2. 회원가입 → API Keys → Create Key

### Typecast TTS API
1. https://typecast.ai 접속
2. 회원가입 → 개발자 센터 → API 키 발급
3. 원하는 음성 캐릭터 선택 → 캐릭터 ID 복사

> 💡 **Typecast 없이도 테스트 가능**: API 키 없으면 자동으로 무음 파일로 대체됩니다.

---

## ⚠️ 에러 처리

| 에러 | 원인 | 해결 방법 |
|------|------|-----------|
| `AuthenticationError` | API 키 오류 | 사이드바에서 키 재확인 |
| `NoTranscriptFound` | 자막 없는 영상 | 다른 영상 URL 입력 |
| `moviepy ImportError` | MoviePy 미설치 | `pip install moviepy` |
| `FFmpeg not found` | FFmpeg 미설치 | `winget install ffmpeg` |
| `RateLimitError` | API 한도 초과 | 잠시 후 재시도 |

---

## 💡 CapCut 편집 에셋 구성 가이드

ZIP 다운로드 후 압축 해제하면 아래 구조로 정리됩니다:

```
project_상품명_날짜시간/
├── 01_audio/voice.wav       ← 타임라인 오디오 트랙에 배치
├── 02_images/               ← 순서대로 비디오 트랙에 배치
│   ├── 01_product.jpg
│   └── 02_product.jpg
├── 03_subtitles/
│   ├── subtitle.srt         ← [캡션] → [SRT 가져오기]로 자동 로드
│   └── subtitle.ass         ← 스타일 있는 자막 (고급)
├── 04_scripts/script.txt    ← 대본 참고용
└── README.txt               ← 편집 가이드
```

---

## 🛠️ 각 모듈 단독 테스트

```bash
# 영상 분석 테스트
python modules/video_analyzer.py

# 이미지 분석 테스트 (test_product.jpg 필요)
python modules/image_analyzer.py

# 대본 생성 테스트
python modules/script_generator.py

# TTS 테스트 (API 키 없으면 무음 파일)
python modules/tts_generator.py

# SRT 자막 생성 테스트
python modules/srt_generator.py

# 에셋 패키징 테스트
python modules/asset_packager.py
```

---

Made with ❤️ by Claude AI (Anthropic)
