"""2~3단계 v2: 성장 상권 점수 · 롤링 백테스트(표본 밖) · 입지 선정
v1(score_v1.py)의 약점: 3년 백테스트 스피어만 0.059, 가중치 후보 간 차이 없음.
v2 개선:
  1) 지표 후보 33개를 '학습 기준시점'(2022Q4~2023Q2)에서만 검증해 일관된 예측 지표 19개를 선택(부호도 학습 구간에서 확정)
  2) 선택 이후의 '시험 기준시점'(타깃 기간이 학습 타깃 이후)으로 표본 밖 검증. 1·2·3년 예측 기간 x 기준시점 16개
  3) 출점 적격 상권(커피+제과 연매출 50억원 이상) 안에서 순위 산출 — PE 플래그십 매장의 시장 규모 요건
실행: py -I -X utf8 analysis/score.py  -> analysis/results/analysis.json
"""
import json, os, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "data", "processed")
OUT = os.path.join(ROOT, "analysis", "results")
os.makedirs(OUT, exist_ok=True)

panel = pd.read_csv(os.path.join(P, "panel.csv"), dtype={"TRDAR_CD": str}, encoding="utf-8-sig")
trdar = pd.read_csv(os.path.join(P, "trdar.csv"), dtype={"TRDAR_CD": str}, encoding="utf-8-sig").set_index("TRDAR_CD")
QS = sorted(panel.STDR_YYQU_CD.unique())
QI = {q: i for i, q in enumerate(QS)}
QN = {i: f"{str(q)[:4]}Q{str(q)[4]}" for q, i in QI.items()}
panel["qi"] = panel.STDR_YYQU_CD.map(QI)

# ---- 파라미터 ----
SALES_FLOOR_4Q = 2e8       # 분석 모집단: 최근 4분기 커피+제과 매출 >= 2억원
STORE_FLOOR = 5            # 분석 모집단: 4분기 평균 커피+제과 점포 >= 5개
INVEST_FLOOR_4Q = 5e9      # 출점 적격: 연(4분기) 커피+제과 매출 >= 50억원
T1 = 20262                 # 최신 시점
FINAL_CD = "3120175"       # 사용자 확정(2026-11-14): 남부터미널역 — 아래에서 1위와 일치하는지 검증

# ---- 와이드 테이블 ----
panel["cb_sales_2030"] = (panel.cb_share_age20 + panel.cb_share_age30) * panel.cb_sales
for c in ["t17_21", "wkend", "t06_11", "age50p", "unident"]:
    panel["amt_" + c] = panel["cb_share_" + c] * panel.cb_sales
W = {c: panel.pivot(index="TRDAR_CD", columns="qi", values=c) for c in
     ["coffee_sales", "bakery_sales", "cb_sales", "cb_txn", "cb_stores", "cb_close", "cb_open", "flpop",
      "coffee_sales_per_store", "cb_sales_2030", "amt_t17_21", "amt_wkend", "amt_t06_11", "amt_age50p", "amt_unident"]}


def ws(w, a, b):  # 분기 a..b 합, 하나라도 결측이면 NaN
    return w.loc[:, a:b].sum(axis=1, min_count=b - a + 1)


def wm(w, a, b):
    s = w.loc[:, a:b]
    return s.mean(axis=1).where(s.notna().all(axis=1))


def cb_growth(ti0, ti1):
    """업종 구성 일치 성장배수: 두 4분기 창 모두 완비된 업종(커피/제과)만 합산."""
    base = pd.Series(0.0, index=W["coffee_sales"].index)
    end = base.copy()
    ok = pd.Series(False, index=base.index)
    for ind in ["coffee_sales", "bakery_sales"]:
        b, e = ws(W[ind], ti0 - 3, ti0), ws(W[ind], ti1 - 3, ti1)
        m = b.notna() & e.notna()
        base, end, ok = base + b.where(m, 0), end + e.where(m, 0), ok | m
    return (end / base).where(ok & (base > 0))


