#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
단위별 메리트오더 SMP 예측 (B) — 팀 S3 데이터.

원리: 발전기별 변동비 오름차순으로 가용용량을 쌓아(supply stack) 수요와 교차 →
      한계발전기의 변동비 = SMP.
  변동비(원/kWh) = 적용열량단가(원/Gcal) × 0.086 / η_입찰(%)
  가용용량: daos_cache(발전기별 시간당 MW)
  수요:     demand_cache(MAINLAND 시간별)
  매핑:     gen_spec(gener_cd→η·연료·fc_발전기명), fuel_cost(fc_발전기명·월→적용열량단가)
  검증:     marginal_gen_cache(실제 한계발전기·SMP)

사용법:
  python merit_order.py --date 20260629        # 하루 상세(시간별 예측 vs 실측 + 한계발전기)
  python merit_order.py --validate 20260601 20260629   # 기간 검증
"""
import os, sys, io, csv, json
import boto3

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "s3cache")
BUCKET = "kpx-epowermarket-data"
KWH_GCAL = 0.086  # 860 kcal/kWh → 원/Gcal × 0.086/η(%) = 원/kWh

def _dl(key, fname):
    p = os.path.join(CACHE, fname)
    if not os.path.exists(p):
        os.makedirs(CACHE, exist_ok=True)
        print(f"  ↓ {fname} 다운로드...")
        boto3.client("s3").download_file(BUCKET, key, p)
    return p

def _s3csv(key):
    o = boto3.client("s3").get_object(Bucket=BUCKET, Key=key)
    return list(csv.DictReader(io.StringIO(o["Body"].read().decode("utf-8-sig"))))

# 경제급전 연료(변동비 순 경제급전). 그 외(도시가스·중유·KOGAS개별/집단 열병합 등)는 열수요 must-run 취급.
ECON_FUELS = {"원자력", "석탄", "직도입", "KOGAS발전"}

def load_spec():
    """gener_cd → {eta, fuel, fcname, cap, capq[1..4]}"""
    def f(x):
        try: return float(x)
        except (TypeError, ValueError): return None
    out = {}
    for r in _s3csv("mapping/df_mapping_gen_spec.csv"):
        capq = {q: f(r.get(f"입찰최대_{q}Q")) for q in range(1, 5)}
        out[str(r["xlsx_코드"]).strip()] = {
            "eta": f(r["η_입찰(%)"]), "fuel": r["연료"], "fcname": r["fc_발전기명"].strip(),
            "cap": f(r["설비용량"]), "capq": capq}
    return out

def avail_cap(spec_row, month):
    """분기별 입찰최대(없으면 설비용량)."""
    q = (int(month) - 1) // 3 + 1
    return spec_row["capq"].get(q) or spec_row["cap"] or 0.0

def load_fuelcost():
    """(fc_발전기명, 'YYYY-MM') → 적용열량단가 ; + 연료대분류 월중앙값(fallback)"""
    from collections import defaultdict
    byname, byfuel = {}, defaultdict(lambda: defaultdict(list))
    for r in _s3csv("data/fuel_cost.csv"):
        try: v = float(r["적용열량단가"])
        except (TypeError, ValueError): continue
        byname[(r["발전기명"].strip(), r["적용월"])] = v
        byfuel[r["대분류"]][r["적용월"]].append(v)
    def med(xs):
        xs = sorted(xs); n = len(xs)
        return xs[n//2] if n else None
    fuelmed = {f: {m: med(v) for m, v in mv.items()} for f, mv in byfuel.items()}
    return byname, fuelmed

# 연료(gen_spec) → fuel_cost 대분류 대략 매핑(fallback용)
FUEL2BIG = {"석탄": "유연탄", "국내탄": "무연탄", "원자력": "원자력",
            "KOGAS발전": "LNG", "KOGAS집단": "LNG", "KOGAS개별": "LNG", "직도입": "LNG",
            "도시가스": "LNG", "LPG": "유류", "중유": "유류", "바이오중유": "유류"}

def varcost(gener_cd, ym, spec, byname, fuelmed):
    """변동비(원/kWh). 없으면 None."""
    s = spec.get(gener_cd)
    if not s or not s["eta"]:
        return None
    hv = byname.get((s["fcname"], ym))
    if hv is None:  # fallback: 연료대분류 월중앙
        hv = fuelmed.get(FUEL2BIG.get(s["fuel"], ""), {}).get(ym)
    if hv is None:
        return None
    return hv * KWH_GCAL / s["eta"]

def load_daos(dates=None):
    """daos_cache → {date: {gener_cd: [24 MW]}} (MAINLAND). dates=set이면 필터."""
    p = _dl("data/daos_cache.csv", "daos_cache.csv")
    out = {}
    with open(p, encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            if r.get("area_div") != "MAINLAND":
                continue
            d = r["deal_date"]
            if dates and d not in dates:
                continue
            mw = []
            for h in range(1, 25):
                try: mw.append(float(r[f"hh{h:02d}_val"]))
                except (TypeError, ValueError): mw.append(0.0)
            out.setdefault(d, {})[str(r["gener_cd"]).strip()] = mw
    return out

def load_demand():
    p = os.path.join(CACHE, "demand_cache.csv")
    if not os.path.exists(p): _dl("data/demand_cache.csv", "demand_cache.csv")
    out = {}
    with open(p, encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            if r.get("area_div") != "MAINLAND": continue
            out[r["deal_date"]] = [float(r[f"hh{h:02d}_val"]) if r.get(f"hh{h:02d}_val") else None
                                   for h in range(1, 25)]
    return out

def load_smp():
    p = os.path.join(CACHE, "smp_cache.csv")
    if not os.path.exists(p): _dl("data/smp_cache.csv", "smp_cache.csv")
    out = {}
    with open(p, encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            if r.get("area_div") != "MAINLAND": continue
            out[r["deal_date"]] = [float(r[f"hh{h:02d}_val"]) if r.get(f"hh{h:02d}_val") else None
                                   for h in range(1, 25)]
    return out

def stack_smp(day_daos, hour_idx, demand_mw, ym, spec, byname, fuelmed):
    """잔여수요 경제 메리트오더 → 한계 변동비(SMP).
       잔여수요 = 수요 − must-run(비경제연료) 급전량. 경제급전 fleet(입찰최대)을
       변동비 순 누적해 잔여수요와 교차 → 한계 변동비. (pred, marginal_cd, units)"""
    month = ym[5:7]
    mustrun = 0.0
    units = []
    for gcd, mws in day_daos.items():
        s = spec.get(gcd)
        out = mws[hour_idx]
        if s is None:
            continue
        if s["fuel"] not in ECON_FUELS:
            if out > 0:
                mustrun += out          # 열수요 must-run → 잔여수요에서 차감
            continue
        cap = avail_cap(s, month)
        vc = varcost(gcd, ym, spec, byname, fuelmed)
        if vc is not None and cap > 0:
            units.append((vc, cap, gcd))
    units.sort()
    resid = demand_mw - mustrun
    cum = 0.0
    for vc, cap, gcd in units:
        cum += cap
        if cum >= resid:
            return vc, gcd, units
    return (units[-1][0], units[-1][2], units) if units else (None, None, units)

def detail(date):
    spec = load_spec(); byname, fuelmed = load_fuelcost()
    daos = load_daos({date}); dem = load_demand(); smp = load_smp()
    marg = {}
    for r in _s3csv("data/marginal_gen_cache.csv"):
        if r["deal_date"] == date and r["area_div"] == "MAINLAND":
            marg[int(r["time"])] = (r["gener_cd"], r["eng_cd"], r.get("smp_prc"))
    ym = f"{date[:4]}-{date[4:6]}"
    dd = daos.get(date, {})
    print(f"=== {date} 단위별 메리트오더 (매핑된 발전기 {sum(1 for g in dd if varcost(g,ym,spec,byname,fuelmed))}/{len(dd)}기) ===")
    print(f"{'hr':>3}{'수요GW':>7}{'예측SMP':>8}{'실측SMP':>8}{'오차':>7}  {'예측한계(연료)':<14}{'실측한계':<8}")
    A, P = [], []
    for h in range(24):
        dmw = dem.get(date, [None]*24)[h]; act = smp.get(date, [None]*24)[h]
        if dmw is None or act is None: continue
        pred, gcd, _ = stack_smp(dd, h, dmw, ym, spec, byname, fuelmed)
        if pred is None: continue
        fuel = spec.get(gcd, {}).get("fuel", "?")
        mg = marg.get(h+1, ("", "", ""))
        A.append(act); P.append(pred)
        print(f"{h+1:3d}{dmw/1000:7.1f}{pred:8.1f}{act:8.1f}{pred-act:+7.1f}  {fuel:<14}{mg[1]:<8}")
    if A:
        mae = sum(abs(a-p) for a,p in zip(A,P))/len(A)
        mape = sum(abs(a-p)/a for a,p in zip(A,P) if a)/len(A)*100
        print(f"{'-'*55}\nMAE {mae:.2f} 원/kWh, MAPE {mape:.2f}%")

def validate(d0, d1):
    spec = load_spec(); byname, fuelmed = load_fuelcost()
    dem = load_demand(); smp = load_smp()
    dates = sorted(d for d in dem if d0 <= d <= d1 and d in smp)
    daos = load_daos(set(dates))
    from collections import defaultdict
    bym = defaultdict(lambda: [[], []]); A, P = [], []
    for date in dates:
        dd = daos.get(date, {})
        if not dd: continue
        ym = f"{date[:4]}-{date[4:6]}"
        for h in range(24):
            dmw = dem[date][h]; act = smp[date][h]
            if dmw is None or act is None: continue
            pred, _, _ = stack_smp(dd, h, dmw, ym, spec, byname, fuelmed)
            if pred is None: continue
            A.append(act); P.append(pred); bym[date[:7]][0].append(act); bym[date[:7]][1].append(pred)
    def mape(a,p): return sum(abs(x-y)/x for x,y in zip(a,p) if x)/len(a)*100
    def mae(a,p): return sum(abs(x-y) for x,y in zip(a,p))/len(a)
    print(f"=== 메리트오더 검증 {d0}~{d1} ({len(A)}시간) ===")
    print(f"{'month':9}{'MAPE%':>8}{'MAE':>8}")
    for m in sorted(bym):
        a,p=bym[m]; print(f"{m:9}{mape(a,p):8.2f}{mae(a,p):8.2f}")
    if A: print(f"{'-'*25}\n{'전체':9}{mape(A,P):8.2f}{mae(A,P):8.2f}")

def main():
    a = sys.argv[1:]
    if "--date" in a:
        detail(a[a.index("--date")+1])
    elif "--validate" in a:
        i = a.index("--validate"); validate(a[i+1], a[i+2])
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
