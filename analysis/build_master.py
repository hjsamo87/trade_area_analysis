"""1단계 데이터 정비: data/raw/*.csv -> data/processed/
  panel.csv     상권(TRDAR_CD) x 분기(STDR_YYQU_CD) 패널
                (커피·제과 매출/점포, 4분기 롤링 기반값, 유동·상주인구, 상권변화지표, 품질 플래그)
  trdar.csv     상권 마스터 (이름·유형·자치구·행정동·좌표·면적, 정적 집객시설, 3년 성장 기반값·관측 커버리지)
  coverage.json 데이터셋별 출처·수집일·api_total·분기 범위·상권 수·결측·품질 점검 리포트
실행: py -I -X utf8 analysis/build_master.py

원칙
  - 패널 키 = (TRDAR_CD, STDR_YYQU_CD). 커피+제과 합산(cb_*)과 업종별(coffee_*, bakery_*) 모두 유지.
  - '행 없음'(추정 불가·비공개)을 0으로 채우지 않는다. 매출은 NaN + *_present 플래그.
    (예외: 점포 데이터에서 같은 상권·분기에 다른 업종 행은 있는데 한 업종 행만 없으면 그 업종 점포 0 — 감사 근거)
  - 성장률(CAGR)은 4분기 합/평균 기준. 기준 창 = 20223~20232, 비교 창 = 20253~20262 (코로나 회복기 2021~2023Q1 제외).
  - 백테스트(원천이 20211부터라 3년 피처 창 불가): BT1 피처 = 4q@20214 -> 4q@20232 (1.5년, 연율화),
    타깃 = A1과 동일 4q@20232 -> 4q@20262. 보조로 1년 롤링 오리진(panel *_4q, *_present_4q로 계산).
  - 창 상태: ok / composition_change / exit(기준 창 완비, 매출 시계열이 비교 끝 분기 전에 끊김) /
    entry(비교 창 완비, 첫 관측이 기준 창 시작 이후) / gap(그 밖의 결측). exit는 버리지 말고 타깃의 쇠퇴 범주로 쓴다.
"""
import json, os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW, OUT = os.path.join(ROOT, "data", "raw"), os.path.join(ROOT, "data", "processed")
os.makedirs(OUT, exist_ok=True)
KEY = ["TRDAR_CD", "STDR_YYQU_CD"]
SVC = {"CS100010": "coffee", "CS100005": "bakery"}
SVCS = ["coffee", "bakery"]

# 3년 성장 창 (4분기 롤링 값의 끝 분기)
BASE_Q, END_Q, YEARS = "20232", "20262", 3
BASE_WIN = ["20223", "20224", "20231", "20232"]
END_WIN = ["20253", "20254", "20261", "20262"]
# 백테스트 피처 창 (BT1): 4q@20214(20211~20214) -> 4q@20232(20223~20232), 6분기 = 1.5년
BT0_Q, BT_FEAT_YEARS = "20214", 1.5
SALES_FLOOR_4Q = 40_000_000         # 기준 창 4분기 합 하한(분기 1,000만원 x 4) - 플래그용
FRC_BREAK_Q = "20254"                # 커피 프랜차이즈 재분류 단절 분기(감사 실측)

DATASETS = {  # API 서비스명 -> (열린데이터광장 데이터셋 ID, 서비스명)
    "VwsmTrdarSelngQq": ("OA-15572", "서울시 상권분석서비스(추정매출-상권)"),
    "VwsmTrdarStorQq": ("OA-15577", "서울시 상권분석서비스(점포-상권)"),
    "VwsmTrdarFlpopQq": ("OA-15568", "서울시 상권분석서비스(길단위인구-상권)"),
    "VwsmTrdarRepopQq": ("OA-15584", "서울시 상권분석서비스(상주인구-상권)"),
    "VwsmTrdarFcltyQq": ("OA-15580", "서울시 상권분석서비스(집객시설-상권)"),
    "VwsmTrdarIxQq": ("OA-15576", "서울시 상권분석서비스(상권변화지표-상권)"),
    "TbgisTrdarRelm": ("OA-15560", "서울시 상권분석서비스(영역-상권)"),
}
missing = [d for d in DATASETS if not os.path.exists(os.path.join(RAW, d + ".csv"))]
if missing:
    raise SystemExit(f"data/raw에 없는 데이터셋: {missing} -> py -I -X utf8 analysis/fetch.py {' '.join(missing)}")


def load(name):
    return pd.read_csv(os.path.join(RAW, name + ".csv"), dtype={"TRDAR_CD": str, "STDR_YYQU_CD": str})


def qrange(a, b):
    out, y, q = [], int(a[:4]), int(a[4])
    while f"{y}{q}" <= b:
        out.append(f"{y}{q}")
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


coverage = {}


def cover(name, d, **extra):
    q = sorted(d["STDR_YYQU_CD"].unique()) if "STDR_YYQU_CD" in d else []
    meta_p = os.path.join(RAW, f"_meta_{name}.json")
    meta = json.load(open(meta_p, encoding="utf-8")) if os.path.exists(meta_p) else {}
    did, title = DATASETS[name]
    coverage[name] = {
        "source": {"portal": "서울 열린데이터광장", "dataset_id": did, "title": title, "api_service": name,
                   "url": f"https://data.seoul.go.kr/dataList/{did}/S/1/datasetView.do",
                   "fetched": meta.get("fetched"), "api_total": meta.get("api_total"),
                   "saved_rows": meta.get("saved"), "meta_quarters": meta.get("quarters")},
        "rows": len(d),
        "trdar": int(d["TRDAR_CD"].nunique()),
        "quarters": [q[0], q[-1]] if q else None,
        "n_quarters": len(q),
        "dup_keys": int(d.duplicated([c for c in KEY + ["SVC_INDUTY_CD"] if c in d]).sum()),
        "null_cells": int(d.isna().sum().sum()),
    }
    if q:
        by = [c for c in ["SVC_INDUTY_CD"] if c in d]
        if by:
            coverage[name]["per_quarter_trdar"] = {
                SVC.get(k, k): v.groupby("STDR_YYQU_CD")["TRDAR_CD"].nunique().to_dict() for k, v in d.groupby(by[0])}
        else:
            coverage[name]["per_quarter_trdar"] = d.groupby("STDR_YYQU_CD")["TRDAR_CD"].nunique().to_dict()
    coverage[name].update(extra)


def wide(series):
    """KEY 인덱스 Series -> TRDAR_CD x 전체 분기(QS) 격자. 빠진 분기는 NaN(연속 분기 보장)."""
    return series.unstack("STDR_YYQU_CD").reindex(columns=QS)


