"""
core/schema.py — 표준 데이터 스키마 & SQLite DB 초기화
"""
import sqlite3
from dataclasses import dataclass, field, asdict
from typing import Optional, List
from datetime import datetime
import json

from config import DB_PATH


@dataclass
class CarListing:
    """모든 플랫폼 매물의 공통 정규화 모델"""
    # 출처
    platform: str = ""          # encar / kcar / kb
    listing_id: str = ""        # 플랫폼 내 고유 ID
    source_url: str = ""        # 원본 매물 URL

    # 차량 기본
    maker: str = ""             # 제조사
    model: str = ""             # 모델명
    trim: str = ""              # 세부 트림
    year: int = 0               # 연식
    mileage_km: int = 0         # 주행거리(km)
    price_manwon: float = 0.0   # 가격(만원)

    # 연료·변속
    fuel: str = ""              # 가솔린 / 디젤 / 하이브리드 / 전기
    transmission: str = ""      # 오토 / 수동

    # 상태
    accident_history: bool = False  # 사고이력 있음
    flooded: bool = False           # 침수이력 있음
    warranty: bool = False          # 보증 여부
    warranty_months: int = 0        # 보증 잔여 개월

    # 판매자
    seller_type: str = ""       # dealer / individual / certified
    region: str = ""            # 지역
    color: str = ""             # 외장 색상 (검정색/흰색 등 원문)

    # 옵션 (리스트)
    options: List[str] = field(default_factory=list)

    # 이미지
    thumbnail_url: str = ""

    # 점수 (Scoring Engine이 채움)
    price_score: float = 0.0
    mileage_score: float = 0.0
    year_score: float = 0.0
    accident_score: float = 0.0
    warranty_score: float = 0.0
    option_score: float = 0.0
    trust_score: float = 0.0
    total_score: float = 0.0
    ai_comment: str = ""        # Claude API 평가 코멘트

    # 수집 메타
    listed_date: str = ""
    collected_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["options"] = json.dumps(d["options"], ensure_ascii=False)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CarListing":
        d = dict(d)
        if isinstance(d.get("options"), str):
            try:
                d["options"] = json.loads(d["options"])
            except Exception:
                d["options"] = []
        # DB에 없는 필드 무시
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid})


def init_db():
    """DB 테이블 초기화 (없으면 생성)"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            platform        TEXT,
            listing_id      TEXT,
            source_url      TEXT,
            maker           TEXT,
            model           TEXT,
            trim            TEXT,
            year            INTEGER,
            mileage_km      INTEGER,
            price_manwon    REAL,
            fuel            TEXT,
            transmission    TEXT,
            accident_history INTEGER DEFAULT 0,
            flooded          INTEGER DEFAULT 0,
            warranty         INTEGER DEFAULT 0,
            warranty_months  INTEGER DEFAULT 0,
            seller_type     TEXT,
            region          TEXT,
            color           TEXT,
            options         TEXT,
            thumbnail_url   TEXT,
            price_score     REAL DEFAULT 0,
            mileage_score   REAL DEFAULT 0,
            year_score      REAL DEFAULT 0,
            accident_score  REAL DEFAULT 0,
            warranty_score  REAL DEFAULT 0,
            option_score    REAL DEFAULT 0,
            trust_score     REAL DEFAULT 0,
            total_score     REAL DEFAULT 0,
            ai_comment      TEXT,
            listed_date     TEXT,
            collected_at    TEXT,
            search_key      TEXT,   -- 검색 조건 키 (dedup 범위)
            UNIQUE(platform, listing_id)
        )
    """)
    # 기존 DB 마이그레이션 — 누락 컬럼 추가
    cur.execute("PRAGMA table_info(listings)")
    existing = {row[1] for row in cur.fetchall()}
    for col, ddl in [("color", "color TEXT")]:
        if col not in existing:
            cur.execute(f"ALTER TABLE listings ADD COLUMN {ddl}")
    conn.commit()
    conn.close()


def save_listings(listings: list, search_key: str = ""):
    """매물 리스트를 DB에 저장 (중복은 UPDATE)"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    saved = 0
    for car in listings:
        d = car.to_dict()
        d["search_key"] = search_key
        d["accident_history"] = int(d["accident_history"])
        d["flooded"] = int(d["flooded"])
        d["warranty"] = int(d["warranty"])
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        update_cols = ", ".join(
            f"{k}=excluded.{k}" for k in d.keys()
            if k not in ("platform", "listing_id")
        )
        cur.execute(f"""
            INSERT INTO listings ({cols})
            VALUES ({placeholders})
            ON CONFLICT(platform, listing_id) DO UPDATE SET {update_cols}
        """, list(d.values()))
        saved += 1
    conn.commit()
    conn.close()
    return saved


def load_listings(search_key: str = "") -> list:
    """DB에서 매물 로드"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if search_key:
        cur.execute("SELECT * FROM listings WHERE search_key=? ORDER BY total_score DESC", (search_key,))
    else:
        cur.execute("SELECT * FROM listings ORDER BY total_score DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return [CarListing.from_dict(r) for r in rows]
