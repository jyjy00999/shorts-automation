# ====================================================
# 모듈 2: 상품 이미지 분석기 (image_analyzer.py)
# Claude Vision API로 상품 이미지를 분석하여
# 핵심 특징과 마케팅 소구점을 텍스트로 추출합니다.
# ====================================================

import base64
import json
from pathlib import Path
from typing import Union
from io import BytesIO
from loguru import logger

import anthropic
from PIL import Image


# ── 비용 관련 설정 ────────────────────────────────
# 이미지 토큰 ≈ 가로×세로÷750 이라 해상도와 장수가 요금을 좌우합니다.
MAX_IMAGE_PX = 768      # 1568 → 768 (토큰 약 1/4)
MAX_IMAGES = 4          # 10 → 4 (상품 파악엔 4장이면 충분)


def image_to_base64(image_source: Union[str, bytes, BytesIO]) -> tuple[str, str]:
    """
    이미지를 Base64 문자열로 변환합니다.

    Args:
        image_source: 파일 경로(str), bytes, 또는 BytesIO 객체

    Returns:
        (base64_string, media_type) 튜플
    """
    if isinstance(image_source, str):
        # 파일 경로인 경우
        with open(image_source, 'rb') as f:
            data = f.read()
        suffix = Path(image_source).suffix.lower()
    elif isinstance(image_source, BytesIO):
        data = image_source.getvalue()
        suffix = '.jpg'  # 기본값
    else:
        data = image_source
        suffix = '.jpg'

    # MIME 타입 결정
    media_type_map = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
    }
    media_type = media_type_map.get(suffix, 'image/jpeg')

    # Pillow로 이미지 최적화
    # 768px면 상품 식별에 충분하고, 1568px 대비 토큰이 1/4로 줄어듭니다.
    # (이미지 토큰 ≈ 가로×세로÷750)
    img = Image.open(BytesIO(data))
    if max(img.size) > MAX_IMAGE_PX:
        img.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX), Image.LANCZOS)
        buffer = BytesIO()
        fmt = 'JPEG' if media_type == 'image/jpeg' else 'PNG'
        img.save(buffer, format=fmt, quality=85)
        data = buffer.getvalue()

    b64 = base64.standard_b64encode(data).decode('utf-8')
    return b64, media_type