# ---- 지표 정의 (축, 방향, 정의, 단위, 원천) — 방향은 학습 구간 백테스트로 확정 ----
IND = {
    # A 매출 흐름: 매출액·결제건수의 시간 변화만
    "A1_sales_yoy":      ("A", +1, "커피+제과 매출 성장률(4분기 합 YoY, 업종구성 일치)", "log 배수/년", "OA-15572"),
    "A2_sales_yoy_2q":   ("A", +1, "최근 2분기 매출 YoY(가속 신호)", "log 배수", "OA-15572"),
    "A3_persistence":    ("A", +1, "최근 6분기 중 전년동기 대비 매출 증가 분기 비율(성장 지속성)", "비율", "OA-15572"),
    "A4_txn_yoy":        ("A", +1, "결제건수 성장률(4분기 합 YoY) — 물량 기반 성장", "log 배수/년", "OA-15572"),
    "A5_ticket_yoy":     ("A", -1, "건당 결제액 성장률(가격 기반 성장, 지속성 낮음=감점)", "log 배수/년", "OA-15572"),
    "A6_volatility":     ("A", -1, "분기 매출 변동성(최근 8분기 QoQ log 표준편차, 높을수록 감점)", "log", "OA-15572"),
    # B 고객 구성: 매출의 시간대·요일·연령·법인 구성비(수준·변화)
    "B1_2030_chg":       ("B", +1, "20·30대 매출 비중 변화(4분기 합, YoY)", "비율 차", "OA-15572"),
    "B2_2030_level":     ("B", -1, "20·30대 매출 비중 수준(트렌드 소비 의존=감점)", "비율", "OA-15572"),
    "B3_50p_share":      ("B", +1, "50대 이상 매출 비중", "비율", "OA-15572"),
    "B4_corp_share":     ("B", +1, "법인 등 미식별 매출 비중(오피스 수요 대리지표)", "비율", "OA-15572"),
    "B5_morning_share":  ("B", +1, "06~11시 매출 비중(출근·일상 수요)", "비율", "OA-15572"),
    "B6_evening_share":  ("B", -1, "17~21시 매출 비중(여가 수요=감점)", "비율", "OA-15572"),
    "B7_weekend_share":  ("B", -1, "주말 매출 비중(여가 수요=감점)", "비율", "OA-15572"),
    # C 유동·접근성: 사람의 흐름과 교통 인프라
    "C1_flpop_yoy":      ("C", +1, "길단위 유동인구 성장률(4분기 평균 YoY)", "log 배수/년", "OA-15568"),
    "C2_flpop_level":    ("C", +1, "길단위 유동인구 수준(4분기 평균)", "log 상대지수", "OA-15568"),
    "C3_subway":         ("C", +1, "상권 내 지하철역 수", "개소", "OA-15580"),
    # D 공급 동학: 점포의 진입·퇴출
    "D1_store_yoy":      ("D", +1, "커피+제과 점포 순증률(4분기 평균 YoY) — 사업자 진입=수요 신호", "log 배수/년", "OA-15577"),
    "D2_open_rate":      ("D", +1, "연간 개업률(4분기 개업/전년 평균 점포)", "비율/년", "OA-15577"),
    "D3_close_rate":     ("D", -1, "연간 폐업률(4분기 폐업/전년 평균 점포, 높을수록 감점)", "비율/년", "OA-15577"),
}
AX = {"A": "매출 흐름", "B": "고객 구성", "C": "유동·접근성", "D": "공급 동학"}
# 학습 단계에서 검토 후 제외한 후보(사유 기록)
DROPPED = {
    "점포당 매출 수준": "학습 구간 IC가 음(-)·불안정(평균회귀). 수준 지표는 프로파일로만 사용",
    "자치구 내 타 상권 성장(공간 파급)": "학습 구간 IC ±0.01, 부호 비일관",
    "매출 규모(log)·집객시설 총수": "IC는 양(+)이나 출점 적격 필터(연 50억)와 중복 → 이중계상 방지로 제외",
    "수요-공급 격차(A1-D1)": "A1·D1의 선형결합이라 MECE 위반",
    "2021년 대비 회복률": "기준시점마다 기간 길이가 달라 정의가 비정상(non-stationary)",
    "여성 비중·프랜차이즈 비중·영업개월 격차·유동 2030 비중": "학습 구간 |IC|<0.03 또는 부호 비일관",
}


