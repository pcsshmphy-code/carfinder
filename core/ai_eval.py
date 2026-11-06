"""
core/ai_eval.py — Claude API 평가 모듈
수집된 매물 상위 N건을 Claude에게 전달해 자연어 평가·추천 코멘트 획득
"""
import os
import re
import json
import logging
from typing import List, Optional, Tuple
import anthropic

from core.schema import CarListing
from config import ANTHROPIC_MODEL, AI_EVAL_ENABLED

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> str:
    """Claude 응답에서 JSON 본문만 추출 (```json 코드펜스/잡텍스트 제거)"""
    if not text:
        return ""
    text = text.strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    # 첫 '{' 부터 마지막 '}' 까지
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


def build_prompt(listings: List[CarListing], user_profile: dict, model_label: str = "이 차종") -> str:
    """Claude에게 전달할 프롬프트 구성. model_label: 검색 차종(예: 'CLS-클래스', '5시리즈')."""
    cars_json = []
    for i, c in enumerate(listings):
        cars_json.append({
            "rank": i + 1,
            "platform": c.platform,
            "id": c.listing_id,
            "year": c.year,
            "model": f"{c.maker} {c.model} {c.trim}".strip(),
            "mileage_km": c.mileage_km,
            "price_manwon": c.price_manwon,
            "accident": "있음" if c.accident_history else "없음",
            "flooded": "있음" if c.flooded else "없음",
            "warranty": f"{c.warranty_months}개월" if c.warranty else "없음",
            "seller_type": c.seller_type,
            "region": c.region,
            "total_score": c.total_score,
            "url": c.source_url,
        })

    profile_str = "\n".join(f"- {k}: {v}" for k, v in user_profile.items())

    return f"""당신은 수입 중고차 전문 딜러입니다. 손님에게 매물을 간결하고 명확하게 브리핑하세요.

## 손님이 찾는 차
{profile_str}

## 추천 후보 (알고리즘 점수 상위 {len(listings)}대)
```json
{json.dumps(cars_json, ensure_ascii=False, indent=2)}
```

## 코멘트 작성 규칙 (매우 중요)
- **간결한 전문가 메모체**로 쓰세요. 핵심만 짧게, 군더더기 없이.
- 형식: 「조건/상태 요약 → 확인할 점 또는 권장사항」. 한 코멘트는 1~2문장으로 끝내세요.
- 문장은 "~권장.", "~확인 필수.", "~조건 충족.", "~주의." 처럼 명료하게 맺으세요.
- 항상 **완결된 문장**으로. 중간에 끊거나 말이 어색하게 꼬이면 안 됩니다.
- 숫자(연식·주행거리·가격)를 근거로 장점과 리스크를 균형 있게 짚으세요.

### 좋은 예시 (이 톤과 길이로)
- "무사고에 옵션 구성 양호, 예산 내 조건 충족. 보증 잔여 여부 확인 후 구매 권장."
- "주행거리 대비 가격 합리적이나 보증 없음. 계약 전 엔진·미션 점검 권장."
- "연식 대비 주행 적고 컨디션 우수. 전 소유 이력(법인·렌트) 확인하면 무난."

### 나쁜 예시 (절대 금지)
- "거라실속 있는", "힘이 있을 지라도" — 말이 안 되는 비문/번역체
- "본 차량은 우수한 가치를 제공하는 것으로 사료됩니다" — 장황한 문어체
- 문장을 중간에 끊는 것 (예: "조금이라도 거리와 사고가")

## 차종 구매 팁 (model_tip)
'{model_label}' 차종에 **특화된** 구매 시 체크포인트를 1~2문장으로 쓰세요.
해당 차종의 알려진 엔진/변속기/전기계통/하체 등 약점이나 점검 포인트를 구체적으로 짚으세요.
(예시 방향 — 차종에 맞게: BMW 5시리즈면 N20/B48 엔진 타이밍체인·오일누유, 아우디 A6면 DSG/S트로닉 변속기 멜라트로닉, 벤츠면 에어서스·48V 시스템 등.)
일반론·다른 차종 이야기 금지. 반드시 '{model_label}'에 해당하는 내용만.

## 응답 형식
아래 JSON 형식으로만, 다른 설명 없이 JSON만 출력하세요:
{{
  "comments": {{
    "1": "1순위 매물 코멘트 (간결 메모체 1~2문장)",
    "2": "2순위 매물 코멘트"
  }},
  "top_pick": {{
    "rank": 1,
    "reason": "1순위로 추천하는 이유 (간결 1~2문장)"
  }},
  "warnings": ["특히 주의할 매물과 이유 (간결)"],
  "model_tip": "'{model_label}' 차종 특화 구매 체크포인트 (1~2문장)"
}}"""


