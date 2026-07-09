"""
ui/app.py — Streamlit 메인 앱
실행: streamlit run ui/app.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# .env 자동 로드 (프로젝트 루트) — ANTHROPIC_API_KEY 등 환경변수 로드
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import streamlit as st
import pandas as pd
import time
import logging

from config import WEIGHT_PRESETS, ALLOW_LIVE_COLLECTION
from core.schema import init_db, save_listings, load_listings, CarListing
from core.normalizer import (
    dedup, apply_hard_filters, apply_color_filter, normalize_color, COLOR_BUCKETS,
)
from core.scoring import score_listings, explain_ranking
from core.ai_eval import ai_evaluate
from collectors.encar import BRAND_MODELS, fetch_encar_color

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── 페이지 기본 설정 ──────────────────────────────────────
st.set_page_config(
    page_title="중고차 추천 시스템",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 네이비/골드 테마 CSS ─────────────────────────────────
st.markdown("""
<style>
    :root {
        --navy:    #0f1f3d;
        --navy-2:  #1a2f54;
        --gold:    #d4af37;
        --gold-lt: #f0d98a;
    }
    /* 전체 배경 */
    .stApp { background: #f4f6fb; }
    /* 사이드바 네이비 */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f1f3d 0%, #16294a 100%);
    }
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span { color: #eaf0fb; }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 { color: var(--gold-lt) !important; }
    /* 셀렉트/멀티셀렉트 컨트롤 — 네이비 배경에서 잘 보이게 (밝은 배경 + 진한 글자) */
    section[data-testid="stSidebar"] div[data-baseweb="select"] > div {
        background-color: #ffffff !important;
        border: 1px solid var(--gold) !important;
        border-radius: 8px !important;
    }
    section[data-testid="stSidebar"] div[data-baseweb="select"] div,
    section[data-testid="stSidebar"] div[data-baseweb="select"] span,
    section[data-testid="stSidebar"] div[data-baseweb="select"] input {
        color: #11203f !important;
        -webkit-text-fill-color: #11203f !important;
    }
    section[data-testid="stSidebar"] div[data-baseweb="select"] svg { fill: #11203f !important; }
    /* 멀티셀렉트 선택 칩 → 골드 */
    section[data-testid="stSidebar"] span[data-baseweb="tag"] {
        background: var(--gold) !important; color:#0f1f3d !important; border:none !important;
    }
    section[data-testid="stSidebar"] span[data-baseweb="tag"] span,
    section[data-testid="stSidebar"] span[data-baseweb="tag"] svg {
        color:#0f1f3d !important; fill:#0f1f3d !important; -webkit-text-fill-color:#0f1f3d !important;
    }
    /* 드롭다운 팝오버 옵션(포털) — 흰 배경에 진한 글자 */
    ul[role="listbox"] li, div[data-baseweb="popover"] li { color:#11203f !important; }
    /* 메인 헤더 */
    .main-header {
        background: linear-gradient(135deg, #0f1f3d 0%, #24407a 100%);
        padding: 1.6rem 2rem;
        border-radius: 14px;
        margin-bottom: 1.4rem;
        color: white;
        border: 1px solid rgba(212,175,55,0.45);
        box-shadow: 0 6px 24px rgba(15,31,61,0.25);
    }
    .main-header h1 { color:#fff; }
    .main-header .accent { color: var(--gold); }
    /* 추천 카드 */
    .rank-card {
        background: white;
        border: 1px solid #e6e9f2;
        border-radius: 14px;
        padding: 1.1rem 1.5rem;
        margin-bottom: 1rem;
        box-shadow: 0 3px 10px rgba(15,31,61,0.08);
        border-left: 5px solid var(--navy-2);
    }
    .rank-1 { border-left: 6px solid #d4af37; background: linear-gradient(90deg,#fffdf5 0%,#ffffff 60%); }
    .rank-2 { border-left: 6px solid #b8bcc7; }
    .rank-3 { border-left: 6px solid #cd7f32; }
    .score-badge {
        background: var(--navy);
        color: var(--gold);
        padding: 5px 14px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 0.95rem;
        border: 1px solid var(--gold);
    }
    /* 기본 버튼 → 골드 */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg,#d4af37 0%,#caa12b 100%);
        color: #0f1f3d; font-weight: 800; border: none; border-radius: 10px;
    }
    .stButton > button[kind="primary"]:hover { filter: brightness(1.06); color:#0f1f3d; }
    /* 탭 강조 */
    .stTabs [aria-selected="true"] { color: var(--navy) !important; }
    .stTabs [data-baseweb="tab-highlight"] { background: var(--gold) !important; }
    /* 태그 */
    .tag-safe   { background:#e8f5e9; color:#2e7d32; padding:2px 9px; border-radius:12px; font-size:0.8rem; }
    .tag-warn   { background:#fff8e1; color:#b8860b; padding:2px 9px; border-radius:12px; font-size:0.8rem; }
    .tag-danger { background:#ffebee; color:#c62828; padding:2px 9px; border-radius:12px; font-size:0.8rem; }
    .tag-color  { background:#eef2fb; color:#0f1f3d; padding:2px 9px; border-radius:12px; font-size:0.8rem; border:1px solid #d4af37; }
</style>
""", unsafe_allow_html=True)

# 색상 버킷 → 표시용 점(dot) 색
_COLOR_DOT = {
    "검정": "#222", "흰색": "#f5f5f5", "회색": "#888", "은색": "#cfd3d8",
    "파랑": "#1f4fd0", "빨강": "#c62828", "갈색": "#7b4a2b",
}


def main():
    init_db()

    # ── 헤더 ──────────────────────────────────────────────
    st.markdown("""
    <div class="main-header">
        <h1 style="margin:0; font-size:1.85rem;">🚗 국내 중고차 <span class="accent">AI</span> 추천 시스템</h1>
        <p style="margin:0.35rem 0 0 0; opacity:0.85;">엔카 · 케이카 실시간 수집 → <span class="accent">가중 점수</span> → Claude AI 평가</p>
    </div>
    """, unsafe_allow_html=True)

    # ── 사이드바: 검색 조건 ───────────────────────────────
    with st.sidebar:
        st.header("🔍 검색 조건")

        # 1·2·3) 브랜드 → 모델그룹 → 세부모델 3단계 캐스케이드
        maker = st.selectbox(
            "브랜드", list(BRAND_MODELS.keys()), index=0,
            help="수입차 20개 브랜드. 브랜드를 바꾸면 모델그룹이 자동 갱신됩니다.",
        )
        model_group = st.selectbox(
            "모델그룹", list(BRAND_MODELS[maker].keys()), index=0,
            help="선택 브랜드의 엔카 모델그룹 (예: 벤츠 → CLS-클래스).",
        )
        sub_options = ["전체"] + BRAND_MODELS[maker][model_group]
        sub_model = st.selectbox(
            "세부모델", sub_options, index=0,
            help="세부 엔진/트림 (예: CLS450). '전체'는 모델그룹 전체 검색.",
        )
        model = model_group if sub_model == "전체" else sub_model

        # 2) 연식/주행/가격 슬라이더
        year_from, year_to = st.slider(
            "연식", 2012, 2025, (2019, 2024), step=1, format="%d년",
        )
        mileage_max = st.slider(
            "최대 주행거리", 10000, 200000, 80000, step=5000, format="%,d km",
        )
        price_max = st.slider(
            "최대 예산 (만원)", 1000, 20000, 9000, step=250, format="%,d만원",
        )

        st.divider()
        st.subheader("🎯 필터")
        c1, c2 = st.columns(2)
        accident_free = c1.checkbox("무사고만", value=False)
        no_flood = c2.checkbox("무침수만", value=True)

        # 5) 색상 필터 (수집 후 텍스트 매칭)
        colors = st.multiselect(
            "외장 색상", COLOR_BUCKETS, default=[],
            help="선택 시 수집 후 색상으로 필터링합니다. 비워두면 전체 색상.",
        )

        st.divider()
        st.subheader("⚖️ 가중치 프리셋")
        preset = st.radio("프리셋 선택", list(WEIGHT_PRESETS.keys()), index=0, horizontal=False)

        with st.expander("가중치 직접 조정"):
            w = dict(WEIGHT_PRESETS[preset])
            w["price_score"] = st.slider("시세 대비 가격", 0.0, 1.0, w["price_score"], 0.05)
            w["mileage_score"] = st.slider("주행거리", 0.0, 1.0, w["mileage_score"], 0.05)
            w["year_score"] = st.slider("연식", 0.0, 1.0, w["year_score"], 0.05)
            w["accident_score"] = st.slider("사고/침수 이력", 0.0, 1.0, w["accident_score"], 0.05)
            w["warranty_score"] = st.slider("보증", 0.0, 1.0, w["warranty_score"], 0.05)
            w["option_score"] = st.slider("옵션 충족도", 0.0, 1.0, w["option_score"], 0.05)
            w["trust_score"] = st.slider("판매자 신뢰도", 0.0, 1.0, w["trust_score"], 0.05)

        st.divider()
        st.subheader("🤖 AI 평가 (선택)")
        ai_enabled = st.checkbox("Claude AI 평가 활성화", value=True)
        ai_top_n = st.slider("AI 평가 대상 (상위 N건)", 3, 20, 10)
        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.caption(
                "ℹ️ `ANTHROPIC_API_KEY` 미설정 상태입니다. "
                "AI 코멘트 없이도 **수집·점수·순위·분석은 모두 정상 동작**합니다. "
                "AI 평가를 켜려면 키(+크레딧) 설정 후 실행하세요."
            )

        st.divider()
        search_btn = st.button("🔍 수집 시작", type="primary", use_container_width=True)

    # ── 메인 영역 ─────────────────────────────────────────
    if search_btn:
        _run_search(
            maker=maker, model=model, model_group=model_group,
            year_from=int(year_from), year_to=int(year_to),
            mileage_max=int(mileage_max), price_max=float(price_max),
            accident_free=accident_free, no_flood=no_flood, colors=colors,
            weights=w, preset_name=preset,
            ai_enabled=ai_enabled, ai_top_n=ai_top_n,
        )
    else:
        # 이전 결과가 있으면 표시
        if "last_results" in st.session_state:
            _display_results(st.session_state["last_results"], w, preset)
        else:
            _show_welcome()


def _run_search(**params):
    """수집 → 필터 → 점수화 → AI 평가 → 표시"""
    maker = params["maker"]
    model = params["model"]
    year_from = params["year_from"]
    year_to = params["year_to"]
    mileage_max = params["mileage_max"]
    price_max = params["price_max"]

    progress = st.progress(0, text="수집 준비 중...")
    status = st.empty()

    all_listings = []

    # ── 엔카 수집 ──────────────────────────────────────
    if ALLOW_LIVE_COLLECTION:
        try:
            status.info("📡 엔카 수집 중...")
            progress.progress(10, "엔카 수집 중...")

            from collectors.encar import collect_encar_sync
            encar_cars = collect_encar_sync(
                maker=maker, model=model,
                year_from=year_from, year_to=year_to,
                mileage_max=mileage_max, price_max=price_max,
                max_pages=3, colors=params.get("colors") or None,
            )
            all_listings.extend(encar_cars)
            status.success(f"✅ 엔카: {len(encar_cars)}건 수집")
            progress.progress(35)

        except Exception as e:
            status.warning(f"⚠️ 엔카 수집 오류: {e}")

        # ── 케이카 수집 ────────────────────────────────
        try:
            status.info("📡 케이카 수집 중...")
            progress.progress(40, "케이카 수집 중...")

            from collectors.kcar import collect_kcar_sync
            kcar_cars = collect_kcar_sync(
                maker=maker, model=model, model_group=params.get("model_group"),
                year_from=year_from, year_to=year_to,
                mileage_max=mileage_max, price_max=price_max,
                max_pages=2,
            )
            all_listings.extend(kcar_cars)
            status.success(f"✅ 케이카: {len(kcar_cars)}건 수집")
            progress.progress(60)

        except Exception as e:
            status.warning(f"⚠️ 케이카 수집 오류: {e}")

    else:
        status.warning("⚠️ ALLOW_LIVE_COLLECTION=False — 데모 데이터 사용")
        all_listings = _get_demo_listings()
        progress.progress(60)

    if not all_listings:
        st.error("수집된 매물이 없습니다. 조건을 완화하거나 잠시 후 재시도하세요.")
        return

    # ── 중복 제거 & 하드 필터 ──────────────────────────
    status.info(f"🔄 중복 제거 및 필터 처리 중... ({len(all_listings)}건)")
    progress.progress(63)
    listings = dedup(all_listings)
    listings = apply_hard_filters(
        listings,
        year_from=year_from, year_to=year_to,
        mileage_max=mileage_max, price_max=price_max,
        accident_free=params["accident_free"],
        no_flood=params["no_flood"],
    )

    # ── 색상 필터 ──────────────────────────────────────
    #  엔카: 수집 단계에서 서버측(Color OR) 필터 적용됨 → color 비어도 정확.
    #  케이카: extrColorNm 보유 → 여기서 매칭. (색상 미입력은 일단 포함)
    colors = params.get("colors") or []
    if colors and listings:
        listings = apply_color_filter(listings, colors)
        # 표시용 색상 보강(엔카 상세 API) — 필터된 소수만, 실패해도 결과는 유지
        status.info("🎨 색상 정보 표시용 보강 중...")
        progress.progress(68)
        for car in listings[:30]:
            if car.platform == "encar" and not car.color:
                car.color = fetch_encar_color(car.listing_id)

    status.success(f"✅ 필터 후: {len(listings)}건")

    if not listings:
        msg = "필터 조건에 맞는 매물이 없습니다."
        if colors:
            msg += f" (색상 필터: {', '.join(colors)} — 조건을 완화해 보세요)"
        st.error(msg)
        return

    # ── 점수화 ─────────────────────────────────────────
    status.info("📊 점수 계산 중...")
    progress.progress(70)
    listings = score_listings(listings, weights=params["weights"], preset_name=params["preset_name"])

    # ── AI 평가 (선택) ─────────────────────────────────
    ai_status = None
    if params["ai_enabled"]:
        status.info("🤖 Claude AI 평가 중...")
        progress.progress(80)
        user_profile = {
            "차종": f"{maker} {model}",
            "연식": f"{year_from}~{year_to}년",
            "주행거리 상한": f"{mileage_max:,}km",
            "예산": f"{price_max:,.0f}만원",
            "선호": "무사고, 옵션 충족, 정비이력 확인",
        }
        # 차종 팁 라벨 = 모델그룹명 (예: 'CLS-클래스', '5시리즈', 'A6')
        tip_label = params.get("model_group") or model
        listings, ai_status = ai_evaluate(
            listings, user_profile, top_n=params["ai_top_n"], model_label=tip_label
        )

    # ── DB 저장 ────────────────────────────────────────
    search_key = f"{maker}_{model}_{year_from}_{year_to}"
    save_listings(listings, search_key=search_key)

    progress.progress(100, "완료!")
    time.sleep(0.5)
    progress.empty()
    status.empty()

    # 세션에 결과 저장
    st.session_state["last_results"] = listings
    st.success(f"✅ 총 {len(listings)}건 수집 완료 | 최고점: {listings[0].total_score:.3f}")

    # AI 평가 안내 — 사용 가능 여부에 따라 톤을 다르게
    if params["ai_enabled"]:
        if ai_status:
            st.info(
                f"🤖 **AI 평가는 이번에 건너뛰었습니다** — {ai_status}\n\n"
                "걱정 마세요. 아래 순위는 **7개 항목 가중 점수 알고리즘**으로 산출된 결과이며, "
                "각 매물의 **‘📊 점수 상세’**에서 산출 근거를 확인할 수 있습니다. "
                "Claude AI 코멘트를 원하시면 `ANTHROPIC_API_KEY`(+크레딧) 설정 후 다시 수집하세요."
            )
        else:
            st.caption("🤖 Claude AI 평가 완료 — 각 매물의 ‘🤖 AI 평가’에서 전문가 코멘트를 확인하세요.")

    _display_results(listings, params["weights"], params["preset_name"])


def _display_results(listings: list, weights: dict, preset_name: str):
    """결과 표시"""
    if not listings:
        return

    # ── 탭 구성 ────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs(["🏆 추천 순위", "📊 데이터 테이블", "📈 분석"])

    with tab1:
        _show_ranking(listings, weights)

    with tab2:
        _show_table(listings)

    with tab3:
        _show_analysis(listings)


def _show_ranking(listings: list, weights: dict):
    """추천 순위 카드 표시"""
    st.subheader(f"추천 순위 (총 {len(listings)}건)")

    for i, car in enumerate(listings[:20]):
        rank = i + 1
        rank_class = f"rank-{min(rank, 4)}" if rank <= 3 else ""
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")

        accident_tag = (
            '<span class="tag-safe">무사고</span>' if not car.accident_history
            else '<span class="tag-warn">사고이력</span>'
        )
        flood_tag = (
            '' if not car.flooded
            else '<span class="tag-danger">침수이력</span>'
        )
        warranty_tag = (
            f'<span class="tag-safe">보증 {car.warranty_months}개월</span>'
            if car.warranty else ''
        )
        seller_tag = {
            "certified": '<span class="tag-safe">인증중고</span>',
            "dealer": '<span class="tag-warn">딜러</span>',
            "individual": '<span class="tag-warn">개인</span>',
        }.get(car.seller_type, "")
        cbucket = normalize_color(car.color)
        color_tag = ""
        if car.color:
            dot = _COLOR_DOT.get(cbucket, "#bbb")
            label = cbucket or car.color
            color_tag = (
                f'<span class="tag-color">'
                f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;'
                f'background:{dot};border:1px solid #999;margin-right:4px;"></span>{label}</span>'
            )

        with st.container():
            st.markdown(f"""
            <div class="rank-card {rank_class}">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span style="font-size:1.3rem; font-weight:bold;">{medal} {car.year}년 {car.maker} {car.model} {car.trim}</span>
                    </div>
                    <span class="score-badge">{car.total_score:.3f}점</span>
                </div>
                <div style="margin:0.5rem 0; color:#555;">
                    💰 <strong>{car.price_manwon:,.0f}만원</strong>
                    &nbsp;|&nbsp; 🛣️ {car.mileage_km:,}km
                    &nbsp;|&nbsp; 📍 {car.region or '-'}
                    &nbsp;|&nbsp; ⛽ {car.fuel or '-'}
                    &nbsp;|&nbsp; [{car.platform.upper()}]
                </div>
                <div style="margin:0.3rem 0;">
                    {accident_tag} {flood_tag} {warranty_tag} {seller_tag} {color_tag}
                </div>
            </div>
            """, unsafe_allow_html=True)

            # AI 코멘트 & 링크
            col1, col2 = st.columns([3, 1])
            with col1:
                if car.ai_comment:
                    with st.expander("🤖 AI 평가"):
                        st.markdown(car.ai_comment)
                else:
                    with st.expander("📊 점수 상세"):
                        st.markdown(explain_ranking(car, rank, weights))
            with col2:
                if car.source_url:
                    st.link_button("🔗 매물 보기", car.source_url, use_container_width=True)


def _show_table(listings: list):
    """데이터 테이블 표시"""
    rows = []
    for i, c in enumerate(listings):
        rows.append({
            "순위": i + 1,
            "플랫폼": c.platform.upper(),
            "연식": c.year,
            "모델": f"{c.maker} {c.model} {c.trim}".strip(),
            "주행거리": c.mileage_km,
            "가격(만원)": c.price_manwon,
            "사고": "있음" if c.accident_history else "없음",
            "침수": "있음" if c.flooded else "없음",
            "색상": normalize_color(c.color) or (c.color or "-"),
            "보증": f"{c.warranty_months}개월" if c.warranty else "없음",
            "판매유형": c.seller_type,
            "지역": c.region,
            "종합점수": c.total_score,
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        column_config={
            "주행거리": st.column_config.NumberColumn(format="%,d km"),
            "가격(만원)": st.column_config.NumberColumn(format="%.0f 만원"),
            "종합점수": st.column_config.ProgressColumn(min_value=0, max_value=1),
        },
        use_container_width=True,
        hide_index=True,
    )

    # CSV 다운로드
    csv = df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button("📥 CSV 다운로드", csv, "carfinder_results.csv", "text/csv")


def _show_analysis(listings: list):
    """분석 차트"""
    import plotly.express as px
    import plotly.graph_objects as go

    df = pd.DataFrame([{
        "플랫폼": c.platform.upper(),
        "연식": c.year,
        "주행거리": c.mileage_km,
        "가격(만원)": c.price_manwon,
        "종합점수": c.total_score,
        "사고유무": "사고있음" if c.accident_history else "무사고",
        "모델": f"{c.model} {c.trim}".strip(),
    } for c in listings])

    col1, col2 = st.columns(2)

    with col1:
        fig = px.scatter(
            df, x="주행거리", y="가격(만원)",
            color="종합점수", size="종합점수",
            hover_data=["연식", "모델", "사고유무", "플랫폼"],
            color_continuous_scale="RdYlGn",
            title="주행거리 vs 가격 (색상=점수)",
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig2 = px.histogram(
            df, x="가격(만원)", color="사고유무",
            nbins=15, title="가격 분포",
            color_discrete_map={"무사고": "#2e7d32", "사고있음": "#c62828"},
        )
        st.plotly_chart(fig2, use_container_width=True)

    # 플랫폼별 통계
    st.subheader("플랫폼별 통계")
    stats = df.groupby("플랫폼").agg(
        매물수=("가격(만원)", "count"),
        평균가격=("가격(만원)", "mean"),
        평균주행거리=("주행거리", "mean"),
        평균점수=("종합점수", "mean"),
    ).round(0)
    st.dataframe(stats, use_container_width=True)


def _get_demo_listings() -> list:
    """ALLOW_LIVE_COLLECTION=False일 때 사용하는 데모 데이터"""
    demos = [
        CarListing(platform="encar", listing_id="demo_001",
                   source_url="https://www.encar.com/dc/dc_cardetailview.do?carid=demo001",
                   maker="벤츠", model="CLS", trim="450 4MATIC AMG Line",
                   year=2021, mileage_km=42000, price_manwon=7800,
                   fuel="가솔린", transmission="오토",
                   accident_history=False, flooded=False,
                   warranty=True, warranty_months=6,
                   seller_type="dealer", region="서울"),
        CarListing(platform="encar", listing_id="demo_002",
                   source_url="https://www.encar.com/dc/dc_cardetailview.do?carid=demo002",
                   maker="벤츠", model="CLS", trim="450 4MATIC",
                   year=2020, mileage_km=58000, price_manwon=7200,
                   fuel="가솔린", transmission="오토",
                   accident_history=True, flooded=False,
                   warranty=False, warranty_months=0,
                   seller_type="dealer", region="경기"),
        CarListing(platform="kcar", listing_id="demo_003",
                   source_url="https://www.kcar.com/vehicle/demo003",
                   maker="벤츠", model="CLS", trim="450 4MATIC AMG Line",
                   year=2022, mileage_km=31000, price_manwon=8500,
                   fuel="가솔린", transmission="오토",
                   accident_history=False, flooded=False,
                   warranty=True, warranty_months=12,
                   seller_type="certified", region="서울"),
        CarListing(platform="encar", listing_id="demo_004",
                   source_url="https://www.encar.com/dc/dc_cardetailview.do?carid=demo004",
                   maker="벤츠", model="CLS", trim="400d 4MATIC",
                   year=2021, mileage_km=67000, price_manwon=6900,
                   fuel="디젤", transmission="오토",
                   accident_history=False, flooded=False,
                   warranty=False, warranty_months=0,
                   seller_type="dealer", region="부산"),
        CarListing(platform="kcar", listing_id="demo_005",
                   source_url="https://www.kcar.com/vehicle/demo005",
                   maker="벤츠", model="CLS", trim="450 4MATIC AMG Line",
                   year=2023, mileage_km=18000, price_manwon=8900,
                   fuel="가솔린", transmission="오토",
                   accident_history=False, flooded=False,
                   warranty=True, warranty_months=18,
                   seller_type="certified", region="인천"),
    ]
    return demos


def _show_welcome():
    """초기 화면"""
    st.info("👈 왼쪽 사이드바에서 검색 조건을 설정하고 **수집 시작** 버튼을 누르세요.")

    st.markdown("""
    ### 사용 방법
    1. **제조사 / 모델** 선택 (예: 벤츠 / CLS 450)
    2. **연식·주행거리·예산** 설정
    3. **가중치 프리셋** 선택 (기본형 / 가성비형 / 안전중시형 / 최신형)
    4. **수집 시작** → 엔카·케이카 실시간 수집 후 AI 평가

    ### 특징
    - 🔴 **실시간 수집**: 엔카·케이카 공개 API 활용
    - ⚖️ **가중 점수**: 7개 요소 min-max 정규화 후 가중합 → 순위 산출
    - 📊 **시각화**: 가격·주행거리 분포, 플랫폼 비교
    - 🤖 **Claude AI 평가 (선택)**: 상위 N건 자연어 전문가 평가
      — *API 키가 없어도 위 기능은 모두 정상 동작합니다.*
    """)


if __name__ == "__main__":
    main()
