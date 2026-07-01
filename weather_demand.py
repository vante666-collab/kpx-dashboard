#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
(C) 내일 예측 루프 1부 — 수요 예측 모델.
수요[date,hr] ~ f(기온, hr, day_type). 시간·요일유형별 기온 2차 회귀(냉난방 U자).
데이터: asos_national(실측기온) + demand_cache(수요) + calendar(요일유형), 모두 S3.

  python weather_demand.py            # 2025 학습→2026 테스트, 수요예측 MAPE
"""
import os, sys, io, csv
import boto3
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "s3cache")
BUCKET = "kpx-epowermarket-data"

def _dl(key, fname):
    p = os.path.join(CACHE, fname)
    if not os.path.exists(p):
        os.makedirs(CACHE, exist_ok=True)
        boto3.client("s3").download_file(BUCKET, key, p)
    return p

def load_temp():
    """asos_national → {(YYYYMMDD, hr1..24): 기온_w1}"""
    p = _dl("weather/asos_national.csv", "asos_national.csv")
    out = {}
    with open(p, encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            ts = r["일시"]  # 'YYYY-MM-DD HH:MM'
            try:
                d = ts[:10].replace("-", ""); hh = int(ts[11:13])
                t = float(r["기온_w1(℃)"])
            except (ValueError, KeyError):
                continue
            hr = 24 if hh == 0 else hh   # 00:00 = 24시로
            out[(d, hr)] = t
    return out

def load_demand():
    p = os.path.join(CACHE, "demand_cache.csv")
    if not os.path.exists(p): _dl("data/demand_cache.csv", "demand_cache.csv")
    out = {}
    with open(p, encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            if r.get("area_div") != "MAINLAND": continue
            for h in range(1, 25):
                v = r.get(f"hh{h:02d}_val")
                if v: out[(r["deal_date"], h)] = float(v)/1000.0  # GW
    return out

def load_daytype():
    p = _dl("weather/calendar.csv", "calendar.csv")
    out = {}
    with open(p, encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            out[r["date"].replace("-", "")] = r["day_type"]
    return out

class DemandModel:
    """(hr, day_type)별 기온 2차 회귀."""
    def __init__(self, temp, dem, dtype, train_days):
        from collections import defaultdict
        pts = defaultdict(lambda: ([], []))
        for (d, hr), t in temp.items():
            if d not in train_days: continue
            dm = dem.get((d, hr)); dt = dtype.get(d)
            if dm is None or dt is None: continue
            pts[(hr, dt)][0].append(t); pts[(hr, dt)][1].append(dm)
        self.coef = {}
        self.fallback = {}  # (hr): 전체 day_type 통합 2차 (희소 대비)
        allh = defaultdict(lambda: ([], []))
        for (hr, dt), (xs, ys) in pts.items():
            if len(xs) >= 8:
                self.coef[(hr, dt)] = np.polyfit(xs, ys, 2)
            allh[hr][0].extend(xs); allh[hr][1].extend(ys)
        for hr, (xs, ys) in allh.items():
            if len(xs) >= 8: self.fallback[hr] = np.polyfit(xs, ys, 2)

    def predict(self, t, hr, dt):
        c = self.coef.get((hr, dt))
        if c is None:
            c = self.fallback.get(hr)
        return float(np.polyval(c, t)) if c is not None else None

def validate():
    temp, dem, dtype = load_temp(), load_demand(), load_daytype()
    days = sorted({d for (d, _) in dem})
    train = {d for d in days if d < "20260101"}
    test  = [d for d in days if d >= "20260101"]
    m = DemandModel(temp, dem, dtype, train)
    print(f"수요모델: 학습 {len(train)}일(2025) → 테스트 {len(test)}일(2026~)")
    from collections import defaultdict
    bym = defaultdict(lambda: [[], []]); A, P = [], []
    for d in test:
        for hr in range(1, 25):
            a = dem.get((d, hr)); t = temp.get((d, hr)); dt = dtype.get(d)
            if a is None or t is None: continue
            p = m.predict(t, hr, dt)
            if p is None: continue
            A.append(a); P.append(p); bym[d[:6]][0].append(a); bym[d[:6]][1].append(p)
    def mape(a, p): return sum(abs(x-y)/x for x, y in zip(a, p) if x)/len(a)*100
    def mae(a, p): return sum(abs(x-y) for x, y in zip(a, p))/len(a)
    print(f"\n{'month':8}{'MAPE%':>8}{'MAE(GW)':>9}")
    for mo in sorted(bym):
        a, p = bym[mo]; print(f"{mo:8}{mape(a,p):8.2f}{mae(a,p):9.2f}")
    print(f"{'-'*25}\n{'전체':8}{mape(A,P):8.2f}{mae(A,P):9.2f}")
    print(f"\n해석: 실측 기온 기준 익일 수요를 MAPE {mape(A,P):.1f}%로 예측 "
          f"(평균 절대오차 {mae(A,P):.2f} GW).")

def chain(K=45):
    """엔드투엔드: 예측수요 → 트레일링 공급곡선 → 예측 SMP → 실측 비교(2026)."""
    import json, importlib.util
    temp, dem, dtype = load_temp(), load_demand(), load_daytype()
    days = sorted({d for (d, _) in dem})
    m = DemandModel(temp, dem, dtype, {d for d in days if d < "20260101"})
    fc = importlib.util.spec_from_file_location("fc", os.path.join(HERE, "smp_forecast.py"))
    F = importlib.util.module_from_spec(fc); fc.loader.exec_module(F)
    hourly = json.load(open(os.path.join(HERE, "smp_hourly_s3.json"), encoding="utf-8"))["hourly"]
    iso = sorted(hourly)  # 'YYYY-MM-DD'
    def A_fit(train):
        def mm(A):
            c = F.Curve(F.pairs(train, solar_A=A)); a, p = [], []
            for dt in train:
                for h in train[dt]:
                    if h.get("smp") is None or h.get("load") is None: continue
                    a.append(h["smp"]); p.append(c.predict(F.net_load(h["load"], h["hr"], A), h["hr"]))
            return sum(abs(x-y)/x for x, y in zip(a, p) if x)/len(a)
        return min(range(0, 16, 2), key=lambda x: mm(float(x)))*1.0
    from collections import defaultdict
    bym = defaultdict(lambda: [[], []]); A, P = [], []
    for i, isod in enumerate(iso):
        d = isod.replace("-", "")
        if d < "20260101" or i < K: continue
        train = {x: hourly[x] for x in iso[i-K:i]}
        Asol = A_fit(train); c = F.Curve(F.pairs(train, solar_A=Asol))
        dt = dtype.get(d)
        for h in hourly[isod]:
            hr = h["hr"]; act = h.get("smp"); t = temp.get((d, hr))
            if act is None or t is None: continue
            pl = m.predict(t, hr, dt)               # 예측 수요(GW)
            if pl is None: continue
            p = c.predict(F.net_load(pl, hr, Asol), hr)  # → 예측 SMP
            A.append(act); P.append(p); bym[d[:6]][0].append(act); bym[d[:6]][1].append(p)
    def mape(a, p): return sum(abs(x-y)/x for x, y in zip(a, p) if x)/len(a)*100
    def mae(a, p): return sum(abs(x-y) for x, y in zip(a, p))/len(a)
    print(f"=== 엔드투엔드 (기온→수요→SMP) 2026 검증, 트레일링 {K}일 ({len(A)}시간) ===")
    print(f"{'month':8}{'MAPE%':>8}{'MAE':>8}")
    for mo in sorted(bym):
        a, p = bym[mo]; print(f"{mo:8}{mape(a,p):8.2f}{mae(a,p):8.2f}")
    print(f"{'-'*24}\n{'전체':8}{mape(A,P):8.2f}{mae(A,P):8.2f}")

def load_forecast_temp():
    """forecast_national → {(YYYYMMDD, clock0..23): 기온_w1} (각 예보일시 최신 발표 채택)."""
    p = _dl("weather/forecast_national.csv", "forecast_national.csv")
    latest = {}  # key → (발표일시, temp)
    with open(p, encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            fdt = r["예보일시"]  # 'YYYYMMDD HHMM'
            try: t = float(r["기온_w1(℃)"])
            except (TypeError, ValueError): continue
            key = (fdt[:8], int(fdt[9:11]))
            pub = r["발표일시"]
            if key not in latest or pub > latest[key][0]:
                latest[key] = (pub, t)
    return {k: v[1] for k, v in latest.items()}

def _nextday(d):
    import datetime
    dt = datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8])) + datetime.timedelta(days=1)
    return dt.strftime("%Y%m%d")

def predict_tomorrow(target, K=45):
    """예보 기온 → 익일 수요 → 트레일링 공급곡선 → 내일 24h SMP 예측(순수 전방 예측)."""
    import json, importlib.util
    temp, dem, dtype = load_temp(), load_demand(), load_daytype()
    ftemp = load_forecast_temp()
    days = sorted({d for (d, _) in dem})
    m = DemandModel(temp, dem, dtype, {d for d in days if d < target})  # target 이전 전부로 학습
    fc = importlib.util.spec_from_file_location("fc", os.path.join(HERE, "smp_forecast.py"))
    F = importlib.util.module_from_spec(fc); fc.loader.exec_module(F)
    hourly = json.load(open(os.path.join(HERE, "smp_hourly_s3.json"), encoding="utf-8"))["hourly"]
    iso = [d for d in sorted(hourly) if d.replace("-", "") < target]
    train = {x: hourly[x] for x in iso[-K:]}
    def A_fit(tr):
        def mm(A):
            c = F.Curve(F.pairs(tr, solar_A=A)); a, p = [], []
            for dt in tr:
                for h in tr[dt]:
                    if h.get("smp") is None or h.get("load") is None: continue
                    a.append(h["smp"]); p.append(c.predict(F.net_load(h["load"], h["hr"], A), h["hr"]))
            return sum(abs(x-y)/x for x, y in zip(a, p) if x)/len(a)
        return min(range(0, 16, 2), key=lambda x: mm(float(x)))*1.0
    Asol = A_fit(train); c = F.Curve(F.pairs(train, solar_A=Asol))
    dt = dtype.get(target); nd = _nextday(target)
    dtnm = {"0": "평일", "1": "토/특수", "2": "휴일"}.get(dt, dt)
    print(f"=== {target} 내일 SMP 예측 (예보기온 기반, day_type={dtnm}, 태양광 A={Asol:.0f}GW) ===")
    print(f"학습: 수요모델 ~{target} 이전 / 공급곡선 직전 {K}일({iso[-1]})")
    print(f"{'hr':>3}{'기온℃':>7}{'예측수요GW':>10}{'예측SMP':>9}")
    ps = []
    for hr in range(1, 25):
        t = ftemp.get((target, hr % 24)) if hr < 24 else ftemp.get((nd, 0))
        if t is None: continue
        pl = m.predict(t, hr, dt)
        if pl is None: continue
        p = c.predict(F.net_load(pl, hr, Asol), hr); ps.append(p)
        print(f"{hr:3d}{t:7.1f}{pl:10.1f}{p:9.1f}")
    if ps:
        print(f"{'-'*30}\n예측 일평균 SMP ≈ {sum(ps)/len(ps):.1f} 원/kWh  (범위 {min(ps):.0f}~{max(ps):.0f})")
        print("※ 예보기온 오차까지 포함된 순수 전방예측. 실측기온 기준 엔드투엔드 검증 MAPE≈14.6%.")

def emit_dashboard(target, K=45):
    """내일 SMP 예측 대시보드용 JSON 생성 + forecast.html 임베드."""
    import json, re, importlib.util
    temp, dem, dtype = load_temp(), load_demand(), load_daytype()
    ftemp = load_forecast_temp()
    days = sorted({d for (d, _) in dem})
    m = DemandModel(temp, dem, dtype, {d for d in days if d < target})
    fc = importlib.util.spec_from_file_location("fc", os.path.join(HERE, "smp_forecast.py"))
    F = importlib.util.module_from_spec(fc); fc.loader.exec_module(F)
    hourly = json.load(open(os.path.join(HERE, "smp_hourly_s3.json"), encoding="utf-8"))["hourly"]
    iso = [d for d in sorted(hourly) if d.replace("-", "") < target]
    train = {x: hourly[x] for x in iso[-K:]}
    def A_fit(tr):
        def mm(A):
            c = F.Curve(F.pairs(tr, solar_A=A)); a, p = [], []
            for dt in tr:
                for h in tr[dt]:
                    if h.get("smp") is None or h.get("load") is None: continue
                    a.append(h["smp"]); p.append(c.predict(F.net_load(h["load"], h["hr"], A), h["hr"]))
            return sum(abs(x-y)/x for x, y in zip(a, p) if x)/len(a)
        return min(range(0, 16, 2), key=lambda x: mm(float(x)))*1.0
    Asol = A_fit(train); c = F.Curve(F.pairs(train, solar_A=Asol))
    dt = dtype.get(target); nd = _nextday(target)
    rows, ps = [], []
    for hr in range(1, 25):
        t = ftemp.get((target, hr % 24)) if hr < 24 else ftemp.get((nd, 0))
        if t is None: continue
        pl = m.predict(t, hr, dt)
        if pl is None: continue
        p = c.predict(F.net_load(pl, hr, Asol), hr); ps.append(p)
        rows.append({"hr": hr, "temp": round(t, 1), "demand": round(pl, 1),
                     "net": round(F.net_load(pl, hr, Asol), 1), "smp": round(p, 1)})
    # 최근 40일 실측 일평균 SMP 추이 + 내일 예측 append
    trend = []
    for isod in iso[-40:]:
        smps = [h["smp"] for h in hourly[isod] if h.get("smp") is not None]
        if smps: trend.append({"date": isod[5:], "smp": round(sum(smps)/len(smps), 1), "f": False})
    ti = f"{target[4:6]}-{target[6:8]}"
    trend.append({"date": ti, "smp": round(sum(ps)/len(ps), 1), "f": True})
    # 수요모델 정확도(빠름) 라이트 계산
    da, dp = [], []
    for d in [x for x in days if x >= "20260101"]:
        for hr in range(1, 25):
            a = dem.get((d, hr)); tt = temp.get((d, hr))
            if a is None or tt is None: continue
            pp = m.predict(tt, hr, dtype.get(d))
            if pp is not None: da.append(a); dp.append(pp)
    dmape = sum(abs(a-p)/a for a, p in zip(da, dp) if a)/len(da)*100 if da else None
    out = {
        "target": f"{target[:4]}-{target[4:6]}-{target[6:8]}",
        "dayType": {"0": "평일", "1": "토/특수", "2": "휴일"}.get(dt, dt),
        "solarA": round(Asol, 0), "trainDays": K, "trainEnd": iso[-1],
        "avg": round(sum(ps)/len(ps), 1), "min": round(min(ps), 1), "max": round(max(ps), 1),
        "peakHr": rows[max(range(len(rows)), key=lambda i: rows[i]["smp"])]["hr"],
        "demandMape": round(dmape, 1) if dmape else None, "e2eMape": 14.6,
        "rows": rows,
        "curve": [{"x": round(x, 2), "y": round(y, 1)} for x, y in zip(c.kx, c.ky)],
        "points": [{"x": round(x, 1), "y": round(s, 1)} for (x, s, h) in F.pairs(train, solar_A=Asol)],
        "trend": trend,
    }
    jp = os.path.join(HERE, "tomorrow_data.json")
    json.dump(out, open(jp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    hp = os.path.join(HERE, "forecast.html")
    if os.path.exists(hp):
        blob = "const TMR_DATA=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "; //__TMR_DATA__"
        html = open(hp, encoding="utf-8").read()
        if not re.search(r'(?:var|const)\s+TMR_DATA=.*?//__TMR_DATA__', html):
            print("⚠ embed 실패: forecast.html 에 //__TMR_DATA__ 마커 없음")
        else:
            html2 = re.sub(r'(?:var|const)\s+TMR_DATA=.*?//__TMR_DATA__', lambda mm: blob, html, count=1)
            open(hp, "w", encoding="utf-8").write(html2)
            print("embedded into forecast.html (OK)" if html2 != html
                  else "embedded into forecast.html (동일 예측 — 변경 없음)")
    print(f"→ {jp}  (내일 {out['target']} 일평균 {out['avg']}원, 피크 {out['max']}@{out['peakHr']}시, 수요MAPE {out['demandMape']}%)")

def main():
    if "--emit-dashboard" in sys.argv:
        i = sys.argv.index("--emit-dashboard")
        emit_dashboard(sys.argv[i+1] if len(sys.argv) > i+1 and not sys.argv[i+1].startswith("--") else "20260702")
    elif "--tomorrow" in sys.argv:
        i = sys.argv.index("--tomorrow")
        target = sys.argv[i+1] if len(sys.argv) > i+1 and not sys.argv[i+1].startswith("--") else "20260702"
        predict_tomorrow(target)
    elif "--chain" in sys.argv:
        chain()
    else:
        validate()

if __name__ == "__main__":
    main()
