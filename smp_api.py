#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
전력거래소 KMOS Open API 자동 수집기 (apis.kmos.kr) — 전력거래자 전용.
인증(/auth) → 하루전 수요예측·SMP·가격결정발전기·가격결정자격(PSI/SMF) 수집 →
smp_data.json 병합 + smp.html 자동 임베드. (제약검토서는 API 미제공: smp_ingest.py로 보완)

사용법:
  # 자격증명은 환경변수로만 (절대 코드/깃에 넣지 말 것)
  set KMOS_API_KEY=...        (요청 헤더 API_KEY)
  set KMOS_USERNAME=...
  set KMOS_PASSWORD=...
  set KMOS_APIKEY=...         (auth 본문 apiKey, 미설정 시 API_KEY 재사용)
  set KMOS_ENV=prod           (prod|stg, 기본 prod)
  python smp_api.py 2026-06-18 2026-06-19      # 날짜 여러 개 가능 (YYYY-MM-DD 또는 YYYYMMDD)

※ 본 스크립트는 실 API 응답으로 1회 검증 필요(td 표시기 포맷, getReports 구조).
   --debug 로 첫 응답 원본을 reports/ 에 덤프해 확인.
"""
import os, sys, re, json, ssl, urllib.request, urllib.parse, urllib.error, importlib.util

# 회사망 SSL 검사(보안 프록시)로 인증서 검증이 실패하는 경우 대비.
# KMOS_INSECURE=1 이면 처음부터 미검증, 아니면 검증 실패 시 1회 경고 후 미검증으로 자동 재시도.
_CTX = ssl._create_unverified_context() if os.environ.get("KMOS_INSECURE","").strip() in ("1","true","True","Y","y") else None
_warned_ssl = False

ENV       = os.environ.get("KMOS_ENV", "prod")
BASE      = f"https://apis.kmos.kr/{ENV}"
API_KEY   = os.environ.get("KMOS_API_KEY")
APIKEY_B  = os.environ.get("KMOS_APIKEY", API_KEY)   # auth 본문 apiKey
USERNAME  = os.environ.get("KMOS_USERNAME")
PASSWORD  = os.environ.get("KMOS_PASSWORD")
DEBUG     = "--debug" in sys.argv
HERE      = os.path.dirname(os.path.abspath(__file__))

def _req(url, method="GET", headers=None, body=None, timeout=30):
    global _CTX, _warned_ssl
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8","replace")[:400]
        except Exception: pass
        raise SystemExit(f"HTTP {e.code} {e.reason}  @ {url.split('?')[0]}  (env={ENV})\n서버응답: {body}\n"
                         f"→ 401이면 보통: 자격증명 불일치 / API_KEY·apiKey 잘못 / 환경(prod↔stg) 불일치. KMOS_ENV=stg 로도 시도해보세요.")
    except ssl.SSLCertVerificationError:
        if not _warned_ssl:
            print("⚠ SSL 인증서 검증 실패 → 미검증 모드로 자동 재시도(회사망 SSL검사 추정). 신뢰되는 내부망에서만 사용하세요.")
            _warned_ssl = True
        _CTX = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))

def auth():
    if not (API_KEY and USERNAME and PASSWORD):
        raise SystemExit("환경변수 KMOS_API_KEY / KMOS_USERNAME / KMOS_PASSWORD 가 필요합니다.")
    h = {"Content-Type": "application/json", "API_KEY": API_KEY}
    j = _req(f"{BASE}/auth", "POST", h, {"username": USERNAME, "password": PASSWORD, "apiKey": APIKEY_B})
    tok = (j.get("resultData") or {}).get("access_token")
    if not tok:
        raise SystemExit(f"토큰 발급 실패: {json.dumps(j, ensure_ascii=False)[:300]}")
    print(f"auth OK (env={ENV})")
    return tok

def _get(token, path, params):
    qs = urllib.parse.urlencode(params)
    h = {"Content-Type": "application/json", "API_KEY": API_KEY, "Authorization": f"Bearer {token}"}
    j = _req(f"{BASE}/{path}?{qs}", "GET", h)
    if DEBUG:
        os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
        with open(os.path.join(HERE, "reports", f"{path}_{params.get('tradYmd','')}_{params.get('gubunCd','')}.json"), "w", encoding="utf-8") as f:
            json.dump(j, f, ensure_ascii=False, indent=1)
    return j

def _rows(j):
    rd = j.get("resultData")
    return rd if isinstance(rd, list) else ([rd] if isinstance(rd, dict) else [])

def _td(row):
    return [row.get(f"td{h:02d}") for h in range(1, 25)]

def _num(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def _flag(v):
    return 1 if str(v).strip() in ("1", "Y", "y", "true", "True", "O") else 0

# ───────────── 개별 수집 ─────────────
def fetch_load(token, ymd):   # 하루전 예측수요 (MW→GW)
    rows = _rows(_get(token, "getDALoadForecast", {"tradYmd": ymd, "mnlnJjClCd": "01"}))
    row = next((r for r in rows if str(r.get("mnlnJjClCd")) == "01"), rows[0] if rows else None)
    if not row: return {}
    return {h+1: (_num(v)/1000 if _num(v) is not None else None) for h, v in enumerate(_td(row))}

def fetch_smp(token, ymd):    # 하루전 SMP (원/kWh)
    rows = _rows(_get(token, "getDAMarginalPrice", {"tradYmd": ymd, "mnlnJjClCd": "01"}))
    row = next((r for r in rows if str(r.get("mnlnJjClCd", "01")) == "01"), rows[0] if rows else None)
    if not row: return {}
    return {h+1: _num(v) for h, v in enumerate(_td(row))}

def fetch_clearing(token, ymd):  # 하루전 가격결정발전기 (long)
    hours = []
    for x in _rows(_get(token, "getDAClearingResource", {"tradYmd": ymd, "mnlnJjClCd": "01"})):
        m = re.match(r"(\d+)", str(x.get("tradHh", "")))
        smp = _num(x.get("smp"))
        if m and smp is not None:
            hours.append({"hr": int(m.group(1)), "smp": smp, "gname": str(x.get("genNm", "")).strip()})
    hours.sort(key=lambda z: z["hr"])
    if not hours: return None
    mx = max(hours, key=lambda z: z["smp"]); mn = min(hours, key=lambda z: z["smp"])
    return {"hours": hours,
            "max": {"smp": mx["smp"], "gname": mx["gname"]},
            "min": {"smp": mn["smp"], "gname": mn["gname"]}}

def fetch_priceind(token, ymd):  # 가격결정자격 PSI(1)/SMF(3)
    out = {}
    for gubun, key in (("1", "psi"), ("3", "smf")):
        for x in _rows(_get(token, "getDAPriceIndicator", {"tradYmd": ymd, "mnlnJjClCd": "01", "gubunCd": gubun})):
            nm = str(x.get("genNm", "")).strip()
            if not nm: continue
            out.setdefault(nm, {})[key] = [_flag(v) for v in _td(x)]
    return out  # { genNm: {psi:[24], smf:[24]} }

def fetch_supply(token, ymd):  # 공급능력표(getReports reportCd=02) — 구조 확인 후 매핑 예정
    j = _get(token, "getReports", {"tradYmd": ymd, "reportCd": "02"})
    # TODO: 첫 실응답(--debug 덤프)으로 reportSections/Lines/Items 코드 확인 후 fuels/total/changes 매핑.
    return None  # 현재는 미매핑 → ⑤는 공급능력표(.txt)/기존 데이터 유지

# ───────────── 메인 ─────────────
def main():
    dates = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not dates:
        raise SystemExit("날짜를 지정하세요. 예) python smp_api.py 2026-06-18 2026-06-19")
    ymds = [re.sub(r"[^0-9]", "", d) for d in dates]

    path = os.path.join(HERE, "smp_data.json")
    data = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else \
        {"daily": [], "marg": {}, "hourly": {}, "constraint": {}, "supply": {}, "priceind": {},
         "mustrun_standing": [], "mustrun_outage": []}
    data.setdefault("priceind", {})
    daily_by = {x["d"]: x for x in data["daily"]}

    token = auth()
    for ymd in ymds:
        iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
        load = fetch_load(token, ymd)
        smp  = fetch_smp(token, ymd)
        marg = fetch_clearing(token, ymd)
        pind = fetch_priceind(token, ymd)
        if marg: marg["date"] = iso; data["marg"][iso] = marg
        hrs = sorted(set(load) | set(smp))
        if hrs:
            data["hourly"][iso] = [{"hr": h, "load": load.get(h), "smp": smp.get(h)} for h in hrs]
        if pind: data["priceind"][iso] = pind
        # 일평균(시간별 평균으로 합성)
        smps = [v for v in smp.values() if v is not None]
        loads = [v for v in load.values() if v is not None]
        if smps:
            daily_by[iso] = {"d": iso, "smp": round(sum(smps)/len(smps), 2),
                             "dem": round(sum(loads)/len(loads), 3) if loads else None}
        sup = fetch_supply(token, ymd)
        if sup: data["supply"][iso] = sup
        print(f"  {iso}: load {len(load)}h / smp {len(smp)}h / marg {len(marg['hours']) if marg else 0}h / priceind {len(pind)}gen")

    data["daily"] = sorted(daily_by.values(), key=lambda x: x["d"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    # smp.html 임베드 (+_site) — smp_ingest의 함수 재사용
    sp = importlib.util.spec_from_file_location("ing", os.path.join(HERE, "smp_ingest.py"))
    ing = importlib.util.module_from_spec(sp); sp.loader.exec_module(ing)
    ing.embed_into_html(data, HERE)
    print(f"\n→ {path}  (marg {list(data['marg'])} / priceind {list(data['priceind'])})")

if __name__ == "__main__":
    main()