def ai_evaluate(
    listings: List[CarListing],
    user_profile: dict,
    top_n: int = 10,
    model_label: str = "이 차종",
) -> Tuple[List[CarListing], Optional[str]]:
    """
    상위 N개 매물을 Claude API로 평가하고 ai_comment 필드를 채움

    Args:
        listings: 점수화된 매물 (total_score 내림차순 정렬 가정)
        user_profile: 구매자 조건 딕셔너리
        top_n: Claude에게 전달할 상위 매물 수 (토큰 절약)

    Returns:
        (listings, status)
        - status가 None이면 AI 평가 성공
        - status가 문자열이면 평가를 건너뛴 사유(사용자에게 표시할 안내 문구)
    """
    if not AI_EVAL_ENABLED:
        logger.info("AI 평가 비활성화됨 (AI_EVAL_ENABLED=False)")
        return listings, "AI 평가가 설정에서 비활성화되어 있습니다 (AI_EVAL_ENABLED=False)."

    if not listings:
        return listings, None

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.info("ANTHROPIC_API_KEY 미설정 — AI 평가 건너뜀")
        return listings, "ANTHROPIC_API_KEY가 설정되지 않았습니다."

    evaluate_targets = listings[:top_n]

    try:
        client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 자동 사용
        prompt = build_prompt(evaluate_targets, user_profile, model_label=model_label)
        logger.info(f"Claude API 호출 중 ({len(evaluate_targets)}건 평가, 차종='{model_label}')")

        # 매물 수에 비례해 토큰 한도 산정 (한국어 코멘트는 길어서 넉넉히 → 중간 끊김 방지)
        max_tokens = min(8192, 2500 + len(evaluate_targets) * 550)
        message = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=(
                "당신은 한국 수입 중고차 전문 딜러입니다. "
                "항상 간결하고 명료한 한국어 전문가 메모체로 답합니다. "
                "핵심만 짧게, '~권장.' '~확인 필수.' 처럼 명확히 맺습니다. "
                "번역 투, 장황한 문어체, 비문, 미완성 문장을 절대 쓰지 않습니다."
            ),
            messages=[{"role": "user", "content": prompt}],
        )

        if message.stop_reason == "max_tokens":
            logger.warning("AI 응답이 max_tokens로 잘렸습니다 — 일부 코멘트가 누락될 수 있습니다.")

        # 텍스트 블록만 모아서 파싱 (첫 블록이 텍스트가 아닐 수도 있음)
        text = "".join(getattr(b, "text", "") for b in message.content if getattr(b, "type", "") == "text")
        raw = _extract_json(text)
        result = json.loads(raw) if raw else {}

        comments = result.get("comments", {})
        top_pick = result.get("top_pick", {})
        warnings = result.get("warnings", [])
        model_tip = result.get("model_tip", "") or result.get("cls_tip", "")  # 구버전 키 호환

        # ai_comment 필드 채우기
        for i, car in enumerate(evaluate_targets):
            rank_str = str(i + 1)
            comment = comments.get(rank_str, "")
            if top_pick.get("rank") == i + 1:
                comment = f"🏆 **AI 추천 1순위**\n{top_pick.get('reason', '')}\n\n{comment}"
            car.ai_comment = comment

        # 차종 특화 구매 팁을 1위 매물에 추가 (라벨/내용 모두 검색 차종 기준)
        if evaluate_targets and model_tip:
            evaluate_targets[0].ai_comment += f"\n\n💡 **{model_label} 구매 팁**: {model_tip}"

        logger.info(f"Claude API 평가 완료: top_pick rank={top_pick.get('rank')}")
        return listings, None

    except anthropic.AuthenticationError:
        logger.warning("Anthropic 인증 실패 — AI 평가 건너뜀")
        return listings, "Anthropic API 키 인증에 실패했습니다 (키를 확인하세요)."
    except anthropic.NotFoundError:
        logger.warning(f"모델 없음: {ANTHROPIC_MODEL}")
        return listings, f"AI 모델 '{ANTHROPIC_MODEL}'을 찾을 수 없습니다 (config.py의 ANTHROPIC_MODEL 확인)."
    except anthropic.RateLimitError:
        logger.warning("Anthropic Rate Limit — AI 평가 건너뜀")
        return listings, "Anthropic API 사용량 한도에 도달했습니다. 잠시 후 다시 시도하세요."
    except anthropic.APIStatusError as e:
        msg = str(getattr(e, "message", "") or e)
        if "credit balance" in msg.lower():
            logger.warning("Anthropic 크레딧 부족 — AI 평가 건너뜀")
            return listings, "Anthropic 계정 크레딧이 부족합니다. Console → Plans & Billing에서 충전하세요."
        logger.error(f"Claude API 오류: {e}")
        return listings, f"Anthropic API 오류로 평가를 건너뛰었습니다 ({e.status_code})."
    except Exception as e:
        logger.error(f"Claude API 평가 오류: {e}")
        return listings, "AI 평가 중 오류가 발생했습니다 (점수 기반 추천은 정상 표시됩니다)."