def roll(w, how, n=4):
    r = w.T.rolling(n, min_periods=n)
    return (r.sum() if how == "sum" else r.mean()).T


def long(w, name):
    """격자 -> KEY 인덱스 Series (결합은 left join이라 격자에만 있는 키는 버려짐)."""
    return w.stack().rename(name)


def qstats(x):
    x = pd.Series(x).dropna()
    return {k: round(float(x.quantile(p)), 4) for k, p in
            [("min", 0), ("p01", .01), ("p25", .25), ("median", .5), ("p75", .75), ("p99", .99), ("max", 1)]}


def i(x):
    return int(x)


# ---- 상권 마스터 -------------------------------------------------------------
relm = load("TbgisTrdarRelm")
relm["SIGNGU_CD"] = relm["SIGNGU_CD"].astype(str)
relm["ADSTRD_CD"] = relm["ADSTRD_CD"].astype(str)
trdar = relm[["TRDAR_CD", "TRDAR_CD_NM", "TRDAR_SE_CD", "TRDAR_SE_CD_NM", "SIGNGU_CD", "SIGNGU_CD_NM",
              "ADSTRD_CD", "ADSTRD_CD_NM", "XCNTS_VALUE", "YDNTS_VALUE", "RELM_AR"]].rename(columns={
    "TRDAR_CD_NM": "name", "TRDAR_SE_CD": "type_cd", "TRDAR_SE_CD_NM": "type", "SIGNGU_CD": "gu_cd",
    "SIGNGU_CD_NM": "gu", "ADSTRD_CD": "dong_cd", "ADSTRD_CD_NM": "dong",
    "XCNTS_VALUE": "x_epsg5181", "YDNTS_VALUE": "y_epsg5181", "RELM_AR": "area_m2"})
trdar["area_km2"] = trdar["area_m2"] / 1e6
trdar["is_tour_zone"] = (trdar["type"] == "관광특구").astype(int)


def tm5181_to_wgs84(x, y):
    """EPSG:5181(Korea 2000 Central Belt, GRS80, 원점 38N 127E, FE 200000, FN 500000) 역투영 (Snyder TM 공식)."""
    a, f = 6378137.0, 1 / 298.257222101
    e2 = f * (2 - f); ep2 = e2 / (1 - e2); k0 = 1.0
    lat0, lon0, FE, FN = np.radians(38.0), np.radians(127.0), 200000.0, 500000.0
    c0 = 1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256
    def M(p):
        return a * (c0 * p - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * np.sin(2 * p)
                    + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * np.sin(4 * p) - (35 * e2**3 / 3072) * np.sin(6 * p))
    mu = (M(lat0) + (np.asarray(y, float) - FN) / k0) / (a * c0)
    e1 = (1 - np.sqrt(1 - e2)) / (1 + np.sqrt(1 - e2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1**3 / 32) * np.sin(2 * mu) + (21 * e1**2 / 16 - 55 * e1**4 / 32) * np.sin(4 * mu)
          + (151 * e1**3 / 96) * np.sin(6 * mu) + (1097 * e1**4 / 512) * np.sin(8 * mu))
    C1, T1 = ep2 * np.cos(p1)**2, np.tan(p1)**2
    N1 = a / np.sqrt(1 - e2 * np.sin(p1)**2)
    R1 = a * (1 - e2) / (1 - e2 * np.sin(p1)**2)**1.5
    D = (np.asarray(x, float) - FE) / (N1 * k0)
    lat = p1 - (N1 * np.tan(p1) / R1) * (D**2 / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1**2 - 9 * ep2) * D**4 / 24
                                         + (61 + 90 * T1 + 298 * C1 + 45 * T1**2 - 252 * ep2 - 3 * C1**2) * D**6 / 720)
    lon = lon0 + (D - (1 + 2 * T1 + C1) * D**3 / 6
                  + (5 - 2 * C1 + 28 * T1 - 3 * C1**2 + 8 * ep2 + 24 * T1**2) * D**5 / 120) / np.cos(p1)
    return np.degrees(lon), np.degrees(lat)


trdar["lon"], trdar["lat"] = tm5181_to_wgs84(trdar["x_epsg5181"], trdar["y_epsg5181"])
trdar[["lon", "lat"]] = trdar[["lon", "lat"]].round(6)

# ---- 매출: 커피·제과 각각 + 합계, 고객 구성 비중 ------------------------------
s = load("VwsmTrdarSelngQq")
s["svc"] = s["SVC_INDUTY_CD"].map(SVC)
QS = qrange(s["STDR_YYQU_CD"].min(), s["STDR_YYQU_CD"].max())
# 행 단위 품질 플래그 (pivot 전에)
s["ticket"] = s["THSMON_SELNG_AMT"] / s["THSMON_SELNG_CO"].where(s["THSMON_SELNG_CO"] > 0)
s["flag_low_txn"] = s["THSMON_SELNG_CO"] < 100
s["flag_round_amt"] = (s["THSMON_SELNG_AMT"] % 1_000_000) == 0
tq = s.groupby("svc")["ticket"].quantile([.01, .99]).unstack()
s["flag_ticket_out"] = (s["ticket"] < s["svc"].map(tq[0.01])) | (s["ticket"] > s["svc"].map(tq[0.99]))
s["flag_dup_value"] = s.duplicated(["TRDAR_CD", "SVC_INDUTY_CD", "THSMON_SELNG_AMT", "THSMON_SELNG_CO"], keep=False)
FLAGS = ["flag_low_txn", "flag_round_amt", "flag_ticket_out", "flag_dup_value"]

base = s.pivot_table(index=KEY, columns="svc", values=["THSMON_SELNG_AMT", "THSMON_SELNG_CO"], aggfunc="sum")
base.columns = [f"{svc}_{'sales' if v.endswith('AMT') else 'txn'}" for v, svc in base.columns]
for v in SVCS:  # pivot NaN = 행 없음(추정 불가·비공개). 0으로 채우지 않는다.
    base[f"{v}_present"] = base[f"{v}_sales"].notna().astype(int)
pivot_nan = {c: i(base[c].isna().sum()) for c in ["coffee_sales", "bakery_sales"]}

# 고객 구성 비중 (커피+제과 합산). 분모를 구성 그룹별로 분리:
#   시간대·요일 = 총액(6개 시간대 합 = 총액, 주중+주말 = 총액 정확히 일치)
#   성별 = 남+여 합, 연령 = 6개 연령대 합 (총액과의 차이 = 성별·연령 미식별 법인 매출, OA-15572 FAQ)
g = s.groupby(KEY)
tot = g["THSMON_SELNG_AMT"].sum()
gsum = g["ML_SELNG_AMT"].sum() + g["FML_SELNG_AMT"].sum()
AGE = {"age10": ["AGRDE_10_SELNG_AMT"], "age20": ["AGRDE_20_SELNG_AMT"], "age30": ["AGRDE_30_SELNG_AMT"],
       "age40": ["AGRDE_40_SELNG_AMT"], "age50p": ["AGRDE_50_SELNG_AMT", "AGRDE_60_ABOVE_SELNG_AMT"]}
