# ====================================================
# 모듈 3: 쇼핑 쇼츠 대본 생성기 (script_generator.py)
# 이미지 분석 결과 + 참고 영상 패턴을 바탕으로
# 구매 전환율을 극대화하는 쇼츠 대본을 생성합니다.
# ====================================================

import json
from loguru import logger
import anthropic


# ── 쇼핑 쇼츠 대본 구조 (업계 표준) ─────────────────
# 1. 후크(Hook)     0~3초   : 시청자를 멈추게 하는 강렬한 첫 문장
# 2. 공감(Empathy)  3~8초   : 시청자의 고통/욕망에 공감
# 3. 소개(Intro)    8~15초  : 상품 자연스럽게 등장
# 4. 혜택(Benefit)  15~40초: 핵심 기능/혜택 2~3가지 설명
# 5. CTA(Action)   40~60초 : 구매/저장/클릭 유도

SHORTS_STRUCTURE = {
    "hook": {"duration": "0~3초", "goal": "3초 안에 스크롤을 멈추게 하기"},
    "empathy": {"duration": "3~8초", "goal": "시청자의 공감 유발"},
    "intro": {"duration": "8~15초", "goal": "상품을 자연스럽게 소개"},
    "benefit": {"duration": "15~40초", "goal": "핵심 혜택 2~3가지 전달"},
    "cta": {"duration": "40~60초", "goal": "구매/저장/팔로우 유도"},
}

# ── 타겟별 말투 가이드 ────────────────────────────
TONE_GUIDES = {
    "5060 시니어": "따뜻하고 신뢰감 있는 말투. 건강, 편리함, 가성비 강조. 과도한 신조어 지양.",
    "2030 직장인": "공감형, 현실적 문제 해결 강조. 바쁜 일상, 가성비, 자기계발 키워드 활용.",
    "MZ 세대": "트렌디하고 솔직한 말투. 유머, 도파민 자극, SNS 공유 욕구 자극.",
    "육아맘": "공감과 신뢰 중심. 안전성, 편리함, 아이 행복 키워드 강조.",
    "운동/헬스": "에너지 넘치는 말투. 성과, 변화, 도전 키워드 강조.",
    "일반 소비자": "친근하고 자연스러운 일상 말투. 보편적 가치 강조.",
}