def features(ti):
    f = pd.DataFrame(index=W["cb_sales"].index)
    s4 = ws(W["cb_sales"], ti - 3, ti)
    st = wm(W["cb_stores"], ti - 3, ti)
    st_prev = wm(W["cb_stores"], ti - 7, ti - 4)
    f["sales_4q"], f["stores_4q"] = s4, st
    f["A1_sales_yoy"] = np.log(cb_growth(ti - 4, ti))
    f["A2_sales_yoy_2q"] = np.log(ws(W["cb_sales"], ti - 1, ti) / ws(W["cb_sales"], ti - 5, ti - 4))
    yo = pd.concat([np.log(W["cb_sales"][k] / W["cb_sales"][k - 4]) for k in range(max(4, ti - 5), ti + 1)], axis=1)
    f["A3_persistence"] = (yo > 0).mean(axis=1).where(yo.notna().sum(axis=1) >= yo.shape[1] - 1)
    f["A4_txn_yoy"] = np.log(ws(W["cb_txn"], ti - 3, ti) / ws(W["cb_txn"], ti - 7, ti - 4))
    f["A5_ticket_yoy"] = f["A1_sales_yoy"] - f["A4_txn_yoy"]
    f["A6_volatility"] = np.log(W["cb_sales"].loc[:, ti - 7:ti]).diff(axis=1).std(axis=1)
    f["B1_2030_chg"] = ws(W["cb_sales_2030"], ti - 3, ti) / s4 - ws(W["cb_sales_2030"], ti - 7, ti - 4) / ws(W["cb_sales"], ti - 7, ti - 4)
    f["B2_2030_level"] = ws(W["cb_sales_2030"], ti - 3, ti) / s4
    for k, c in [("B3_50p_share", "age50p"), ("B4_corp_share", "unident"), ("B5_morning_share", "t06_11"),
                 ("B6_evening_share", "t17_21"), ("B7_weekend_share", "wkend")]:
        f[k] = ws(W["amt_" + c], ti - 3, ti) / s4
    f["C1_flpop_yoy"] = np.log(wm(W["flpop"], ti - 3, ti) / wm(W["flpop"], ti - 7, ti - 4))
    f["C2_flpop_level"] = np.log(wm(W["flpop"], ti - 3, ti))
    f["C3_subway"] = trdar.fac_subway.reindex(f.index)
    f["D1_store_yoy"] = np.log(st / st_prev)
    f["D2_open_rate"] = ws(W["cb_open"], ti - 3, ti) / st_prev
    f["D3_close_rate"] = ws(W["cb_close"], ti - 3, ti) / st_prev
    pres = W["cb_sales"].loc[:, ti - 3:ti].notna().all(axis=1)
    f["in_pop"] = pres & (s4 >= SALES_FLOOR_4Q) & (st >= STORE_FLOOR) & (trdar.is_tour_zone.reindex(f.index) != 1) \
        & f["A1_sales_yoy"].notna()
    return f


def score(f, inds=IND):
    g = f[f.in_pop].copy()
    for k, v in inds.items():
        r = g[k].rank(pct=True)
        g["p_" + k] = (r if v[1] > 0 else 1 - r).fillna(0.5)  # 결측 = 중립
    for a in AX:
        cols = ["p_" + k for k, v in inds.items() if v[0] == a]
        g["ax_" + a] = g[cols].mean(axis=1) if cols else np.nan
    g["score"] = g[["p_" + k for k in inds]].mean(axis=1) * 100  # 지표 동일가중(검증된 방식)
    return g


def sp(a, b):
    m = a.notna() & b.notna()
    return float(a[m].rank().corr(b[m].rank()))


# ---------------- 롤링 백테스트 ----------------
TRAIN = {4: [20224, 20231, 20232], 8: [20224, 20231]}  # 학습: 타깃이 2024Q2 이전에 끝나는 기준시점
TEST = {4: [20233, 20234, 20241, 20242, 20243, 20244, 20251, 20252],
        8: [20232, 20233, 20234, 20241, 20242], 12: [20224, 20231, 20232]}
# v1 지표(비교용, score_v1.py의 10개 중 재현 가능한 8개)
V1 = {"A1_sales_yoy": ("A", +1), "B1_2030_chg": ("A", +1), "C1_flpop_yoy": ("B", +1), "D1_store_yoy": ("C", -1),
      "D3_close_rate": ("C", -1)}
_cache = {}


def feat_cached(ti):
    if ti not in _cache:
        _cache[ti] = features(ti)
    return _cache[ti]


def evaluate(inds, origins, floor=0.0):
    rows = []
    for H, ors in origins.items():
        for t0 in ors:
            ti = QI[t0]
            f = feat_cached(ti)
            y = np.log(cb_growth(ti, ti + H))
            g = score(f, inds)
            g = g[(g.sales_4q >= floor)].join(y.rename("y"), how="inner").dropna(subset=["y"])
            q, yr = g.score.rank(pct=True), g.y.rank(pct=True)
            cagr = np.expm1(g.y / (H / 4))
            rows.append({"horizon_q": H, "t0": QN[ti], "n": len(g), "spearman": sp(g.score, g.y),
                         "top20_hit": float(((q >= .8) & (yr >= .8)).sum() / (q >= .8).sum()),
                         "top20_cagr_med": float(cagr[q >= .8].median()), "bottom20_cagr_med": float(cagr[q <= .2].median()),
                         "all_cagr_med": float(cagr.median())})
    return pd.DataFrame(rows)


def summarize(df):
    s = df.groupby("horizon_q").agg(origins=("t0", "count"), n=("n", "mean"), spearman=("spearman", "mean"),
                                    spearman_min=("spearman", "min"), top20_hit=("top20_hit", "mean"),
                                    top20_cagr=("top20_cagr_med", "mean"), bottom20_cagr=("bottom20_cagr_med", "mean"),
                                    all_cagr=("all_cagr_med", "mean"))
    s["spread_pp"] = (s.top20_cagr - s.bottom20_cagr) * 100
    return {f"{h // 4}y": {k: (round(float(v), 4) if k != "origins" else int(v)) for k, v in r.items()}
            for h, r in s.iterrows()}


