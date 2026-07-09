"""
collectors/encar.py v10
- 엔카 공개 검색 API(api.encar.com)를 requests로 직접 호출
- Playwright 불필요 (헤드리스 브라우저 없이 동작)
- q 쿼리는 flat 포맷 사용:
    (And.Hidden.N._.CarType.N._.Manufacturer.벤츠._.ModelGroup.CLS-클래스._.Year.range(..)._.Mileage.range(..)._.Price.range(..).)
"""
import asyncio
import re
import logging
from typing import List, Optional

import requests

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import REQUEST_DELAY_SEC, MAX_LISTINGS_PER_PLATFORM, USER_AGENT
from core.schema import CarListing

logger = logging.getLogger(__name__)

ENCAR_API = "https://api.encar.com/search/car/list/general"

# ── 수입차 3단계 카탈로그: 브랜드 → 모델그룹 → 세부모델 ──────
#  화이트리스트 20개 브랜드(고정). 모델그룹/세부모델은 api.encar.com
#  CarType.N Manufacturer/ModelGroup/Badge facet 실데이터로 생성.
BRAND_MODELS = {
    "벤츠": {
        "E-클래스": ["E300", "E220d", "E450", "E200", "E350", "E250"],
        "S-클래스": ["S450L", "S500L", "마이바흐", "S350d", "S400d", "S350L"],
        "GLC-클래스": ["GLC300", "GLC220d", "GLC300e", "GLC43 AMG", "GLC350e", "GLC63 AMG"],
        "GLE-클래스": ["GLE450", "GLE400d", "GLE300d", "GLE53 AMG", "GLE350d", "GLE63 AMG"],
        "C-클래스": ["C200", "C220d", "C300", "C220", "C63", "C350e"],
        "CLS-클래스": ["CLS300d", "CLS450", "CLS400d", "CLS53 AMG", "CLS250d", "CLS350"],
        "A-클래스": ["A220", "A45 AMG", "A35 AMG", "A45", "A250", "A200"],
        "GLB-클래스": ["GLB250", "GLB35 AMG", "GLB220", "GLB200d"],
        "GLA-클래스": ["GLA220", "GLA250", "GLA45", "GLA200", "GLA200d"],
        "GLS-클래스": ["GLS400d", "GLS580", "마이바흐", "GLS500", "GLS450d", "GLS450"],
        "AMG GT": [],
    },
    "BMW": {
        "5시리즈": ["520i", "520d", "530i", "523d", "530e", "540i"],
        "3시리즈": ["320d", "320i", "M340i", "330i", "330e", "320e"],
        "7시리즈": ["740d", "740i", "740Li", "730d", "730Ld", "750Li"],
        "X5": ["M50d", "M50i"],
        "X6": ["xDrive40i", "xDrive30d", "xDrive40d", "M50i", "40d", "M50d"],
        "X3": [],
        "X7": ["M60i", "M50i"],
        "1시리즈": ["118d", "120i", "M135i", "120d", "120", "M135"],
        "X4": ["xDrive20i", "xDrive20d", "xDrive30d"],
        "4시리즈": ["420i", "420d", "428i", "M440i", "430i", "435d"],
    },
    "아우디": {
        "A6": ["A6 45 TFSI", "A6 40 TDI", "A6 40 TFSI", "A6 45 TDI", "A6 35 TDI", "A6 3.0 TDI"],
        "Q5": ["Q5 45 TFSI", "Q5 40 TDI", "Q5 35 TDI", "Q5 50 TDI", "Q5 40 TFSI", "Q5 3.2 FSI"],
        "A4": ["A4 40 TFSI", "A4 35 TDI", "A4 30 TDI", "A4 2.0 TDI", "A4 2.0 TFSI", "A4 40 TDI"],
        "Q7": ["Q7 45 TDI", "Q7 45 TFSI", "Q7 55 TFSI", "Q7 50 TDI", "Q7 35 TDI", "Q7 3.0 TDI"],
        "A7": ["A7 55 TFSI", "A7 50 TDI", "A7 45 TDI", "A7 3.0 TFSI", "A7 55 TDI", "A7 3.0 TDI"],
        "A8": ["A8 55 TFSI", "A8 50 TDI", "A8 60 TFSI", "A8 4.2 FSI", "A8 3.0 TDI", "A8 60 TDI"],
        "A5": ["A5 40 TFSI", "A5 45 TFSI", "A5 35 TDI", "A5 40 TDI", "A5 2.0 TFSI", "A5 2.0 TDI"],
        "Q8": ["Q8 55 TFSI", "Q8 50 TDI", "Q8 45 TDI"],
        "A3": ["A3 40 TFSI", "A3 25 TDI", "A3 35 TDI", "A3 2.0 TDI", "A3 2.0 TFSI"],
        "Q3": ["Q3 35 TDI", "Q3 40 TFSI", "Q3 2.0 TDI", "Q3 30 TDI", "Q3 2.0 TFSI"],
    },
    "포르쉐": {
        "카이엔": ["3.0", "4.0", "3.6"],
        "파나메라": ["2.9", "3.0", "4.0", "3.6", "4.8"],
        "911": ["카레라", "터보", "GT3", "타르가"],
        "마칸": ["3.0", "2.0", "2.9", "4S", "베이스", "터보"],
        "718": ["4.0", "2.0", "2.5"],
        "타이칸": ["4S", "베이스", "터보", "GTS"],
        "박스터": ["2.7", "3.4", "2.9"],
        "카이맨": [],
    },
    "볼보": {
        "XC60": ["B5", "T8", "D5", "T6", "B6", "D4"],
        "XC90": ["B6", "D5", "T8", "T6"],
        "S90": ["B5", "B6", "T5", "D5", "T8"],
        "XC40": ["B4", "T4", "트윈"],
        "S60": ["B5", "T5", "D4", "D2", "D3", "폴스타"],
        "V60": ["B5", "T5", "D4", "D2", "D3"],
        "V90": ["B5", "T5", "D5"],
        "V40": ["D3", "T5", "D2", "D4"],
        "S80": ["T5", "D4", "D5", "T6", "3.2", "D2"],
        "XC70": ["D5", "D4", "2.5T", "2.4T"],
    },
    "렉서스": {
        "ES": ["이그제큐티브", "슈프림", "슈프림+", "리미티드", "슈페리어", "F-Sport"],
        "NX": ["슈프림", "이그제큐티브", "F-Sport"],
        "UX": ["2.0", "2WD"],
        "RX": ["이그제큐티브", "F-Sport", "슈프림", "L-Grade", "Premium", "Standard"],
        "LS": ["3.5", "AWD", "5인승", "STD", "P-Grade", "슈프림"],
        "IS": ["2.5", "슈프림", "F-Sport", "이그제큐티브"],
        "CT200h": ["1.8"],
        "GS": ["STD", "슈프림", "F-Sport", "이그제큐티브"],
        "LM": ["500h"],
        "LX": ["700h"],
    },
    "토요타": {
        "시에나": ["2.5", "3.5"],
        "캠리": ["2.5", "하이브리드", "XLE", "3.5"],
        "프리우스": ["1.8", "2.0", "1.5"],
        "RAV4": ["2.5"],
        "알파드": ["2.5", "3.5"],
        "크라운": ["2.5", "2.4"],
        "86": ["2.4", "2.0"],
        "아발론": ["2.5"],
        "수프라": ["GR", "TURBO"],
        "FJ 크루져": ["4WD"],
    },
    "랜드로버": {
        "디스커버리": ["3.0", "D250", "2.0", "P360", "D350", "D300"],
        "레인지로버": ["4.4", "P530", "5.0", "D350", "P550E", "V8"],
        "레인지로버 이보크": ["P250", "2.0", "D180"],
        "디스커버리 스포츠": ["P250", "2.0", "D180", "D200", "2.2"],
        "레인지로버 스포츠": ["3.0", "P360", "P400", "P550E", "5.0", "2.7"],
        "디펜더": ["110", "130", "90"],
        "레인지로버 벨라": ["3.0", "2.0", "5.0"],
        "프리랜더": ["2.2", "2.5", "I6"],
    },
    "재규어": {
        "XF": ["20d", "2.2D", "25t", "2.0", "3.0", "3.0D"],
        "F-PACE": ["20d", "30d", "D200", "35t"],
        "XE": ["20d", "20t", "D180", "3.0", "P300"],
        "XJ": ["3.0D", "3.0", "2.7D", "2.0", "5.0", "4.2"],
        "E-PACE": ["P250", "D180"],
        "F-TYPE": ["3.0", "P300", "5.0", "P380"],
        "I-PACE": ["EV400"],
        "XJ-8": ["3.5", "4.0", "4.2"],
    },
    "미니": {
        "쿠퍼": ["5도어", "기본형", "클래식", "JCW", "HIGH", "SE"],
        "컨트리맨": ["ALL4", "클래식", "HIGH", "JCW", "SE", "기본형"],
        "클럽맨": ["기본형", "High", "클래식", "JCW", "멀티톤", "햄튼"],
        "쿠퍼 컨버터블": ["기본형", "클래식", "JCW", "레솔루트", "페이버드", "하이게이트"],
        "쿠페": ["1.6", "2.0", "JCW"],
        "로드스터": ["1.6"],
        "에이스맨": ["SE", "JCW"],
        "페이스맨": ["기본형"],
    },
    "링컨": {
        "에비에이터": ["3.0"],
        "코세어": ["2.0"],
        "MKZ": ["2.0", "하이브리드"],
        "노틸러스": ["2.7", "2.0"],
        "컨티넨탈": ["3.0", "3.8L"],
        "MKX": ["2.7", "3.7"],
        "네비게이터": ["3.5L", "5.4L"],
        "MKC": ["2.0"],
        "MKS": ["3.7", "3.5"],
        "MKT": ["3.5"],
    },
    "캐딜락": {
        "에스컬레이드": ["6.2", "6.0"],
        "CT6": ["3.6", "2.0"],
        "CTS": ["2.0", "3.0", "3.6", "2.8"],
        "XT5": ["3.6"],
        "XT6": ["3.6"],
        "ATS": ["2.0"],
        "XT4": ["2.0"],
        "CT4": ["2.0"],
        "CT5": ["2.0"],
    },
    "테슬라": {
        "모델 Y": ["RWD", "퍼포먼스", "스탠다드"],
        "모델 3": ["스탠다드", "퍼포먼스", "RWD"],
        "모델 X": ["100D", "AWD", "퍼포먼스", "75D", "플래드"],
        "모델 S": ["플래드", "100D", "90D", "AWD", "75D"],
        "사이버트럭": ["AWD", "Cyberbeast", "RWD"],
    },
    "마세라티": {
        "르반떼": ["3.0", "3.8", "2.0"],
        "기블리": ["3.0", "3.0S", "2.0", "3.8"],
        "콰트로포르테": ["3.0", "GTS", "Q4", "4.2"],
        "그레칼레": ["2.0", "3.0", "AWD"],
        "그란투리스모": ["4.7", "3.0"],
        "그란카브리오": ["3.0", "4.7"],
        "MC20": ["3.0"],
    },
    "벤틀리": {
        "컨티넨탈": ["4.0", "6.0", "GT"],
        "플라잉스퍼": ["4.0", "6.0"],
        "벤테이가": ["4.0", "6.0", "3.0"],
        "뮬산": ["6.8"],
    },
    "푸조": {
        "3008": ["1.5", "1.2", "1.6", "2.0"],
        "2008": ["1.6", "1.5", "EV"],
        "5008": ["1.2", "1.5", "2.0", "1.6"],
        "508": ["2.0", "1.6", "1.5", "2.2"],
        "308": ["1.5", "1.6", "2.0", "1.2"],
        "408": ["1.2"],
        "208": ["GT", "1.6", "1.4"],
        "207": ["1.6"],
        "206": ["1.6", "2.0"],
    },
    "크라이슬러": {
        "300C": ["3.6", "3.0", "3.5", "6.4", "6.1"],
        "200": ["2.4", "3.6"],
        "그랜드 보이저": ["3.6", "3.8"],
        "세브링": ["2.4", "2.7"],
        "크로스파이어": ["로드스터", "쿠페"],
    },
    "지프": {
        "랭글러": ["2.0", "3.6", "2.8", "3.8"],
        "체로키": ["2.4", "3.6", "3.0", "2.2", "4xe", "2.0"],
        "레니게이드": ["2.4", "2.0", "1.3", "1.6"],
        "컴패스": ["2.4"],
        "글래디에이터": ["3.6"],
        "어벤저": ["알티튜드"],
    },
    "혼다": {
        "어코드": ["2.0", "2.4", "1.5", "3.5"],
        "CR-V": ["1.5", "2.0", "4WD", "2.4", "2WD"],
        "오딧세이": ["3.5"],
        "파일럿": ["3.5"],
        "시빅": ["2.0", "1.8", "하이브리드", "1.5", "Type"],
        "레전드": ["3.5", "3.7"],
        "크로스투어": ["3.5"],
        "HR-V": ["1.8"],
        "N-BOX": ["0.6"],
    },
    "닛산": {
        "알티마": ["2.5", "3.5"],
        "큐브": ["1.8"],
        "쥬크": ["1.6", "1.5"],
        "맥시마": ["3.5"],
        "패스파인더": ["3.5"],
        "엑스트레일": ["2.5"],
        "무라노": ["3.5", "2.5"],
        "리프": ["EV"],
        "370Z": ["3.7"],
    },
    "폭스바겐": {
        "티구안": ["티구안 2.0 TDI", "티구안 2.0 TSI"],
        "골프": ["골프 2.0 TDI", "2.0", "골프 1.4 TSI", "골프 1.6 TDI"],
        "아테온": ["아테온 2.0 TDI"],
        "제타": ["제타 1.5 TSI", "제타 1.4 TSI", "제타 2.0 TDI", "제타 1.6 TDI"],
        "파사트": ["파사트 2.0 TDI", "파사트 2.0 TSI", "파사트 1.8 TSI", "2.5"],
        "투아렉": ["투아렉 3.0 TDI", "V6", "투아렉 4.0 TDI", "V10"],
        "CC": ["CC 2.0 TDI", "CC 2.0 TSI", "V6"],
        "비틀": ["비틀 2.0 TDI", "DELUXE", "2.0", "GLS"],
    },
    "포드": {
        "익스플로러": ["2.3", "3.5", "3.0", "2.0", "3.3"],
        "머스탱": ["쿠페", "GT", "컨버터블", "2.3", "5.0"],
        "레인저": ["2.0"],
        "F150": ["3.5L", "5.0L", "5.4L", "4.6L", "2.7L", "5.7L"],
        "브롱코": ["2.7", "2.3"],
        "토러스": ["2.0", "3.5"],
        "몬데오": ["2.0"],
        "익스페디션": ["플래티넘"],
    },
    "인피니티": {
        "Q50": ["2.2d", "3.5", "2.0", "3.0"],
        "Q30": ["2.0"],
        "G": ["세단", "쿠페", "컨버터블"],
        "QX50": ["2.0", "3.7"],
        "QX60": ["3.5"],
        "M": ["스탠다드", "스포츠타입", "3.0", "M37x", "P그레이드"],
        "Q70": ["3.7", "3.0d"],
        "FX": ["5.0", "3.5", "4.5", "3.0"],
    },
    "페라리": {
        "로마": ["3.9"],
        "296": ["3.0"],
        "SF90": ["4.0"],
        "F8": ["3.9"],
        "포르토피노": ["3.9"],
        "푸로산게": ["6.5"],
        "488": ["3.9"],
        "캘리포니아": ["30", "4.3"],
    },
    "람보르기니": {
        "우루스": ["4.0"],
        "우라칸": ["LP640-4", "LP610-4", "LP640-2", "LP580-2", "LP610-2"],
        "아벤타도르": ["LP770-4", "LP750-4", "LP700-4"],
        "레부엘토": ["6.5"],
    },
    "롤스로이스": {
        "고스트": ["6.6", "6.7"],
        "컬리넌": ["6.7"],
        "레이스": ["6.6"],
        "팬텀": ["6.7"],
        "스펙터": ["쿠페"],
        "던": ["6.6"],
    },
    "애스턴마틴": {
        "밴티지": ["4.0", "4.7S", "5.2"],
        "DBX": ["4.0"],
        "라피드": ["6.0S", "6.0"],
        "뱅퀴시": ["6.0"],
        "DB12": ["4.0"],
    },
    "마쯔다": {
        "MX-5 MIATA": ["MIATA"],
    },
    "시트로엥/DS": {
        "C4 피카소": ["1.6", "2.0"],
        "DS3": ["1.6", "1.5", "E-텐스"],
        "C4 칵투스": ["1.6", "1.5"],
        "C4 스페이스투어러": ["1.5", "2.0"],
        "C3 에어크로스": ["1.5"],
        "DS4": ["1.5", "2.0"],
        "DS7": ["2.0", "1.2"],
        "C5 에어크로스": ["1.5"],
    },
    "피아트": {
        "500": ["1.4", "아바스", "1.2", "EV", "0.9"],
        "500X": ["2.4", "2.0"],
        "프리몬트": ["2.0"],
        "124": ["1.4"],
    },
    "GMC": {
        "시에라": ["드날리-X", "드날리", "2500HD", "3500HD", "1500"],
        "사바나": ["6.0", "5.3"],
    },
    "쉐보레": {
        "익스프레스밴": ["6.0", "5.3", "5.7", "6.5"],
        "콜벳": ["쿠페", "컨버터블"],
        "서버밴": ["5.3", "6.2"],
        "실버라도": ["5.3"],
        "타호": ["LT", "하이브리드"],
        "아발란치": ["5.3"],
    },
    "닷지": {
        "램픽업": ["5.7", "3.0", "6.2", "3.6"],
        "챌린저": ["5.7", "3.6", "6.4", "6.2"],
        "다코타": ["QUAD", "REGULAR"],
        "그랜드 캐러밴": ["3.6"],
        "캘리버": ["2.0"],
    },
    "스바루": {
        "아웃백": ["2.5", "3.6"],
        "임프레자": ["WRX"],
        "레거시": ["2.5i", "2.0", "3.6R"],
    },
    "맥라렌": {
        "GT": ["4.0"],
        "570S": ["3.8"],
        "720S": ["4.0"],
        "750S": ["4.0"],
        "650S": ["3.8"],
    },
    "BYD": {
        "아토 3": ["플러스", "베이직"],
        "씰": ["플러스"],
    },
    "미쯔비시": {
        "랜서 에볼루션": ["10세대", "9세대"],
    },
}