asum = g[[c for cs in AGE.values() for c in cs]].sum().sum(axis=1)
TIME = {"wkend": ["WKEND_SELNG_AMT"], "t00_06": ["TMZON_00_06_SELNG_AMT"], "t06_11": ["TMZON_06_11_SELNG_AMT"],
        "t11_14": ["TMZON_11_14_SELNG_AMT"], "t14_17": ["TMZON_14_17_SELNG_AMT"],
        "t17_21": ["TMZON_17_21_SELNG_AMT"], "t21_24": ["TMZON_21_24_SELNG_AMT"]}
mix = {f"cb_share_{k}": g[c].sum().sum(axis=1) / tot for k, c in TIME.items()}
mix["cb_share_female"] = g["FML_SELNG_AMT"].sum() / gsum.where(gsum > 0)
mix.update({f"cb_share_{k}": g[c].sum().sum(axis=1) / asum.where(asum > 0) for k, c in AGE.items()})
mix["cb_share_unident"] = (1 - gsum / tot).clip(lower=0)
mix = pd.DataFrame(mix)
qflags = g[FLAGS].any().astype(int).rename(columns=lambda c: "sales_" + c)
qflags["sales_flag_any"] = qflags.max(axis=1)

sales = base.join(mix).join(qflags)
sales["cb_sales"] = sales[["coffee_sales", "bakery_sales"]].sum(axis=1, min_count=1)
sales["cb_txn"] = sales[["coffee_txn", "bakery_txn"]].sum(axis=1, min_count=1)
sales["cb_ticket"] = sales["cb_sales"] / sales["cb_txn"]
for v in SVCS:
    sales[f"{v}_ticket"] = sales[f"{v}_sales"] / sales[f"{v}_txn"]

# 4분기 롤링 합 (연속 4분기가 모두 있을 때만; 분기 격자 reindex로 공백 시 NaN)
W = {c: wide(sales[c]) for c in ["cb_sales", "coffee_sales", "bakery_sales"]}
for v in SVCS:
    W[f"{v}_present"] = wide(sales[f"{v}_present"]).fillna(0)
R = {f"{c}_4q": roll(W[c], "sum") for c in ["cb_sales", "coffee_sales", "bakery_sales"]}
R.update({f"{v}_present_4q": roll(W[f"{v}_present"], "sum") for v in SVCS})
sales = sales.join(pd.concat([long(R[c], c) for c in ["cb_sales_4q", "coffee_sales_4q", "bakery_sales_4q"]], axis=1))

# 매출 커버리지·품질 리포트
gs_ratio = (s["ML_SELNG_AMT"] + s["FML_SELNG_AMT"]) / s["THSMON_SELNG_AMT"]


def series_cov(w):
    obs = w.notna()
    obs = obs[obs.any(axis=1)]  # 해당 업종 관측이 1개 이상인 상권만
    n = obs.sum(axis=1)
    first =obs.idxmax(axis=1).map(QS.index); last = obs.iloc[:, ::-1].idxmax(axis=1).map(QS.index)
    gap = (last - first + 1 - n)
    return {"trdar": i((n > 0).sum()), "complete_22q": i((n == len(QS)).sum()),
            "with_internal_gap": i((gap > 0).sum()), "internal_gap_quarters": i(gap.sum()),
            "late_start": i((first > 0).sum()), "early_end": i((last < len(QS) - 1).sum())}


cover("VwsmTrdarSelngQq", s, filter="SVC_INDUTY_CD in CS100010(커피-음료), CS100005(제과점)",
      unit_note="THSMON_SELNG_AMT: 필드명은 '당월'이나 데이터셋은 분기(Qq). OA-15572 FAQ '분기당 매출 금액은 개인+법인 매출 합산' -> 원/분기(추정)",
      pivot_nan_cells=pivot_nan, panel_keys=len(sales),
      series=dict(coffee=series_cov(wide(sales["coffee_sales"])), bakery=series_cov(wide(sales["bakery_sales"])),
                  cb=series_cov(W["cb_sales"])),
      gender_sum_over_total=qstats(gs_ratio),
      gender_sum_exact_rows=i((s["ML_SELNG_AMT"] + s["FML_SELNG_AMT"] == s["THSMON_SELNG_AMT"]).sum()),
      gender_sum_gt_total_rows=i((gs_ratio > 1).sum()),
      time6_sum_equals_total_rows=i((s.filter(regex=r"^TMZON_.*_SELNG_AMT$").sum(axis=1) == s["THSMON_SELNG_AMT"]).sum()),
      mdwk_wkend_equals_total_rows=i((s["MDWK_SELNG_AMT"] + s["WKEND_SELNG_AMT"] == s["THSMON_SELNG_AMT"]).sum()),
      zero_or_negative_amt_rows=i((s["THSMON_SELNG_AMT"] <= 0).sum()),
      ticket_quantiles={v: qstats(s.loc[s["svc"] == v, "ticket"]) for v in SVCS},
      ticket_flag_bounds={v: [round(float(tq.loc[v, 0.01]), 1), round(float(tq.loc[v, 0.99]), 1)] for v in SVCS},
      flag_rows={f: {v: i(s.loc[s["svc"] == v, f].sum()) for v in SVCS} for f in FLAGS},
      flag_any_keys=i(qflags["sales_flag_any"].sum()))

# ---- 점포: 커피·제과 점포수/일반/프랜차이즈/개폐업 -----------------------------
st = load("VwsmTrdarStorQq")
st = st[st["SVC_INDUTY_CD"].isin(SVC)].copy()
st["svc"] = st["SVC_INDUTY_CD"].map(SVC)
SV = ["SIMILR_INDUTY_STOR_CO", "STOR_CO", "FRC_STOR_CO", "OPBIZ_STOR_CO", "CLSBIZ_STOR_CO"]
ren = {"SIMILR_INDUTY_STOR_CO": "stores", "STOR_CO": "indep", "FRC_STOR_CO": "frc",
       "OPBIZ_STOR_CO": "open", "CLSBIZ_STOR_CO": "close"}
