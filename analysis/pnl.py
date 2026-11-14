# -*- coding: utf-8 -*-
"""서초구 남부터미널역 상권(TRDAR 3120175) 출점 손익(P&L) 모델: 3 시나리오 x 2027~2029.
입력: data/processed/panel.csv, analysis/results/analysis.json(v2), analysis/results/concept.json(있으면)
출력: analysis/results/pnl.json, analysis/results/pnl.md
표기: [D]=데이터 기반(서울 열린데이터) / [E]=외부 공식 통계 / [A]=업계 관행·설계 가정
실행: py -I -X utf8 analysis/pnl.py
"""
import json, os
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "analysis", "results")
TR = "3120175"
Q4 = [20253, 20254, 20261, 20262]

an = json.load(open(os.path.join(RES, "analysis.json"), encoding="utf8"))
cp_path = os.path.join(RES, "concept.json")
cc = json.load(open(cp_path, encoding="utf8")) if os.path.exists(cp_path) else {}

p = pd.read_csv(os.path.join(ROOT, "data", "processed", "panel.csv"), dtype={"TRDAR_CD": str})
s = p[(p.TRDAR_CD == TR) & (p.STDR_YYQU_CD.isin(Q4))]
assert len(s) == 4, "남부터미널역 최근 4분기 행 누락"

# ---------- 데이터 기반 값 [D] ----------
mkt_sales_4q = float(s.cb_sales.sum())                     # 원/4분기(=연)
mkt_txn_4q = float(s.cb_txn.sum())                         # 건/4분기
stores_avg = float(s.cb_stores.mean())                     # 커피+제과 점포 평균
txn_per_store_day = mkt_txn_4q / stores_avg / 365          # 건/일/점포
sales_per_store_month = mkt_sales_4q / stores_avg / 12     # 원/월/점포
mkt_ticket = mkt_sales_4q / mkt_txn_4q                     # 원/건
w = s.cb_sales / s.cb_sales.sum()
site_daypart = {k: float((s[f"cb_share_{c}"] * w).sum()) for k, c in
                [("00-06", "t00_06"), ("06-11", "t06_11"), ("11-14", "t11_14"), ("14-17", "t14_17"),
                 ("17-21", "t17_21"), ("21-24", "t21_24")]}
kp = an["final_site"]["kpis"]
cagr3_site = kp["sales_cagr_3y_2023Q2_2026Q2"]
yoy_site = kp["sales_yoy"]
bt3 = an["backtest"]["v2_investable"]["3y"]                 # 출점 적격 상권 롤링 백테스트(3년)
g_top20, g_all, g_bot20 = bt3["top20_cagr"], bt3["all_cagr"], bt3["bottom20_cagr"]

# ---------- 컨셉 값 [A, 컨셉 담당 설계; concept.json 없으면 기본값] ----------
area_m2 = cc.get("area_m2", 148.8)
area_py = cc.get("area_pyeong", 45)
seats = cc.get("seats", 48)
TICKET_PREMIUM = 1.30                                      # [A] 브랜드·베이커리 동반구매 프리미엄
ticket_base = cc.get("avg_ticket_krw", round(mkt_ticket * TICKET_PREMIUM, -2))
_oh = cc.get("opening_hours") if isinstance(cc.get("opening_hours"), dict) else {}
days = _oh.get("days_per_year", 364 if cc else 360)   # concept.json 연매출 계산과 동일(364일)
cogs_base = cc.get("blended_cost_rate", 0.30)
dp_raw = cc.get("daypart_mix") or {}
if isinstance(dp_raw.get("store_plan_sales_share"), dict):   # concept.json: 매장 영업시간 기준 시간대 계획
    dp_raw = dp_raw["store_plan_sales_share"]
daypart = {k: v for k, v in dp_raw.items() if k != "basis" and isinstance(v, (int, float))}
if not daypart:  # 영업 07~22시 가정: 00~06시 제외 후 재정규화
    _t = sum(v for k, v in site_daypart.items() if k != "00-06")
    daypart = {k: v / _t for k, v in site_daypart.items() if k != "00-06"}

