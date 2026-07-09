"""
collectors/kcar.py v2 — 케이카(K Car) 라이브 수집기
- 케이카 공개 검색 API(api.kcar.com/bc/search/list)를 requests로 직접 호출
- Playwright 불필요
- 요청 파라미터는 케이카 방식대로 AES-128-CBC 암호화하여 {"enc": ...} 로 전송
    key="SKFJ2424DasfaJRI", iv="sfq241sf3dscs321", PKCS7, base64
- 제조사/모델 코드는 케이카 그룹 API로 동적 조회 (캐시)
"""
import asyncio
import re
import json
import base64
import logging
from typing import List, Optional, Tuple

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import REQUEST_DELAY_SEC, MAX_LISTINGS_PER_PLATFORM, USER_AGENT
from core.schema import CarListing

logger = logging.getLogger(__name__)

KCAR_API = "https://api.kcar.com"
_AES_KEY = b"SKFJ2424DasfaJRI"
_AES_IV = b"sfq241sf3dscs321"

# 자주 쓰는 모델의 모델그룹 토큰/배지 힌트
#  (제조사, 모델) → (모델그룹 매칭 토큰, 배지 키워드)
KCAR_MODEL_HINTS = {
    ("벤츠", "CLS"):     ("CLS", ""),
    ("벤츠", "CLS 450"): ("CLS", "450"),
    ("벤츠", "CLS450"):  ("CLS", "450"),
    ("벤츠", "E"):       ("E-클래스", ""),
    ("BMW", "5시리즈"):  ("5", ""),
}

_code_cache: dict = {}


def _enc(obj: dict) -> str:
    """케이카 요청 파라미터 AES-128-CBC 암호화 → base64 문자열"""
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    padder = PKCS7(128).padder()
    data = padder.update(raw) + padder.finalize()
    enc = Cipher(algorithms.AES(_AES_KEY), modes.CBC(_AES_IV)).encryptor()
    ct = enc.update(data) + enc.finalize()
    return base64.b64encode(ct).decode()


def _post(path: str, cond: dict) -> dict:
    """케이카 API 호출 (cond는 암호화하여 전송)"""
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://www.kcar.com/",
        "Origin": "https://www.kcar.com",
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
    }
    resp = requests.post(KCAR_API + path, json={"enc": _enc(cond)},
                         headers=headers, timeout=25)
    resp.raise_for_status()
    return resp.json()


