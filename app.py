# ====================================================
# 🎬 쇼핑 쇼츠 영상 자동화 앱 (app.py)
# 메인 Streamlit 웹 애플리케이션
#
# 실행 방법:
#   pip install -r requirements.txt
#   streamlit run app.py
# ====================================================

import os
import json
import tempfile
import time
from pathlib import Path
from io import BytesIO
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv
from loguru import logger

# 모듈 임포트
from modules.video_analyzer import analyze_reference_videos
from modules.image_analyzer import analyze_product_images, format_analysis_for_display
from modules.script_generator import generate_scripts, get_full_script, generate_test_scripts
from modules.tts_generator import TypecastTTS, create_silent_audio, get_audio_duration
from modules.srt_generator import generate_srt, generate_ass_subtitles, srt_to_preview
from modules.asset_packager import create_project_package, get_package_summary

# ── 환경변수 로드 ─────────────────────────────────
load_dotenv()

# ── 페이지 기본 설정 ──────────────────────────────
st.set_page_config(
    page_title="🎬 쇼핑 쇼츠 자동화",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 커스텀 CSS ────────────────────────────────────
st.markdown("""
<style>
    /* Deploy 버튼/메뉴 숨기기 */
    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }
    [data-testid="stMainMenu"] { display: none !important; }
    #MainMenu { visibility: hidden !important; }
    footer { visibility: hidden !important; }

    /* 탭이 항상 클릭 가능하도록 보장 */
    .stTabs { position: relative !important; z-index: 10 !important; }
    [data-baseweb="tab-list"] {
        pointer-events: auto !important;
        position: relative !important;
        z-index: 10 !important;
    }
    [data-baseweb="tab"] {
        pointer-events: auto !important;
        cursor: pointer !important;
    }

    /* 사이드바 진행 상태 네비 버튼 — 링크처럼 보이게 */
    [data-testid="stSidebar"] button[kind="secondary"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        text-align: left !important;
        padding: 4px 8px !important;
        color: inherit !important;
        font-size: 0.9rem !important;
        border-radius: 6px !important;
        transition: background 0.15s !important;
    }
    [data-testid="stSidebar"] button[kind="secondary"]:hover {
        background: rgba(120,120,120,0.15) !important;
        cursor: pointer !important;
    }

    /* 전체 배경 */
    .main { background-color: #0e1117; }

    /* 제목 영역 */
    .hero-title {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 16px;
        text-align: center;
        margin-bottom: 2rem;
        color: white;
    }

    /* 단계 카드 */
    .step-card {
        background: #1e2130;
        border: 1px solid #2d3250;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1rem;
    }

    /* 성공 뱃지 */
    .badge-success {
        background: #00b894;
        color: white;
        padding: 0.2rem 0.8rem;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: bold;
    }

    /* 강조 박스 */
    .highlight-box {
        background: linear-gradient(135deg, #1a1a2e, #16213e);
        border-left: 4px solid #667eea;
        padding: 1rem 1.5rem;
        border-radius: 0 8px 8px 0;
        margin: 1rem 0;
    }

    /* 버튼 스타일 */
    .stButton > button {
        border-radius: 8px;
        font-weight: bold;
        transition: all 0.3s;
    }

    /* 스크립트 표시 박스 */
    .script-box {
        background: #1a1a2e;
        color: #f0f0f8;
        border: 1px solid #6a6aba;
        border-radius: 8px;
        padding: 1.5rem;
        font-size: 1.15rem;
        line-height: 2;
        white-space: pre-wrap;
        font-weight: 400;
    }
</style>
""", unsafe_allow_html=True)


# ── 세션 상태 초기화 ──────────────────────────────
def init_session_state():
    """세션 상태 초기화 (앱 첫 로드 시)"""
    defaults = {
        'step': 1,                    # 현재 진행 단계
        'video_analysis': None,       # 참고 영상 분석 결과
        'image_analysis': None,       # 상품 이미지 분석 결과
        'scripts_data': None,         # 생성된 대본 데이터
        'selected_script': None,      # 선택된 대본 텍스트
        'audio_path': None,           # 생성된 음성 파일 경로
        'srt_path': None,             # SRT 자막 파일 경로
        'ass_path': None,             # ASS 자막 파일 경로
        'video_path': None,           # 렌더링된 MP4 경로
        'zip_path': None,             # 최종 ZIP 파일 경로
        'uploaded_images': [],        # 업로드된 이미지 경로 리스트
        'product_name': '상품',       # 상품명 (패키징용)
        'target_audience': '일반 소비자',
        'additional_info': '',        # 추가 상품 정보
        'active_tab': 0,              # 현재 열린 탭 (0~4)
        'source_videos': [],          # ① 입력 탭에서 올린 컷편집용 소재 영상
        'images_from_video': False,   # uploaded_images가 영상에서 뽑은 프레임인지
        'delogo_boxes': {},           # 영상별 원본 자막 제거 영역 {경로: {x,y,w,h}}
        'voice_preview': None,        # 미리듣기 오디오 {voice_id, name, audio}
        'chosen_voice_id': None,      # 사용자가 고른 음성 ID
        'chosen_voice_name': None,    # 고른 음성 이름
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


init_session_state()


# ── 어디서 돌고 있나 ──────────────────────────────
# Streamlit Cloud에는 .env 파일이 없고 Secrets로 값을 받습니다.
IS_CLOUD = os.environ.get("HOSTNAME", "").startswith("streamlit") or \
           os.path.exists("/home/appuser") or \
           bool(os.environ.get("STREAMLIT_SERVER_HEADLESS") == "1" and not Path(".env").exists())


def get_secret(key: str, default: str = "") -> str:
    """Secrets(클라우드) → 환경변수(.env) 순으로 값을 찾습니다."""
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


# ── 비밀번호 잠금 (설정했을 때만 작동) ─────────────
def _login_token(pw: str) -> str:
    """비밀번호로 로그인 토큰을 만듭니다 (비밀번호 자체는 주소에 안 남깁니다)."""
    import hashlib
    return hashlib.sha256(f"shorts-app::{pw}".encode()).hexdigest()[:32]


def check_password() -> bool:
    """
    APP_PASSWORD가 설정돼 있으면 로그인 화면을 띄웁니다.
    없으면 그냥 통과 — 내 PC에서 혼자 쓸 때는 귀찮지 않게 합니다.

    '로그인 유지'를 켜면 주소에 토큰이 붙습니다. 그 상태로 휴대폰
    홈 화면에 추가하면 다음부터 비밀번호를 묻지 않습니다.
    """
    # 앞뒤 공백은 떼어냅니다 — Secrets나 환경변수에 실수로 섞여 들어가면
    # 맞는 비밀번호를 넣어도 계속 틀렸다고 나옵니다.
    pw = get_secret("APP_PASSWORD", "").strip()
    if not pw:
        return True
    if st.session_state.get("_authed"):
        return True

    token = _login_token(pw)

    # 주소에 토큰이 들어 있으면 통과 (홈 화면 바로가기용)
    try:
        if st.query_params.get("t") == token:
            st.session_state["_authed"] = True
            return True
    except Exception:
        pass

    st.markdown("""
    <div class="hero-title">
        <h1>🛍️ 쇼핑 쇼츠 영상 자동화</h1>
        <p>비밀번호를 입력해 주세요</p>
    </div>
    """, unsafe_allow_html=True)

    c = st.columns([1, 2, 1])[1]
    with c:
        entered = st.text_input("비밀번호", type="password", label_visibility="collapsed",
                                placeholder="비밀번호")
        keep = st.checkbox("로그인 유지 (휴대폰에서 편합니다)", value=True)

        if st.button("들어가기", use_container_width=True, type="primary"):
            if entered.strip() == pw:
                st.session_state["_authed"] = True
                if keep:
                    # 주소에 토큰을 남겨 다음 접속 때 바로 들어가게 합니다
                    try:
                        st.query_params["t"] = token
                    except Exception:
                        pass
                st.rerun()
            else:
                st.error("비밀번호가 다릅니다.")

        st.caption(
            "💡 '로그인 유지'를 켜고 들어간 뒤 **홈 화면에 추가**하면 "
            "다음부터 비밀번호 없이 열립니다. "
            "다만 그 주소를 남에게 보내면 비밀번호 없이 들어올 수 있으니 주의하세요."
        )
    return False


if not check_password():
    st.stop()


# ── .env 파일 저장/정리 ───────────────────────────
ENV_PATH = Path(__file__).parent / ".env"


def save_env(key: str, value: str):
    """
    API 키를 .env 파일에 영구 저장합니다.
    클라우드에서는 파일을 못 쓰므로 현재 세션에만 반영합니다
    (영구 저장은 Streamlit Secrets로 합니다).
    """
    os.environ[key] = value

    if IS_CLOUD:
        return

    lines = []
    found = False
    if ENV_PATH.exists():
        with open(ENV_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                found = True
                break
    if not found:
        lines.append(f"{key}={value}\n")
    with open(ENV_PATH, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    os.environ[key] = value   # 현재 세션에도 즉시 반영


def clean_env(value: str) -> str:
    """.env의 플레이스홀더 값(your_..._here)을 빈 문자열로 취급합니다."""
    if not value:
        return ""
    v = value.strip()
    if v.startswith("your_") and v.endswith("_here"):
        return ""
    return v


# ── 음성 목록 (build_voice_list.py 로 생성) ───────
VOICE_LIST_PATH = Path(__file__).parent / "assets" / "voices_ko.json"


@st.cache_data(show_spinner=False)
def load_voice_list() -> dict:
    """성별로 분류된 음성 목록을 읽습니다. 없으면 빈 dict."""
    try:
        with open(VOICE_LIST_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def play_voice_preview(voice: dict, api_key: str, script: str):
    """선택한 음성으로 짧은 샘플을 만들어 session_state에 담습니다."""
    # 대본 첫 문장으로 미리듣기 (없으면 기본 문구)
    sample = (script or "").strip().split('\n')[0][:60]
    if not sample:
        sample = "안녕하세요. 이 음성으로 쇼츠 대본을 읽어드릴게요."

    try:
        with st.spinner(f"🔊 {voice['name']} 음성 생성 중..."):
            tts = TypecastTTS(api_key=api_key, actor_id=voice['voice_id'])
            audio_bytes = tts.synthesize(
                text=sample,
                model=voice.get('model'),
                output_format='wav',
            )
        st.session_state['voice_preview'] = {
            'voice_id': voice['voice_id'],
            'name': voice['name'],
            'audio': audio_bytes,
        }
        st.rerun()
    except Exception as e:
        st.error(f"❌ 미리듣기 실패: {e}")


# ── 사이드바: API 설정 ────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ API 설정")
    st.markdown("---")

    # Anthropic API 키
    anthropic_key = st.text_input(
        "🤖 Anthropic API 키",
        value=clean_env(get_secret("ANTHROPIC_API_KEY", "")),
        type="password",
        help="https://console.anthropic.com 에서 발급",
        placeholder="sk-ant-...",
        key="input_anthropic_key",
    )
    if anthropic_key and anthropic_key != clean_env(get_secret("ANTHROPIC_API_KEY", "")):
        save_env("ANTHROPIC_API_KEY", anthropic_key)
        st.success("✅ API 키 저장됨", icon="💾")

    # Typecast API 설정
    st.markdown("---")
    typecast_key = st.text_input(
        "🎙️ Typecast API 키",
        value=clean_env(get_secret("TYPECAST_API_KEY", "")),
        type="password",
        help="https://typecast.ai 에서 발급 (없으면 테스트 모드)",
        placeholder="typecast_...",
        key="input_typecast_key",
    )
    if typecast_key and typecast_key != clean_env(get_secret("TYPECAST_API_KEY", "")):
        save_env("TYPECAST_API_KEY", typecast_key)

    typecast_actor = st.text_input(
        "🎭 음성 캐릭터 ID",
        value=clean_env(get_secret("TYPECAST_ACTOR_ID", "")),
        help="아래 '음성 캐릭터 목록 불러오기' 버튼으로 자동 입력할 수 있습니다",
        placeholder="actor_...",
        key="input_typecast_actor",
    )
    if typecast_actor and typecast_actor != clean_env(get_secret("TYPECAST_ACTOR_ID", "")):
        save_env("TYPECAST_ACTOR_ID", typecast_actor)

    # 캐릭터 ID를 모를 때: API로 목록 직접 불러오기
    if typecast_key:
        if st.button("🔍 음성 캐릭터 목록 불러오기", use_container_width=True):
            try:
                with st.spinner("목록 조회 중..."):
                    _tts = TypecastTTS(api_key=typecast_key)
                    st.session_state['_actor_list'] = _tts.list_actors()
            except Exception as e:
                st.session_state['_actor_list'] = []
                st.error(str(e))

        _actors = st.session_state.get('_actor_list') or []
        if _actors:
            st.caption(f"사용 가능한 음성 {len(_actors)}개")

            _q = st.text_input(
                "이름으로 검색",
                placeholder="예: Junwoo, Jiseon, Hyejin",
                key="actor_search",
                help="한국식 이름(Junwoo, Jiseon 등)을 검색하면 한국어에 자연스러운 음성을 찾기 쉽습니다",
            )

            _filtered = [
                a for a in _actors
                if not _q or _q.lower() in (a.get('name') or '').lower()
            ]

            if not _filtered:
                st.warning("검색 결과가 없습니다.")
            else:
                _opts = {}
                for _a in _filtered[:50]:
                    _aid = _a.get('actor_id') or _a.get('voice_id') or ''
                    _nm = _a.get('name') or _aid
                    if _aid:
                        _opts[_nm] = _aid

                if len(_filtered) > 50:
                    st.caption(f"상위 50개만 표시 중 (검색 {len(_filtered)}개)")

                _pick = st.selectbox("음성 선택", list(_opts.keys()), key="actor_pick")
                if st.button("✅ 이 음성 사용", use_container_width=True):
                    save_env("TYPECAST_ACTOR_ID", _opts[_pick])
                    st.rerun()

    # 현재 저장 상태 표시
    if clean_env(get_secret("ANTHROPIC_API_KEY", "")):
        st.caption("💾 키가 .env에 저장되어 있습니다")

    # 테스트 모드 안내
    if not typecast_key:
        st.info("💡 Typecast 키 없으면\n자동으로 **테스트 모드** (무음 파일)로 진행됩니다")

    st.markdown("---")

    # ── API 사용액 ────────────────────────────────
    st.markdown("## 💰 API 사용액")
    try:
        from modules.cost_tracker import summary as _cost_summary, reset as _cost_reset
        _cs = _cost_summary()
        _c1, _c2 = st.columns(2)
        _c1.metric("오늘", f"{_cs['today_krw']:,}원")
        _c2.metric("누적", f"{_cs['krw']:,}원")

        if _cs['by_step']:
            with st.expander(f"항목별 ({_cs['calls']}회 호출)"):
                for _k, _v in sorted(_cs['by_step'].items(), key=lambda x: -x[1]):
                    st.caption(f"{_k}: {_v:,}원")
                if st.button("기록 초기화", use_container_width=True):
                    _cost_reset()
                    st.rerun()
        else:
            st.caption("아직 사용 기록이 없습니다")
    except Exception as _e:
        st.caption(f"사용액 표시 오류: {_e}")

    st.markdown("---")

    # 진행 상태 표시 (클릭하면 해당 탭으로 이동)
    st.markdown("## 📊 진행 상태")
    steps = {
        1: ("📹", "참고 영상 분석"),
        2: ("🖼️", "이미지 분석"),
        3: ("✍️", "대본 생성"),
        4: ("🎙️", "음성 생성"),
        5: ("🎬", "영상 만들기"),
    }
    current_step = st.session_state.get('step', 1)

    for num, (icon, name) in steps.items():
        if num < current_step:
            label = f"✅ {icon} {name}"
        elif num == current_step:
            label = f"▶️ {icon} **{name}** ← 현재"
        else:
            label = f"⏸️ {icon} {name}"

        if st.button(label, key=f"nav_step_{num}", use_container_width=True):
            st.session_state['active_tab'] = num - 1
            st.rerun()

    st.markdown("---")
    if st.button("🔄 처음부터 다시 시작", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    # 비밀번호를 쓰는 경우에만 로그아웃을 보여줍니다
    if get_secret("APP_PASSWORD", "").strip():
        if st.button("🔒 로그아웃", use_container_width=True):
            st.session_state["_authed"] = False
            try:
                st.query_params.clear()   # 주소에 남은 토큰도 지웁니다
            except Exception:
                pass
            st.rerun()


# ══════════════════════════════════════════════════
# 메인 화면
# ══════════════════════════════════════════════════

# 히어로 타이틀
st.markdown("""
<div class="hero-title">
    <h1>🛍️ 쇼핑 쇼츠 영상 자동화</h1>
    <p>상품 이미지 + 참고 영상 URL → AI가 자동으로 후킹 대본·음성·자막·영상 에셋 생성</p>
</div>
""", unsafe_allow_html=True)

# ── 커스텀 탭 (session_state로 탭 상태 유지) ──────
TAB_LABELS = ["① 입력", "② 이미지 분석", "③ 대본 생성", "④ 음성·자막", "⑤ 영상 만들기"]

tab_cols = st.columns(len(TAB_LABELS))
for _i, (_col, _label) in enumerate(zip(tab_cols, TAB_LABELS)):
    with _col:
        _is_active = (st.session_state['active_tab'] == _i)
        if st.button(
            _label,
            key=f"maintab_{_i}",
            use_container_width=True,
            type="primary" if _is_active else "secondary",
        ):
            st.session_state['active_tab'] = _i
            st.rerun()

st.markdown("---")
_active = st.session_state['active_tab']


# ══════════════════════════════════════════════════
# 탭 ①: 입력 (참고 영상 URL + 상품 이미지 + 타겟)
# ══════════════════════════════════════════════════
if _active == 0:
    st.markdown("### 📥 Step 1 — 기본 정보 입력")

    col1, col2 = st.columns([1, 1], gap="large")

    with col1:
        st.markdown("#### 🎬 참고 쇼츠 영상 URL")
        st.caption("경쟁사 또는 유사 상품의 잘 되는 쇼츠 영상 URL을 입력하세요 (1개 이상)")

        ref_urls_text = st.text_area(
            "URL 입력 (한 줄에 하나씩)",
            height=150,
            placeholder="https://www.tiktok.com/@username/video/1234567890\nhttps://youtube.com/shorts/...",
            help="YouTube 쇼츠 또는 TikTok 영상 URL 지원. 없으면 비워두세요 (기본 패턴 사용)"
        )
        st.caption(
            "✅ 지원 플랫폼: **YouTube 쇼츠** · **TikTok 영상** | "
            "⚠️ TikTok 프로필 URL(@username만 있는 것)은 불가 — 반드시 특정 영상 URL을 입력하세요"
        )

        st.markdown("#### 👥 타겟 고객")
        target_options = [
            "2030 직장인",
            "5060 시니어",
            "MZ 세대 (1020)",
            "육아맘",
            "운동/헬스 관심층",
            "일반 소비자",
        ]
        target_audience = st.selectbox(
            "타겟 고객을 선택하세요",
            options=target_options,
            index=0,
        )
        st.session_state['target_audience'] = target_audience

        additional_info = st.text_area(
            "추가 상품 정보 (선택)",
            height=80,
            placeholder="예: 실제 가격 29,900원, 무료배송, 한정수량 500개",
            help="이미지에서 보이지 않는 정보를 입력하면 대본에 반영됩니다"
        )

    with col2:
        st.markdown("#### 🖼️ 상품 이미지 업로드")
        st.caption("1~10장. 여러 각도의 상품 이미지를 업로드하면 더 정확한 분석이 됩니다.")

        uploaded_files = st.file_uploader(
            "이미지 선택",
            type=['jpg', 'jpeg', 'png', 'webp'],
            accept_multiple_files=True,
            help="JPG, PNG, WEBP 형식 지원. 최대 10장"
        )

        if uploaded_files:
            cols = st.columns(min(len(uploaded_files), 3))
            for i, uploaded in enumerate(uploaded_files[:6]):
                with cols[i % 3]:
                    st.image(uploaded, caption=f"이미지 {i+1}", use_container_width=True)

            if len(uploaded_files) > 6:
                st.caption(f"+{len(uploaded_files) - 6}장 더...")

        # ── 소재 영상 업로드 (컷편집용) ──────────
        st.markdown("#### 🎬 소재 영상 업로드 (선택)")
        st.caption(
            "알리·1688·타오바오 공급사 영상이나 직접 찍은 영상을 올려두면 "
            "'⑤ 영상 만들기'에서 컷편집에 바로 씁니다."
        )

        uploaded_videos = st.file_uploader(
            "영상 선택",
            type=['mp4', 'mov', 'webm', 'mkv'],
            accept_multiple_files=True,
            key="src_video_upload_tab1",
            help="MP4, MOV, WEBM, MKV 지원",
        )

        if uploaded_videos:
            _src_dir = os.path.join("outputs", "source_videos")
            Path(_src_dir).mkdir(parents=True, exist_ok=True)
            _saved = []
            for _uv in uploaded_videos:
                _dst = os.path.join(_src_dir, _uv.name)
                # 이미 같은 파일이 있으면 다시 쓰지 않습니다
                if not os.path.exists(_dst) or os.path.getsize(_dst) != _uv.size:
                    with open(_dst, 'wb') as _f:
                        _f.write(_uv.getbuffer())
                _saved.append(_dst)
            st.session_state['source_videos'] = _saved
            st.success(f"✅ 소재 영상 {len(_saved)}개 저장됨")
            for _p in _saved[:5]:
                st.caption(f"• {os.path.basename(_p)}")
        elif st.session_state.get('source_videos'):
            _keep = [p for p in st.session_state['source_videos'] if os.path.exists(p)]
            if _keep:
                st.info(f"📁 이전에 올린 영상 {len(_keep)}개가 있습니다")

    st.markdown("---")

    # 실행 전 예상 비용 안내
    col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
    with col_btn2:
        try:
            from modules.cost_tracker import estimate_run
            _n_img = len(uploaded_files) if uploaded_files else 3
            _est = estimate_run(n_images=min(_n_img, 4), smart_match=False)
            st.caption(
                f"💰 예상 비용: 약 **{_est['krw']}원** "
                f"(이미지 분석 {_est['detail'].get('이미지 분석', 0)}원 + "
                f"대본 생성 {_est['detail'].get('대본 생성', 0)}원)"
            )
        except Exception:
            pass

    # 분석 실행 버튼 (영상 분석 + 이미지 분석 + 대본 생성 한 번에)
    with col_btn2:
        _src_videos = [
            p for p in st.session_state.get('source_videos', [])
            if os.path.exists(p)
        ]

        if st.button("🚀 분석 + 대본 자동 생성", use_container_width=True, type="primary"):
            if not anthropic_key:
                st.error("❌ Anthropic API 키를 먼저 입력하세요 (사이드바)")
            elif not uploaded_files and not _src_videos:
                st.error("❌ 상품 이미지나 소재 영상 중 하나는 올려 주세요")
            else:
                tmp_image_paths = []

                if uploaded_files:
                    # 업로드한 이미지를 임시 파일로 저장
                    for uf in uploaded_files[:10]:
                        tmp_path = os.path.join(
                            tempfile.gettempdir(),
                            f"shorts_img_{uf.name}"
                        )
                        with open(tmp_path, 'wb') as f:
                            f.write(uf.getvalue())
                        tmp_image_paths.append(tmp_path)
                    st.session_state['images_from_video'] = False
                else:
                    # 이미지가 없으면 소재 영상에서 프레임을 뽑아 대신 씁니다
                    # (분석용일 뿐, 컷편집에서는 정지컷으로 쓰지 않습니다)
                    st.session_state['images_from_video'] = True
                    with st.spinner("🎞️ 영상에서 상품 화면 추출 중..."):
                        try:
                            from modules.clip_editor import extract_frames_from_videos
                            tmp_image_paths = extract_frames_from_videos(
                                _src_videos, per_video=3, max_total=9
                            )
                            if tmp_image_paths:
                                st.info(
                                    f"🖼️ 상품 이미지가 없어 영상에서 {len(tmp_image_paths)}장을 "
                                    "뽑아 분석에 씁니다."
                                )
                                cols_pv = st.columns(min(len(tmp_image_paths), 5))
                                for _i, _p in enumerate(tmp_image_paths[:5]):
                                    with cols_pv[_i]:
                                        st.image(_p, use_container_width=True)
                            else:
                                st.warning("⚠️ 영상에서 화면을 뽑지 못했습니다.")
                        except Exception as e:
                            st.warning(f"⚠️ 프레임 추출 실패: {e}")

                st.session_state['uploaded_images'] = tmp_image_paths

                # ── STEP 1: 참고 영상 분석 ────────────────
                ref_urls = [u.strip() for u in ref_urls_text.strip().split('\n') if u.strip()]
                st.session_state['ref_urls'] = ref_urls   # ⑤ 컷편집에서 재사용

                with st.spinner("🎬 [1/3] 참고 영상 자막 분석 중... (TikTok은 10~20초 소요)"):
                    if ref_urls:
                        try:
                            video_result = analyze_reference_videos(ref_urls)
                            st.session_state['video_analysis'] = video_result
                            analyzed = video_result.get('analyzed_count', 0)
                            errors = video_result.get('errors', [])

                            if analyzed > 0:
                                st.success(f"✅ 참고 영상 {analyzed}개 분석 완료! (입력 {len(ref_urls)}개 중)")

                            for e in errors:
                                if e.startswith('⚠️'):
                                    st.warning(e)
                                elif 'TikTok 접근 차단' in e or '차단됨' in e:
                                    st.error(e)
                                    st.info(
                                        "💡 **TikTok 차단 해결법**: "
                                        "Chrome에서 [TikTok](https://www.tiktok.com)에 로그인한 상태로 앱을 재실행하면 "
                                        "Chrome 쿠키를 자동으로 사용해서 접근됩니다."
                                    )
                                else:
                                    st.error(e)

                            if analyzed == 0 and errors:
                                st.info("💡 분석 성공한 영상이 없어 기본 패턴으로 진행합니다.")
                                st.session_state['video_analysis']['summary'] = {
                                    "dominant_patterns": ["공감형", "숫자형"],
                                    "avg_duration_sec": 50,
                                    "sample_hooks": [],
                                    "sample_ctas": [],
                                }

                        except Exception as e:
                            st.warning(f"⚠️ 참고 영상 분석 실패 (기본 패턴 사용): {e}")
                            st.session_state['video_analysis'] = {
                                "success": False,
                                "analyzed_count": 0,
                                "errors": [str(e)],
                                "summary": {}
                            }
                    else:
                        st.session_state['video_analysis'] = {
                            "success": False,
                            "analyzed_count": 0,
                            "errors": [],
                            "summary": {
                                "dominant_patterns": ["공감형", "숫자형"],
                                "avg_duration_sec": 50,
                                "sample_hooks": [],
                                "sample_ctas": [],
                            }
                        }
                        st.info("💡 참고 영상 URL 없음 → 기본 쇼츠 패턴 사용")

                st.session_state['additional_info'] = additional_info

                # ── STEP 2: 이미지 분석 ──────────────────────
                img_analysis = {}
                with st.spinner("🖼️ [2/3] 상품 이미지 AI 분석 중..."):
                    try:
                        img_result = analyze_product_images(
                            images=tmp_image_paths,
                            api_key=anthropic_key,
                            target_audience=target_audience,
                        )
                        st.session_state['image_analysis'] = img_result
                        img_analysis = img_result.get('analysis', {})
                        st.success("✅ 이미지 분석 완료!")
                    except Exception as e:
                        st.error(f"❌ 이미지 분석 오류: {e}")
                        st.warning("⚠️ 이미지 분석 실패 — 대본은 기본 정보로 생성됩니다.")

                # ── STEP 3: 대본 자동 생성 ───────────────────
                with st.spinner("✍️ [3/3] 쇼핑 쇼츠 대본 3가지 버전 생성 중..."):
                    try:
                        script_result = generate_scripts(
                            image_analysis=img_analysis,
                            video_analysis=st.session_state.get('video_analysis', {}),
                            target_audience=target_audience,
                            api_key=anthropic_key,
                            additional_info=additional_info,
                        )
                        st.session_state['scripts_data'] = script_result
                        st.success("✅ 대본 생성 완료!")
                    except Exception as e:
                        err_msg = str(e)
                        if "크레딧 부족" in err_msg or "billing" in err_msg.lower() or "credit" in err_msg.lower():
                            st.warning("💳 Anthropic 크레딧 부족 → 샘플 대본으로 계속 진행합니다.")
                            st.session_state['scripts_data'] = generate_test_scripts(target_audience)
                        else:
                            st.error(f"❌ 대본 생성 오류: {e}")

                st.session_state['step'] = 4
                st.session_state['active_tab'] = 2   # ③ 대본 생성 탭으로 이동
                st.balloons()
                st.rerun()


# ══════════════════════════════════════════════════
# 탭 ②: 상품 이미지 분석
# ══════════════════════════════════════════════════
if _active == 1:
    st.markdown("### 🖼️ Step 2 — 상품 이미지 AI 분석")

    if not st.session_state.get('image_analysis'):
        st.info("👈 '① 입력' 탭에서 이미지를 업로드하고 **분석 + 대본 자동 생성** 버튼을 누르면 여기에 결과가 표시됩니다.")
    else:
        analysis = st.session_state['image_analysis']['analysis']
        st.success("✅ 이미지 분석 완료!")

        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown(format_analysis_for_display(analysis))

        with col2:
            st.markdown("#### 🎬 후킹 앵글 아이디어")
            for angle in analysis.get('hook_angles', []):
                st.markdown(f'> 💡 "{angle}"')

            st.markdown("#### 🏷️ 감성 키워드")
            keywords = analysis.get('emotional_keywords', [])
            if keywords:
                st.markdown(" ".join([f"`{k}`" for k in keywords]))

        # 상품명 저장
        st.session_state['product_name'] = analysis.get('product_name', '상품')

        if st.button("🔄 다시 분석", help="이미지 분석 결과를 지우고 다시 실행합니다"):
            del st.session_state['image_analysis']
            st.rerun()

        st.markdown("---")
        st.info("✅ 분석 완료! '③ 대본 생성' 탭에서 대본을 확인하세요.")


# ══════════════════════════════════════════════════
# 탭 ③: 대본 생성
# ══════════════════════════════════════════════════
if _active == 2:
    st.markdown("### ✍️ Step 3 — 쇼핑 쇼츠 대본 생성")

    if not st.session_state.get('uploaded_images') and not st.session_state.get('image_analysis'):
        st.info("👈 먼저 '① 입력' 탭에서 이미지를 업로드하고 **분석 + 대본 자동 생성**을 눌러주세요.")
    else:
        # 생성 버튼 (자동 생성이 실패했을 때만 표시)
        if not st.session_state.get('scripts_data'):
            col_center = st.columns([1, 2, 1])[1]
            with col_center:
                if st.button("✨ 대본 3가지 버전 생성", use_container_width=True, type="primary"):
                    with st.spinner("✍️ 구매 전환율 최고의 쇼핑 대본 작성 중..."):
                        try:
                            img_analysis = {}
                            if st.session_state.get('image_analysis'):
                                img_analysis = st.session_state['image_analysis'].get('analysis', {})

                            result = generate_scripts(
                                image_analysis=img_analysis,
                                video_analysis=st.session_state.get('video_analysis', {}),
                                target_audience=st.session_state.get('target_audience', '일반 소비자'),
                                api_key=anthropic_key,
                                additional_info=st.session_state.get('additional_info', ''),
                            )
                            st.session_state['scripts_data'] = result
                            st.session_state['step'] = 4
                            st.session_state['active_tab'] = 2
                            st.rerun()
                        except Exception as e:
                            err_msg = str(e)
                            if "크레딧 부족" in err_msg or "billing" in err_msg.lower() or "credit" in err_msg.lower():
                                st.warning(
                                    "💳 크레딧 부족 → 샘플 대본으로 진행합니다. "
                                    "(console.anthropic.com/settings/billing 에서 충전)"
                                )
                                st.session_state['scripts_data'] = generate_test_scripts(
                                    st.session_state.get('target_audience', '일반 소비자')
                                )
                                st.session_state['step'] = 4
                                st.session_state['active_tab'] = 2
                                st.rerun()
                            else:
                                st.error(f"❌ 대본 생성 오류: {e}")

        # 대본 표시
        if st.session_state.get('scripts_data'):
            scripts_data = st.session_state['scripts_data']

            if scripts_data.get('success') and 'scripts' in scripts_data.get('scripts_data', {}):
                scripts = scripts_data['scripts_data']['scripts']
                recommended = scripts_data['scripts_data'].get('recommended_version', 'A')

                st.success(f"✅ {len(scripts)}개 대본 버전 생성 완료! 추천: 버전 {recommended}")
                st.caption(scripts_data['scripts_data'].get('recommendation_reason', ''))

                version_tabs = st.tabs([
                    f"버전 {s.get('version', i+1)}" + (" ⭐" if s.get('version') == recommended else "")
                    for i, s in enumerate(scripts)
                ])

                for i, (vtab, script) in enumerate(zip(version_tabs, scripts)):
                    with vtab:
                        col1, col2 = st.columns([3, 2])

                        with col1:
                            st.markdown(f"**후킹 유형:** `{script.get('hook_type', '-')}`")
                            st.markdown(f"**앵글:** {script.get('hook_angle', '-')}")
                            st.markdown(f"**예상 길이:** ⏱️ {script.get('estimated_duration_sec', '?')}초")
                            st.markdown(f"**핵심 감성:** 💭 {script.get('key_emotion', '-')}")
                            st.markdown("---")

                            full_script = script.get('full_script', '')
                            st.markdown("**📜 전체 대본:**")
                            st.markdown(f'<div class="script-box">{full_script}</div>', unsafe_allow_html=True)

                        with col2:
                            st.markdown("**📋 섹션별 구분:**")
                            script_parts = script.get('script', {})
                            sections = [
                                ("🎣 후크 (0~3초)", script_parts.get('hook', '')),
                                ("🤝 공감 (3~8초)", script_parts.get('empathy', '')),
                                ("📦 소개 (8~15초)", script_parts.get('intro', '')),
                                ("✨ 혜택 (15~40초)", script_parts.get('benefit', '')),
                                ("👆 CTA (40~60초)", script_parts.get('cta', '')),
                            ]
                            for section_name, section_text in sections:
                                with st.expander(section_name):
                                    st.write(section_text)

                        # 이 버전 선택 → 음성·자막 탭으로 자동 이동
                        if st.button(
                            f"✅ 버전 {script.get('version', i+1)} 선택 → 음성·자막 탭으로 이동",
                            key=f"select_v{i}",
                            use_container_width=True,
                            type="primary",
                        ):
                            st.session_state['selected_script'] = script.get('full_script', '')
                            st.session_state['selected_version'] = script.get('version', str(i+1))
                            st.session_state['step'] = 4
                            st.session_state['active_tab'] = 3
                            st.rerun()

                st.markdown("---")
                if st.button("🔄 대본 다시 생성"):
                    del st.session_state['scripts_data']
                    st.rerun()

            else:
                # JSON 파싱 실패 시 원본 표시
                st.markdown("**생성된 대본:**")
                st.text_area("대본 (직접 복사 가능)", value=scripts_data.get('raw_response', ''), height=400)

                manual_script = st.text_area("✏️ 사용할 대본을 여기에 입력/수정하세요", height=200)
                if st.button("✅ 이 대본으로 음성 생성", type="primary"):
                    st.session_state['selected_script'] = manual_script
                    st.session_state['step'] = 4
                    st.session_state['active_tab'] = 3
                    st.rerun()


# ══════════════════════════════════════════════════
# 탭 ④: 음성 + 자막 생성
# ══════════════════════════════════════════════════
if _active == 3:
    st.markdown("### 🎙️ Step 4 — 음성·자막 생성")

    if not st.session_state.get('selected_script') and not st.session_state.get('scripts_data'):
        st.info("👈 먼저 '③ 대본 생성' 탭에서 대본을 선택해 주세요.")
    else:
        # 대본이 선택되지 않았으면 자동으로 추천 버전 사용
        if not st.session_state.get('selected_script') and st.session_state.get('scripts_data'):
            scripts_d = st.session_state['scripts_data'].get('scripts_data', {})
            st.session_state['selected_script'] = get_full_script(scripts_d)

        current_script = st.session_state.get('selected_script', '')

        # ══════════════════════════════════════════
        # 음성 선택 (여성 좌 / 남성 우) + 미리듣기
        # ══════════════════════════════════════════
        st.markdown("#### 🎧 음성 선택")

        voice_data = load_voice_list()

        if not voice_data:
            st.warning(
                "음성 목록 파일이 없습니다. 터미널에서 `python build_voice_list.py` 를 "
                "실행하면 목록이 만들어집니다."
            )
        elif not typecast_key:
            st.info("💡 Typecast API 키를 입력하면 음성을 고르고 미리들을 수 있습니다.")
        else:
            vc_f, vc_m = st.columns(2)

            # ── 여성 (좌측) ──────────────────────
            with vc_f:
                st.markdown("**👩 여성 음성**")
                f_list = voice_data.get('female', [])
                f_names = [v['name'] for v in f_list]
                if f_names:
                    f_sel = st.selectbox(
                        "여성 음성 선택", f_names,
                        key="voice_pick_f", label_visibility="collapsed",
                    )
                    if st.button("▶️ 미리듣기", key="prev_f", use_container_width=True):
                        v = next(x for x in f_list if x['name'] == f_sel)
                        play_voice_preview(v, typecast_key, current_script)

            # ── 남성 (우측) ──────────────────────
            with vc_m:
                st.markdown("**👨 남성 음성**")
                m_list = voice_data.get('male', [])
                m_names = [v['name'] for v in m_list]
                if m_names:
                    m_sel = st.selectbox(
                        "남성 음성 선택", m_names,
                        key="voice_pick_m", label_visibility="collapsed",
                    )
                    if st.button("▶️ 미리듣기", key="prev_m", use_container_width=True):
                        v = next(x for x in m_list if x['name'] == m_sel)
                        play_voice_preview(v, typecast_key, current_script)

            # ── 미리듣기 결과 ────────────────────
            prev = st.session_state.get('voice_preview')
            if prev:
                st.markdown("---")
                st.caption(f"🔊 미리듣기 — **{prev['name']}**")
                st.audio(prev['audio'], format='audio/wav')

                pc1, pc2 = st.columns(2)
                with pc1:
                    if st.button("✅ 이 음성으로 결정", use_container_width=True, type="primary"):
                        st.session_state['chosen_voice_id'] = prev['voice_id']
                        st.session_state['chosen_voice_name'] = prev['name']
                        st.session_state['voice_preview'] = None
                        st.rerun()
                with pc2:
                    if st.button("🗑️ 삭제 (마음에 안 들어요)", use_container_width=True):
                        st.session_state['voice_preview'] = None
                        st.rerun()

            # ── 현재 결정된 음성 ─────────────────
            chosen_name = st.session_state.get('chosen_voice_name')
            if chosen_name:
                cc1, cc2 = st.columns([3, 1])
                cc1.success(f"🎙️ 사용할 음성: **{chosen_name}**")
                with cc2:
                    if st.button("🗑️ 선택 해제", use_container_width=True):
                        st.session_state['chosen_voice_id'] = None
                        st.session_state['chosen_voice_name'] = None
                        st.rerun()
            else:
                st.caption(
                    "⬆️ 미리듣고 **이 음성으로 결정**을 누르세요. "
                    "정하지 않으면 사이드바의 기본 음성으로 생성됩니다."
                )

            st.caption(
                "ℹ️ Typecast가 성별 정보를 주지 않아 **이름으로 추정**한 분류입니다. "
                "간혹 성별이 다를 수 있으니 미리듣기로 확인하세요."
            )

        st.markdown("---")

        col1, col2 = st.columns([3, 2])

        with col1:
            st.markdown("#### 📝 사용할 대본 (수정 가능)")
            edited_script = st.text_area(
                "대본",
                value=current_script,
                height=300,
                help="여기서 직접 수정 후 생성할 수 있습니다",
                label_visibility="collapsed"
            )

        with col2:
            st.markdown("#### 🎙️ 음성 설정")
            tts_speed = st.slider(
                "말하기 속도",
                min_value=0.8, max_value=1.5, value=1.05, step=0.05,
                help="쇼츠는 1.0~1.2 권장"
            )
            tts_emotion = st.selectbox(
                "감정 설정",
                options=["보통", "기쁨", "슬픔", "화남", "차분함"],
                index=0,
            )
            audio_format = st.radio(
                "오디오 형식",
                options=["wav", "mp3"],
                horizontal=True,
                help="wav는 무손실, mp3는 용량이 작습니다"
            )

            st.markdown("#### 📄 자막 설정")
            max_chars = st.slider(
                "자막 한 줄 최대 글자 수",
                min_value=10, max_value=30, value=18,
                help="쇼츠는 15~20자 권장"
            )

        st.markdown("---")

        if st.button("🎙️ 음성 + 자막 생성", use_container_width=True, type="primary"):
            if not edited_script.strip():
                st.error("❌ 대본이 비어 있습니다.")
            else:
                st.session_state['selected_script'] = edited_script

                output_dir = "outputs"
                Path(output_dir).mkdir(exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                audio_path = None

                # 위에서 고른 음성을 우선 사용하고, 없으면 사이드바 기본값
                use_voice_id = st.session_state.get('chosen_voice_id') or typecast_actor
                use_voice_name = st.session_state.get('chosen_voice_name')

                # ── TTS 음성 생성 ─────────────────────────
                with st.spinner("🎙️ AI 음성 생성 중..."):
                    audio_path = os.path.join(output_dir, f"voice_{timestamp}.{audio_format}")
                    try:
                        if typecast_key and use_voice_id:
                            tts = TypecastTTS(api_key=typecast_key, actor_id=use_voice_id)
                            tts.synthesize_long_text(
                                text=edited_script,
                                output_path=audio_path,
                                speed=tts_speed,
                                emotion=tts_emotion,
                                output_format=audio_format,
                            )
                            if use_voice_name:
                                st.success(f"✅ **{use_voice_name}** 음성으로 생성 완료!")
                            else:
                                st.success("✅ Typecast AI 음성 생성 완료!")
                        else:
                            estimated_sec = len(edited_script) / 5.5
                            audio_path = os.path.join(output_dir, f"voice_{timestamp}.wav")
                            create_silent_audio(duration_sec=estimated_sec, output_path=audio_path)
                            if not typecast_key:
                                st.warning("⚠️ 테스트 모드: 무음 WAV 생성 (실제 음성은 Typecast API 키 필요)")
                            else:
                                st.warning("⚠️ 음성 캐릭터 ID가 없어 무음 WAV로 진행합니다. 사이드바에서 캐릭터를 선택하세요.")

                        st.session_state['audio_path'] = audio_path

                    except Exception as e:
                        # Typecast 인증/크레딧 실패 시 테스트 모드로 이어서 진행
                        err = str(e)
                        if "API 키" in err or "401" in err or "크레딧" in err:
                            st.warning(f"⚠️ Typecast 사용 불가 → 무음 파일로 계속 진행합니다.\n\n{err}")
                            estimated_sec = len(edited_script) / 5.5
                            audio_path = os.path.join(output_dir, f"voice_{timestamp}.wav")
                            try:
                                create_silent_audio(duration_sec=estimated_sec, output_path=audio_path)
                                st.session_state['audio_path'] = audio_path
                            except Exception as e2:
                                st.error(f"❌ 무음 파일 생성 실패: {e2}")
                                audio_path = None
                        else:
                            st.error(f"❌ 음성 생성 오류: {e}")
                            audio_path = None

                # ── SRT / ASS 자막 생성 ───────────────────
                if audio_path:
                    with st.spinner("📑 자막 파일 생성 중..."):
                        try:
                            duration = get_audio_duration(audio_path)

                            srt_path = os.path.join(output_dir, f"subtitle_{timestamp}.srt")
                            generate_srt(
                                script=edited_script,
                                total_duration_sec=duration,
                                output_path=srt_path,
                                max_chars_per_line=max_chars,
                            )
                            st.session_state['srt_path'] = srt_path

                            ass_path = os.path.join(output_dir, f"subtitle_{timestamp}.ass")
                            generate_ass_subtitles(
                                script=edited_script,
                                total_duration_sec=duration,
                                output_path=ass_path,
                            )
                            st.session_state['ass_path'] = ass_path

                            st.session_state['step'] = 5
                            st.success(f"✅ 자막 생성 완료! (총 {duration:.1f}초)")

                        except Exception as e:
                            st.error(f"❌ 자막 생성 오류: {e}")

        # ── 결과 표시 ─────────────────────────────────
        if st.session_state.get('audio_path'):
            st.markdown("---")
            st.markdown("#### 🎧 생성된 음성")

            audio_file = st.session_state['audio_path']
            if os.path.exists(audio_file):
                with open(audio_file, 'rb') as f:
                    st.audio(f.read())
                st.caption(f"📁 {audio_file}")

            if st.session_state.get('srt_path') and os.path.exists(st.session_state['srt_path']):
                st.markdown("#### 📄 생성된 자막 미리보기")
                try:
                    preview = srt_to_preview(st.session_state['srt_path'])
                    st.code(preview, language=None)
                except Exception as e:
                    st.warning(f"자막 미리보기 실패: {e}")

            st.markdown("---")
            if st.button("🎬 영상 만들기 탭으로 이동", use_container_width=True, type="primary"):
                st.session_state['active_tab'] = 4
                st.rerun()


# ══════════════════════════════════════════════════
# 탭 ⑤: 에셋 패키징 + 다운로드
# ══════════════════════════════════════════════════
if _active == 4:
    st.markdown("### 🎬 Step 5 — 쇼츠 영상 만들기")

    if not st.session_state.get('audio_path'):
        st.info("👈 먼저 '④ 음성·자막' 탭에서 음성과 자막을 생성해 주세요.")
    else:
        audio_p = st.session_state.get('audio_path')
        srt_p = st.session_state.get('srt_path')
        ass_p = st.session_state.get('ass_path')
        imgs = st.session_state.get('uploaded_images', [])
        script_txt = st.session_state.get('selected_script', '')

        # ── 재료 확인 ─────────────────────────────────
        c1, c2, c3 = st.columns(3)
        c1.metric("🖼️ 상품 이미지", f"{len(imgs)}장")
        try:
            _dur = get_audio_duration(audio_p) if os.path.exists(audio_p) else 0
            c2.metric("🎧 음성 길이", f"{_dur:.1f}초")
        except Exception:
            c2.metric("🎧 음성 길이", "-")
        c3.metric("📄 자막", "있음" if (srt_p and os.path.exists(srt_p)) else "없음")

        if len(imgs) < 3:
            st.info(
                f"💡 이미지가 {len(imgs)}장이라 한 장당 오래 머뭅니다. "
                "**5~8장**을 올리면 3~4초마다 바뀌어 훨씬 보기 좋습니다."
            )

        st.markdown("---")

        # ── 영상 만드는 방식 선택 ─────────────────────
        # 소재 영상이 있으면 컷편집을 기본으로 둡니다
        # (슬라이드쇼로 만들면 화면이 움직이지 않습니다)
        _has_src_video = bool([
            p for p in st.session_state.get('source_videos', [])
            if os.path.exists(p)
        ])

        st.markdown("#### 🎞️ 영상 만드는 방식")
        mode = st.radio(
            "방식",
            options=["상품 이미지 슬라이드쇼", "컷편집 (영상·이미지)"],
            index=1 if _has_src_video else 0,
            horizontal=True,
            label_visibility="collapsed",
            help="슬라이드쇼는 정지 이미지, 컷편집은 영상 클립을 잘라 붙입니다",
        )

        if _has_src_video and mode == "상품 이미지 슬라이드쇼":
            st.warning(
                "⚠️ 올리신 소재 영상이 있는데 **슬라이드쇼**를 고르셨습니다. "
                "슬라이드쇼는 정지 화면만 나옵니다 — 영상이 움직이게 하려면 "
                "**컷편집**을 선택하세요."
            )

        cut_local_paths = []
        cut_urls = []
        use_imgs_ui = []
        img_every = 3
        smart_match = True

        if mode == "컷편집 (영상·이미지)":
            st.caption(
                "**자막 한 줄마다 화면 하나씩** 배정해 이어붙입니다. "
                "원본 소리는 버리고 생성한 음성을 입힙니다. "
                "영상만 넣으면 영상만, 이미지만 넣으면 이미지만, 둘 다 넣으면 섞어서 만듭니다."
            )

            src_tab1, src_tab2 = st.tabs(["📁 영상 파일 올리기 (권장)", "🔗 URL로 받기"])

            # ── 로컬 영상 (① 탭에서 올린 것 + 여기서 추가) ──
            with src_tab1:
                # ① 입력 탭에서 올려둔 영상을 그대로 이어받습니다
                from_tab1 = [
                    p for p in st.session_state.get('source_videos', [])
                    if os.path.exists(p)
                ]
                if from_tab1:
                    st.success(f"✅ ① 입력 탭에서 올린 영상 {len(from_tab1)}개를 씁니다")
                    for p in from_tab1[:5]:
                        st.caption(f"• {os.path.basename(p)}")
                    cut_local_paths.extend(from_tab1)

                st.caption(
                    "여기서 더 추가할 수도 있습니다. "
                    "알리·1688·타오바오 공급사 영상이나 직접 찍은 영상은 저작권 문제가 없습니다."
                )
                up_videos = st.file_uploader(
                    "영상 파일 추가 (여러 개 가능)",
                    type=['mp4', 'mov', 'webm', 'mkv'],
                    accept_multiple_files=True,
                    key="cut_video_upload",
                )
                if up_videos:
                    src_dir = os.path.join("outputs", "source_videos")
                    Path(src_dir).mkdir(parents=True, exist_ok=True)
                    added = []
                    for uv in up_videos:
                        dst = os.path.join(src_dir, uv.name)
                        if not os.path.exists(dst) or os.path.getsize(dst) != uv.size:
                            with open(dst, 'wb') as f:
                                f.write(uv.getbuffer())
                        if dst not in cut_local_paths:
                            cut_local_paths.append(dst)
                            added.append(dst)
                    if added:
                        st.success(f"✅ {len(added)}개 추가됨 (총 {len(cut_local_paths)}개)")

            # ── URL 입력 ──────────────────────────
            with src_tab2:
                st.warning(
                    "⚠️ **저작권 주의** — 틱톡·유튜브 등 남의 영상을 잘라 쓰면 침해가 됩니다. "
                    "본인 영상이거나 사용 허락을 받은 경우에만 쓰세요."
                )
                default_urls = "\n".join(st.session_state.get('ref_urls', []))
                cut_urls_text = st.text_area(
                    "영상 URL (한 줄에 하나씩)",
                    value=default_urls,
                    height=100,
                    placeholder="https://www.tiktok.com/@username/video/1234567890",
                    help="① 입력 탭에 넣은 URL이 자동으로 채워집니다",
                )
                cut_urls = [u.strip() for u in cut_urls_text.strip().split('\n') if u.strip()]

            # ── 상품 이미지 (있으면 자동으로 섞임) ─
            st.markdown("**🖼️ 상품 이미지**")
            use_imgs_ui = []

            # 영상에서 뽑은 프레임은 분석용이므로 정지컷으로 쓰지 않습니다
            # (같은 영상의 한 장면이 멈춰 있는 것이라 넣어봐야 의미가 없습니다)
            imgs_are_frames = st.session_state.get('images_from_video', False)

            if imgs and not imgs_are_frames:
                use_imgs_ui = imgs
                st.caption(f"① 입력 탭의 상품 이미지 {len(imgs)}장을 함께 씁니다.")
            elif imgs_are_frames:
                st.caption(
                    "영상에서 뽑은 화면은 분석용이라 정지컷으로 넣지 않습니다. "
                    "따로 상품 이미지를 올리면 여기서 섞어 씁니다."
                )
            else:
                st.caption("① 입력 탭에서 상품 이미지를 올리면 함께 쓸 수 있습니다.")

            # ── 원본 자막 지우기 (중국어 등) ───────
            if cut_local_paths:
                st.markdown("**🧽 원본에 박힌 자막 지우기**")
                st.caption(
                    "알리·타오바오 영상에 중국어 자막이 박혀 있으면 여기서 지웁니다. "
                    "주변 픽셀로 메우는 방식이라 배경이 단순할수록 깨끗합니다."
                )

                from modules.clip_editor import preview_delogo, get_video_size

                DEFAULT_BOX = {'x': 1, 'y': 82, 'w': 98, 'h': 16}

                _boxes = st.session_state.setdefault('delogo_boxes', {})
                _seen = st.session_state.setdefault('_delogo_seen', set())

                # ── 자막 위치 자동 찾기 (OCR) ──────────
                st.caption(
                    "**🔎 자동 찾기**를 누르면 영상마다 자막이 어디 있는지 OCR로 찾아 "
                    "그 영역만 정확히 지웁니다. 상단·중앙·하단 어디든 찾습니다."
                )
                _ac1, _ac2 = st.columns([2, 1])
                with _ac1:
                    if st.button("🔎 자막 위치 자동 찾기", use_container_width=True, type="primary"):
                        try:
                            from modules.subtitle_detect import detect_subtitle_bands
                            _prog = st.progress(0.0, text="준비 중...")
                            _found = 0
                            for _i, _vp in enumerate(cut_local_paths):
                                _prog.progress(
                                    _i / max(len(cut_local_paths), 1),
                                    text=f"{os.path.basename(_vp)[:28]} 분석 중...",
                                )
                                _bands = detect_subtitle_bands(_vp, frames=14, gpu=False)
                                if _bands is None:
                                    st.warning(
                                        "EasyOCR이 없어 자동 찾기를 못 합니다. "
                                        "`pip install easyocr` 후 다시 시도하세요."
                                    )
                                    break
                                if _bands:
                                    # 가장 확실한 영역 하나를 씁니다
                                    # 슬라이더가 정수만 받으므로 int로 맞춥니다
                                    # (바깥쪽으로 넉넉히 반올림해서 자막이 삐져나오지 않게)
                                    _best = max(_bands, key=lambda b: b['votes'])
                                    _bx = max(0, int(_best['x']))
                                    _by = max(0, int(_best['y']))
                                    _boxes[_vp] = {
                                        'x': _bx,
                                        'y': _by,
                                        'w': min(100 - _bx, int(_best['x'] + _best['w'] + 0.999) - _bx),
                                        'h': min(100 - _by, int(_best['y'] + _best['h'] + 0.999) - _by),
                                    }
                                    _seen.add(_vp)
                                    _found += 1
                                else:
                                    _boxes.pop(_vp, None)
                                    _seen.add(_vp)
                            _prog.empty()
                            st.success(
                                f"✅ 영상 {len(cut_local_paths)}개 중 {_found}개에서 자막을 찾았습니다"
                            )
                            st.rerun()
                        except Exception as _e:
                            st.error(f"자동 찾기 실패: {_e}")
                with _ac2:
                    st.caption("영상당 30~60초")

                # 자동 찾기를 안 돌린 새 영상은 기본값(하단)으로 켜둡니다
                for _vp in cut_local_paths:
                    if _vp not in _seen:
                        _seen.add(_vp)
                        _boxes.setdefault(_vp, dict(DEFAULT_BOX))

                for _vp in cut_local_paths:
                    _nm = os.path.basename(_vp)
                    with st.expander(f"✂️ {_nm[:40]}"):
                        _cur = _boxes.get(_vp, dict(DEFAULT_BOX))
                        _on = st.checkbox(
                            "이 영상의 자막 지우기",
                            value=_vp in _boxes,
                            key=f"dl_on_{_nm}",
                        )

                        if _on:
                            st.caption(
                                "기본값은 하단 82~98%입니다. 자막이 다른 곳에 있으면 "
                                "아래 미리보기를 보며 맞추세요."
                            )
                            # 슬라이더는 값과 범위의 자료형이 같아야 합니다
                            def _iv(key, lo, hi, default):
                                try:
                                    return max(lo, min(hi, int(round(float(_cur.get(key, default))))))
                                except (TypeError, ValueError):
                                    return default

                            _pc1, _pc2 = st.columns(2)
                            with _pc1:
                                _x = st.slider("좌측 시작 %", 0, 95, _iv('x', 0, 95, 1), key=f"dl_x_{_nm}")
                                _w = st.slider("가로 폭 %", 5, 100, _iv('w', 5, 100, 98), key=f"dl_w_{_nm}")
                            with _pc2:
                                _y = st.slider("위에서 %", 0, 95, _iv('y', 0, 95, 82), key=f"dl_y_{_nm}")
                                _h = st.slider("세로 높이 %", 3, 50, _iv('h', 3, 50, 16), key=f"dl_h_{_nm}")

                            _box = {'x': _x, 'y': _y, 'w': _w, 'h': _h}
                            _boxes[_vp] = _box

                            _bc1, _bc2 = st.columns(2)
                            try:
                                _before = preview_delogo(_vp, None, width=300)
                                _after = preview_delogo(_vp, _box, width=300)
                                if _before:
                                    _bc1.caption("지우기 전")
                                    _bc1.image(_before, use_container_width=True)
                                if _after:
                                    _bc2.caption("지운 후")
                                    _bc2.image(_after, use_container_width=True)
                            except Exception as _e:
                                st.warning(f"미리보기 실패: {_e}")

                            _vw, _vh = get_video_size(_vp)
                            st.caption(
                                f"원본 {_vw}×{_vh} · 지우는 영역 "
                                f"{int(_vw*_x/100)},{int(_vh*_y/100)} "
                                f"크기 {int(_vw*_w/100)}×{int(_vh*_h/100)}"
                            )
                        else:
                            _boxes.pop(_vp, None)

                if _boxes:
                    st.success(f"✅ 영상 {len(_boxes)}개에서 자막을 지웁니다")

            # ── 장면 매칭 방식 ─────────────────────
            st.markdown("**🎯 장면 고르는 방식**")
            smart_match = st.checkbox(
                "자막 내용에 맞는 장면을 AI가 골라 배치 (권장)",
                value=True,
                help="끄면 장면을 순서대로만 배치합니다",
            )
            if smart_match:
                if anthropic_key:
                    st.caption(
                        "각 장면을 Claude가 보고 자막 내용과 맞는 화면을 고릅니다. "
                        "(Anthropic 크레딧이 조금 듭니다)"
                    )
                else:
                    st.warning("⚠️ Anthropic API 키가 없어 순서대로 배치됩니다.")
            else:
                st.caption("장면을 순서대로 배치합니다. 내용과 화면이 안 맞을 수 있습니다.")

            # ── 무엇으로 만들지 자동 판정 ──────────
            n_vid = len(cut_local_paths) + len(cut_urls)
            n_img = len(use_imgs_ui)

            if n_vid and n_img:
                st.success(f"🎬 영상 {n_vid}개 + 🖼️ 이미지 {n_img}장 → **섞어서** 편집합니다")
                img_every = st.slider(
                    "몇 번째 컷마다 이미지를 넣을까요",
                    min_value=2, max_value=6, value=3,
                    help="3이면 영상 2컷 뒤에 이미지 1컷",
                )
            elif n_vid:
                st.success(f"🎬 영상 {n_vid}개 → **영상만으로** 편집합니다")
            elif n_img:
                st.success(f"🖼️ 이미지 {n_img}장 → **이미지만으로** 편집합니다")
            else:
                st.info("영상이나 이미지 중 하나는 있어야 합니다.")

        st.markdown("---")

        # ── 컷편집 실행 ───────────────────────────────
        if mode == "컷편집 (영상·이미지)":
            col_btn = st.columns([1, 2, 1])[1]
            with col_btn:
                if st.button("✂️ 컷편집 영상 만들기", use_container_width=True, type="primary"):
                    use_imgs = use_imgs_ui

                    if not cut_local_paths and not cut_urls and not use_imgs:
                        st.error("❌ 영상 파일이나 URL, 또는 상품 이미지 중 하나는 필요합니다.")
                    elif not srt_p or not os.path.exists(srt_p):
                        st.error("❌ 자막(SRT)이 없습니다. '④ 음성·자막' 탭에서 먼저 생성해 주세요.")
                    else:
                        from modules.clip_editor import auto_cut_edit

                        bar = st.progress(0.0, text="준비 중...")

                        def _prog(cur, total, msg):
                            bar.progress(min(cur / max(total, 1), 1.0), text=msg)

                        try:
                            out_mp4 = os.path.join(
                                "outputs",
                                f"cut_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                            )
                            result = auto_cut_edit(
                                audio_path=audio_p,
                                srt_path=srt_p,
                                output_path=out_mp4,
                                local_videos=cut_local_paths,
                                reference_urls=cut_urls,
                                image_paths=use_imgs,
                                image_every=img_every,
                                anthropic_key=anthropic_key,
                                smart_match=smart_match,
                                delogo_boxes=st.session_state.get('delogo_boxes'),
                                progress_cb=_prog,
                            )
                            bar.empty()
                            st.session_state['video_path'] = result['video_path']
                            st.session_state['cut_plan'] = result['plan']
                            st.session_state['cut_ai_matched'] = result.get('ai_matched', False)
                            st.session_state['step'] = 5
                            st.rerun()
                        except Exception as e:
                            bar.empty()
                            st.error(f"❌ 컷편집 실패: {e}")

        # ── 슬라이드쇼 실행 ───────────────────────────
        else:
            col_btn = st.columns([1, 2, 1])[1]
            with col_btn:
                if st.button("🎬 MP4 영상 만들기", use_container_width=True, type="primary"):
                    if not imgs:
                        st.error("❌ 상품 이미지가 없습니다. '① 입력' 탭에서 업로드해 주세요.")
                    else:
                        with st.spinner("🎬 9:16 쇼츠 영상 렌더링 중... (보통 10~30초)"):
                            try:
                                from modules.video_renderer import (
                                    create_product_slideshow,
                                    render_with_ffmpeg_direct,
                                )
                                out_mp4 = os.path.join(
                                    "outputs",
                                    f"shorts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                                )
                                # FFmpeg 직접 호출이 훨씬 빠르므로 우선 시도합니다.
                                # (MoviePy는 줌 효과가 있지만 같은 작업에 10배 이상 걸립니다)
                                try:
                                    video_path = render_with_ffmpeg_direct(
                                        image_paths=imgs,
                                        audio_path=audio_p,
                                        output_path=out_mp4,
                                        srt_path=srt_p,
                                    )
                                except Exception as e_ff:
                                    logger.warning(f"FFmpeg 렌더링 실패, MoviePy로 대체: {e_ff}")
                                    video_path = create_product_slideshow(
                                        image_paths=imgs,
                                        audio_path=audio_p,
                                        output_path=out_mp4,
                                        srt_path=srt_p,
                                    )
                                st.session_state['video_path'] = video_path
                                st.session_state['step'] = 5
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ 영상 생성 실패: {e}")

        # ── 결과: 미리보기 + MP4 다운로드 ──────────────
        vp = st.session_state.get('video_path')
        if vp and os.path.exists(vp):
            st.markdown("---")
            st.success("✅ 쇼츠 영상 완성!")

            v1, v2 = st.columns([1, 1])
            with v1:
                st.markdown("#### 👀 미리보기")
                with open(vp, 'rb') as f:
                    st.video(f.read())

            with v2:
                st.markdown("#### ⬇️ 다운로드")
                size_mb = os.path.getsize(vp) / (1024 * 1024)
                st.caption(f"1080×1920 · 30fps · {size_mb:.1f} MB")

                with open(vp, 'rb') as f:
                    st.download_button(
                        "⬇️ MP4 영상 다운로드",
                        data=f.read(),
                        file_name=os.path.basename(vp),
                        mime="video/mp4",
                        use_container_width=True,
                        type="primary",
                    )

                st.caption(f"📁 저장 위치: `{vp}`")

                st.markdown("---")
                st.markdown("**바로 업로드 가능**")
                st.caption(
                    "YouTube 쇼츠 · 인스타 릴스 · 틱톡 규격(9:16, 1080×1920)에 "
                    "맞춰져 있어 그대로 올리시면 됩니다."
                )

            # ── 컷 구성표 (컷편집으로 만든 경우) ───────
            cut_plan = st.session_state.get('cut_plan')
            if cut_plan:
                st.markdown("---")
                _ai = st.session_state.get('cut_ai_matched')
                _label = "🎯 AI가 자막에 맞춰 배치" if _ai else "↔️ 순서대로 배치"
                with st.expander(f"✂️ 컷 구성 보기 ({len(cut_plan)}개 클립 · {_label})"):
                    if not _ai:
                        st.caption(
                            "AI 매칭이 적용되지 않았습니다 "
                            "(크레딧 부족이거나 옵션을 끈 경우). 내용과 화면이 안 맞을 수 있습니다."
                        )
                    rows = []
                    _t = 0.0
                    for c in cut_plan:
                        is_img = c.get('type') == 'image'
                        rows.append({
                            "순서": c['sub_index'],
                            "위치": f"{_t:.1f}s",
                            "종류": "🖼️ 이미지" if is_img else "🎬 영상",
                            "출처": os.path.basename(c['src']),
                            "원본 구간": "-" if is_img else f"{c['src_start']:.1f}s",
                            "길이": f"{c['dur']:.1f}s",
                            "자막": c['text'].replace('\n', ' ')[:30],
                        })
                        _t += c['dur']
                    st.dataframe(rows, use_container_width=True, hide_index=True)

            # ── 편집용 원본 파일 (선택) ────────────────
            st.markdown("---")
            with st.expander("✂️ CapCut에서 직접 편집하고 싶다면 (원본 파일 ZIP)"):
                st.caption(
                    "음성·자막·이미지·대본 원본을 폴더 구조로 묶어 내려받습니다. "
                    "영상을 직접 손보고 싶을 때만 쓰세요."
                )

                if st.button("📦 편집용 ZIP 만들기", use_container_width=True):
                    with st.spinner("📦 에셋 패키징 중..."):
                        try:
                            zip_path = create_project_package(
                                project_name=st.session_state.get('product_name', '상품'),
                                audio_path=audio_p,
                                image_paths=imgs,
                                srt_path=srt_p,
                                ass_path=ass_p,
                                script_text=script_txt,
                                video_path=vp,
                            )
                            st.session_state['zip_path'] = zip_path
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ 패키징 오류: {e}")

                zp = st.session_state.get('zip_path')
                if zp and os.path.exists(zp):
                    try:
                        summary = get_package_summary(zp)
                        st.caption(f"파일 {summary['file_count']}개 · {summary['size_mb']} MB")
                    except Exception:
                        pass

                    with open(zp, 'rb') as f:
                        st.download_button(
                            "⬇️ ZIP 다운로드",
                            data=f.read(),
                            file_name=os.path.basename(zp),
                            mime="application/zip",
                            use_container_width=True,
                        )

                    st.markdown("""
**CapCut 편집 순서**
1. ZIP 압축 해제 → CapCut **새 프로젝트**
2. `images/` 이미지를 타임라인에 추가
3. `audio/` 음성을 오디오 트랙에 추가
4. `subtitles/*.srt` 를 **자막 → 자막 가져오기**
5. 9:16 (1080×1920, 30fps)로 내보내기
""")


# ── 푸터 ──────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<div style='text-align:center; opacity:0.6; font-size:0.85rem;'>"
    "🛍️ 쇼핑 쇼츠 자동화 v1.0 | Powered by Claude AI + Typecast TTS"
    "</div>",
    unsafe_allow_html=True,
)
