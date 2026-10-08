# ====================================================
# 영상 자막 제거 (clean_videos.py)
#
# 영상에 박힌 자막 위치를 OCR로 찾아 지운 뒤 새 파일로 저장합니다.
# 앱과 별개로 단독 실행합니다.
#
# 사용법:
#   python clean_videos.py                    # source_videos 폴더 전체
#   python clean_videos.py 영상.mp4            # 파일 하나
#   python clean_videos.py C:\내폴더           # 폴더 지정
#   python clean_videos.py 영상.mp4 --check    # 찾기만 하고 안 지움
#
# 결과: outputs/cleaned/ 에 저장
# ====================================================

import os
import sys
import glob
import shutil
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.subtitle_detect import detect_subtitle_bands
from modules.clip_editor import get_video_size, delogo_filter, preview_delogo

DEFAULT_IN = os.path.join("outputs", "source_videos")
DEFAULT_OUT = os.path.join("outputs", "cleaned")
VIDEO_EXT = ('.mp4', '.mov', '.webm', '.mkv', '.avi')


def collect(target: str) -> list:
    """대상 경로에서 영상 파일 목록을 만듭니다."""
    if os.path.isfile(target):
        return [target] if target.lower().endswith(VIDEO_EXT) else []
    files = []
    for ext in VIDEO_EXT:
        files += glob.glob(os.path.join(target, f"*{ext}"))
    return sorted(files)


