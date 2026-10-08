# ====================================================
# 모듈 7: 에셋 패키저 (asset_packager.py)
# 생성된 모든 결과물을 캡컷(CapCut)에서 바로
# 사용할 수 있도록 폴더 구조에 맞게 ZIP으로 패키징합니다.
#
# 📁 ZIP 구조:
# project_[상품명]_[날짜시간]/
# ├── 📁 01_audio/
# │   └── voice.wav          (TTS 음성 파일)
# ├── 📁 02_images/
# │   ├── 01_product.jpg     (상품 이미지들)
# │   └── ...
# ├── 📁 03_subtitles/
# │   ├── subtitle.srt       (SRT 자막)
# │   └── subtitle.ass       (ASS 자막, 스타일 포함)
# ├── 📁 04_scripts/
# │   └── script.txt         (전체 대본 텍스트)
# ├── 📁 05_video/           (MP4 렌더링 결과물, 선택)
# │   └── final_shorts.mp4
# └── README.txt             (CapCut 편집 가이드)
# ====================================================

import os
import zipfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from loguru import logger


CAPCUT_GUIDE = """
╔══════════════════════════════════════════════════════════════╗
║          🎬 CapCut 편집 가이드 (쇼핑 쇼츠 에셋 팩)           ║
╚══════════════════════════════════════════════════════════════╝

📦 이 ZIP 파일에 포함된 파일들:

01_audio/  → TTS로 생성된 AI 음성 파일
02_images/ → 상품 이미지들 (번호 순서대로 슬라이드쇼 구성)
03_subtitles/ → 자막 파일 (SRT: 기본 / ASS: 스타일 포함)
04_scripts/ → 전체 대본 텍스트 (참고용)
05_video/  → 1차 가편집본 MP4 (있는 경우)

────────────────────────────────────────────────────────────────
🎬 CapCut PC 버전 편집 순서
────────────────────────────────────────────────────────────────

1️⃣  새 프로젝트 생성
   - CapCut 실행 → [새 프로젝트] 클릭
   - 비율: 9:16 (쇼츠/릴스 표준)

2️⃣  음성 파일 추가
   - [미디어] → [가져오기] → 01_audio/voice.wav 선택
   - 타임라인에 오디오 트랙으로 배치

3️⃣  이미지 슬라이드쇼 구성
   - [미디어] → [가져오기] → 02_images/ 폴더의 이미지 전체 선택
   - 순서대로 타임라인에 배치
   - 각 이미지 길이를 음성에 맞게 조정

4️⃣  자막 추가 (방법 A: SRT 자동 불러오기)
   - [캡션] → [SRT 가져오기] → 03_subtitles/subtitle.srt 선택
   - ✅ 타이밍이 자동으로 맞춰집니다!

5️⃣  자막 스타일링 (권장 설정)
   - 폰트: 나눔고딕 Bold 또는 Noto Sans KR Bold
   - 크기: 화면 대비 7~8%
   - 위치: 화면 하단 20~25% 지점
   - 색상: 흰색 + 검정 테두리 (두께 3~5)
   - 애니메이션: 팝업 또는 타이핑 효과

6️⃣  전환 효과 추가
   - 이미지 사이 전환점 클릭 → [전환] 패널
   - 권장: 디졸브(Dissolve) 또는 슬라이드, 0.3~0.5초

7️⃣  브랜드 요소 추가 (선택)
   - 로고 이미지를 우측 상단에 배치
   - 브랜드 색상으로 텍스트 하이라이트

8️⃣  배경음악 추가 (선택)
   - [오디오] → CapCut 제공 무료 BGM 사용
   - 볼륨: 음성의 20~30% 수준으로 조절

9️⃣  최종 내보내기
   - [내보내기] → 해상도: 1080p, 프레임: 30fps
   - 형식: MP4

────────────────────────────────────────────────────────────────
💡 추가 편집 팁
────────────────────────────────────────────────────────────────

✔ 첫 3초 후크 구간: 텍스트 강조 효과 추가 권장
✔ 상품 확대 장면: 줌인 효과 (키프레임 사용)
✔ CTA 구간: 빨간색 텍스트 또는 깜빡임 효과
✔ 배경음악: 밝고 경쾌한 BGM (쇼핑 분위기)
✔ 썸네일: 첫 번째 프레임 또는 별도 이미지로 설정

────────────────────────────────────────────────────────────────
📱 플랫폼별 업로드 설정
────────────────────────────────────────────────────────────────

유튜브 쇼츠:
  - 해시태그에 #쇼츠 #쇼핑 필수 포함
  - 제목: 첫 5단어가 핵심 키워드

인스타그램 릴스:
  - 커버 이미지: 상품이 잘 보이는 프레임 선택
  - 캡션 첫 줄: 후킹 문구로 시작

틱톡:
  - 트렌딩 사운드 추가 권장
  - 첫 업로드: 최소 10개 해시태그

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
생성일: {datetime}
쇼핑 쇼츠 자동화 앱 v1.0 (Powered by Claude AI)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""


def create_project_package(
    project_name: str,
    audio_path: Optional[str] = None,
    image_paths: Optional[list[str]] = None,
    srt_path: Optional[str] = None,
    ass_path: Optional[str] = None,
    script_text: Optional[str] = None,
    video_path: Optional[str] = None,
    output_dir: str = "outputs",
) -> str:
    """
    모든 에셋을 캡컷 편집에 최적화된 ZIP 파일로 패키징합니다.

    Args:
        project_name: 프로젝트명 (상품명 등)
        audio_path: TTS 음성 파일 경로
        image_paths: 상품 이미지 파일 경로 리스트
        srt_path: SRT 자막 파일 경로
        ass_path: ASS 자막 파일 경로
        script_text: 대본 텍스트 (직접 저장)
        video_path: 1차 편집 MP4 경로 (선택)
        output_dir: ZIP 파일 저장 디렉토리

    Returns:
        생성된 ZIP 파일 경로
    """
    # 타임스탬프 기반 프로젝트 폴더명
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '-', '_')).strip()
    safe_name = safe_name.replace(' ', '_')[:30]  # 최대 30자
    folder_name = f"project_{safe_name}_{timestamp}"

    zip_filename = f"{folder_name}.zip"
    zip_path = os.path.join(output_dir, zip_filename)

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    logger.info(f"ZIP 패키징 시작: {zip_path}")
    added_files = []

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:

        # ── 1. 음성 파일 ─────────────────────────────
        if audio_path and os.path.exists(audio_path):
            ext = Path(audio_path).suffix
            arc_name = f"{folder_name}/01_audio/voice{ext}"
            zf.write(audio_path, arc_name)
            added_files.append(f"✅ 음성: {arc_name}")
            logger.info(f"음성 파일 추가: {arc_name}")

        # ── 2. 상품 이미지 ────────────────────────────
        if image_paths:
            for i, img_path in enumerate(image_paths, start=1):
                if os.path.exists(img_path):
                    ext = Path(img_path).suffix
                    arc_name = f"{folder_name}/02_images/{i:02d}_product{ext}"
                    zf.write(img_path, arc_name)
                    added_files.append(f"✅ 이미지 {i}: {arc_name}")
            logger.info(f"이미지 {len(image_paths)}장 추가")

        # ── 3. 자막 파일 ─────────────────────────────
        if srt_path and os.path.exists(srt_path):
            arc_name = f"{folder_name}/03_subtitles/subtitle.srt"
            zf.write(srt_path, arc_name)
            added_files.append(f"✅ SRT 자막: {arc_name}")

        if ass_path and os.path.exists(ass_path):
            arc_name = f"{folder_name}/03_subtitles/subtitle.ass"
            zf.write(ass_path, arc_name)
            added_files.append(f"✅ ASS 자막: {arc_name}")

        # ── 4. 대본 텍스트 ────────────────────────────
        if script_text:
            arc_name = f"{folder_name}/04_scripts/script.txt"
            zf.writestr(arc_name, script_text.encode('utf-8'))
            added_files.append(f"✅ 대본: {arc_name}")

        # ── 5. MP4 편집 결과물 ────────────────────────
        if video_path and os.path.exists(video_path):
            arc_name = f"{folder_name}/05_video/final_shorts.mp4"
            zf.write(video_path, arc_name)
            added_files.append(f"✅ 영상: {arc_name}")
            logger.info("MP4 파일 추가")

        # ── 6. CapCut 편집 가이드 ─────────────────────
        guide_content = CAPCUT_GUIDE.format(datetime=datetime.now().strftime('%Y년 %m월 %d일 %H:%M'))
        zf.writestr(f"{folder_name}/README.txt", guide_content.encode('utf-8'))

        # ── 7. 프로젝트 메타데이터 ───────────────────
        import json
        metadata = {
            "project_name": project_name,
            "created_at": timestamp,
            "files": {
                "audio": bool(audio_path and os.path.exists(audio_path or "")),
                "images": len(image_paths) if image_paths else 0,
                "srt": bool(srt_path and os.path.exists(srt_path or "")),
                "ass": bool(ass_path and os.path.exists(ass_path or "")),
                "video": bool(video_path and os.path.exists(video_path or "")),
            }
        }
        zf.writestr(
            f"{folder_name}/project_info.json",
            json.dumps(metadata, ensure_ascii=False, indent=2).encode('utf-8')
        )

    zip_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    logger.info(f"✅ ZIP 패키징 완료: {zip_path} ({zip_size_mb:.1f} MB)")

    return zip_path


def get_package_summary(zip_path: str) -> dict:
    """ZIP 파일의 내용 요약을 반환합니다."""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        file_list = zf.namelist()

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)

    return {
        "zip_path": zip_path,
        "file_count": len(file_list),
        "size_mb": round(size_mb, 2),
        "files": file_list,
    }


# ── 직접 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    # 테스트용 더미 파일 생성
    import tempfile

    # 더미 파일들 생성
    dummy_files = {}
    for name, content in [
        ("test_audio.wav", b"RIFF" + b"\x00" * 100),
        ("test_img1.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 100),
        ("test_subtitle.srt", "1\n00:00:00,000 --> 00:00:03,000\n테스트 자막\n".encode()),
    ]:
        path = os.path.join(tempfile.gettempdir(), name)
        with open(path, 'wb') as f:
            f.write(content)
        dummy_files[name] = path

    zip_path = create_project_package(
        project_name="스마트마사지쿠션",
        audio_path=dummy_files["test_audio.wav"],
        image_paths=[dummy_files["test_img1.jpg"]],
        srt_path=dummy_files["test_subtitle.srt"],
        script_text="목이 너무 아프세요? 저도 그랬어요...",
        output_dir="outputs",
    )

    summary = get_package_summary(zip_path)
    print(f"✅ 패키지 생성 완료!")
    print(f"📦 경로: {summary['zip_path']}")
    print(f"📊 크기: {summary['size_mb']} MB")
    print(f"📁 파일 수: {summary['file_count']}개")