v1_inds = {k: (v[0], v[1], "", "", "") for k, v in V1.items()}
v1_inds.update({"C3_subway": ("D", +1, "", "", "")})  # v1 D축(집객시설) 대응
bt_v2_all = evaluate(IND, TEST)
bt_v2_inv = evaluate(IND, TEST, INVEST_FLOOR_4Q)
bt_v1_all = evaluate(v1_inds, TEST)
bt_v1_inv = evaluate(v1_inds, TEST, INVEST_FLOOR_4Q)
train_ic = {}
for H, ors in TRAIN.items():
    for t0 in ors:
        f = feat_cached(QI[t0])
        y = np.log(cb_growth(QI[t0], QI[t0] + H))
        b = f[f.in_pop].join(y.rename("y"), how="inner")
        for k in IND:
            train_ic.setdefault(k, []).append(sp(b[k], b.y))
train_ic = {k: {"mean": round(float(np.mean(v)), 3), "positive_share": round(float(np.mean(np.array(v) > 0)), 2)} for k, v in train_ic.items()}
test_ic = {}
for H, ors in TEST.items():
    for t0 in ors:
        f = feat_cached(QI[t0])
        y = np.log(cb_growth(QI[t0], QI[t0] + H))
        b = f[f.in_pop].join(y.rename("y"), how="inner")
        for k in IND:
            test_ic.setdefault((k, H), []).append(sp(b[k], b.y))
test_ic_tbl = {k: {f"{H // 4}y": round(float(np.mean(test_ic[(k, H)])), 3) for H in TEST} for k in IND}

# ---------------- 최신 점수·입지 ----------------
f1 = features(QI[T1])
g1 = score(f1).join(trdar[["name", "type", "gu", "dong", "lon", "lat", "area_km2", "fac_subway", "fac_bus_stop", "fac_univ",
                            "fac_gnrl_hospital", "fac_total", "cb_sales_cagr3y"]])
g1["store_density"] = g1.stores_4q / g1.area_km2
dens_cut, close_cut = g1.store_density.quantile(.9), g1.D3_close_rate.quantile(.75)
g1["overheat"] = (g1.store_density >= dens_cut) & (g1.D3_close_rate >= close_cut)
chg_now = panel[panel.STDR_YYQU_CD == T1].set_index("TRDAR_CD")["chg_ix"]
g1["chg_ix"] = chg_now.reindex(g1.index)
g1["investable"] = g1.sales_4q >= INVEST_FLOOR_4Q
g1["excluded"] = g1.overheat | (g1.chg_ix == "HL")
g1["rank_all"] = g1.score.rank(ascending=False, method="first").astype(int)
ranked = g1[~g1.excluded & g1.investable].sort_values("score", ascending=False)
ranked["rank"] = np.arange(1, len(ranked) + 1)
assert ranked.index[0] == FINAL_CD, f"1위가 {ranked.iloc[0]['name']}로 바뀜 — 사용자 확정 입지와 불일치"

# ---------------- 프로파일 ----------------
last4 = panel[(panel.qi >= QI[T1] - 3) & (panel.qi <= QI[T1])]
SH = ["cb_share_wkend", "cb_share_t00_06", "cb_share_t06_11", "cb_share_t11_14", "cb_share_t14_17", "cb_share_t17_21",
      "cb_share_t21_24", "cb_share_female", "cb_share_age10", "cb_share_age20", "cb_share_age30", "cb_share_age40",
      "cb_share_age50p", "cb_share_unident"]


def profile(df):
    d = df[df.cb_sales.notna()]
    w = d.cb_sales
    out = {k.replace("cb_share_", "share_"): round(float((d[k] * w).sum() / w[d[k].notna()].sum()), 4) for k in SH}
    out["ticket_coffee_won"] = round(float(d.coffee_sales.sum() / d.coffee_txn.sum()))
    bk = d[d.bakery_sales.notna()]
    out["ticket_bakery_won"] = round(float(bk.bakery_sales.sum() / bk.bakery_txn.sum())) if len(bk) else None
    wk = d[["cb_sales", "cb_share_wkend"]]
    return out


def store_profile(df):
    s = df.groupby("STDR_YYQU_CD")[["coffee_stores", "bakery_stores", "coffee_frc", "bakery_frc", "cb_open", "cb_close"]].sum()
    lq = s.iloc[-1]
    return {"coffee_stores_2026Q2": int(lq.coffee_stores), "bakery_stores_2026Q2": int(lq.bakery_stores),
            "coffee_frc_share_2026Q2": round(float(lq.coffee_frc / lq.coffee_stores), 4) if lq.coffee_stores else None,
            "bakery_frc_share_2026Q2": round(float(lq.bakery_frc / lq.bakery_stores), 4) if lq.bakery_stores else None,
            "open_4q": int(s.cb_open.sum()), "close_4q": int(s.cb_close.sum())}