def analyze_product_images(
    images: list[Union[str, bytes, BytesIO]],
    api_key: str,
    target_audience: str = "일반 소비자",
    model: str = "claude-sonnet-5"  # 최신 Claude 모델
) -> dict:
    """
    상품 이미지들을 Claude Vision으로 분석하여 마케팅 인사이트를 추출합니다.

    Args:
        images: 이미지 파일 경로 또는 bytes 리스트
        api_key: Anthropic API 키
        target_audience: 타겟 고객 설명 (예: "5060 시니어", "2030 직장인")
        model: 사용할 Claude 모델 ID

    Returns:
        상품 분석 결과 딕셔너리
    """
    if not images:
        raise ValueError("분석할 이미지가 없습니다.")

    client = anthropic.Anthropic(api_key=api_key)

    # ── 멀티 이미지 메시지 구성 ──────────────────────
    content = []

    # 분석할 이미지들을 content에 추가
    for i, img_source in enumerate(images[:MAX_IMAGES]):
        try:
            b64_data, media_type = image_to_base64(img_source)
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64_data,
                }
            })
            logger.info(f"이미지 {i+1} 변환 완료")
        except Exception as e:
            logger.warning(f"이미지 {i+1} 변환 실패: {e}")
            continue

    if not content:
        raise RuntimeError("변환 가능한 이미지가 없습니다.")

    # ── 분석 프롬프트 ──────────────────────────────
    analysis_prompt = f"""당신은 쇼핑 쇼츠 전문 마케터입니다.
제공된 상품 이미지들을 분석하여 아래 항목을 JSON 형식으로 반환하세요.

타겟 고객: {target_audience}

분석 항목:
1. product_name: 상품명 추정 (간결하게)
2. category: 상품 카테고리 (예: 뷰티, 패션, 주방용품, 건강식품 등)
3. design_features: 디자인 특징 리스트 (색상, 형태, 소재, 패키지 등) - 최대 5개
4. key_benefits: 핵심 혜택/기능 리스트 (이 상품이 해결하는 문제) - 최대 5개
5. target_pain_points: 타겟 고객의 고통 포인트 (이 상품이 필요한 이유) - 최대 3개
6. usp: 경쟁 제품 대비 차별화 포인트 (Unique Selling Point) - 1~2문장
7. emotional_keywords: 감성적 키워드 리스트 (예: 편안함, 자신감, 새로움 등) - 최대 5개
8. hook_angles: 쇼츠 영상 후킹에 활용 가능한 앵글 리스트 - 최대 3개
   (예: "이거 쓰고 나서 남편이 변했어요", "직장인들이 몰래 사는 이유")
9. price_perception: 예상 가격대 (저가/중가/고가/프리미엄)
10. visual_highlights: 영상에서 강조해야 할 시각적 포인트 - 최대 3개

반드시 JSON 형식으로만 응답하고, 한국어로 작성하세요.
```json
{{
  "product_name": "...",
  "category": "...",
  ...
}}
```"""

    content.append({
        "type": "text",
        "text": analysis_prompt
    })

    # ── API 호출 ──────────────────────────────────
    try:
        logger.info(f"Claude Vision API 호출 중... (이미지 {len(content)-1}장)")
        response = client.messages.create(
            model=model,
            max_tokens=2000,
            messages=[{"role": "user", "content": content}]
        )

        raw_text = response.content[0].text
        logger.info("이미지 분석 완료")

        # JSON 파싱 (마크다운 코드 블록 제거)
        json_match = __import__('re').search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_text)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = raw_text

        analysis = json.loads(json_str)
        analysis['image_count'] = len(content) - 1  # 분석된 이미지 수
        analysis['raw_response'] = raw_text

        try:
            from modules.cost_tracker import record
            record("이미지 분석", model, response.usage)
        except Exception:
            pass

        return {
            "success": True,
            "analysis": analysis,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        }

    except json.JSONDecodeError as e:
        logger.error(f"JSON 파싱 오류: {e}")
        # JSON 파싱 실패 시 원본 텍스트 반환
        return {
            "success": True,
            "analysis": {"raw_text": raw_text, "parse_error": str(e)},
            "usage": {}
        }
    except anthropic.AuthenticationError:
        raise ValueError("❌ Anthropic API 키가 올바르지 않습니다.")
    except anthropic.RateLimitError:
        raise RuntimeError("❌ API 요청 한도 초과. 잠시 후 다시 시도해 주세요.")
    except anthropic.BadRequestError as e:
        raise RuntimeError(f"❌ 이미지 형식 오류: {e}")
    except Exception as e:
        raise RuntimeError(f"❌ 이미지 분석 중 오류: {e}")


def format_analysis_for_display(analysis: dict) -> str:
    """분석 결과를 읽기 좋은 마크다운 형식으로 변환합니다."""
    if 'raw_text' in analysis:
        return analysis['raw_text']

    lines = [
        f"## 🛍️ {analysis.get('product_name', '상품명 미상')}",
        f"**카테고리:** {analysis.get('category', '-')}",
        f"**가격대:** {analysis.get('price_perception', '-')}",
        "",
        "### ✨ 디자인 특징",
        *[f"- {f}" for f in analysis.get('design_features', [])],
        "",
        "### 💡 핵심 혜택",
        *[f"- {b}" for b in analysis.get('key_benefits', [])],
        "",
        "### 🎯 타겟 고통 포인트",
        *[f"- {p}" for p in analysis.get('target_pain_points', [])],
        "",
        "### 🏆 차별화 포인트 (USP)",
        analysis.get('usp', '-'),
        "",
        "### 🎬 후킹 앵글 아이디어",
        *[f"- {h}" for h in analysis.get('hook_angles', [])],
    ]
    return "\n".join(lines)


# ── 직접 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    # 테스트용 이미지 경로 (실제 이미지로 교체)
    test_image_path = "test_product.jpg"

    if not os.path.exists(test_image_path):
        print("테스트 이미지 파일이 없습니다. 'test_product.jpg'를 준비해 주세요.")
    else:
        result = analyze_product_images(
            images=[test_image_path],
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            target_audience="2030 직장인 여성"
        )
        print(json.dumps(result['analysis'], ensure_ascii=False, indent=2))