# 표시 브랜드명 → 엔카 Manufacturer 실제 표기 (다를 때만)
ENCAR_MAKER_ALIAS = {"토요타": "도요타"}

# UI 색상 버킷 → 엔카 Color facet 값(여러 개면 OR). 엔카 canonical 30색 기준 매핑.
ENCAR_COLOR_VALUES = {
    "검정": ["검정색", "검정투톤"],
    "흰색": ["흰색", "흰색투톤", "진주색", "진주투톤"],
    "회색": ["쥐색"],
    "은색": ["은색", "은색투톤", "명은색", "은하색", "은회색"],
    "파랑": ["청색", "하늘색", "청옥색"],
    "빨강": ["빨간색", "자주색"],
    "갈색": ["갈색", "갈색투톤", "갈대색"],
}

# 하위호환: 일부 모델은 (제조사,모델)→(ModelGroup,배지) 별칭 유지
ENCAR_MODEL_GROUPS = {
    ("벤츠", "CLS"):     ("CLS-클래스", ""),
    ("벤츠", "CLS 450"): ("CLS-클래스", "450"),
    ("벤츠", "CLS450"):  ("CLS-클래스", "450"),
    ("벤츠", "E"):       ("E-클래스", ""),
    ("BMW", "5시리즈"):  ("5시리즈", ""),
}