sp = st.pivot_table(index=KEY, columns="svc", values=SV, aggfunc="sum")
sp.columns = [f"{svc}_{ren[v]}" for v, svc in sp.columns]
# 같은 상권·분기에 다른 업종 행이 있는데 이 업종 행만 없으면 = 점포 0 (끝나는 시계열 181개 중 177개의 마지막 행이 SIMILR=0).
# 상권·분기 자체가 점포 데이터에 없으면(행 없음) panel 결합 후 NaN 유지.
sp = sp.fillna(0)
for k in ren.values():
    sp[f"cb_{k}"] = sp[[f"{v}_{k}" for v in SVCS]].sum(axis=1)
sp["cb_frc_share"] = sp["cb_frc"] / sp["cb_stores"].where(sp["cb_stores"] > 0)
for v in SVCS:
    sp[f"{v}_frc_share"] = sp[f"{v}_frc"] / sp[f"{v}_stores"].where(sp[f"{v}_stores"] > 0)
# 4분기 롤링: 폐업·개업률(건수 재계산), 점포 4분기 평균
Ws = {c: wide(sp[c]) for c in ["cb_stores", "cb_open", "cb_close"]}
stock_lag4 = roll(Ws["cb_stores"], "mean").shift(1, axis=1)  # t-4..t-1 평균
Rs = {"cb_stores_4q_avg": roll(Ws["cb_stores"], "mean"),
      "cb_close_4q": roll(Ws["cb_close"], "sum"), "cb_open_4q": roll(Ws["cb_open"], "sum"),
      "cb_stores_lag4_avg": stock_lag4}
Rs["cb_close_rt_4q"] = 100 * Rs["cb_close_4q"] / stock_lag4.where(stock_lag4 > 0)
Rs["cb_open_rt_4q"] = 100 * Rs["cb_open_4q"] / stock_lag4.where(stock_lag4 > 0)
Rs["store_small_n"] = (stock_lag4 < 5).astype(float).where(stock_lag4.notna())
sp = sp.join(pd.concat([long(w, c) for c, w in Rs.items()], axis=1))

# 점포 품질 점검
stv = st.sort_values(["TRDAR_CD", "SVC_INDUTY_CD", "STDR_YYQU_CD"]).copy()
stv["qi"] = stv["STDR_YYQU_CD"].map(QS.index)
prev = stv.groupby(["TRDAR_CD", "SVC_INDUTY_CD"]).shift(1)
cons = (stv["qi"] - prev["qi"]) == 1
resid = (stv["SIMILR_INDUTY_STOR_CO"] - prev["SIMILR_INDUTY_STOR_CO"]) - (stv["OPBIZ_STOR_CO"] - stv["CLSBIZ_STOR_CO"])
rhu = lambda num, den: np.floor(100 * num / den.where(den > 0) + 0.5)
op_m = st["OPBIZ_STOR_CO"] > 0; cl_m = st["CLSBIZ_STOR_CO"] > 0
frc_tot = st[st["svc"] == "coffee"].groupby("STDR_YYQU_CD")[["FRC_STOR_CO", "STOR_CO", "SIMILR_INDUTY_STOR_CO"]].sum()
cover("VwsmTrdarStorQq", st, filter="SVC_INDUTY_CD in CS100010, CS100005",
      similr_eq_stor_plus_frc_violations=i((st["SIMILR_INDUTY_STOR_CO"] != st["STOR_CO"] + st["FRC_STOR_CO"]).sum()),
      stock_flow_residual_nonzero_by_quarter=stv.loc[cons].assign(r=resid[cons] != 0).groupby("STDR_YYQU_CD")["r"].sum().astype(int).to_dict(),
      stock_flow_pairs=i(cons.sum()), stock_flow_match_rate=round(float((resid[cons] == 0).mean()), 4),
      published_rate_check={
          "opbiz_rt_match_round_half_up": round(float((rhu(st.loc[op_m, "OPBIZ_STOR_CO"], st.loc[op_m, "SIMILR_INDUTY_STOR_CO"]) == st.loc[op_m, "OPBIZ_RT"]).mean()), 4),
          "clsbiz_rt_match_round_half_up": round(float((rhu(st.loc[cl_m, "CLSBIZ_STOR_CO"], st.loc[cl_m, "SIMILR_INDUTY_STOR_CO"]) == st.loc[cl_m, "CLSBIZ_RT"]).mean()), 4),
          "clsbiz_rt_gt_100_rows": i((st["CLSBIZ_RT"] > 100).sum()),
          "similr0_close_pos_rows": i(((st["SIMILR_INDUTY_STOR_CO"] == 0) & cl_m).sum()),
          "note": "공표 OPBIZ_RT/CLSBIZ_RT는 정수 반올림·당분기 SIMILR 분모 -> panel에 넣지 않고 건수로 재계산(cb_*_rt_4q)"},
      coffee_seoul_totals_by_quarter={q: {k: i(r[k]) for k in r.index} for q, r in frc_tot.iterrows()},
      frc_break_quarter=FRC_BREAK_Q)

# ---- 유동인구 ----------------------------------------------------------------
fl = load("VwsmTrdarFlpopQq")
fli = fl.set_index(KEY)
age_c = [f"AGRDE_{a}_FLPOP_CO" for a in ["10", "20", "30", "40", "50", "60_ABOVE"]]
tm_c = [c for c in fl.columns if c.startswith("TMZON_")]
dow_c = [f"{d}_FLPOP_CO" for d in ["MON", "TUES", "WED", "THUR", "FRI", "SAT", "SUN"]]
age_sum, tm_sum, dow_sum = fli[age_c].sum(axis=1), fli[tm_c].sum(axis=1), fli[dow_c].sum(axis=1)
flow = pd.DataFrame({
    "flpop": fli["TOT_FLPOP_CO"],
    "flpop_share_2030": (fli["AGRDE_20_FLPOP_CO"] + fli["AGRDE_30_FLPOP_CO"]) / age_sum,
    "flpop_share_06_11": fli["TMZON_06_11_FLPOP_CO"] / tm_sum,
    "flpop_share_11_17": (fli["TMZON_11_14_FLPOP_CO"] + fli["TMZON_14_17_FLPOP_CO"]) / tm_sum,
    "flpop_share_wkend": (fli["SAT_FLPOP_CO"] + fli["SUN_FLPOP_CO"]) / dow_sum,
})
Wf = wide(flow["flpop"])
lr = np.log(Wf).diff(axis=1).abs()
jump = (lr > np.log(1.5)).astype(float).where(lr.notna())
flow = flow.join(long(roll(Wf, "mean"), "flpop_4q_avg")).join(long(jump, "flpop_jump_flag"))
win_jump = jump[[q for q in QS if "20233" <= q <= END_Q]].sum(axis=1)
sales_trdar = set(sales.index.get_level_values(0))
cover("VwsmTrdarFlpopQq", fl,
      unit_note="TOT_FLPOP_CO 단위·집계기준(일평균/합계) 공식 문서 미기재. 요일 컬럼이 요일 횟수에 비례하지 않음 -> 상대지수(성장률·비중·순위)로만 사용",
      sum_check_max_abs_diff={"age": float((age_sum - fli["TOT_FLPOP_CO"]).abs().max()),
                              "time": float((tm_sum - fli["TOT_FLPOP_CO"]).abs().max()),
                              "dow": float((dow_sum - fli["TOT_FLPOP_CO"]).abs().max())},
      jump_rate_by_quarter={q: round(float(jump[q].mean()), 4) for q in QS[1:]},
      jump_trdar_20233_20262=sorted(win_jump[win_jump > 0].index),
      jump_trdar_20233_20262_in_sales=sorted(set(win_jump[win_jump > 0].index) & sales_trdar))

