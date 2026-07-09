"""
core/scoring.py — 가중 점수 엔진
min-max 정규화 후 가중합 → 종합점수 산출
"""
import pandas as pd
import numpy as np
from typing import List, Dict
import logging

from core.schema import CarListing
from config import WEIGHT_PRESETS

logger = logging.getLogger(__name__)


def score_listings(
    listings: List[CarListing],
    weights: Dict[str, float] = None,
    preset_name: str = "기본형",
    desired_options: List[str] = None,
) -> List[CarListing]:
    """
    매물 리스트에 점수를 부여하고 정렬하여 반환

    Args:
        listings: 정규화된 매물 리스트
        weights: 가중치 딕셔너리 (None이면 preset 사용)
        preset_name: 프리셋 이름
        desired_options: 원하는 옵션 리스트 (옵션 충족도 계산용)
    """
    if not listings:
        return []

    w = weights or WEIGHT_PRESETS.get(preset_name, WEIGHT_PRESETS["기본형"])
    desired_options = desired_options or []

    df = pd.DataFrame([vars(c) for c in listings])

    # ── 1. 가격 점수 (낮을수록 ↑) ─────────────────────────
    df["price_score"] = _normalize_inverse(df["price_manwon"])

    # ── 2. 주행거리 점수 (적을수록 ↑) ────────────────────
    df["mileage_score"] = _normalize_inverse(df["mileage_km"])

    # ── 3. 연식 점수 (최신일수록 ↑) ──────────────────────
    df["year_score"] = _normalize(df["year"])

    # ── 4. 사고/침수 이력 점수 ────────────────────────────
    # 무사고·무침수 = 1.0, 사고 = 0.3, 침수 = 0.0
    def accident_score(row):
        if row["flooded"]:
            return 0.0
        if row["accident_history"]:
            return 0.3
        return 1.0
    df["accident_score"] = df.apply(accident_score, axis=1)

    # ── 5. 보증 점수 ──────────────────────────────────────
    def warranty_score(row):
        if row["warranty"]:
            months = row.get("warranty_months", 0) or 0
            # 보증 있음 0.6 + 잔여 기간 최대 0.4 (12개월 기준)
            return min(0.6 + (months / 12) * 0.4, 1.0)
        return 0.0
    df["warranty_score"] = df.apply(warranty_score, axis=1)

    # ── 6. 옵션 충족도 점수 ───────────────────────────────
    def option_score(row):
        if not desired_options:
            return 0.5  # 기본 0.5 (중립)
        opts = row.get("options", []) or []
        opts_lower = [o.lower() for o in opts]
        matched = sum(1 for d in desired_options if d.lower() in " ".join(opts_lower))
        return matched / len(desired_options)
    df["option_score"] = df.apply(option_score, axis=1)

    # ── 7. 판매자 신뢰도 점수 ────────────────────────────
    trust_map = {"certified": 1.0, "dealer": 0.6, "individual": 0.4}
    df["trust_score"] = df["seller_type"].map(trust_map).fillna(0.5)

    # ── 종합 점수 계산 ────────────────────────────────────
    score_cols = ["price_score", "mileage_score", "year_score",
                  "accident_score", "warranty_score", "option_score", "trust_score"]

    df["total_score"] = sum(df[col] * w.get(col, 0) for col in score_cols)

    # ── 결과를 CarListing 객체에 반영 ────────────────────
    for i, car in enumerate(listings):
        row = df.iloc[i]
        for col in score_cols:
            setattr(car, col, round(float(row[col]), 4))
        car.total_score = round(float(row["total_score"]), 4)

    # 점수 내림차순 정렬
    listings.sort(key=lambda x: x.total_score, reverse=True)

    logger.info(f"점수화 완료: {len(listings)}건 | 최고 {listings[0].total_score:.3f} | 최저 {listings[-1].total_score:.3f}")
    return listings


def _normalize(series: pd.Series) -> pd.Series:
    """Min-Max 정규화 (높을수록 1)"""
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series([0.5] * len(series), index=series.index)
    return (series - mn) / (mx - mn)


def _normalize_inverse(series: pd.Series) -> pd.Series:
    """역 Min-Max 정규화 (낮을수록 1)"""
    return 1 - _normalize(series)


def explain_ranking(car: CarListing, rank: int, weights: Dict[str, float]) -> str:
    """순위 근거 설명 생성"""
    factors = []
    w = weights

    if car.accident_score == 1.0:
        factors.append("✅ 무사고·무침수")
    elif car.accident_score == 0.3:
        factors.append("⚠️ 사고이력 있음")
    else:
        factors.append("🚫 침수이력 있음")

    if car.price_score >= 0.7:
        factors.append(f"✅ 시세 대비 저렴 (가격점수 {car.price_score:.0%})")
    elif car.price_score <= 0.3:
        factors.append(f"⚠️ 시세 대비 비쌈 (가격점수 {car.price_score:.0%})")

    if car.mileage_score >= 0.7:
        factors.append(f"✅ 주행거리 양호 ({car.mileage_km:,}km)")
    elif car.mileage_score <= 0.3:
        factors.append(f"⚠️ 주행거리 많음 ({car.mileage_km:,}km)")

    if car.warranty:
        factors.append(f"✅ 보증 있음 ({car.warranty_months}개월)")

    if car.seller_type == "certified":
        factors.append("✅ 인증중고차")

    reason = f"**#{rank}위 선정 이유**\n" + "\n".join(f"- {f}" for f in factors)
    reason += f"\n\n**종합점수**: {car.total_score:.3f}"
    return reason