def _sub_badge(model_group: str, sub_label: str) -> str:
    """세부모델 라벨 → 엔카 Badge 매칭 키워드.
    'A6 45 TFSI'(그룹 A6) → '45 TFSI', 'CLS53 AMG' → 'CLS53', 'CLS450' → 'CLS450'."""
    if sub_label.startswith(model_group + " "):
        return sub_label[len(model_group) + 1:]
    if sub_label.endswith(" AMG"):
        return sub_label[:-4]
    return sub_label


def _resolve_model(maker: str, model: str):
    """모델명 → (ModelGroup, 배지 키워드) 매핑.
    우선순위: 별칭 → 모델그룹명(전체) → 세부모델 → 일반 추론.
    BRAND_MODELS는 {브랜드: {모델그룹: [세부모델...]}} 3단계 구조."""
    key = (maker, model)
    if key in ENCAR_MODEL_GROUPS:
        return ENCAR_MODEL_GROUPS[key]

    catalog = BRAND_MODELS.get(maker, {})
    # 모델그룹명 자체 선택 → 그룹 전체 (배지 없음)
    if model in catalog:
        return model, ""
    # 세부모델 선택 → 소속 모델그룹 + 배지 키워드
    for mg, subs in catalog.items():
        if model in subs:
            return mg, _sub_badge(mg, model)

    # 미등록 — 라벨에서 추론
    badge = ""
    m = re.search(r"\d{3}", model)
    if m:
        badge = m.group(0)
    group = model.split()[0] if model else ""
    if maker == "벤츠" and group and "클래스" not in group:
        group = f"{group}-클래스"
    logger.warning(f"모델 맵 없음 — 추론값 사용: ModelGroup='{group}', badge='{badge}'")
    return group, badge


