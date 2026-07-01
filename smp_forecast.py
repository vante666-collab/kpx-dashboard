#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
내일 SMP 예측 — 경험적 공급곡선(메리트오더) MVP.

아이디어:
  SMP 는 그 시각 한계발전기의 변동비. 수요(=순부하)가 오르면 더 비싼 발전기가
  한계가 되어 SMP 가 오른다 → SMP 는 수요에 대해 단조증가. 과거 (수요, SMP) 쌍으로
  단조증가 공급곡선 f(수요)→SMP 를 등위회귀(isotonic, PAV)로 적합하고,
  시간대별 잔차 평균으로 보정한다.

데이터: smp_data.json 의 hourly[{hr,load,smp}] (smp_ingest.py 가 엑셀에서 생성).
  load 단위 GW, smp 원/kWh.

사용법:
  python smp_forecast.py                 # leave-one-out 교차검증(전체 정확도)
  python smp_forecast.py --date 2026-06-29   # 특정일: 나머지로 학습→그날 예측 vs 실측
  python smp_forecast.py --predict-load "<금일수요예측.xlsx>"  # 익일 수요예측 파일로 24h SMP 예측
"""
import json, os, sys, math, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))

def load_data():
    return json.load(open(os.path.join(HERE, "smp_data.json"), encoding="utf-8"))

# ── 태양광 보정: 순부하 = 수요 − A·pv(hr). pv 는 한낮 피크 종 모양(일출5~일몰20, 정점 12.5시).
#    A(GW)는 데이터로 적합. A=0 이면 보정 없음(self-correcting).
def pv_shape(hr):
    return math.sin(math.pi * (hr - 5) / 15.0) if 5 < hr < 20 else 0.0

def net_load(load, hr, solar_A):
    return load - solar_A * pv_shape(hr)

def pairs(hourly, exclude=None, solar_A=0.0):
    """[(net_load, smp, hr), ...] — load·smp 둘 다 있는 것만, exclude 날짜는 제외."""
    out = []
    for dt, H in hourly.items():
        if dt == exclude:
            continue
        for h in H:
            if h.get("load") is not None and h.get("smp") is not None:
                out.append((net_load(h["load"], h["hr"], solar_A), h["smp"], h["hr"]))
    return out

def _pav(ys):
    """등위회귀(Pool Adjacent Violators) — 비감소 적합값 반환(입력 순서 = x 오름차순)."""
    vals, wts, cnt = [], [], []
    for y in ys:
        v, w, c = y, 1.0, 1
        while vals and vals[-1] > v:
            pv, pw, pc = vals.pop(), wts.pop(), cnt.pop()
            v = (v * w + pv * pw) / (w + pw); w += pw; c += pc
        vals.append(v); wts.append(w); cnt.append(c)
    out = []
    for v, c in zip(vals, cnt):
        out.extend([v] * c)
    return out

class Curve:
    """단조증가 공급곡선 f(load)->smp + 시간대 보정."""
    def __init__(self, pts):
        s = sorted(pts, key=lambda p: p[0])
        xs = [p[0] for p in s]
        fit = _pav([p[1] for p in s])
        # 동일 load 묶어 보간용 노드(kx 오름차순, ky 평균)
        self.kx, self.ky = [], []
        i = 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and xs[j + 1] == xs[i]:
                j += 1
            self.kx.append(xs[i]); self.ky.append(sum(fit[i:j + 1]) / (j + 1 - i))
            i = j + 1
        # 시간대별 잔차 평균(곡선이 못 잡는 시간대 효과)
        res = {h: [] for h in range(1, 25)}
        for (l, smp, hr) in pts:
            res[hr].append(smp - self.f(l))
        self.hadj = {h: (sum(v) / len(v) if v else 0.0) for h, v in res.items()}

    def f(self, load):
        kx, ky = self.kx, self.ky
        if load <= kx[0]:  return ky[0]
        if load >= kx[-1]: return ky[-1]
        lo, hi = 0, len(kx) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if kx[mid] <= load: lo = mid
            else: hi = mid
        x0, x1, y0, y1 = kx[lo], kx[hi], ky[lo], ky[hi]
        t = (load - x0) / (x1 - x0) if x1 > x0 else 0.0
        return y0 + t * (y1 - y0)

    def predict(self, load, hr, use_hour=True):
        return self.f(load) + (self.hadj.get(hr, 0.0) if use_hour else 0.0)

def _metrics(act, pred):
    n = len(act)
    mae = sum(abs(a - p) for a, p in zip(act, pred)) / n
    mape = sum(abs(a - p) / a for a, p in zip(act, pred) if a) / n * 100
    return mae, mape

def loo(hourly, solar_A):
    """leave-one-out 전체 (실측, 예측) 누적 → (act, pred). net load(solar_A) 기준."""
    A, P = [], []
    for d in sorted(hourly):
        c = Curve(pairs(hourly, exclude=d, solar_A=solar_A))
        for h in hourly[d]:
            if h.get("load") is None or h.get("smp") is None:
                continue
            A.append(h["smp"])
            P.append(c.predict(net_load(h["load"], h["hr"], solar_A), h["hr"]))
    return A, P

def fit_solar(hourly, grid=None):
    """태양광 피크 A(GW)를 LOO MAPE 최소화로 적합."""
    grid = grid if grid is not None else [i * 0.5 for i in range(0, 31)]  # 0~15 GW
    best = min(grid, key=lambda A: _metrics(*loo(hourly, A))[1])
    return best

def validate(data):
    hourly = data["hourly"]
    A0 = fit_solar(hourly)
    print(f"=== Leave-One-Out 교차검증 ({len(hourly)}일) ===")
    print(f"태양광 보정 적합값: A = {A0:.1f} GW (한낮 순부하 차감 피크)\n")
    print(f"{'date':12} {'MAE':>6} {'MAPE%':>7}   (순부하+시간보정)")
    AA, PP = [], []
    for d in sorted(hourly):
        c = Curve(pairs(hourly, exclude=d, solar_A=A0))
        act = [h["smp"] for h in hourly[d] if h.get("smp") is not None and h.get("load") is not None]
        pr  = [c.predict(net_load(h["load"], h["hr"], A0), h["hr"])
               for h in hourly[d] if h.get("smp") is not None and h.get("load") is not None]
        mae, mape = _metrics(act, pr)
        print(f"{d:12} {mae:6.2f} {mape:7.2f}")
        AA += act; PP += pr
    mae, mape = _metrics(AA, PP)
    b_mae, b_mape = _metrics(*loo(hourly, 0.0))   # 보정 전 베이스라인
    print(f"{'-'*38}")
    print(f"{'전체(순부하보정)':12} {mae:6.2f} {mape:7.2f}")
    print(f"{'전체(보정전 baseline)':12} {b_mae:6.2f} {b_mape:7.2f}")
    print(f"\n해석: 순부하 보정으로 MAPE {b_mape:.1f}% → {mape:.1f}% "
          f"(MAE {b_mae:.2f} → {mae:.2f} 원/kWh). 한낮 태양광 효과 반영.")

def predict_date(data, d):
    hourly = data["hourly"]
    if d not in hourly:
        raise SystemExit(f"{d} 의 hourly 데이터 없음. 가능: {sorted(hourly)}")
    A0 = fit_solar({k: v for k, v in hourly.items() if k != d})
    c = Curve(pairs(hourly, exclude=d, solar_A=A0))
    print(f"=== {d} 예측 (나머지 {len(hourly)-1}일로 학습, 태양광 A={A0:.1f}GW) ===")
    print(f"{'hr':>3} {'load':>7} {'순부하':>7} {'예측':>7} {'실측':>7} {'오차':>7}")
    act, pred = [], []
    for h in hourly[d]:
        if h.get("load") is None or h.get("smp") is None:
            continue
        nl = net_load(h["load"], h["hr"], A0)
        p = c.predict(nl, h["hr"]); a = h["smp"]
        act.append(a); pred.append(p)
        print(f"{h['hr']:3d} {h['load']:7.2f} {nl:7.2f} {p:7.2f} {a:7.2f} {p-a:+7.2f}")
    mae, mape = _metrics(act, pred)
    print(f"{'-'*46}\nMAE {mae:.2f} 원/kWh,  MAPE {mape:.2f}%")

def predict_load_file(data, path):
    """익일 수요예측 엑셀(금일수요예측 목록) → 24h SMP 예측. 전체 데이터로 학습."""
    sp = importlib.util.spec_from_file_location("ing", os.path.join(HERE, "smp_ingest.py"))
    ing = importlib.util.module_from_spec(sp); sp.loader.exec_module(ing)
    loads = ing.parse_hourly_load(path)  # {hr: GW}
    hourly = data["hourly"]
    A0 = fit_solar(hourly)
    c = Curve(pairs(hourly, solar_A=A0))
    print(f"=== 익일 SMP 예측 (입력: {os.path.basename(path)}, 태양광 A={A0:.1f}GW) ===")
    print(f"{'hr':>3} {'load':>7} {'순부하':>7} {'예측SMP':>8}")
    ps = []
    for hr in sorted(loads):
        nl = net_load(loads[hr], hr, A0)
        p = c.predict(nl, hr); ps.append(p)
        print(f"{hr:3d} {loads[hr]:7.2f} {nl:7.2f} {p:8.2f}")
    print(f"{'-'*32}\n예측 일평균 SMP ≈ {sum(ps)/len(ps):.2f} 원/kWh")

def emit(data):
    """forecast.html 대시보드용 JSON 생성 + HTML 임베드."""
    import re
    hourly = data["hourly"]
    A = fit_solar(hourly)
    full = Curve(pairs(hourly, solar_A=A))
    points = [{"x": round(x, 2), "smp": round(s, 2), "hr": h}
              for (x, s, h) in pairs(hourly, solar_A=A)]
    curve = [{"x": round(x, 3), "y": round(y, 2)} for x, y in zip(full.kx, full.ky)]
    perDate, AA, PP = {}, [], []
    for d in sorted(hourly):
        Ad = fit_solar({k: v for k, v in hourly.items() if k != d})
        c = Curve(pairs(hourly, exclude=d, solar_A=Ad))
        rows, act, pred = [], [], []
        for h in hourly[d]:
            if h.get("load") is None or h.get("smp") is None:
                continue
            nl = net_load(h["load"], h["hr"], Ad); p = c.predict(nl, h["hr"]); a = h["smp"]
            rows.append({"hr": h["hr"], "load": round(h["load"], 2), "net": round(nl, 2),
                         "pred": round(p, 2), "act": round(a, 2)})
            act.append(a); pred.append(p)
        mae, mape = _metrics(act, pred); AA += act; PP += pred
        perDate[d] = {"A": round(Ad, 1), "rows": rows, "mae": round(mae, 2), "mape": round(mape, 2)}
    omae, omape = _metrics(AA, PP); bmae, bmape = _metrics(*loo(hourly, 0.0))
    out = {"solarA": round(A, 1), "ndays": len(hourly), "dates": sorted(hourly),
           "overall": {"mae": round(omae, 2), "mape": round(omape, 2),
                       "baseMae": round(bmae, 2), "baseMape": round(bmape, 2)},
           "curve": curve, "points": points, "perDate": perDate}
    jp = os.path.join(HERE, "forecast_data.json")
    json.dump(out, open(jp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    # forecast.html 임베드
    hp = os.path.join(HERE, "forecast.html")
    if os.path.exists(hp):
        blob = "const FORECAST_DATA=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "; //__FORECAST_DATA__"
        html = open(hp, encoding="utf-8").read()
        html2 = re.sub(r'(?:var|const)\s+FORECAST_DATA=.*?//__FORECAST_DATA__', lambda m: blob, html, count=1)
        open(hp, "w", encoding="utf-8").write(html2)
        print(f"embedded into forecast.html  (마커 치환: {'OK' if html2!=html else '실패-마커없음'})")
    print(f"→ {jp}  (MAPE {omape:.2f}%, A={A:.1f}GW, {len(hourly)}일)")

def main():
    data = load_data()
    a = sys.argv[1:]
    if "--date" in a:
        predict_date(data, a[a.index("--date") + 1])
    elif "--predict-load" in a:
        predict_load_file(data, a[a.index("--predict-load") + 1])
    elif "--emit" in a:
        emit(data)
    else:
        validate(data)

if __name__ == "__main__":
    main()