# ---------- 인건비 상수 ----------
MIN_WAGE_2026 = 10320          # [E] 고용노동부 고시 2026년 최저임금
JUHYU = 1.20                   # [E] 주휴수당(주 15h 이상, 8h/40h) -> 시급 x1.2
INS = 0.107                    # [E] 사업주 4대보험 2026: 국민연금 4.75 + 건강 3.595 + 장기요양 0.47 + 고용 1.15 + 산재 약 0.7
SEV = 0.0833                   # [E] 퇴직급여 1/12(근로자퇴직급여보장법)
BURDEN = 1 + INS + SEV
WK2MO = 52.14 / 12             # 4.345주/월
WAGE_ESC = 0.03                # [A] 2027~ 임금 연 3% 인상
RENT_ESC = 0.02                # [A] 임대료 연 2% 인상(서울 상가 임대가격지수 최근 분기 +0.46~0.48% ≈ 연 1.9%)

# ---------- 임대료 외부 앵커 [E] ----------
RENT_SEOUL_2025Q2 = 55400      # [E] 한국부동산원 상업용부동산 임대동향 2025Q2 서울 중대형 상가(1층) 원/㎡/월
RENT_NATION_2026Q2 = 26700     # [E] 같은 조사 2026Q2 전국 중대형 상가(1층) 원/㎡/월
RENT_SEOUL_2026 = round(RENT_SEOUL_2025Q2 * 1.02, -2)   # [E+A] 서울 지수 연 ~+2% 반영 → 56,500

SC = {
    "보수": dict(share=0.08, txn_mult=5.0, ticket=ticket_base * 0.95, growth=g_all, ramp=0.85,
               cogs=cogs_base + 0.02, rent_mult=1.20, ft=[420, 400, 320, 300], pt_h_wk=240, capex_py=330, key_money=1.2e8),
    "기준": dict(share=0.10, txn_mult=6.0, ticket=ticket_base, growth=g_top20, ramp=0.92,
               cogs=cogs_base, rent_mult=1.00, ft=[420, 400, 320, 300], pt_h_wk=280, capex_py=300, key_money=1.0e8),
    "낙관": dict(share=0.12, txn_mult=7.0, ticket=ticket_base * 1.05, growth=round(cagr3_site / 2, 4), ramp=1.00,
               cogs=cogs_base - 0.015, rent_mult=0.85, ft=[420, 400, 320, 300], pt_h_wk=320, capex_py=280, key_money=0.8e8),
}
for c in SC.values():
    c["rent_m2"] = round(RENT_SEOUL_2026 * c["rent_mult"], -2)
VAR = dict(card=0.015, hq=0.03, mkt=0.02, util=0.04, supplies=0.03, other=0.01)
MGMT_M2 = 5000                 # [A] 관리비 원/㎡/월
EQUIP = 1.0e8 + 0.35e8 + 0.30e8  # [A] 베이커리 설비 1.0억 + 커피 설비 0.35억 + 가구·간판·POS 0.3억
PREOPEN = 0.3e8                # [A] 개업 전 비용(교육·초도물품·오픈 마케팅)
DEP_YEARS = 5                  # [A] 인테리어·설비 정액 5년


def labor_month(c, yi):
    esc = (1 + WAGE_ESC) ** yi
    ft = sum(c["ft"]) * 1e4
    pt = c["pt_h_wk"] * WK2MO * MIN_WAGE_2026 * JUHYU
    return (ft + pt) * BURDEN * esc, len(c["ft"]) * 40 + c["pt_h_wk"]