def model_belongs_to_group(model_str: str, model_group: str) -> bool:
    """매물 Model 필드가 선택한 ModelGroup에 속하는지 검증(후처리 안전망).
    엔카 ModelGroup 서버 필터는 정확(exact)하지만, Model 필드 표기는 브랜드마다
    제각각이다 — 'S-클래스 W223', 'ES300h 7세대', '쿠퍼 컨트리맨', '뉴 A4', 'G37' 등.
    따라서 ModelGroup 토큰이 Model 문자열에 포함되는지(부분일치)로 관대하게 검증한다.
    (서버가 이미 정확히 걸렀으므로 오염 매물은 들어오지 않으며, 표기 변형을 잘못 버리지 않음)"""
    if not model_group:
        return True
    s = model_str or ""
    # ModelGroup의 모든 토큰이 Model 문자열에 포함되면 동일 그룹으로 인정
    #  ('쿠퍼 컨버터블' → '쿠퍼 S 컨버터블' 매칭, 표기 변형 허용)
    return all(tok in s for tok in model_group.split())


def _build_color_clause(colors) -> str:
    """UI 색상 버킷 리스트 → 엔카 (Or.Color.X._.Color.Y.) 절. 없으면 ''"""
    if not colors:
        return ""
    vals = []
    for c in colors:
        vals.extend(ENCAR_COLOR_VALUES.get(c, []))
    if not vals:
        return ""
    inner = "_.".join(f"Color.{v}." for v in vals)
    return f"_.(Or.{inner})"