def build_script_prompt(
    image_analysis: dict,
    video_analysis: dict,
    target_audience: str,
    additional_info: str = "",
) -> str:
    """
    대본 생성용 프롬프트를 구성합니다.
    이미지 분석 + 참고 영상 패턴 + 타겟 정보를 종합합니다.
    """
    # 타겟별 말투 가이드 선택
    tone = TONE_GUIDES.get(target_audience, TONE_GUIDES["일반 소비자"])

    # 참고 영상에서 추출한 오프닝 후크 샘플
    sample_hooks = video_analysis.get('summary', {}).get('sample_hooks', [])
    hooks_text = "\n".join([f'  - "{h}"' for h in sample_hooks[:3]]) if sample_hooks else "  - 없음"

    # 참고 영상 CTA 샘플
    sample_ctas = video_analysis.get('summary', {}).get('sample_ctas', [])
    ctas_text = "\n".join([f'  - "{c}"' for c in sample_ctas[:3]]) if sample_ctas else "  - 없음"

    # 주요 후킹 패턴
    dominant_patterns = video_analysis.get('summary', {}).get('dominant_patterns', [])
    patterns_text = ", ".join(dominant_patterns) if dominant_patterns else "자유 형식"

    # 상품 분석 정보
    product = image_analysis if isinstance(image_analysis, dict) else {}
    product_name = product.get('product_name', '상품')
    key_benefits = product.get('key_benefits', [])
    pain_points = product.get('target_pain_points', [])
    hook_angles = product.get('hook_angles', [])
    usp = product.get('usp', '')
    emotional_keywords = product.get('emotional_keywords', [])

    prompt = f"""당신은 대한민국 최고의 쇼핑 쇼츠 카피라이터입니다.
수백만 조회수를 기록하는 쇼핑 쇼츠 대본을 전문으로 작성합니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 상품 정보 (이미지 분석 결과)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 상품명: {product_name}
- 핵심 혜택: {', '.join(key_benefits[:3]) if key_benefits else '미상'}
- 고객 고통 포인트: {', '.join(pain_points[:2]) if pain_points else '미상'}
- 차별화 포인트: {usp}
- 감성 키워드: {', '.join(emotional_keywords[:5]) if emotional_keywords else '미상'}
- 후킹 앵글 아이디어: {', '.join(hook_angles[:2]) if hook_angles else '미상'}
{f'- 추가 정보: {additional_info}' if additional_info else ''}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎬 참고 영상 분석 결과
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 주요 후킹 패턴: {patterns_text}
- 오프닝 후크 예시:
{hooks_text}
- CTA 예시:
{ctas_text}
- 평균 영상 길이: {video_analysis.get('summary', {}).get('avg_duration_sec', 45)}초

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👥 타겟 고객 & 말투 가이드
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 타겟: {target_audience}
- 말투 가이드: {tone}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📝 대본 작성 규칙
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 총 길이: 45~60초 분량 (읽기 속도 기준 약 180~220자)
2. 구조: Hook(0~3초) → Empathy(3~8초) → Intro(8~15초) → Benefit(15~40초) → CTA(40~60초)
3. 첫 문장(후크)은 반드시 시청자가 스크롤을 멈추게 해야 합니다
4. 자연스러운 구어체로 작성 (읽는 글이 아닌 말하는 글)
5. 문장은 짧고 임팩트 있게 (한 문장 15자 이하 권장)
6. 상품명은 자연스럽게 1~2번만 언급
7. 숫자, 구체적 사실로 신뢰도 높이기

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 출력 형식 (JSON)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
아래 JSON 형식으로 **3가지 버전**의 대본을 작성해 주세요.
각 버전은 다른 후킹 앵글을 사용해야 합니다.

```json
{{
  "scripts": [
    {{
      "version": "A",
      "hook_type": "후킹 유형 (예: 질문형, 공감형, 숫자형 등)",
      "hook_angle": "이 버전의 후킹 앵글 설명",
      "script": {{
        "hook": "후크 대사 (0~3초)",
        "empathy": "공감 대사 (3~8초)",
        "intro": "상품 소개 대사 (8~15초)",
        "benefit": "혜택 설명 대사 (15~40초)",
        "cta": "CTA 대사 (40~60초)"
      }},
      "full_script": "위 섹션을 자연스럽게 이어붙인 전체 대본",
      "estimated_duration_sec": 예상 초수,
      "key_emotion": "핵심 감성 키워드"
    }},
    ...
  ],
  "recommended_version": "A",
  "recommendation_reason": "추천 이유"
}}
```"""

    return prompt


def generate_scripts(
    image_analysis: dict,
    video_analysis: dict,
    target_audience: str,
    api_key: str,
    additional_info: str = "",
    model: str = "claude-sonnet-5"
) -> dict:
    """
    Claude API를 호출하여 쇼핑 쇼츠 대본 3가지 버전을 생성합니다.

    Args:
        image_analysis: image_analyzer.py의 분석 결과
        video_analysis: video_analyzer.py의 분석 결과
        target_audience: 타겟 고객 설명
        api_key: Anthropic API 키
        additional_info: 추가 상품 정보 (선택)
        model: Claude 모델 ID

    Returns:
        생성된 대본 딕셔너리
    """
    client = anthropic.Anthropic(api_key=api_key)

    # 프롬프트 구성
    prompt = build_script_prompt(
        image_analysis=image_analysis,
        video_analysis=video_analysis,
        target_audience=target_audience,
        additional_info=additional_info,
    )

    logger.info("대본 생성 중... Claude API 호출")

    try:
        response = client.messages.create(
            model=model,
            # 대본 3버전에 2500토큰이면 충분합니다 (4000 → 2500, 출력 요금 34% 절감)
            max_tokens=2500,
            system="""당신은 대한민국 최고의 쇼핑 쇼츠 카피라이터입니다.
유튜브 쇼츠와 인스타그램 릴스에서 구매 전환율을 높이는
감성적이고 임팩트 있는 대본 작성에 특화되어 있습니다.
항상 JSON 형식으로만 응답합니다.""",
            messages=[{"role": "user", "content": prompt}]
        )

        raw_text = response.content[0].text
        logger.info("대본 생성 완료")

        # JSON 파싱
        import re
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_text)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = raw_text

        scripts_data = json.loads(json_str)

        try:
            from modules.cost_tracker import record
            record("대본 생성", model, response.usage)
        except Exception:
            pass

        return {
            "success": True,
            "scripts_data": scripts_data,
            "raw_response": raw_text,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        }

    except json.JSONDecodeError as e:
        logger.warning(f"JSON 파싱 실패, 원본 텍스트 반환: {e}")
        return {
            "success": True,
            "scripts_data": {"raw_text": raw_text},
            "raw_response": raw_text,
            "usage": {}
        }
    except anthropic.AuthenticationError:
        raise ValueError("❌ Anthropic API 키가 올바르지 않습니다.")
    except anthropic.RateLimitError:
        raise RuntimeError("❌ API 요청 한도 초과. 잠시 후 다시 시도해 주세요.")
    except Exception as e:
        err = str(e)
        if "credit balance is too low" in err or "billing" in err.lower():
            raise RuntimeError(
                "💳 Anthropic 크레딧 부족\n"
                "→ console.anthropic.com/settings/billing 에서 충전 후 다시 시도하세요."
            )
        raise RuntimeError(f"❌ 대본 생성 중 오류: {e}")