out = {"meta": {
    "site": "서초구 남부터미널역 상권(TRDAR 3120175)", "version": "v2",
    "unit": "원(월 평균 또는 연간), 비율",
    "basis_period": "상권 데이터 2025Q3~2026Q2(4분기), 손익 2027~2029(2027.1 개점 가정)",
    "legend": "[D]=서울 열린데이터 기반, [E]=외부 공식 통계, [A]=업계 관행·설계 가정",
    "concept_used": bool(cc),
    "concept_note": f"concept.json 값 사용(면적 {area_py}평·{seats}석·객단가 {ticket_base:,.0f}원·원가율 {cogs_base:.1%}·{days}일·시간대 계획 비중)" if cc else "concept.json 미생성 → 면적 45평·48석·객단가(상권 객단가 x1.3)·원가율 30%·360일 기본값 가정. 컨셉 확정 후 재실행"},
    "data_inputs": {
        "market_cb_sales_4q_won": round(mkt_sales_4q), "market_cb_txn_4q": round(mkt_txn_4q),
        "cb_stores_avg": stores_avg, "txn_per_store_day": round(txn_per_store_day, 1),
        "sales_per_store_month_won": round(sales_per_store_month), "market_ticket_won": round(mkt_ticket),
        "daypart_sales_share": {k: round(v, 4) for k, v in site_daypart.items()},
        "sales_yoy": yoy_site, "sales_cagr_3y_2023Q2_2026Q2": cagr3_site,
        "backtest_investable_3y": {"top20_cagr": g_top20, "all_cagr": g_all, "bottom20_cagr": g_bot20,
                                   "origins": bt3["origins"], "spearman": bt3["spearman"]},
        "source": "OA-15572(추정매출·건수), OA-15577(점포), 2025Q3~2026Q2, panel.csv; 백테스트 analysis.json backtest.v2_investable.3y"},
    "scenarios": {}}

for name, c in SC.items():
    revA = mkt_sales_4q * c["share"] / 12
    txn_day = txn_per_store_day * c["txn_mult"]
    revB = txn_day * c["ticket"] * days / 12
    rev2026 = (revA + revB) / 2
    capex = area_py * c["capex_py"] * 1e4 + EQUIP
    dep = capex / DEP_YEARS / 12
    invest = capex + c["key_money"] + PREOPEN
    deposit = area_m2 * c["rent_m2"] * 10
    years = {}
    for yi, y in enumerate([2027, 2028, 2029]):
        rev = rev2026 * (1 + c["growth"]) ** (y - 2026) * (c["ramp"] if y == 2027 else 1)
        cogs = rev * c["cogs"]
        var = {k: rev * v for k, v in VAR.items()}
        lab, hrs = labor_month(c, yi)
        rent = area_m2 * c["rent_m2"] * (1 + RENT_ESC) ** yi
        mgmt = area_m2 * MGMT_M2
        ebitda = rev - cogs - sum(var.values()) - lab - rent - mgmt
        op = ebitda - dep
        var_rate = c["cogs"] + sum(VAR.values())
        bep = (lab + rent + mgmt + dep) / (1 - var_rate)
        m = dict(revenue=rev, cogs=cogs, labor=lab, rent=rent, mgmt_fee=mgmt,
                 card_fee=var["card"], hq_fee=var["hq"], marketing=var["mkt"], utilities=var["util"],
                 supplies=var["supplies"], other=var["other"], ebitda=ebitda, depreciation=dep, op_income=op)
        years[y] = {"monthly": {k: round(v) for k, v in m.items()},
                    "annual": {k: round(v * 12) for k, v in m.items()},
                    "op_margin": round(op / rev, 4), "ebitda_margin": round(ebitda / rev, 4),
                    "bep_monthly_revenue": round(bep), "bep_ratio": round(bep / rev, 3),
                    "labor_hours_week": hrs, "cogs_ratio": round(c["cogs"], 4),
                    "labor_ratio": round(lab / rev, 4), "rent_ratio": round((rent + mgmt) / rev, 4)}
    # 투자회수: 2027.1부터 월 EBITDA 누적(세전), 2030년 이후는 2029 수준 유지
    cum, mo = 0.0, 0
    while cum < invest and mo < 240:
        y = min(2027 + mo // 12, 2029)
        cum += years[y]["monthly"]["ebitda"]
        mo += 1
    payback = mo / 12 if cum >= invest else None
    out["scenarios"][name] = {
        "revenue_crosscheck_2026basis": {
            "A_share_won_month": round(revA),
            "A_formula": f"상권 커피+제과 연매출 {mkt_sales_4q/1e8:.1f}억[D] x 점유 {c['share']:.0%}[A] / 12",
            "B_txn_won_month": round(revB),
            "B_formula": f"점포당 {txn_per_store_day:.0f}건/일[D] x {c['txn_mult']}배[A] = {txn_day:.0f}건/일 x 객단가 {c['ticket']:,.0f}원 x {days}일 / 12",
            "B_txn_by_daypart": {k: round(txn_day * v) for k, v in daypart.items()},
            "gap_A_vs_B": round(revA / revB - 1, 3), "used": round(rev2026),
            "implied_share_of_market": round(rev2026 * 12 / mkt_sales_4q, 3),
            "implied_multiple_of_avg_store": round(rev2026 / sales_per_store_month, 2),
            "implied_daily_txn": round(rev2026 * 12 / days / c["ticket"]),
            "implied_daily_txn_2027": round(years[2027]["monthly"]["revenue"] * 12 / days / c["ticket"]),
            "days_per_year": days},
        "params": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in c.items()},
        "investment": {"capex_interior_equip": round(capex), "key_money": c["key_money"], "preopen": PREOPEN,
                       "total_excl_deposit": round(invest), "deposit_refundable": round(deposit)},
        "years": years,
        "payback_years_pretax_ebitda": None if payback is None else round(payback, 1)}