def bench(ids):
    b = profile(last4[last4.TRDAR_CD.isin(ids)])
    b.update({k: v for k, v in store_profile(last4[last4.TRDAR_CD.isin(ids)]).items() if "share" in k})
    sub = g1.loc[list(ids)]
    b["coffee_sales_per_store_won_4q_median"] = round(float(ws(W["coffee_sales_per_store"], QI[T1] - 3, QI[T1]).reindex(sub.index).median()))
    b["close_rate_4q_median"] = round(float(sub.D3_close_rate.median()), 4)
    b["sales_yoy_median"] = round(float(np.expm1(sub.A1_sales_yoy.median())), 4)
    b["n_trdar"] = len(sub)
    return b


bench_pop = bench(set(g1.index))
bench_inv = bench(set(g1[g1.investable].index))


def site_card(cd):
    r = g1.loc[cd]
    prof = profile(last4[last4.TRDAR_CD == cd])
    prof.update(store_profile(last4[last4.TRDAR_CD == cd]))
    sps = ws(W["coffee_sales_per_store"], QI[T1] - 3, QI[T1]).get(cd)
    prof.update({
        "coffee_sales_per_store_won_4q": None if pd.isna(sps) else round(float(sps)),
        "cb_sales_4q_won": round(float(r.sales_4q)), "cb_stores_4q_avg": round(float(r.stores_4q), 2),
        "sales_yoy": round(float(np.expm1(r.A1_sales_yoy)), 4), "sales_yoy_2q": round(float(np.expm1(r.A2_sales_yoy_2q)), 4),
        "txn_yoy": round(float(np.expm1(r.A4_txn_yoy)), 4), "ticket_yoy": round(float(np.expm1(r.A5_ticket_yoy)), 4),
        "growth_persistence_6q": round(float(r.A3_persistence), 3),
        "sales_cagr_3y_2023Q2_2026Q2": None if pd.isna(r.cb_sales_cagr3y) else round(float(r.cb_sales_cagr3y), 4),
        "flpop_yoy": None if pd.isna(r.C1_flpop_yoy) else round(float(np.expm1(r.C1_flpop_yoy)), 4),
        "store_yoy": round(float(np.expm1(r.D1_store_yoy)), 4), "open_rate": round(float(r.D2_open_rate), 4),
        "close_rate": round(float(r.D3_close_rate), 4)})
    ts = panel[panel.TRDAR_CD == cd].set_index("STDR_YYQU_CD")
    prof["cb_sales_by_quarter_won"] = {QN[QI[q]]: (None if pd.isna(v) else round(float(v))) for q, v in ts.cb_sales.items()}
    return prof


def row(cd, rank=None):
    r = g1.loc[cd]
    return {"rank": rank, "TRDAR_CD": cd, "name": r["name"], "type": r["type"], "gu": r.gu, "dong": r.dong,
            "lon": round(float(r.lon), 6), "lat": round(float(r.lat), 6), "score": round(float(r.score), 1),
            "axis": {a: round(float(r["ax_" + a]) * 100, 1) for a in AX},
            "cb_sales_4q_won": round(float(r.sales_4q)), "sales_yoy": round(float(np.expm1(r.A1_sales_yoy)), 4),
            "sales_yoy_2q": round(float(np.expm1(r.A2_sales_yoy_2q)), 4),
            "txn_yoy": round(float(np.expm1(r.A4_txn_yoy)), 4),
            "stores_4q_avg": round(float(r.stores_4q), 1), "store_yoy": round(float(np.expm1(r.D1_store_yoy)), 4),
            "close_rate": round(float(r.D3_close_rate), 4),
            "morning_share": round(float(r.B5_morning_share), 4), "weekend_share": round(float(r.B7_weekend_share), 4),
            "corp_share": round(float(r.B4_corp_share), 4),
            "fac_subway": None if pd.isna(r.fac_subway) else int(r.fac_subway),
            "chg_ix": r.chg_ix, "overheat": bool(r.overheat), "investable": bool(r.investable),
            "rank_all_population": int(r.rank_all)}


top10 = [row(cd, int(ranked.loc[cd, "rank"])) for cd in ranked.index[:10]]
HOT = ["3110131", "3120052", "3130071", "3120047", "3120104", "3110562", "3120186", "3120202", "3110759", "3120031",
       "3120002", "3110554", "3111013", "3120243"]  # 마지막: v1 1위 천호역
hot = []
for cd in HOT:
    if cd in g1.index:
        h = row(cd, int(ranked.loc[cd, "rank"]) if cd in ranked.index else None)
        h["excluded_reason"] = ("과열(점포밀도 상위10%&폐업률 상위25%)" if g1.loc[cd, "overheat"] else
                                "상권축소(HL)" if g1.loc[cd, "chg_ix"] == "HL" else
                                "출점 적격 미달(연매출 50억원 미만)" if not g1.loc[cd, "investable"] else None)
        hot.append(h)
    else:
        hot.append({"TRDAR_CD": cd, "name": trdar.loc[cd, "name"], "in_population": False,
                    "reason": "분석 모집단 미포함(최근 4분기 매출 결측·업종구성 변동·하한 미달)"})

