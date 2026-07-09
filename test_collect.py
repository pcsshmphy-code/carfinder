"""
test_collect.py — 로컬 PC에서 수집 테스트
실행: python test_collect.py
"""
import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("collect_debug.log", encoding="utf-8"),
    ]
)

from collectors.encar import collect_encar_sync

print("=" * 50)
print("엔카 수집 테스트 시작")
print("=" * 50)

cars = collect_encar_sync(
    maker="벤츠",
    model="CLS 450",
    year_from=2019,
    year_to=2024,
    mileage_max=70000,
    price_max=5000,
    max_pages=2,
)

print(f"\n수집 결과: {len(cars)}건")
for i, c in enumerate(cars[:10]):
    print(f"  #{i+1} {c.year}년 {c.model} {c.trim}")
    print(f"       {c.mileage_km:,}km | {c.price_manwon:,.0f}만원 | 사고:{c.accident_history}")
    print(f"       {c.source_url}")
    print()

if not cars:
    print("\n[0건] collect_debug.log 파일을 확인하세요.")
    print("또는 브라우저에서 아래 URL이 열리는지 확인:")
    print("https://www.encar.com")