def _build_query(maker, model_group, year_from, year_to, mileage_max, price_max, colors=None) -> str:
    """엔카 검색 q 쿼리 문자열 생성"""
    maker = ENCAR_MAKER_ALIAS.get(maker, maker)   # 표시명 → 엔카 실제 제조사명
    q = f"(And.Hidden.N._.CarType.N._.Manufacturer.{maker}._.ModelGroup.{model_group}."
    if year_from and year_to:
        # 엔카 연식은 YYYYMM 포맷 (예: 2020 → 202000 ~ 2024 → 202412)
        q += f"_.Year.range({year_from}00..{year_to}12)."
    if mileage_max:
        q += f"_.Mileage.range(..{int(mileage_max)})."
    if price_max:
        q += f"_.Price.range(..{int(price_max)})."
    q += _build_color_clause(colors)   # 색상은 서버측 OR 필터로 전달
    q += ")"
    return q


def _fetch_page(query: str, offset: int, limit: int) -> dict:
    """엔카 API 한 페이지 호출"""
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "http://www.encar.com/",
        "Origin": "http://www.encar.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    params = {
        "count": "true",
        "q": query,
        "sr": f"|ModifiedDate|{offset}|{limit}",
    }
    resp = requests.get(ENCAR_API, headers=headers, params=params, timeout=25)
    resp.raise_for_status()
    return resp.json()


