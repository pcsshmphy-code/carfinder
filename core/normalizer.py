"""
core/normalizer.py — 중복 제거 & 정규화
"""
import logging
from typing import List
from core.schema import CarListing

logger = logging.getLogger(__name__)


def dedup(listings: List[CarListing]) -> List[CarListing]:
    """
    중복 제거. 두 가지만 제거한다:
      (1) 같은 플랫폼의 '재등록' 매물 — 연식·주행거리·가격이 완전히 동일
      (2) 플랫폼 간 동일 차량 — 퍼지 키(연식 + 1,000km + 100만원 버킷)로 교차 판단

    중요: 같은 플랫폼에서 스펙이 비슷하기만 한(완전 동일이 아닌) '서로 다른' 매물은
    보존한다. (예: 2020년 CLS450이 비슷한 주행/가격대로 여러 대 매물로 나오는 경우)
    우선순위: encar > kcar > 기타
    """
    if not listings:
        return []

    priority = {"encar": 0, "kcar": 1, "kb": 2}
    listings.sort(key=lambda c: priority.get(c.platform, 9))

    seen_exact = set()    # 같은 플랫폼 재등록 (완전 동일 스펙)
    seen_fuzzy = {}       # 퍼지키 → 플랫폼 (교차 중복 판단)
    result = []
    removed = 0

    for car in listings:
        ek = _dedup_key_exact(car)
        if ek in seen_exact:
            removed += 1
            continue
        fk = _dedup_key_fuzzy(car)
        if fk in seen_fuzzy and seen_fuzzy[fk] != car.platform:
            removed += 1                          # 다른 플랫폼 동일 차량
            continue
        seen_exact.add(ek)
        seen_fuzzy.setdefault(fk, car.platform)
        result.append(car)

    logger.info(f"중복 제거: {len(listings)}건 → {len(result)}건 (제거 {removed})")
    return result


def _dedup_key_exact(car: CarListing) -> tuple:
    """같은 플랫폼 재등록 판별 — 연식·주행거리·가격 완전 동일"""
    return (car.platform, car.year, car.mileage_km, round(car.price_manwon), car.model)


def _dedup_key_fuzzy(car: CarListing) -> tuple:
    """플랫폼 간 동일 차량 판별 — 연식 + 1,000km 버킷 + 100만원 버킷.
    모델 문자열은 플랫폼마다 표기가 달라(엔카 'CLS-클래스 C257' vs 케이카 'CLS-클래스')
    키에서 제외한다. (검색은 단일 모델 단위라 다른 모델과 충돌할 일이 거의 없음)"""
    mileage_bucket = round(car.mileage_km / 1000)
    price_bucket = round(car.price_manwon / 100)
    return (car.year, mileage_bucket, price_bucket)


def apply_hard_filters(
    listings: List[CarListing],
    year_from: int = 0,
    year_to: int = 9999,
    mileage_max: int = 999999,
    price_max: float = 99999,
    price_min: float = 0,
    accident_free: bool = False,
    no_flood: bool = True,
) -> List[CarListing]:
    """하드 필터 — 기준 미달 매물 제거"""
    before = len(listings)
    filtered = []
    for car in listings:
        if car.year < year_from or car.year > year_to:
            continue
        if car.mileage_km > mileage_max:
            continue
        if car.price_manwon > price_max or car.price_manwon < price_min:
            continue
        if accident_free and car.accident_history:
            continue
        if no_flood and car.flooded:
            continue
        filtered.append(car)

    logger.info(f"하드 필터: {before}건 → {len(filtered)}건")
    return filtered


# 색상 정규화 — 전차종 범용. 엔카 canonical 30색 + 제조사 마케팅 색상명 커버.
# 순서 중요(먼저 매칭되는 버킷 채택): 은색('은회','은하')이 회색보다 앞.
COLOR_BUCKETS = ["검정", "흰색", "회색", "은색", "파랑", "빨강", "갈색"]
_COLOR_RULES = [
    ("검정", ["검정", "흑", "블랙", "black", "오브시디안", "obsidian",
            "마이티블랙", "코스모스블랙", "팬텀블랙", "녹턴블랙", "제트블랙", "카본블랙"]),
    ("흰색", ["흰", "백", "화이트", "white", "진주", "펄", "pearl",
            "폴라화이트", "크리스탈화이트", "아이보리", "다이아몬드화이트", "글래시어", "민트화이트"]),
    ("은색", ["은색", "은하", "은회", "명은", "실버", "silver",
            "문실버", "메탈릭실버", "퓨전실버", "브라이트실버", "아이언실버", "투오라이트실버"]),
    ("회색", ["쥐", "그레이", "gray", "grey", "회",
            "셀레나이트", "그라파이트", "스페이스그레이", "데이토나그레이", "마그네틱그레이", "티타늄"]),
    ("파랑", ["파랑", "파란", "블루", "blue", "네이비", "navy", "청",
            "카브리올레블루", "다임블루", "스피드블루", "타니트", "야스마리나"]),
    ("빨강", ["빨", "적", "레드", "red", "와인", "버건디", "카민", "자주",
            "루비", "디자이어레드", "패션레드"]),
    ("갈색", ["갈", "브라운", "brown", "베이지", "beige", "모카", "코퍼", "copper",
            "마호가니", "샌드", "토프"]),
]


def normalize_color(raw: str) -> str:
    """원문 색상 문자열 → 표준 버킷('검정'/'흰색'...). 매칭 실패 시 ''"""
    if not raw:
        return ""
    s = raw.lower()
    for bucket, keys in _COLOR_RULES:
        if any(k in s for k in keys):
            return bucket
    return ""


def apply_color_filter(listings: List[CarListing], colors: List[str]) -> List[CarListing]:
    """선택한 색상 버킷에 해당하는 매물만 유지.
    - colors가 비면 그대로 통과.
    - 색상 정보가 없는(미입력) 매물은 일단 포함한다(과도한 누락 방지).
      엔카는 서버측에서 이미 색상 필터링되므로 color가 비어 있어도 정확하다."""
    if not colors:
        return listings
    want = set(colors)
    before = len(listings)
    kept = [
        c for c in listings
        if (not c.color) or normalize_color(c.color) in want
    ]
    logger.info(f"색상 필터({', '.join(colors)}): {before}건 → {len(kept)}건 (색상미입력 포함)")
    return kept