def _resolve_codes(maker: str, model: str,
                   model_group: Optional[str] = None) -> Optional[Tuple[str, str, str, str, str]]:
    """(제조사, 모델) → (carType, mnuftrCd, modelGrpCd, badge_kw, modelGrpNm) 동적 조회.
    model_group: UI에서 선택한 엔카 ModelGroup명 — 케이카 modelGrpNm과 '정확히' 매칭."""
    cache_key = (maker, model, model_group)
    if cache_key in _code_cache:
        return _code_cache[cache_key]

    # 매칭 대상 그룹명: 우선 model_group, 없으면 힌트/모델에서 추출
    hint_token, hint_badge = KCAR_MODEL_HINTS.get(
        (maker, model),
        (model.split()[0] if model else "", ""),
    )
    grp_token = model_group or hint_token
    badge_kw = hint_badge or ((re.search(r"\d{3}", model) or [""])[0]
                              if re.search(r"\d{3}", model) else "")

    # 1) 제조사 코드 — 국산/수입 양쪽에서 검색
    mnuftr_cd = car_type = None
    for ct in ("IMP", "KOR"):
        try:
            data = _post("/bc/search/group/mnuftr", {"wr_eq_car_type": ct}).get("data", [])
        except Exception as e:
            logger.warning(f"케이카 제조사 코드 조회 실패({ct}): {e}")
            continue
        for m in data:
            if m.get("mnuftrNm") == maker:
                mnuftr_cd, car_type = m.get("mnuftrCd"), ct
                break
        if mnuftr_cd:
            break
    if not mnuftr_cd:
        logger.warning(f"케이카 제조사 코드 없음: {maker}")
        return None

    # 2) 모델그룹 코드 — '정확 매칭' 우선 (부분매칭 오염 방지: S-클래스 ≠ CLS-클래스)
    model_grp_cd = ""
    model_grp_nm = ""
    try:
        groups = _post("/bc/search/group/modelGrp",
                       {"wr_eq_car_type": car_type, "wr_eq_mnuftr_cd": mnuftr_cd}).get("data", [])
        tok = (grp_token or "").upper()
        # ① 완전 일치 (예: 'S-클래스' → 'S-클래스')
        for g in groups:
            if tok and (g.get("modelGrpNm") or "").upper() == tok:
                model_grp_cd, model_grp_nm = g.get("modelGrpCd"), g.get("modelGrpNm")
                break
        # ② '단어 경계' 접두 매칭 (예: 'CLS' → 'CLS-클래스'). 'S-클래스'는 'CLS-클래스'에 매칭 안 됨.
        if not model_grp_cd:
            for g in groups:
                nm = (g.get("modelGrpNm") or "")
                u = nm.upper()
                if tok and (u.startswith(tok + " ") or u.startswith(tok + "-")):
                    model_grp_cd, model_grp_nm = g.get("modelGrpCd"), nm
                    break
    except Exception as e:
        logger.warning(f"케이카 모델그룹 코드 조회 실패: {e}")

    result = (car_type, mnuftr_cd, model_grp_cd, badge_kw, model_grp_nm)
    _code_cache[cache_key] = result
    logger.info(f"케이카 코드: maker={maker}({mnuftr_cd}/{car_type}) "
                f"modelGrp='{grp_token}'→'{model_grp_nm}'({model_grp_cd}) badge='{badge_kw}'")
    return result


def collect_kcar_sync(
    maker: str = "벤츠",
    model: str = "CLS",
    year_from: int = 2020,
    year_to: int = 2024,
    mileage_max: int = 80000,
    price_max: int = 9000,
    max_pages: int = 2,
    model_group: Optional[str] = None,
) -> List[CarListing]:
    """케이카 매물 수집 (동기). carCd 기준 중복 제거 + 조건 필터.
    model_group: UI 선택 ModelGroup명 — 정확 매칭/후처리 필터에 사용."""
    codes = _resolve_codes(maker, model, model_group)
    if not codes:
        logger.info("케이카 코드 해석 실패 — 0건")
        return []
    car_type, mnuftr_cd, model_grp_cd, badge_kw, model_grp_nm = codes
    if model_group and not model_grp_cd:
        logger.info(f"케이카 '{model_group}' 모델그룹 코드 없음 — 0건 (오염 방지)")
        return []

    base_cond = {
        "wr_eq_car_type": car_type,
        "wr_eq_mnuftr_cd": mnuftr_cd,
        "orderBy": "mfg_dt:desc",
        "orderFlag": True,
    }
    if model_grp_cd:
        base_cond["wr_eq_model_grp_cd"] = model_grp_cd
    if price_max:
        base_cond["wr_lt_prc"] = str(int(price_max))

    limit = 100
    results: List[CarListing] = []
    seen = set()

    for pg in range(1, max_pages + 1):
        cond = dict(base_cond, pageno=pg, limit=limit)
        try:
            data = _post("/bc/search/list", cond).get("data", {})
        except Exception as e:
            logger.warning(f"케이카 page={pg} 호출 실패: {e}")
            break

        rows = data.get("rows", []) or []
        total = data.get("totalCnt", 0)
        logger.info(f"케이카 page={pg} 응답: {len(rows)}건 (전체 {total}건)")
        if not rows:
            break

        for item in rows:
            car = _parse_kcar_item(item)
            if not car or not car.listing_id or car.listing_id in seen:
                continue
            # 모델그룹 정확도 후처리 — modelGrpNm 불일치 매물 제거 (CLS 섞임 방지)
            if model_grp_nm and car.model != model_grp_nm:
                continue
            # 조건 필터 (연식/주행/가격/배지)
            if badge_kw and badge_kw not in (car.trim + " " + car.model):
                continue
            if year_from and car.year and not (year_from <= car.year <= year_to):
                continue
            if mileage_max and car.mileage_km > mileage_max:
                continue
            if price_max and car.price_manwon > price_max:
                continue
            seen.add(car.listing_id)
            results.append(car)
            if len(results) >= MAX_LISTINGS_PER_PLATFORM:
                break

        if len(results) >= MAX_LISTINGS_PER_PLATFORM:
            break
        if pg * limit >= total:
            break
        if REQUEST_DELAY_SEC:
            import time
            time.sleep(REQUEST_DELAY_SEC)

    logger.info(f"케이카 최종 수집: {len(results)}건")
    return results


