"""서울열린데이터 상권분석서비스 수집. 키는 .env(SEOUL_API_KEY)에서 읽는다.
실행: py -I analysis/fetch.py   -> data/raw/<dataset>.csv  (+ _meta_<dataset>.json: 출처·수집일·행수·분기범위)"""
import csv, json, os, sys, time, datetime, urllib.request
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = [l.split("=",1)[1].strip() for l in open(os.path.join(ROOT,".env")) if l.startswith("SEOUL_API_KEY=")][0]
OUT = os.path.join(ROOT,"data","raw"); os.makedirs(OUT,exist_ok=True)
STEP = 1000
# 커피-음료(CS100010), 제과점(CS100005)만 남길 데이터셋
SVC = {"CS100010","CS100005"}
DATASETS = {"VwsmTrdarSelngQq":True,"VwsmTrdarStorQq":True,"VwsmTrdarFlpopQq":False,
            "VwsmTrdarRepopQq":False,"VwsmTrdarIxQq":False,"VwsmTrdarFcltyQq":False,
            "TbgisTrdarRelm":False}  # 상권영역(좌표·자치구·행정동·면적)
def get(ds,s,e,tries=4):
    url=f"http://openapi.seoul.go.kr:8088/{KEY}/json/{ds}/{s}/{e}/"
    for i in range(tries):
        try:
            with urllib.request.urlopen(url,timeout=40) as r: return json.load(r)[ds]
        except Exception: time.sleep(1.5*(i+1))
    raise RuntimeError(f"{ds} {s}-{e} 실패")
def run(ds,filt):
    total=get(ds,1,1)["list_total_count"]
    starts=list(range(1,total+1,STEP))
    def one(s): return get(ds,s,min(s+STEP-1,total))["row"]
    rows=[]
    with ThreadPoolExecutor(6) as ex:
        for part in ex.map(one,starts):
            rows += [r for r in part if (not filt or r.get("SVC_INDUTY_CD") in SVC)]
    cols=list(rows[0].keys())
    with open(os.path.join(OUT,ds+".csv"),"w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,cols); w.writeheader(); w.writerows(rows)
    qs=sorted({r.get("STDR_YYQU_CD","-") for r in rows})
    print(ds,"전체",total,"저장",len(rows),"분기",qs[0],"~",qs[-1],flush=True)
    return {"source":f"서울 열린데이터광장 {ds}","fetched":str(datetime.date.today()),"api_total":total,"saved":len(rows),"quarters":[qs[0],qs[-1]]}
todo=sys.argv[1:] or list(DATASETS)   # 인자로 일부 데이터셋만 수집 가능 (병렬 실행 안전: 메타는 데이터셋별 파일)
for ds in todo:
    m=run(ds,DATASETS[ds])
    json.dump(m,open(os.path.join(OUT,f"_meta_{ds}.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=1)