def collect_encar_sync(
    maker="벤츠", model="CLS",
    year_from=2020, year_to=2024,
    mileage_max=80000, price_max=9000,
    max_pages=3, colors=None,
) -> List[CarListing]:
    """엔카 매물 수집 (동기). 결과는 Id 기준 중복 제거.
    colors: UI 색상 버킷 리스트(예: ['검정','회색']) — 엔카 서버측 필터로 전달."""
    model_group, badge_kw = _resolve_model(maker, model)
    query = _build_query(maker, model_group, year_from, year_to, mileage_max, price_max, colors)
    logger.info(f"엔카 검색 쿼리: {query}  (badge='{badge_kw}')")

    limit = 100                      # 한 번에 최대 100건
    results: List[CarListing] = []
    seen_ids = set()

    for pg in range(max_pages):
        offset = pg * limit
        try:
            data = _fetch_page(query, offset, limit)
        except Exception as e:
            logger.warning(f"page={pg+1} API 호출 실패: {e}")
            break

        items = data.get("SearchResults", []) or []
        total = data.get("Count", 0)
        logger.info(f"page={pg+1} 응답: {len(items)}건 (전체 {total}건)")
        if not items:
            break

        for item in items:
            cid = str(item.get("Id", ""))
            if not cid or cid in seen_ids:
                continue
            badge = item.get("Badge", "") or ""
            if badge_kw and badge_kw not in badge:
                continue
            car = _parse_api_item(item)
            if not car:
                continue
            # 모델그룹 정확도 후처리 — 부분매칭 오염 제거 (S-클래스에 CLS 섞임 방지)
            if not model_belongs_to_group(car.model, model_group):
                continue
            seen_ids.add(cid)
            results.append(car)
            if len(results) >= MAX_LISTINGS_PER_PLATFORM:
                break

        if len(results) >= MAX_LISTINGS_PER_PLATFORM:
            break
        if offset + limit >= total:      # 더 가져올 페이지 없음
            break
        if REQUEST_DELAY_SEC:
            import time
            time.sleep(REQUEST_DELAY_SEC)

    logger.info(f"엔카 최종 수집: {len(results)}건")
    return results