def _parse_kcar_item(item: dict) -> Optional[CarListing]:
    try:
        car = CarListing()
        car.platform = "kcar"
        car.listing_id = str(item.get("carCd", "") or item.get("cno", ""))
        if not car.listing_id:
            return None
        car.source_url = (
            f"https://www.kcar.com/bc/detail/carInfoDtl?i_sCarCd={car.listing_id}"
        )
        car.maker = item.get("mnuftrNm", "") or ""
        car.model = item.get("modelGrpNm", "") or item.get("modelNm", "") or ""
        car.trim = " ".join(
            x for x in [item.get("grdNm", ""), item.get("grdDtlNm", "")] if x
        ).strip()

        # 연식: mfgDt = YYYYMM
        mfg = str(item.get("mfgDt", "") or "")
        car.year = int(mfg[:4]) if len(mfg) >= 4 and mfg[:4].isdigit() else 0

        car.mileage_km = int(item.get("milg", 0) or 0)
        car.price_manwon = float(item.get("prc", 0) or 0)   # 케이카 prc는 만원 단위
        car.fuel = item.get("fuelNm", "") or ""
        car.transmission = item.get("trnsmsnNm", "") or ""

        # acdtHistCd: "100"=무사고, 그 외(300 등)=사고이력
        acdt = str(item.get("acdtHistCd", "") or "")
        car.accident_history = bool(acdt) and acdt != "100"
        car.flooded = False

        car.seller_type = "certified"  # 케이카는 인증 직매입
        car.region = item.get("cntrRgnNm", "") or item.get("cntrNm", "")
        car.color = item.get("extrColorNm", "") or ""

        optn = item.get("optnNm", "") or ""
        car.options = [o for o in optn.split("|") if o] if optn else []
        car.thumbnail_url = item.get("msizeImgPath", "") or item.get("lsizeImgPath", "")
        car.listed_date = str(item.get("prepareBuyRegDt", "") or "")
        return car
    except Exception as e:
        logger.warning(f"케이카 항목 파싱 오류: {e}")
        return None


async def collect_kcar(
    maker: str = "벤츠",
    model: str = "CLS",
    year_from: int = 2020,
    year_to: int = 2024,
    mileage_max: int = 80000,
    price_max: int = 9000,
    max_pages: int = 2,
    model_group: Optional[str] = None,
) -> List[CarListing]:
    """비동기 래퍼 — 동기 수집을 스레드에서 실행"""
    return await asyncio.to_thread(
        collect_kcar_sync,
        maker=maker, model=model,
        year_from=year_from, year_to=year_to,
        mileage_max=mileage_max, price_max=price_max,
        max_pages=max_pages, model_group=model_group,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cars = collect_kcar_sync(
        maker="벤츠", model="CLS 450",
        year_from=2019, year_to=2024,
        mileage_max=70000, price_max=5000,
        max_pages=2,
    )
    print(f"\n수집 결과: {len(cars)}건")
    for c in cars[:10]:
        print(f"  [{c.platform}] {c.year}년 {c.model} {c.trim} "
              f"| {c.mileage_km:,}km | {c.price_manwon:,.0f}만원 | 사고:{c.accident_history}")
        print(f"       {c.source_url}")