def generate_test_scripts(target_audience: str = "일반 소비자") -> dict:
    """API 크레딧이 없을 때 쓰는 테스트용 샘플 대본입니다."""

    def _mk(version, hook_type, angle, emotion, dur, hook, empathy, intro, benefit, cta):
        return {
            "version": version,
            "hook_type": hook_type,
            "hook_angle": angle,
            "key_emotion": emotion,
            "estimated_duration_sec": dur,
            "script": {
                "hook": hook,
                "empathy": empathy,
                "intro": intro,
                "benefit": benefit,
                "cta": cta,
            },
            "full_script": "\n".join([hook, empathy, intro, benefit, cta]),
        }

    product = "스마트 창문 청소 로봇"

    return {
        "success": True,
        "scripts_data": {
            "scripts": [
                _mk(
                    "A", "공감형", "청소 노동의 고단함에 공감", "안도감", 45,
                    "창문 닦다가 팔 아팔던 적 있죠? 저도 그랬어요.",
                    "매주 주말마다 창문 붙잡고 씨름했는데, 솔직히 너무 힘들었어요.",
                    "그러다 이 " + product + "을 알게 됐어요.",
                    "유리에 붙여두기만 하면 알아서 닦아요. 리모컨으로 조작되고, 배터리는 4시간 갑니다.",
                    "지금 링크 눌러서 확인해보세요!",
                ),
                _mk(
                    "B", "숫자형", "시간 절약을 수치로 설득", "효율", 40,
                    "청소 시간 90% 줄이는 방법, 30초만 보세요.",
                    "주말 2시간씩 쓰던 창문 청소가 10분으로 끝났어요.",
                    product + ", 한 번 붙여두면 끝이에요.",
                    "청소 모드 3가지, 고층에서도 안전하게, 물자국 없이 깔끔하게.",
                    "품절 전에 아래 링크 확인하세요!",
                ),
                _mk(
                    "C", "호기심형", "믿기 힘든 기능으로 시선 고정", "놀라움", 42,
                    "이게 진짜 혼자서 창문을 닦는다고요?",
                    "처음엔 저도 안 믿었는데, 직접 써보고 생각이 바뀜어요.",
                    product + "은 AI가 경로를 계산해서 한 칸도 안 놓쳐요.",
                    "자동 경로 계산, 낙하 방지 센서, 초극세사 패드까지 들어있어요.",
                    "댓글에 '정보' 남겨주시면 링크 보내드릴게요!",
                ),
            ],
            "recommended_version": "A",
            "recommendation_reason": (
                "⚠️ 테스트 모드 샘플입니다 — 실제 상품 이미지 분석이 반영되지 않았습니다. "
                "Anthropic 크레딧 충전 후 '다시 생성'을 눌러 실제 대본을 만드세요."
            ),
        },
        "usage": {},
        "is_test": True,
    }


def get_full_script(scripts_data: dict, version: str = None) -> str:
    """
    생성된 대본 중 특정 버전의 전체 대본 텍스트를 반환합니다.
    version이 None이면 추천 버전을 사용합니다.
    """
    if not isinstance(scripts_data, dict):
        return ""

    if "raw_text" in scripts_data:
        return scripts_data.get("raw_text", "")

    scripts = scripts_data.get("scripts", [])
    if not scripts:
        return ""

    target = version or scripts_data.get("recommended_version")
    if target:
        for s in scripts:
            if str(s.get("version", "")) == str(target):
                return s.get("full_script", "")

    return scripts[0].get("full_script", "")
