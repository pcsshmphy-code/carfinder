"""
설정 파일 — 모든 파라미터를 여기서 관리
"""

# ── 수집 제어 ──────────────────────────────────────────────
ALLOW_LIVE_COLLECTION = True   # False → fixture 테스트 모드

# 요청 간 지연(초) — 서버 부하 최소화
REQUEST_DELAY_SEC = 2.0
MAX_PAGES_PER_PLATFORM = 3     # 플랫폼당 최대 수집 페이지
MAX_LISTINGS_PER_PLATFORM = 50 # 플랫폼당 최대 매물 수

# ── Anthropic API ──────────────────────────────────────────
ANTHROPIC_MODEL = "claude-sonnet-5-5"   # 최신 Sonnet (구 claude-sonnet-4-6)
AI_EVAL_ENABLED = True         # False → 알고리즘 점수만 사용

# ── DB ────────────────────────────────────────────────────
DB_PATH = "carfinder.db"

# ── 가중치 프리셋 ──────────────────────────────────────────
WEIGHT_PRESETS = {
    "기본형": {
        "price_score":    0.30,  # 시세 대비 가격
        "mileage_score":  0.20,  # 주행거리
        "year_score":     0.15,  # 연식
        "accident_score": 0.15,  # 사고/침수 이력
        "warranty_score": 0.10,  # 인증/보증
        "option_score":   0.05,  # 옵션 충족도
        "trust_score":    0.05,  # 판매자 신뢰도
    },
    "가성비형": {
        "price_score":    0.45,
        "mileage_score":  0.20,
        "year_score":     0.10,
        "accident_score": 0.10,
        "warranty_score": 0.05,
        "option_score":   0.05,
        "trust_score":    0.05,
    },
    "안전중시형": {
        "price_score":    0.15,
        "mileage_score":  0.15,
        "year_score":     0.10,
        "accident_score": 0.35,
        "warranty_score": 0.15,
        "option_score":   0.05,
        "trust_score":    0.05,
    },
    "최신형": {
        "price_score":    0.20,
        "mileage_score":  0.15,
        "year_score":     0.35,
        "accident_score": 0.15,
        "warranty_score": 0.10,
        "option_score":   0.03,
        "trust_score":    0.02,
    },
}

# ── User-Agent ─────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