# ---- 상주인구 (값이 실제로 바뀐 분기 = 빈티지) ----------------------------------
rp = load("VwsmTrdarRepopQq")
rpi = rp.set_index(KEY)
num_c = [c for c in rp.columns if c.endswith("_CO")]
chg_rate = {}
for a, b in zip(QS[:-1], QS[1:]):
    A = rpi.xs(a, level=1)[num_c]; B = rpi.xs(b, level=1)[num_c]
    common = A.index.intersection(B.index)
    chg_rate[b] = round(float((A.loc[common] != B.loc[common]).any(axis=1).mean()), 4)
breaks = [q for q, r in chg_rate.items() if r > 0.5]
starts = [QS[0]] + breaks
vint = {q: f"R{sum(q >= b for b in starts)}" for q in QS}
repop = pd.DataFrame({
    "repop": rpi["TOT_REPOP_CO"],
    # 상주인구 100명 미만은 비중 불안정 -> NaN
    "repop_share_2030": ((rpi["AGRDE_20_REPOP_CO"] + rpi["AGRDE_30_REPOP_CO"]) / rpi["TOT_REPOP_CO"]).where(rpi["TOT_REPOP_CO"] >= 100),
    "repop_hshld": rpi["TOT_HSHLD_CO"],
    "repop_hshld_gt_pop": (rpi["TOT_HSHLD_CO"] > rpi["TOT_REPOP_CO"]).astype(int),
})
# 상주인구는 빈티지 갱신 분기에만 값이 바뀜 -> 분기 성장률·CAGR 계산 금지
repop["repop_vintage"] = repop.index.get_level_values("STDR_YYQU_CD").map(vint)
cover("VwsmTrdarRepopQq", rp,
      unit_note="TOT_REPOP_CO: 명(시점 인구). 값은 빈티지 시작 분기에만 갱신되고 이후 분기는 동일값 반복",
      row_change_rate_vs_prev_quarter=chg_rate,
      vintages={f"R{k + 1}": [starts[k], (QS[QS.index(starts[k + 1]) - 1] if k + 1 < len(starts) else QS[-1])]
                for k in range(len(starts))},
      age_sum_equals_total_rows=i((rpi[[f"AGRDE_{a}_REPOP_CO" for a in ["10", "20", "30", "40", "50", "60_ABOVE"]]].sum(axis=1) == rpi["TOT_REPOP_CO"]).sum()),
      hshld_gt_pop_rows=i(repop["repop_hshld_gt_pop"].sum()),
      repop_missing_sales_trdar=sorted(sales_trdar - set(rp["TRDAR_CD"])))

# ---- 집객시설 (22분기 변동 0 -> 상권 정적 속성으로 trdar.csv에) ------------------
fc = load("VwsmTrdarFcltyQq")
FAC = {"VIATR_FCLTY_CO": "fac_total", "SUBWAY_STATN_CO": "fac_subway", "BUS_STTN_CO": "fac_bus_stop",
       "UNIV_CO": "fac_univ", "GNRL_HSPTL_CO": "fac_gnrl_hospital", "THEAT_CO": "fac_theater",
       "STAYNG_FCLTY_CO": "fac_lodging", "SUPMK_CO": "fac_supermkt", "BANK_CO": "fac_bank", "PBLOFC_CO": "fac_pubofc"}
# fac_total = VIATR_FCLTY_CO (API 총계. 하위 19개 항목 합이 아님 -> fac_total과 하위 항목을 함께 합산하지 말 것)
# RLROAD_STATN_CO는 전 행 0이라 제외
sub_c = [c for c in fc.columns if c.endswith("_CO") and c != "VIATR_FCLTY_CO"]
fac = (fc.sort_values("STDR_YYQU_CD").drop_duplicates("TRDAR_CD", keep="last")
       .set_index("TRDAR_CD")[list(FAC)].rename(columns=FAC))
time_var = i((fc.groupby("TRDAR_CD")[list(FAC)].nunique() > 1).any(axis=1).sum())
cover("VwsmTrdarFcltyQq", fc,
      fclty_time_varying_trdar=time_var,
      viatr_by_quarter=fc.groupby("STDR_YYQU_CD")["VIATR_FCLTY_CO"].sum().astype(int).to_dict(),
      viatr_equals_subsum_rate=round(float((fc["VIATR_FCLTY_CO"] == fc[sub_c].sum(axis=1)).mean()), 4),
      viatr_min=float(fc["VIATR_FCLTY_CO"].min()),
      rlroad_all_zero=bool((fc["RLROAD_STATN_CO"] == 0).all()),
      missing_relm_trdar=i(len(set(trdar["TRDAR_CD"]) - set(fc["TRDAR_CD"]))),
      missing_sales_trdar=sorted(sales_trdar - set(fc["TRDAR_CD"])))

# ---- 상권변화지표 (전 업종, 서울 평균 대비 상대 등급) -----------------------------
ixr = load("VwsmTrdarIxQq")
ix = ixr.set_index(KEY)[["TRDAR_CHNGE_IX", "TRDAR_CHNGE_IX_NM", "OPR_SALE_MT_AVRG", "CLS_SALE_MT_AVRG",
                         "SU_OPR_SALE_MT_AVRG", "SU_CLS_SALE_MT_AVRG"]]
