#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
팀 S3(kpx-epowermarket-data) 에서 시간별 SMP+수요를 받아 예측엔진용 hourly 로 변환.
자격증명은 ~/.aws/credentials(default) 사용 — 코드/깃에 키 없음.

  python s3_backfill.py            # S3→로컬캐시 다운로드 + smp_hourly_s3.json 생성
  python s3_backfill.py --validate # 트레일링 윈도우(직전 N일) LOO 검증(연중 MAPE)
"""
import os, sys, json, importlib.util
import boto3

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "s3cache")
BUCKET = "kpx-epowermarket-data"
FILES = ["smp_cache.csv", "demand_cache.csv"]

def download():
    os.makedirs(CACHE, exist_ok=True)
    s3 = boto3.client("s3")
    for f in FILES:
        dst = os.path.join(CACHE, f)
        s3.download_file(BUCKET, f"data/{f}", dst)
        print(f"  ↓ {f}  ({os.path.getsize(dst)/1e6:.2f} MB)")

def build_hourly():
    """smp_cache+demand_cache(MAINLAND) → {date_iso: [{hr,load(GW),smp}]}"""
    import csv
    def read_wide(path, scale=1.0):
        out = {}
        with open(path, encoding="utf-8-sig") as fp:
            for r in csv.DictReader(fp):
                if r.get("area_div") != "MAINLAND":
                    continue
                d = r["deal_date"]
                vals = {}
                for h in range(1, 25):
                    v = r.get(f"hh{h:02d}_val")
                    try:
                        vals[h] = float(v) * scale
                    except (TypeError, ValueError):
                        vals[h] = None
                out[d] = vals
        return out
    smp = read_wide(os.path.join(CACHE, "smp_cache.csv"))              # 원/kWh
    dem = read_wide(os.path.join(CACHE, "demand_cache.csv"), 1/1000.0)  # MW→GW
    hourly = {}
    for d in sorted(set(smp) & set(dem)):
        iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        rows = []
        for h in range(1, 25):
            s, l = smp[d].get(h), dem[d].get(h)
            if s is not None and l is not None:
                rows.append({"hr": h, "load": round(l, 3), "smp": round(s, 2)})
        if rows:
            hourly[iso] = rows
    return hourly

def save(hourly):
    p = os.path.join(HERE, "smp_hourly_s3.json")
    json.dump({"hourly": hourly}, open(p, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    days = sorted(hourly)
    print(f"→ {p}  ({len(days)}일, {days[0]} ~ {days[-1]})")
    return p

# ── 트레일링 윈도우 검증: 각 날짜를 '직전 K일'로만 학습해 예측 ──
def _mape(a, p): return sum(abs(x - y) / x for x, y in zip(a, p) if x) / len(a) * 100
def _mae(a, p):  return sum(abs(x - y) for x, y in zip(a, p)) / len(a)

def validate(hourly, K=45):
    fc = importlib.util.spec_from_file_location("fc", os.path.join(HERE, "smp_forecast.py"))
    F = importlib.util.module_from_spec(fc); fc.loader.exec_module(F)
    dates = sorted(hourly)
    def fit_A_window(train):   # 윈도우 인샘플로 태양광 A 적합(계절 적응)
        def m(Asol):
            c = F.Curve(F.pairs(train, solar_A=Asol))
            a, p = [], []
            for dt in train:
                for h in train[dt]:
                    if h.get("smp") is None or h.get("load") is None: continue
                    a.append(h["smp"]); p.append(c.predict(F.net_load(h["load"], h["hr"], Asol), h["hr"]))
            return _mape(a, p)
        return min(range(0, 21), key=lambda x: m(float(x))) * 1.0
    from collections import defaultdict
    bymon = defaultdict(lambda: [[], []])
    A, P = [], []
    for i, d in enumerate(dates):
        if i < K:
            continue
        train = {dt: hourly[dt] for dt in dates[i - K:i]}   # 직전 K일
        Asol = fit_A_window(train)
        c = F.Curve(F.pairs(train, solar_A=Asol))
        for h in hourly[d]:
            if h.get("load") is None or h.get("smp") is None:
                continue
            p = c.predict(F.net_load(h["load"], h["hr"], Asol), h["hr"])
            A.append(h["smp"]); P.append(p)
            m = d[:7]; bymon[m][0].append(h["smp"]); bymon[m][1].append(p)
    print(f"=== 트레일링 {K}일 윈도우 + 윈도우별 태양광A 검증 (예측 {len(A)}시간) ===")
    print(f"{'month':9}{'MAPE%':>8}{'MAE':>8}")
    for m in sorted(bymon):
        a, p = bymon[m]
        print(f"{m:9}{_mape(a,p):8.2f}{_mae(a,p):8.2f}")
    print(f"{'-'*25}\n{'전체':9}{_mape(A,P):8.2f}{_mae(A,P):8.2f}")

def load_fuel():
    """월별 LNG 중앙 적용열량단가 {'YYYY-MM': val}. 로컬 캐시."""
    import csv
    p = os.path.join(CACHE, "fuel_cost.csv")
    if not os.path.exists(p):
        os.makedirs(CACHE, exist_ok=True)
        boto3.client("s3").download_file(BUCKET, "data/fuel_cost.csv", p)
    from collections import defaultdict
    vals = defaultdict(list)
    with open(p, encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            if r.get("대분류") == "LNG":
                try: vals[r["적용월"]].append(float(r["적용열량단가"]))
                except (TypeError, ValueError): pass
    def median(xs):
        xs = sorted(xs); n = len(xs)
        return (xs[n//2] if n % 2 else (xs[n//2-1]+xs[n//2])/2) if n else None
    return {m: median(v) for m, v in vals.items()}

def validate_fuel(hourly, fuel, K=0):
    """연료비 정규화 모델: SMP/LNG단가 로 곡선 학습→예측→대상월 단가 곱. K=0이면 전체(leave-1day-out)."""
    fc = importlib.util.spec_from_file_location("fc", os.path.join(HERE, "smp_forecast.py"))
    F = importlib.util.module_from_spec(fc); fc.loader.exec_module(F)
    dates = [d for d in sorted(hourly) if d[:7] in fuel]
    def norm_pairs(days, A):
        out = []
        for d in days:
            fm = fuel[d[:7]]
            for h in hourly[d]:
                if h.get("load") is not None and h.get("smp") is not None:
                    out.append((F.net_load(h["load"], h["hr"], A), h["smp"]/fm, h["hr"]))
        return out
    # 태양광 A: 정규화 데이터로 1회 인샘플 적합
    def insample(A):
        c = F.Curve(norm_pairs(dates, A))
        a, p = [], []
        for d in dates:
            fm = fuel[d[:7]]
            for h in hourly[d]:
                if h.get("load") is None or h.get("smp") is None: continue
                a.append(h["smp"]); p.append(c.predict(F.net_load(h["load"], h["hr"], A), h["hr"])*fm)
        return _mape(a, p)
    A = min(range(0, 21), key=lambda x: insample(float(x))) * 1.0
    from collections import defaultdict
    bymon = defaultdict(lambda: [[], []]); AA, PP = [], []
    for i, d in enumerate(dates):
        train = dates[max(0, i-K):i] + dates[i+1:i+1+K] if K else [x for x in dates if x != d]
        c = F.Curve(norm_pairs(train, A)); fm = fuel[d[:7]]
        for h in hourly[d]:
            if h.get("load") is None or h.get("smp") is None: continue
            p = c.predict(F.net_load(h["load"], h["hr"], A), h["hr"]) * fm
            AA.append(h["smp"]); PP.append(p)
            m = d[:7]; bymon[m][0].append(h["smp"]); bymon[m][1].append(p)
    tag = f"전체(leave-1day-out)" if not K else f"트레일링±{K}일"
    print(f"=== 연료비 정규화 모델 [{tag}] (태양광 A={A:.0f}GW, {len(AA)}시간) ===")
    print(f"{'month':9}{'MAPE%':>8}{'MAE':>8}")
    for m in sorted(bymon):
        a, p = bymon[m]; print(f"{m:9}{_mape(a,p):8.2f}{_mae(a,p):8.2f}")
    print(f"{'-'*25}\n{'전체':9}{_mape(AA,PP):8.2f}{_mae(AA,PP):8.2f}")

def main():
    a = sys.argv[1:]
    if "--validate-fuel" in a:
        hourly = json.load(open(os.path.join(HERE, "smp_hourly_s3.json"), encoding="utf-8"))["hourly"]
        K = int(a[a.index("--K") + 1]) if "--K" in a else 0
        validate_fuel(hourly, load_fuel(), K)
    elif "--validate" in a:
        p = os.path.join(HERE, "smp_hourly_s3.json")
        if not os.path.exists(p):
            print("smp_hourly_s3.json 없음 → 먼저 다운로드/빌드");
            if not os.path.isdir(CACHE): download()
            save(build_hourly())
        hourly = json.load(open(p, encoding="utf-8"))["hourly"]
        K = int(a[a.index("--K") + 1]) if "--K" in a else 45
        validate(hourly, K)
    else:
        download()
        save(build_hourly())

if __name__ == "__main__":
    main()