b = out["scenarios"]["기준"]
out["headline"] = {
    "base_2027_monthly_revenue": b["years"][2027]["monthly"]["revenue"],
    "base_2029_monthly_revenue": b["years"][2029]["monthly"]["revenue"],
    "base_2027_op_margin": b["years"][2027]["op_margin"], "base_2029_op_margin": b["years"][2029]["op_margin"],
    "base_bep_monthly_revenue_2027": b["years"][2027]["bep_monthly_revenue"],
    "base_investment_excl_deposit": b["investment"]["total_excl_deposit"],
    "base_payback_years": b["payback_years_pretax_ebitda"],
    "range_payback_years": {n: sc["payback_years_pretax_ebitda"] for n, sc in out["scenarios"].items()},
    "range_2029_op_margin": {n: sc["years"][2029]["op_margin"] for n, sc in out["scenarios"].items()},
}

pct = lambda v: f"{v:+.2%}"
out["assumptions"] = [
    {"item": "상권 커피+제과 매출", "value": f"{mkt_sales_4q/1e8:.1f}억원/년(4분기 합)", "type": "D", "source": "OA-15572, 2025Q3~2026Q2"},
    {"item": "점포당 결제건수", "value": f"{txn_per_store_day:.1f}건/일 (점포 평균 {stores_avg:.2f}개)", "type": "D", "source": "OA-15572 건수 / OA-15577 점포수, 같은 기간"},
    {"item": "상권 객단가", "value": f"{mkt_ticket:,.0f}원/건 (커피 {kp['ticket_coffee_won']:,}·제과 {kp['ticket_bakery_won']:,})", "type": "D", "source": "OA-15572, 2025Q3~2026Q2"},
    {"item": "시간대 매출 비중", "value": ", ".join(f"{k} {v:.1%}" for k, v in site_daypart.items()), "type": "D", "source": "OA-15572, 2025Q3~2026Q2(매출 가중)"},
    {"item": "상권 성장률 2027~29", "value": f"보수 {pct(g_all)}(적격 상권 전체) / 기준 {pct(g_top20)}(점수 상위20%) / 낙관 {pct(SC['낙관']['growth'])}(남부터미널 3년 CAGR {cagr3_site:.1%}의 절반)", "type": "D+A",
     "source": "analysis.json backtest.v2_investable.3y: 롤링 기준시점 2022Q4·2023Q1·2023Q2 → 3년 뒤 실제 CAGR. 남부터미널 최근 YoY +14.4%는 지속 가정에 쓰지 않음(보수적)"},
    {"item": "점유율", "value": "8% / 10% / 12% (상권 커피+제과 점포 약 67개 중 45평 플래그십)", "type": "A", "source": "브랜드 프리미엄·규모 가정; 교차검증 (B)와 비교"},
    {"item": "거래건수 배수", "value": "상권 평균 점포의 5 / 6 / 7배", "type": "A", "source": "면적 45평(평균 소형점 약 15평의 3배) x 베이커리 동반·브랜드 1.7~2.3배"},
    {"item": "객단가", "value": f"{ticket_base:,.0f}원(기준, 보수 -5%, 낙관 +5%)", "type": "D+A", "source": f"상권 객단가 {mkt_ticket:,.0f}원[D] x 프리미엄 {TICKET_PREMIUM}[A]" if not cc else "concept.json"},
    {"item": "영업일·면적·좌석", "value": f"{days}일/년, {area_py}평({area_m2}㎡), {seats}석", "type": "A", "source": "concept.json" if cc else "기본값(컨셉 확정 전)"},
    {"item": "원가율", "value": f"{cogs_base+0.02:.1%} / {cogs_base:.1%} / {cogs_base-0.015:.1%}", "type": "A", "source": "concept.json" if cc else "커피 약 22%·베이커리 약 35% 혼합 업계 관행"},
    {"item": "최저임금", "value": "10,320원/시(2026), 2027~ 연 +3%", "type": "E+A", "source": "고용노동부 2026년 적용 최저임금 고시; 인상률은 가정"},
    {"item": "주휴·4대보험·퇴직", "value": "주휴 x1.2(PT), 사업주 4대보험 10.7%, 퇴직 8.33%", "type": "E", "source": "근로기준법 제55조; 2026 요율(국민연금 9.5%의 1/2, 건강 7.19%의 1/2, 장기요양 건강보험료의 13.14%, 고용 1.15%, 산재 업종 약 0.7%); 근로자퇴직급여보장법"},
    {"item": "정규직 급여", "value": "점장 420·헤드베이커 400·베이커 320·바리스타리드 300만원/월", "type": "A", "source": "업계 관행"},
    {"item": "PT 시간", "value": "주 240 / 280 / 320h (정규 4명 160h 합산 400~480h, 평일 06:30~21시 운영)", "type": "A", "source": "아침 06~11시 비중 24%[D] 대응 오전 피크 배치"},
    {"item": "임대료", "value": f"{SC['보수']['rent_m2']:,} / {SC['기준']['rent_m2']:,} / {SC['낙관']['rent_m2']:,}원/㎡/월(1층), 연 +2%", "type": "E+A",
     "source": f"한국부동산원 상업용부동산 임대동향 2025Q2 서울 중대형 상가 {RENT_SEOUL_2025Q2:,}원/㎡(1층)[E] x 1.02(서울 임대가격지수 2026Q1 +0.48%·Q2 +0.46%) = {RENT_SEOUL_2026:,.0f}원 → 역 앞 코너 1.2배 / 서울 평균 / 이면 0.85배[A]. 참고: 2026Q2 전국 중대형 1층 {RENT_NATION_2026Q2:,}원. 남부터미널·교대 하위상권 수치는 공개 기사에서 미확인 → R-ONE 원자료·현장 시세 검증 필요"},
    {"item": "보증금", "value": "월세 10개월", "type": "A", "source": "관행, 회수 가능이라 회수기간 계산에서 제외"},
    {"item": "관리비", "value": "5,000원/㎡/월", "type": "A", "source": "업계 관행"},
    {"item": "카드수수료", "value": "1.5%", "type": "E+A", "source": "여신금융협회 우대수수료(연매출 10~30억 신용 약 1.25%) + 간편결제 가산"},
    {"item": "로열티/본사비", "value": "3%", "type": "A", "source": "PE 보유 직영 브랜드 본사 공통비 배부(가맹 로열티 아님)"},
    {"item": "마케팅·수도광열·소모품·기타", "value": "2% / 4% / 3% / 1%", "type": "A", "source": "업계 관행(오븐 전력, 테이크아웃 포장재)"},
    {"item": "투자비", "value": "인테리어 평당 330/300/280만원 x 45평 + 설비·집기 1.65억, 권리금 1.2/1.0/0.8억, 개업비 0.3억", "type": "A", "source": "업계 관행; 권리금은 현장 검증 필요"},
    {"item": "감가상각", "value": "인테리어·설비 정액 5년", "type": "A", "source": "법인세법 기준내용연수 범위 내 가정"},
]
out["sources_external"] = [
    "한국부동산원 2026년 2분기 상업용부동산 임대동향조사(2026-07-30 발표): 전국 중대형 상가 1층 26,700원/㎡, 서울 상가 임대가격지수 +0.46%(전분기 +0.48%) — 뉴시스 2026-07-29 https://www.newsis.com/view/NISX20260729_0003728100",
    "한국부동산원 2025년 2분기 상업용부동산 임대동향조사: 서울 중대형 상가 55,400원/㎡ — 뉴시스 2025-07-31 https://www.newsis.com/view/NISX20250731_0003273840",
    "고용노동부 2026년 적용 최저임금 고시 10,320원/시",
]