async def collect_encar(
    maker="벤츠", model="CLS",
    year_from=2020, year_to=2024,
    mileage_max=80000, price_max=9000,
    max_pages=3, colors=None,
) -> List[CarListing]:
    """비동기 래퍼 — 내부적으로 동기 수집을 스레드에서 실행"""
    return await asyncio.to_thread(
        collect_encar_sync,
        maker=maker, model=model,
        year_from=year_from, year_to=year_to,
        mileage_max=mileage_max, price_max=price_max,
        max_pages=max_pages, colors=colors,
    )


def _parse_api_item(item: dict) -> Optional[CarListing]:
    try:
        car = CarListing()
        car.platform = "encar"
        car.listing_id = str(item.get("Id", ""))
        if not car.listing_id:
            return None
        car.source_url = (
            f"http://www.encar.com/dc/dc_cardetailview.do?carid={car.listing_id}"
        )
        car.maker = item.get("Manufacturer", "") or ""
        car.model = item.get("ModelGroup", "") or item.get("Model", "") or ""
        car.trim = item.get("Badge", "") or item.get("BadgeName", "") or ""

        # 연식: 엔카는 YYYYMM (예: 202011) → YYYY
        year_raw = int(item.get("Year", 0) or 0)
        car.year = year_raw // 100 if year_raw > 9999 else year_raw

        car.mileage_km = int(item.get("Mileage", 0) or 0)
        car.price_manwon = float(item.get("Price", 0) or 0)
        car.fuel = item.get("FuelType", "") or ""
        car.transmission = item.get("Transmission", "") or item.get("GearType", "") or ""

        # 사고/침수 — Condition 배열 또는 개별 필드
        cond = item.get("Condition", []) or []
        car.accident_history = bool(item.get("HasAccident", False))
        car.flooded = bool(item.get("Flooded", False))

        car.region = item.get("OfficeCityState", "") or ""
        photos = item.get("Photos") or []
        if photos:
            loc = photos[0].get("location", "")
            car.thumbnail_url = f"https://ci.encar.com{loc}" if loc.startswith("/") else loc
        car.listed_date = str(item.get("ModifiedDate", "") or item.get("RegisterDate", ""))
        car.seller_type = "individual" if item.get("SellerType") == "개인" else "dealer"

        if car.price_manwon <= 0:
            return None
        return car
    except Exception as e:
        logger.warning(f"API 파싱 오류: {e}")
        return None


ENCAR_DETAIL_API = "https://api.encar.com/v1/readside/vehicle/{id}"


def fetch_encar_color(listing_id: str) -> str:
    """엔카 상세 API에서 차량 색상(spec.colorName) 조회. 실패 시 ''"""
    if not listing_id:
        return ""
    try:
        headers = {"User-Agent": USER_AGENT, "Referer": "http://www.encar.com/"}
        r = requests.get(ENCAR_DETAIL_API.format(id=listing_id), headers=headers, timeout=15)
        r.raise_for_status()
        return (r.json().get("spec", {}) or {}).get("colorName", "") or ""
    except Exception as e:
        logger.debug(f"엔카 색상 조회 실패({listing_id}): {e}")
        return ""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cars = collect_encar_sync(maker="벤츠", model="CLS 450")
    print(f"\n수집: {len(cars)}건")
    for c in cars[:10]:
        print(f"  {c.year}년 {c.model} {c.trim} | {c.mileage_km:,}km | {c.price_manwon:,.0f}만원 | {c.source_url}")