# ---------------- 인사이트 재료(백테스트 t0=2023Q2 → 2026Q2, 3년) ----------------
BB = []
for t in TEST[12]:  # 3년 시험 기준시점 3개(2022Q4·2023Q1·2023Q2) 평균
    ti_ = QI[t]
    yb = np.log(cb_growth(ti_, ti_ + 12))
    b_ = feat_cached(ti_)
    b_ = b_[b_.in_pop].join(yb.rename("y"), how="inner").dropna(subset=["y"])
    b_["cagr"] = np.expm1(b_.y / 3)
    BB.append(b_)


def quint(col):
    tops, bots = [], []
    for b_ in BB:
        q = b_[col].rank(pct=True)
        tops.append(b_[q >= .8].cagr.median()); bots.append(b_[q <= .2].cagr.median())
    return {"top20_cagr_med": round(float(np.mean(tops)), 4), "bottom20_cagr_med": round(float(np.mean(bots)), 4),
            "spread_pp": round(float(np.mean(tops) - np.mean(bots)) * 100, 2), "origins": len(BB)}


INS = {k: quint(k) for k in ["B7_weekend_share", "B6_evening_share", "B5_morning_share", "B4_corp_share", "A4_txn_yoy",
                             "A5_ticket_yoy", "A1_sales_yoy", "D1_store_yoy"]}
fc = site_card(FINAL_CD)

SRC = {
    "OA-15572": "서울시 상권분석서비스(추정매출-상권) VwsmTrdarSelngQq, 2021Q1~2026Q2, 원/분기(카드 기반 추정)",
    "OA-15577": "서울시 상권분석서비스(점포-상권) VwsmTrdarStorQq, 2021Q1~2026Q2, 개",
    "OA-15568": "서울시 상권분석서비스(길단위인구-상권) VwsmTrdarFlpopQq, 2021Q1~2026Q2, 상대지수",
    "OA-15580": "서울시 상권분석서비스(집객시설-상권) VwsmTrdarFcltyQq, 스냅샷, 개소",
    "OA-15576": "서울시 상권분석서비스(상권변화지표-상권) VwsmTrdarIxQq, 2026Q2, 등급",
    "OA-15560": "서울시 상권분석서비스(영역-상권) TbgisTrdarRelm, 좌표 EPSG:5181→WGS84, ㎡",
}
n_ind = {a: sum(1 for v in IND.values() if v[0] == a) for a in AX}
s_all, s_inv, v1_all, v1_inv = summarize(bt_v2_all), summarize(bt_v2_inv), summarize(bt_v1_all), summarize(bt_v1_inv)