def clean_one(video: str, out_dir: str, frames: int, ratio: float,
              check_only: bool, keep_audio: bool) -> dict:
    """영상 하나의 자막을 찾아 지웁니다."""
    name = os.path.basename(video)
    print(f"\n{'='*58}")
    print(f"  {name[:52]}")
    print('='*58)

    w, h = get_video_size(video)
    print(f"  해상도 {w}x{h}")

    print("  자막 위치 찾는 중... (30~60초)")
    bands = detect_subtitle_bands(video, frames=frames, gpu=False,
                                  min_vote_ratio=ratio)

    if bands is None:
        print("  ❌ EasyOCR 없음 — pip install easyocr 후 다시 실행하세요")
        return {'status': 'no_ocr', 'video': video}

    if not bands:
        print("  ✅ 자막 없음 — 원본을 그대로 복사합니다")
        if not check_only:
            dst = os.path.join(out_dir, name)
            shutil.copy2(video, dst)
            print(f"  → {dst}")
        return {'status': 'clean', 'video': video, 'bands': []}

    for b in bands:
        print(f"  📍 자막 발견: 세로 {b['y']:.0f}~{b['y']+b['h']:.0f}% "
              f"가로 {b['x']:.0f}~{b['x']+b['w']:.0f}%  "
              f"({b['votes']}/{b['frames']} 프레임)")

    # 미리보기 (전/후)
    prev_dir = os.path.join(out_dir, "_preview")
    os.makedirs(prev_dir, exist_ok=True)
    stem = Path(name).stem[:20]
    try:
        preview_delogo(video, None,
                       out_path=os.path.join(prev_dir, f"{stem}_before.png"), width=320)
        preview_delogo(video, bands[0],
                       out_path=os.path.join(prev_dir, f"{stem}_after.png"), width=320)
        print(f"  🖼️  미리보기: {prev_dir}")
    except Exception:
        pass

    if check_only:
        print("  (--check 모드라 지우지 않았습니다)")
        return {'status': 'found', 'video': video, 'bands': bands}

    # 찾은 영역을 모두 제거
    chain = [c for c in (delogo_filter(b, w, h) for b in bands) if c]
    if not chain:
        print("  ⚠️ 유효한 영역이 없습니다")
        return {'status': 'skip', 'video': video}

    dst = os.path.join(out_dir, name)
    cmd = ['ffmpeg', '-y', '-v', 'error', '-i', video,
           '-vf', ','.join(chain),
           '-c:v', 'libx264', '-preset', 'medium', '-crf', '18']
    cmd += ['-c:a', 'copy'] if keep_audio else ['-an']
    cmd.append(dst)

    print("  🧽 자막 지우는 중...")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if r.returncode != 0:
        print(f"  ❌ 실패: {(r.stderr or '')[-200:]}")
        return {'status': 'error', 'video': video}

    mb = os.path.getsize(dst) / 1024 / 1024
    print(f"  ✅ 완료 → {dst}  ({mb:.1f} MB)")

    # 전/후를 나란히 붙인 짧은 비교 영상
    cmp_path = os.path.join(prev_dir, f"{stem}_비교.mp4")
    c = subprocess.run(
        ['ffmpeg', '-y', '-v', 'error',
         '-t', '8', '-i', video,
         '-t', '8', '-i', dst,
         '-filter_complex',
         '[0:v]scale=360:-2,drawtext=text=BEFORE:fontcolor=white:fontsize=22:'
         'box=1:boxcolor=black@0.6:x=10:y=10[a];'
         '[1:v]scale=360:-2,drawtext=text=AFTER:fontcolor=white:fontsize=22:'
         'box=1:boxcolor=black@0.6:x=10:y=10[b];'
         '[a][b]hstack=inputs=2',
         '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
         cmp_path],
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    if c.returncode == 0 and os.path.exists(cmp_path):
        print(f"  🎬 비교 영상 → {cmp_path}")
    else:
        print(f"  (비교 영상 생성 건너뜀)")

    return {'status': 'done', 'video': video, 'out': dst, 'bands': bands,
            'compare': cmp_path if os.path.exists(cmp_path) else None}


def main():
    ap = argparse.ArgumentParser(
        description="영상에 박힌 자막을 찾아 지웁니다",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="예시:\n"
               "  python clean_videos.py\n"
               "  python clean_videos.py 영상.mp4\n"
               "  python clean_videos.py C:\\소재폴더 --check\n")
    ap.add_argument('target', nargs='?', default=DEFAULT_IN,
                    help=f"영상 파일 또는 폴더 (기본: {DEFAULT_IN})")
    ap.add_argument('-o', '--out', default=DEFAULT_OUT,
                    help=f"저장 폴더 (기본: {DEFAULT_OUT})")
    ap.add_argument('--check', action='store_true',
                    help="찾기만 하고 지우지 않습니다")
    ap.add_argument('--frames', type=int, default=14,
                    help="분석할 프레임 수 (기본 14, 많을수록 정확하고 느림)")
    ap.add_argument('--ratio', type=float, default=0.5,
                    help="자막 판정 기준 0~1 (기본 0.5, 낮출수록 더 많이 잡음)")
    ap.add_argument('--no-audio', action='store_true',
                    help="소리를 빼고 저장합니다")
    args = ap.parse_args()

    if not shutil.which('ffmpeg'):
        print("❌ FFmpeg가 없습니다. 설치 후 다시 실행하세요.")
        return 1

    videos = collect(args.target)
    if not videos:
        print(f"❌ 영상을 찾지 못했습니다: {args.target}")
        return 1

    os.makedirs(args.out, exist_ok=True)

    print(f"\n영상 {len(videos)}개를 처리합니다")
    print(f"저장 위치: {os.path.abspath(args.out)}")
    if args.check:
        print("※ --check 모드: 찾기만 합니다")

    results = [clean_one(v, args.out, args.frames, args.ratio,
                         args.check, not args.no_audio) for v in videos]

    print(f"\n{'='*58}")
    print("  요약")
    print('='*58)
    for tag, label in (('done', '자막 제거'), ('clean', '자막 없음'),
                       ('found', '자막 발견(미처리)'), ('error', '실패'),
                       ('no_ocr', 'OCR 없음'), ('skip', '건너뜀')):
        n = sum(1 for r in results if r['status'] == tag)
        if n:
            print(f"  {label}: {n}개")

    if not args.check:
        print(f"\n결과 폴더를 앱 ① 입력 탭에 올리시면 됩니다:")
        print(f"  {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