json.dump(out, open(os.path.join(RES, "pnl.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)

# ---------- pnl.md ----------
def e(v): return f"{v/1e4:,.0f}"
L = ["# 남부터미널역 출점 손익(P&L) 2027~2029", "",
     "단위: 만원/월(별도 표기 제외). [D]=서울 열린데이터, [E]=외부 공식 통계, [A]=가정. 계산: `analysis/pnl.py`, 전체 수치: `pnl.json`.", ""]
if not cc:
    L += [f"> 주의: {out['meta']['concept_note']}", ""]
L += [f"**결론(기준):** 2027 월매출 {e(b['years'][2027]['monthly']['revenue'])}만원, 영업이익률 {b['years'][2027]['op_margin']:.1%} → 2029 월매출 {e(b['years'][2029]['monthly']['revenue'])}만원, 영업이익률 {b['years'][2029]['op_margin']:.1%}. 손익분기 월매출 {e(b['years'][2027]['bep_monthly_revenue'])}만원(2027 매출의 {b['years'][2027]['bep_ratio']:.0%}), 투자 {b['investment']['total_excl_deposit']/1e8:.1f}억원(보증금 제외) 회수 {b['payback_years_pretax_ebitda']}년(세전 EBITDA). 회수기간 범위: " +  " / ".join(f"{n} {v}년" if v else f"{n} 20년+(3년 내 회수 불가)" for n, v in out['headline']['range_payback_years'].items()) + ".", ""]
L += ["## 1. 매출 교차검증 (2026 기준값, 2025Q3~2026Q2 상권 데이터)", "| 시나리오 | (A) 점유 방식 | (B) 거래건수 방식 | A/B 차이 | 채택(평균) | 상권 점유 | 평균 점포 대비 | 환산 일 결제(건) |", "|---|---|---|---|---|---|---|---|"]
for n, sc in out["scenarios"].items():
    r = sc["revenue_crosscheck_2026basis"]
    L.append(f"| {n} | {e(r['A_share_won_month'])} | {e(r['B_txn_won_month'])} | {r['gap_A_vs_B']:+.1%} | {e(r['used'])} | {r['implied_share_of_market']:.1%} | {r['implied_multiple_of_avg_store']:.1f}배 | {r['implied_daily_txn']} |")
L += ["", f"- (A) {b['revenue_crosscheck_2026basis']['A_formula']}", f"- (B) {b['revenue_crosscheck_2026basis']['B_formula']}",
      f"- 기준 시간대별 거래(건/일): {b['revenue_crosscheck_2026basis']['B_txn_by_daypart']} (시간대 비중 = concept.json 매장 시간대 계획[A], 상권 실측[D] 기반)",
      f"- 성장 가정 근거: 출점 적격 상권 3년 롤링 백테스트(기준시점 3개) 점수 상위20% 실제 CAGR {pct(g_top20)}, 전체 {pct(g_all)}, 하위20% {pct(g_bot20)} — 상권 평균이 역성장한 시기에도 상위 20%는 플러스.", ""]
L += ["## 2. 시나리오별 연도 P&L (월 평균, 만원)", "| 시나리오·연도 | 매출 | 원가 | 인건비 | 임대+관리 | 기타변동비 | EBITDA | 감가 | 영업이익 | 영업이익률 | BEP 월매출 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
for n, sc in out["scenarios"].items():
    for y, d in sc["years"].items():
        m = d["monthly"]; oth = m["card_fee"] + m["hq_fee"] + m["marketing"] + m["utilities"] + m["supplies"] + m["other"]
        L.append(f"| {n} {y} | {e(m['revenue'])} | {e(m['cogs'])} | {e(m['labor'])} | {e(m['rent']+m['mgmt_fee'])} | {e(oth)} | {e(m['ebitda'])} | {e(m['depreciation'])} | {e(m['op_income'])} | {d['op_margin']:.1%} | {e(d['bep_monthly_revenue'])} |")
L += ["", "## 3. 연간 요약·투자회수", "| 시나리오 | 2027 연매출(억) | 2029 연매출(억) | 2027 영업이익(억) | 2029 영업이익(억) | 투자(억, 보증금 제외) | 보증금(억) | 회수기간(년) |", "|---|---|---|---|---|---|---|---|"]
for n, sc in out["scenarios"].items():
    a7, a9 = sc["years"][2027]["annual"], sc["years"][2029]["annual"]
    pb = sc["payback_years_pretax_ebitda"]
    L.append(f"| {n} | {a7['revenue']/1e8:.1f} | {a9['revenue']/1e8:.1f} | {a7['op_income']/1e8:.2f} | {a9['op_income']/1e8:.2f} | {sc['investment']['total_excl_deposit']/1e8:.1f} | {sc['investment']['deposit_refundable']/1e8:.2f} | {pb if pb else '20년+'} |")
d7 = b["years"][2027]
L += ["", "## 4. 비용 구조(기준 2027)", f"- 원가 {d7['cogs_ratio']:.1%} · 인건비 {d7['labor_ratio']:.1%}(주 {d7['labor_hours_week']}h) · 임대+관리 {d7['rent_ratio']:.1%} · 카드·본사·마케팅·광열·소모품·기타 {sum(VAR.values()):.1%}",
      "- 아침(06~11시) 매출 비중 24.0%[D]: 출근 시간 회전이 손익의 핵심 — 오전 피크 PT를 집중 배치하고 베이커 생산을 05~07시 1차·14시 2차로 나눈다.", ""]
L += ["## 5. 가정표", "| 항목 | 값 | 구분 | 출처 |", "|---|---|---|---|"]
for a in out["assumptions"]:
    L.append(f"| {a['item']} | {a['value']} | {a['type']} | {a['source']} |")
L += ["", "## 6. 출처(외부)"] + [f"- {x}" for x in out["sources_external"]]
L += ["", "## 7. 한계", "- 상권 매출은 카드 기반 추정치라 현금·법인카드 일부가 빠질 수 있다(점유·배수 가정으로 보정).",
      "- 임대료는 서울 중대형 1층 평균(2025Q2)에 지수 상승과 입지 배수를 곱한 가정이다. 남부터미널·교대 1층 실거래 시세로 교체해야 한다.",
      "- 성장 가정은 백테스트 3개 기준시점 평균이라 표본이 작다(스피어만 0.23). 남부터미널 최근 YoY +14.4%는 기준 시나리오에 반영하지 않았다.",
      "- 법인세·이자는 제외(세전 영업이익·EBITDA 기준).", ""]
open(os.path.join(RES, "pnl.md"), "w", encoding="utf8").write("\n".join(L))
print("\n".join(L[:30]))