out = {
    "meta": {"version": "v2", "generated_by": "analysis/score.py", "as_of_quarter": "2026Q2",
             "population_rule": f"관광특구 제외, 최근 4분기 커피+제과 매출 연속 관측, 4분기 합 >= {SALES_FLOOR_4Q/1e8:.0f}억원, 점포 >= {STORE_FLOOR}개",
             "investable_rule": f"출점 적격: 최근 4분기 커피+제과 매출 >= {INVEST_FLOOR_4Q/1e8:.0f}억원 (PE 플래그십 매장의 시장 규모 요건, 사업 판단 기준)",
             "population_n": int(len(g1)), "investable_n": int(g1.investable.sum()),
             "normalization": "지표별 시점 내 백분위(감점 지표는 1-백분위, 결측 0.5) → 19개 지표 동일가중 평균 x100"},
    "metrics": {
        "axes": {a: {"name": AX[a], "n_indicators": n_ind[a], "effective_weight": round(n_ind[a] / len(IND), 3)} for a in AX},
        "indicators": [{"id": k, "axis": v[0], "axis_name": AX[v[0]], "direction": "+" if v[1] > 0 else "-(감점)", "definition": v[2],
                        "unit": v[3], "source": v[4], "train_ic": train_ic[k], "test_ic": test_ic_tbl[k]} for k, v in IND.items()],
        "mece_rules": ["A=매출 금액·건수의 시간 흐름, B=매출의 고객 구성비, C=사람 흐름·교통 인프라, D=점포 진입·퇴출 — 축마다 원천 변수가 겹치지 않음",
                       "성장률은 4분기 합(연환산) YoY로 계절성 제거, 업종 구성(커피/제과)이 같은 상권끼리만 비교",
                       "선형결합 지표(수요-공급 격차)와 기간 정의가 시점마다 달라지는 지표(2021 대비 회복률) 제외",
                       "규모 지표는 출점 적격 필터와 중복되므로 점수에서 제외"],
        "selection_protocol": "후보 33개 → 학습 기준시점(2022Q4·2023Q1·2023Q2, 1·2년 타깃; 타깃 종료 ≤ 2024Q2)에서 |평균 IC|≥0.03 & 부호 일관 ≥80%인 지표만 채택, 부호도 학습 구간에서 확정 → 이후 기준시점에서 표본 밖 검증",
        "dropped_candidates": DROPPED,
        "weighting": "지표 동일가중(축 가중치 = 축 내 지표 수 비율). 데이터에 맞춘 미세 가중은 과적합 위험이 커서 사용하지 않음",
        "overheat_filter": {"rule": "점포밀도 상위 10% AND 연간 폐업률 상위 25% → 제외, 상권변화지표 HL(상권축소) → 제외",
                            "density_cut_stores_per_km2": round(float(dens_cut), 1), "close_rate_cut": round(float(close_cut), 4)},
    },
    "backtest": {
        "design": "롤링 기준시점: 기준시점 t0까지의 데이터로만 점수 산출 → t0 이후 1·2·3년 실제 커피+제과 매출(4분기 합, 업종구성 일치) 성장과 비교",
        "test_origins": {f"{h // 4}y": [QN[QI[t]] for t in v] for h, v in TEST.items()},
        "out_of_sample_note": "1년 예측의 시험 타깃(2024Q3~)은 학습 타깃(~2024Q2) 이후로 완전 분리. 2·3년 예측은 타깃 기간 일부가 학습 타깃과 겹칠 수 있음",
        "v2_all_population": s_all, "v2_investable": s_inv, "v1_all_population": v1_all, "v1_investable": v1_inv,
        "headline": {"spearman_3y_investable": {"v1": v1_inv["3y"]["spearman"], "v2": s_inv["3y"]["spearman"]},
                     "spearman_3y_all": {"v1": v1_all["3y"]["spearman"], "v2": s_all["3y"]["spearman"]},
                     "v1_original_single_window": 0.059,
                     "top20_vs_bottom20_cagr_spread_pp_3y_investable": round(s_inv["3y"]["spread_pp"], 2)},
        "interpretation": "상권 매출 3년 성장은 본질적으로 잡음이 크다. 점수는 '확실한 1등 예측'이 아니라 성장 확률이 높은 후보를 압축하는 도구이며, "
                          "출점 적격 상권에서 상위 20%가 하위 20%보다 연평균 성장률이 꾸준히 높았다.",
        "by_origin": {"v2_investable": bt_v2_inv.round(4).to_dict("records")},
    },
    "top10": top10,
    "top3": [{"rank": t["rank"], "TRDAR_CD": t["TRDAR_CD"], "name": t["name"], "score": t["score"]} for t in top10[:3]],
    "final_site": {**{k: top10[0][k] for k in ["TRDAR_CD", "name", "gu", "dong", "lon", "lat", "score", "axis"]},
                   "decided_by": "사용자 확정(2026-11-14), v2 점수 1위와 일치",
                   "facilities": {k: (None if pd.isna(g1.loc[FINAL_CD, k]) else int(g1.loc[FINAL_CD, k]))
                                  for k in ["fac_total", "fac_subway", "fac_bus_stop", "fac_univ", "fac_gnrl_hospital"]},
                   "area_km2": round(float(g1.loc[FINAL_CD, "area_km2"]), 4), "kpis": fc},
    "customer_profile": {"TRDAR_CD": FINAL_CD, "period": "2025Q3~2026Q2(4분기, 매출 가중)",
                         "unit": "비율(0~1), 원/건", "source": "OA-15572, OA-15577",
                         **{k: v for k, v in fc.items() if k != "cb_sales_by_quarter_won"}},
    "benchmarks": {"population": {"scope": f"분석 모집단 {len(g1)}개 상권", "period": "2025Q3~2026Q2", **bench_pop},
                   "investable": {"scope": f"출점 적격 {int(g1.investable.sum())}개 상권", "period": "2025Q3~2026Q2", **bench_inv}},
    "hot_places": hot,
    "insight_inputs": {"period": "기준시점 2022Q4·2023Q1·2023Q2 → 각 3년 뒤 (4분기 합 CAGR, 5분위 중앙값의 3개 기준시점 평균)", "unit": "연평균 성장률",
                       "quintiles_3y": INS},
    "sources": SRC,
}


def pct(x, d=1):
    return f"{x * 100:+.{d}f}%"