ix.columns = ["chg_ix", "chg_ix_nm", "opr_months_avg", "cls_months_avg", "seoul_opr_months_avg", "seoul_cls_months_avg"]
ix["opr_gap"] = ix["opr_months_avg"] - ix["seoul_opr_months_avg"]
ix["cls_gap"] = ix["cls_months_avg"] - ix["seoul_cls_months_avg"]
ix["chg_expand"] = (ix["chg_ix"] == "LH").astype(int)  # 상권확장
ix["chg_shrink"] = (ix["chg_ix"] == "HL").astype(int)  # 상권축소
dopr = wide(ix["opr_months_avg"]).diff(axis=1).abs()
ix = ix.join(long((dopr > 30).astype(float).where(dopr.notna()), "ix_opr_jump_flag"))
tie = (ix["opr_gap"] == 0) | (ix["cls_gap"] == 0)
pred = np.where(ix["opr_gap"] > 0, "H", "L").astype(object) + np.where(ix["cls_gap"] > 0, "H", "L").astype(object)
cover("VwsmTrdarIxQq", ixr,
      code_pairs={f"{a}={b}": i(n) for (a, b), n in ixr.groupby(["TRDAR_CHNGE_IX", "TRDAR_CHNGE_IX_NM"]).size().items()},
      code_rule="1글자: 운영 사업체 평균 영업개월 > 서울 평균이면 H / 2글자: 폐업 사업체 평균 영업개월 > 서울 평균이면 H",
      code_rule_match_non_tie=round(float((pred[~tie.values] == ix["chg_ix"].values[~tie.values]).mean()), 4),
      tie_rows=i(tie.sum()),
      opr_jump_gt30_rows=i((dopr > 30).sum().sum()),
      seoul_opr_months_range=[float(ix["seoul_opr_months_avg"].min()), float(ix["seoul_opr_months_avg"].max())],
      seoul_cls_months_range=[float(ix["seoul_cls_months_avg"].min()), float(ix["seoul_cls_months_avg"].max())])

# ---- 결합 (panel) ---------------------------------------------------------------
panel = sales.join(sp, how="outer")
for v in SVCS:
    panel[f"{v}_present"] = panel[f"{v}_present"].fillna(0).astype(int)
panel["has_sales"] = ((panel["coffee_present"] + panel["bakery_present"]) > 0).astype(int)
panel["has_store_row"] = panel.index.isin(sp.index).astype(int)
panel = panel.join(flow, how="left").join(repop, how="left").join(ix, how="left").reset_index()
panel = panel.merge(trdar[["TRDAR_CD", "name", "type", "gu", "dong", "is_tour_zone"]], on="TRDAR_CD", how="left")
# 점포당 매출: 업종별 / 합산은 매출 행이 있는 업종의 점포만 분모
for v in SVCS:
    panel[f"{v}_sales_per_store"] = panel[f"{v}_sales"] / panel[f"{v}_stores"].where(panel[f"{v}_stores"] > 0)
den = sum(panel[f"{v}_stores"] * panel[f"{v}_present"] for v in SVCS)
panel["sales_per_store"] = panel["cb_sales"] / den.where(den > 0)
sps_p99 = {v: float(panel[f"{v}_sales_per_store"].quantile(.99)) for v in SVCS}
panel["sps_flag_p99"] = np.where(panel[[f"{v}_sales_per_store" for v in SVCS]].isna().all(axis=1), np.nan,
                                 sum((panel[f"{v}_sales_per_store"] > sps_p99[v]).astype(int) for v in SVCS).clip(upper=1))
panel["frc_break_20254"] = (panel["STDR_YYQU_CD"] >= FRC_BREAK_Q).astype(int)
# 업종 구성 점검용: 최근 4분기 중 업종 매출 행이 있는 분기 수 (0~4). 롤링 창이 완성되는 20214부터,
# 매출 행이 한 번도 없는 상권은 0 (20211~20213은 창 미완성이라 NaN)
pk = pd.MultiIndex.from_frame(panel[KEY])
for v in SVCS:
    pv = long(R[f"{v}_present_4q"], f"{v}_present_4q").reindex(pk).to_numpy()
    panel[f"{v}_present_4q"] = np.where(np.isnan(pv) & (panel["STDR_YYQU_CD"] >= QS[3]), 0, pv)
panel = panel.sort_values(KEY)

ORDER = (KEY + ["name", "type", "gu", "dong", "is_tour_zone", "has_sales", "has_store_row"]
         + [f"{v}_{k}" for v in SVCS for k in ["present", "sales", "txn", "ticket"]]
         + ["cb_sales", "cb_txn", "cb_ticket"]
         + [c for c in mix.columns]
         + ["cb_sales_4q", "coffee_sales_4q", "bakery_sales_4q", "coffee_present_4q", "bakery_present_4q"]
         + list(qflags.columns)
         + [f"{v}_{k}" for v in SVCS for k in ["stores", "indep", "frc", "open", "close", "frc_share"]]
         + [f"cb_{k}" for k in ren.values()] + ["cb_frc_share", "frc_break_20254"]
         + list(Rs)
         + ["coffee_sales_per_store", "bakery_sales_per_store", "sales_per_store", "sps_flag_p99"]
         + list(flow.columns) + list(repop.columns) + list(ix.columns))
assert set(ORDER) == set(panel.columns), set(ORDER) ^ set(panel.columns)
panel = panel[ORDER]
panel.to_csv(os.path.join(OUT, "panel.csv"), index=False, encoding="utf-8-sig")

# ---- 상권 단위: 정적 집객시설 + 관측 커버리지 + 3년 성장 기반값 -----------------------
T = trdar.set_index("TRDAR_CD")
T = T.join(fac)
T["fac_missing"] = (~T.index.isin(fac.index)).astype(int)  # 집객시설 행 없음 (0으로 채우지 않음: '0개' 여부 미확인)
T["in_sales_universe"] = T.index.isin(sales_trdar).astype(int)
obs = W["cb_sales"].notna()
n = obs.sum(axis=1)
T["sales_n_q_obs"] = n
T["sales_first_q"] = obs.idxmax(axis=1).where(n > 0)
T["sales_last_q"] = obs.iloc[:, ::-1].idxmax(axis=1).where(n > 0)
T["sales_gap_q"] = (T["sales_last_q"].map(QS.index, na_action="ignore")
                    - T["sales_first_q"].map(QS.index, na_action="ignore") + 1 - T["sales_n_q_obs"])
for v in SVCS:
    T[f"{v}_n_q_obs"] = wide(sales[f"{v}_sales"]).notna().sum(axis=1)
for c in ["sales_n_q_obs", "coffee_n_q_obs", "bakery_n_q_obs"]:
    T[c] = T[c].fillna(0).astype(int)
obs_first = obs.idxmax(axis=1)  # obs 행 = 매출 상권(관측 1개 이상)
obs_last = obs.iloc[:, ::-1].idxmax(axis=1)


def win_status(q0, q1):
    """4q@q0 -> 4q@q1 비교 가능 여부. 양쪽 창 완비 + 업종 구성 동일(각 업종이 창 내 0 또는 4분기, 두 창 동일)이면 ok.
    결측 3분류: exit = q0 창 완비 & 매출 시계열이 q1 전에 끝남(마지막 관측 < q1)
                entry = q1 창 완비 & 첫 관측이 q0 창 시작 분기 이후
                gap = 그 밖(중간 공백, 양쪽 창 부분 관측 등)"""
    b, e = R["cb_sales_4q"][q0], R["cb_sales_4q"][q1]
    comp = pd.Series(True, index=b.index)
    for v in SVCS:
        p0, p1 = R[f"{v}_present_4q"][q0], R[f"{v}_present_4q"][q1]
        comp &= p0.isin([0, 4]) & (p0 == p1)
    st = pd.Series("ok", index=b.index)
    st[~comp] = "composition_change"
    miss = b.isna() | e.isna()
    st[miss] = "gap"
    st[b.notna() & e.isna() & (obs_last < q1)] = "exit"
    st[b.isna() & e.notna() & (obs_first > QS[QS.index(q0) - 3])] = "entry"
    return b, e, st


# A1 기반(= 백테스트 타깃): 4분기 합 CAGR 20232 -> 20262
cb_b, cb_e, status = win_status(BASE_Q, END_Q)
T["cb_sales_4q_base"], T["cb_sales_4q_end"] = cb_b, cb_e
T["cb_sales_cagr3y"] = ((cb_e / cb_b) ** (1 / YEARS) - 1).where(status == "ok")
T["cb_cagr_status"] = status
T.loc[T["in_sales_universe"] == 0, "cb_cagr_status"] = "no_sales"
# exit 상권의 마지막 분기 점포 수(매출 비공표 != 점포 0 확인용)
exit_ix = status[status == "exit"].index
exit_last_stores = pd.Series([sp["cb_stores"].get((t, q), np.nan) for t, q in obs_last[exit_ix].items()], index=exit_ix)
exit_end_stores = Ws["cb_stores"].reindex(exit_ix)[END_Q]
# 백테스트 피처(BT1): 4q@20214 -> 4q@20232, 1.5년 연율화. 타깃은 위 A1(cb_cagr_status 포함)
bt0, _, bt_status = win_status(BT0_Q, BASE_Q)
T["cb_sales_4q_bt0"] = bt0
T["cb_sales_cagr_btfeat"] = ((cb_b / bt0) ** (1 / BT_FEAT_YEARS) - 1).where(bt_status == "ok")
T["cb_btfeat_status"] = bt_status
T.loc[T["in_sales_universe"] == 0, "cb_btfeat_status"] = "no_sales"
T["cb_base_low"] = (cb_b < SALES_FLOOR_4Q).astype(float).where(cb_b.notna())
for v in SVCS:
    b_, e_ = R[f"{v}_sales_4q"][BASE_Q], R[f"{v}_sales_4q"][END_Q]
    T[f"{v}_sales_cagr3y"] = (e_ / b_) ** (1 / YEARS) - 1
T["sales_flag_q_in_window"] = wide(qflags["sales_flag_any"])[BASE_WIN + END_WIN].sum(axis=1)
T.loc[T["in_sales_universe"] == 0, "sales_flag_q_in_window"] = np.nan
# C1 기반: 점포수(SIMILR) 4분기 평균 CAGR
sb, se = Rs["cb_stores_4q_avg"][BASE_Q], Rs["cb_stores_4q_avg"][END_Q]
T["cb_stores_4q_avg_base"], T["cb_stores_4q_avg_end"] = sb, se
T["cb_stores_cagr3y"] = (se / sb.where(sb > 0)) ** (1 / YEARS) - 1
sb0 = Rs["cb_stores_4q_avg"][BT0_Q]
T["cb_stores_4q_avg_bt0"] = sb0
T["cb_stores_cagr_btfeat"] = (sb / sb0.where(sb0 > 0)) ** (1 / BT_FEAT_YEARS) - 1
# B1 기반: 유동인구 4분기 평균 CAGR (서울 중앙값 대비 상대화는 지표 단계에서)
fb, fe = roll(Wf, "mean")[BASE_Q], roll(Wf, "mean")[END_Q]
T["flpop_4q_avg_base"], T["flpop_4q_avg_end"] = fb, fe
T["flpop_cagr3y"] = (fe / fb) ** (1 / YEARS) - 1
T["flpop_jump_n_window"] = win_jump
fb0 = roll(Wf, "mean")[BT0_Q]
T["flpop_4q_avg_bt0"] = fb0
T["flpop_cagr_btfeat"] = (fb / fb0) ** (1 / BT_FEAT_YEARS) - 1
T["flpop_jump_n_btfeat"] = jump[[q for q in QS if QS[1] <= q <= BASE_Q]].sum(axis=1)  # 20212~20232
# D2 기반: 서울 평균 대비 영업개월 격차의 3년 변화
og = wide(ix["opr_gap"]); cg = wide(ix["cls_gap"])
T["opr_gap_chg3y"] = og[END_Q] - og[BASE_Q]
T["cls_gap_chg3y"] = cg[END_Q] - cg[BASE_Q]
T["opr_gap_chg_btfeat"] = og[BASE_Q] - og[BT0_Q]
T["cls_gap_chg_btfeat"] = cg[BASE_Q] - cg[BT0_Q]
trdar_out = T.reset_index()
trdar_out.to_csv(os.path.join(OUT, "trdar.csv"), index=False, encoding="utf-8-sig")

cover("TbgisTrdarRelm", relm,
      crs_note="XCNTS/YDNTS: EPSG:5181로 추정(역 11곳 대조, 공식 문서 미확인). 상권 대표점 좌표, 폴리곤 없음",
      area_unit="RELM_AR = ㎡로 판단",
      type_counts=relm["TRDAR_SE_CD_NM"].value_counts().astype(int).to_dict(),
      sales_trdar_matched=f"{len(sales_trdar & set(relm['TRDAR_CD']))}/{len(sales_trdar)}",
      relm_only_no_sales=i(len(set(relm["TRDAR_CD"]) - sales_trdar)),
      lonlat_range={"lon": [float(trdar["lon"].min()), float(trdar["lon"].max())],
                    "lat": [float(trdar["lat"].min()), float(trdar["lat"].max())]})