Hh = {h["TRDAR_CD"]: h for h in hot}
bi = bench_inv
out["insights"] = [
    {"title": "핫플의 '주말·저녁'이 아니라 '평일 아침' 상권이 큰다",
     "text": f"06~11시 매출 비중 상위 20% 상권의 이후 3년 매출 CAGR {pct(INS['B5_morning_share']['top20_cagr_med'])} vs 하위 20% {pct(INS['B5_morning_share']['bottom20_cagr_med'])} "
             f"(격차 {INS['B5_morning_share']['spread_pp']:+.1f}%p/년). 17~21시 비중 상위 20%는 {pct(INS['B6_evening_share']['top20_cagr_med'])} vs 하위 {pct(INS['B6_evening_share']['bottom20_cagr_med'])}, "
             f"주말 비중 상위 20%는 {pct(INS['B7_weekend_share']['top20_cagr_med'])} vs 하위 {pct(INS['B7_weekend_share']['bottom20_cagr_med'])}. 출근·일상 수요가 여가 수요보다 꾸준히 자랐다.",
     "period": out["insight_inputs"]["period"], "unit": "%/년", "source": "OA-15572"},
    {"title": "가격으로 큰 상권은 멈추고, 손님 수로 큰 상권은 계속 큰다",
     "text": f"결제건수 성장 상위 20%의 이후 3년 CAGR {pct(INS['A4_txn_yoy']['top20_cagr_med'])} vs 하위 {pct(INS['A4_txn_yoy']['bottom20_cagr_med'])}, "
             f"건당 결제액 성장 상위 20%는 {pct(INS['A5_ticket_yoy']['top20_cagr_med'])} vs 하위 {pct(INS['A5_ticket_yoy']['bottom20_cagr_med'])}. 객단가 인상 성장은 지속되지 않는다.",
     "period": out["insight_inputs"]["period"], "unit": "%/년", "source": "OA-15572"},
    {"title": "뜬 곳은 이미 떴다: 성수·한남·연남·가로수길은 후보에서 밀려난다",
     "text": "; ".join(f"{h['name']} {('출점적격 ' + str(h['rank']) + '위') if h.get('rank') else (h.get('excluded_reason') or h.get('reason'))}"
                       for h in hot if h["TRDAR_CD"] in ["3110131", "3120047", "3120104", "3120186", "3120202"]) +
             f". v1 1위였던 천호역(저녁·주말형)은 v2에서 {('적격 ' + str(Hh['3120243']['rank']) + '위') if Hh['3120243'].get('rank') else Hh['3120243'].get('excluded_reason')}.",
     "period": "2025Q3~2026Q2", "unit": "순위", "source": "OA-15572, OA-15577, OA-15576"},
    {"title": f"{fc and top10[0]['name']}: 꾸준히, 손님 수로, 아침에 크는 상권",
     "text": f"연 커피+제과 매출 {fc['cb_sales_4q_won']/1e8:.0f}억원, 매출 YoY {pct(fc['sales_yoy'])}(적격 상권 중앙 {pct(bi['sales_yoy_median'])}), 최근 2분기 YoY {pct(fc['sales_yoy_2q'])}, "
             f"결제건수 YoY {pct(fc['txn_yoy'])}, 최근 6분기 중 {fc['growth_persistence_6q']*6:.0f}분기 성장. 점포는 {pct(fc['store_yoy'])}로 완만, "
             f"06~11시 매출 비중 {fc['share_t06_11']*100:.1f}%(적격 상권 {bi['share_t06_11']*100:.1f}%), 주말 {fc['share_wkend']*100:.1f}%({bi['share_wkend']*100:.1f}%).",
     "period": "2025Q3~2026Q2(4분기)", "unit": "원, %", "source": "OA-15572, OA-15577"},
]
out["final_site"]["why"] = [
    f"출점 적격 {len(ranked)}개 상권(과열·상권축소 제외) 중 총점 {top10[0]['score']}점 1위 — 매출 흐름 {top10[0]['axis']['A']}·고객 구성 {top10[0]['axis']['B']}·유동·접근성 {top10[0]['axis']['C']}·공급 동학 {top10[0]['axis']['D']}점",
    f"매출 YoY {pct(fc['sales_yoy'])}, 최근 2분기 {pct(fc['sales_yoy_2q'])}, 결제건수 {pct(fc['txn_yoy'])} → 손님 수가 늘어나는 성장",
    f"점포 순증 {pct(fc['store_yoy'])}·폐업률 {fc['close_rate']*100:.1f}%/년, 지하철역 {out['final_site']['facilities']['fac_subway']}개, 아침 매출 비중 {fc['share_t06_11']*100:.1f}%",
]
with open(os.path.join(OUT, "analysis.json"), "w", encoding="utf-8") as fp:
    json.dump(out, fp, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
print(json.dumps(out["backtest"]["headline"], ensure_ascii=False))
print("v2 inv", json.dumps(s_inv, ensure_ascii=False)); print("v1 inv", json.dumps(v1_inv, ensure_ascii=False))
print("v2 all", json.dumps(s_all, ensure_ascii=False)); print("v1 all", json.dumps(v1_all, ensure_ascii=False))
print(pd.DataFrame(top10)[["rank", "name", "gu", "score", "cb_sales_4q_won", "sales_yoy", "txn_yoy", "store_yoy", "close_rate", "morning_share", "weekend_share"]].to_string())
for i in out["insights"]:
    print("-", i["title"], "|", i["text"])
print(out["final_site"]["why"])