# ---- 결합 품질 리포트 -----------------------------------------------------------
hs = panel[panel["has_sales"] == 1]
coverage["_panel"] = {
    "rows": len(panel), "trdar": i(panel["TRDAR_CD"].nunique()),
    "rows_has_sales": len(hs), "rows_store_only": i((panel["has_sales"] == 0).sum()),
    "unmatched_trdar_master": i(panel["name"].isna().sum()),
    "sales_key_match_rate": {c: round(float(hs[c].notna().mean()), 4)
                             for c in ["cb_stores", "flpop", "repop", "chg_ix"]},
    "sales_trdar_fac_match_rate": round(float(T.loc[T["in_sales_universe"] == 1, "fac_missing"].eq(0).mean()), 4),
    "has_sales_rows_missing": {c: i(hs[c].isna().sum()) for c in ["cb_stores", "flpop", "repop", "chg_ix"]},
    "sales_trdar_complete_22q": i((T["sales_n_q_obs"] == len(QS)).sum()),
    "sales_trdar_complete_13q_20232_20262": i(obs[[q for q in QS if BASE_Q <= q <= END_Q]].all(axis=1).sum()),
    "tour_zone_trdar": i(trdar["is_tour_zone"].sum()),
    "growth_windows": {"base": BASE_WIN, "end": END_WIN, "years": YEARS,
                       "reason": "2021~2023Q1 코로나 회복기(커피 YoY 2022 +8~+20%, 20231 +23.1%) 기준점 제외. 데이터는 20211부터만 제공"},
    "cb_cagr_status_counts": T.loc[T["in_sales_universe"] == 1, "cb_cagr_status"].value_counts().astype(int).to_dict(),
    "cb_cagr_status_rule": "exit=기준 창 완비 & 마지막 관측 < 20262 / entry=비교 창 완비 & 첫 관측 > 20223 / gap=그 밖 결측 / composition_change / ok",
    "exit_profile": {"n": len(exit_ix),
                     "last_q_counts": obs_last[exit_ix].value_counts().sort_index().astype(int).to_dict(),
                     "cb_stores_at_last_obs_q": qstats(exit_last_stores),
                     "cb_stores_at_20262": qstats(exit_end_stores),
                     "cb_stores_20262_missing": i(exit_end_stores.isna().sum()),
                     "base_4q_median_won": round(float(cb_b[exit_ix].median())),
                     "ok_base_4q_median_won": round(float(cb_b[status == "ok"].median())),
                     "note": "점포가 남아 있는데 매출만 비공표 -> 매출 0이 아니라 '추정 불가·비공표'. 타깃에서 버리면 생존 편향"},
    "backtest": {
        "bt1": {"feature": {"from": f"4q@{BT0_Q} (20211~20214)", "to": f"4q@{BASE_Q} (20223~20232)", "years": BT_FEAT_YEARS,
                            "columns": ["cb_sales_cagr_btfeat", "cb_stores_cagr_btfeat", "flpop_cagr_btfeat", "opr_gap_chg_btfeat", "cls_gap_chg_btfeat"]},
                "target": {"from": f"4q@{BASE_Q}", "to": f"4q@{END_Q}", "years": YEARS, "columns": ["cb_sales_cagr3y", "cb_cagr_status"]},
                "btfeat_status_counts": T.loc[T["in_sales_universe"] == 1, "cb_btfeat_status"].value_counts().astype(int).to_dict(),
                "feature_ok_and_target_ok": i(((T["cb_btfeat_status"] == "ok") & (T["cb_cagr_status"] == "ok")).sum()),
                "feature_ok_and_target_exit": i(((T["cb_btfeat_status"] == "ok") & (T["cb_cagr_status"] == "exit")).sum()),
                "feature_ok_and_target_composition_change": i(((T["cb_btfeat_status"] == "ok") & (T["cb_cagr_status"] == "composition_change")).sum()),
                "coffee_complete_seoul_4q_sum_won": {q: round(float(R["coffee_sales_4q"].loc[wide(sales["coffee_sales"]).notna().all(axis=1), q].sum()))
                                                     for q in [BT0_Q, BASE_Q, "20242", "20252", END_Q]},
                "limits": ["피처 창 1.5년 vs 전망 모델 피처 3년(20232->20262): 기간 불일치. 연율화해도 노이즈 수준이 다름",
                           "피처 창 전체가 코로나 회복기(완비 커피 916개 4q 합 +20.6%/1.5년) -> 절대 성장률이 아니라 서울 중앙값 대비 상대값·순위로만 비교",
                           "flpop 4q@20214 창에 20213 수준 단절(점프율 4.36%) 포함 -> flpop_jump_n_btfeat>0 상권 주의",
                           "상주인구(빈티지 R1/R2)·집객시설(정적)은 백테스트 피처로 시점 분리 불가",
                           "원천 2021년 이후만 제공(API 20194·20204 요청 시 INFO-200 데이터 없음, 2026-11-14 확인)"]},
        "rolling_origin_1y": {"definition": "피처 = 4q@(t-4) -> 4q@t, 타깃 = 4q@t -> 4q@(t+4). panel의 cb_sales_4q와 coffee/bakery_present_4q(각 0 또는 4, 양 끝 동일)로 구성 점검",
                              "origins_all": [q for q in QS if QS[7] <= q <= QS[-5]],
                              "origins_recovery_free": [q for q in QS if QS[QS.index(BASE_Q) + 4] <= q <= QS[-5]],
                              "limits": "1년 지평이라 3년 타깃과 지평 불일치. 오리진 간 창이 겹쳐 독립 표본이 아님"}},
    "cb_sales_cagr3y_quantiles": qstats(T["cb_sales_cagr3y"]),
    "cb_base_low_trdar": i((T["cb_base_low"] == 1).sum()),
    "sps_p99": {v: round(x) for v, x in sps_p99.items()},
    "units": {
        "*_sales": "원/분기 (추정, 원천 필드명 THSMON_SELNG_AMT '당월_매출_금액'; 월 환산 시 /3 '환산' 표기)",
        "*_txn": "건/분기", "*_ticket": "원/건", "*_sales_4q": "원/4분기(연간) 합",
        "*_sales_per_store": "원/분기/점포", "*_stores,*_indep,*_frc": "개(분기말 스톡)", "*_open,*_close": "개/분기",
        "cb_*_rt_4q": "%/연(4분기 누적 건수 / 직전 4분기 평균 점포)",
        "flpop": "명(서울시 상권분석서비스 분기 집계값; 일평균/합계 기준 미공개) -> 상대지수",
        "repop": "명(시점 인구, 빈티지 갱신값 반복)", "fac_*": "개소(시점 미상 스냅샷)",
        "opr/cls_months_avg": "개월", "cb_share_*,flpop_share_*,repop_share_*": "비율(0~1)",
        "*_cagr3y": "비율/년 (0.05 = 연 5%)", "area_m2": "㎡", "x/y_epsg5181": "m"},
}
json.dump(coverage, open(os.path.join(OUT, "coverage.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(coverage["_panel"], ensure_ascii=False, indent=1, default=str))
print("panel", panel.shape, "trdar", trdar_out.shape)
