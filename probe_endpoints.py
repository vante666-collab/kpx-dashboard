#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
KMOS 엔드포인트 구조 점검(probe) — 메리트오더 SMP 예측 입력 후보 검증용.

★ 중요: urllib 은 요청 헤더 이름을 capitalize 해버려서 'API_KEY' 가 'Api_key' 로
나간다(확인됨). KMOS 게이트웨이는 헤더 이름을 대소문자 구분 → 401 No authorized user.
그래서 이 probe 는 헤더를 원형 그대로 보내는 requests 로 직접 auth/GET 한다.

getDAEnSchedule(발전기별 발전계획)·getDAGeneratingPrice(발전기별 변동비)가
  (1) 시장 전체인지 자사 한정인지, (2) 필드 구조가 어떤지 를 1회 실호출로 확인.

사용법(자격증명은 환경변수로만 — probe_run.bat 가 입력):
  python probe_endpoints.py 2026-06-26
결과: reports/probe_<endpoint>_<ymd>.json (원본) + 콘솔 구조 요약. (비밀번호/키 미출력)
"""
import os, sys, re, json, importlib.util
import requests
from requests.adapters import HTTPAdapter

HERE = os.path.dirname(os.path.abspath(__file__))

# 파싱 헬퍼만 smp_api 에서 재사용(네트워크 X)
sp = importlib.util.spec_from_file_location("smp_api", os.path.join(HERE, "smp_api.py"))
K = importlib.util.module_from_spec(sp); sp.loader.exec_module(K)

ENV      = os.environ.get("KMOS_ENV", "prod")
BASE     = f"https://apis.kmos.kr/{ENV}"
API_KEY  = os.environ.get("KMOS_API_KEY")
APIKEY_B = os.environ.get("KMOS_APIKEY") or API_KEY     # 본문 apiKey(규격상 필수, 헤더와 별개일 수 있음)
USERNAME = os.environ.get("KMOS_USERNAME")
PASSWORD = os.environ.get("KMOS_PASSWORD")
# 회사망 SSL 검사 대응: 기본 검증, 실패 시 미검증 재시도
VERIFY   = not (os.environ.get("KMOS_INSECURE", "").strip() in ("1", "true", "True", "Y", "y"))

TARGETS = [
    ("getDAEnSchedule",      [{}, {"gubunCd": "1"}]),
    ("getDAGeneratingPrice", [{}, {"gubunCd": "1"}]),
]

def _post(path, headers, body):
    global VERIFY
    url = f"{BASE}/{path}"
    try:
        r = requests.post(url, headers=headers, json=body, timeout=30, verify=VERIFY)
    except requests.exceptions.SSLError:
        print("⚠ SSL 검증 실패 → 미검증 재시도(회사망 SSL검사 추정)")
        VERIFY = False
        r = requests.post(url, headers=headers, json=body, timeout=30, verify=VERIFY)
    return r

def _get(path, headers, params):
    global VERIFY
    url = f"{BASE}/{path}"
    try:
        r = requests.get(url, headers=headers, params=params, timeout=30, verify=VERIFY)
    except requests.exceptions.SSLError:
        VERIFY = False
        r = requests.get(url, headers=headers, params=params, timeout=30, verify=VERIFY)
    return r

def auth():
    if not (API_KEY and USERNAME and PASSWORD):
        raise SystemExit("환경변수 KMOS_API_KEY / KMOS_USERNAME / KMOS_PASSWORD 가 필요합니다.")
    if not os.environ.get("KMOS_APIKEY"):
        print("ℹ 본문 apiKey 미입력 → 헤더 API_KEY 재사용. (규격상 apiKey는 64자 필수, "
              "헤더와 다른 값이면 그래도 401 날 수 있음)")
    h = {"Content-Type": "application/json", "API_KEY": API_KEY}     # requests = 원형 그대로 전송
    r = _post("auth", h, {"username": USERNAME, "password": PASSWORD, "apiKey": APIKEY_B})
    if r.status_code != 200:
        raise SystemExit(f"HTTP {r.status_code} @ /auth (env={ENV})\n서버응답: {r.text[:400]}\n"
                         f"→ 헤더는 이제 원형('API_KEY') 전송됨. 그래도 401이면 자격증명 값(특히 본문 apiKey) 확인.")
    tok = (r.json().get("resultData") or {}).get("access_token")
    if not tok:
        raise SystemExit(f"토큰 없음: {r.text[:300]}")
    # 전송된 헤더 키 확인용(키 값은 마스킹)
    sent = {k: ("***" if k.upper() == "API_KEY" else v) for k, v in r.request.headers.items()}
    print(f"auth OK (env={ENV}).  전송 헤더 키: {list(r.request.headers.keys())}")
    return tok

def summarize(name, j):
    rows = K._rows(j)
    print(f"\n{'='*60}\n● {name}  —  resultData rows: {len(rows)}")
    if not rows:
        print("  ⚠ 빈 응답 — 파라미터/날짜/권한 확인")
        ci = j.get("commandCntInfo") or {}
        print(f"  resultCode/Msg: {ci.get('resultCode')} / {ci.get('resultMsg')}")
        return
    r0 = rows[0]
    print(f"  row[0] keys ({len(r0)}): {list(r0.keys())}")
    idkeys = [k for k in r0 if re.search(r"(genId|genNm|hostId|resourceId|gen_cd|genCd|unitNm)", k, re.I)]
    for ik in idkeys:
        distinct = sorted({str(x.get(ik)).strip() for x in rows if x.get(ik) not in (None, "")})
        verdict = "시장 전체 가능성↑ ✅" if len(distinct) >= 30 else \
                  ("자사 한정 가능성 ⚠" if len(distinct) <= 5 else "중간")
        print(f"  distinct '{ik}': {len(distinct)}개 [{verdict}]  예시: {distinct[:8]}")
    tdk = [k for k in r0 if re.match(r"td\d{2}$", k)]
    if tdk:
        print(f"  시간대 wide td01~td{len(tdk):02d}. row[0] 일부: { {k: r0.get(k) for k in list(r0)[:4]} }")
    else:
        print(f"  (long 포맷) row[0]: { {k: r0.get(k) for k in list(r0)[:12]} }")

def main():
    dates = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not dates:
        raise SystemExit("날짜를 지정하세요. 예) python probe_endpoints.py 2026-06-26")
    ymd = re.sub(r"[^0-9]", "", dates[0])
    os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
    print(f"env={ENV}  date={ymd}  인증 시도(requests, 헤더 원형 전송)...")
    token = auth()
    for name, variants in TARGETS:
        h = {"Content-Type": "application/json", "API_KEY": API_KEY, "Authorization": f"Bearer {token}"}
        j, used = None, None
        for extra in variants:
            params = {"tradYmd": ymd, "mnlnJjClCd": "01", **extra}
            r = _get(name, h, params)
            if r.status_code != 200:
                print(f"\n● {name} {extra}: HTTP {r.status_code} — {r.text[:200]}"); continue
            cand = r.json()
            if K._rows(cand):
                j, used = cand, params; break
            j, used = j or cand, used or params
        path = os.path.join(HERE, "reports", f"probe_{name}_{ymd}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(j or {}, f, ensure_ascii=False, indent=1)
        print(f"\n[{name}] params={used} → reports/probe_{name}_{ymd}.json")
        summarize(name, j or {})
    print(f"\n{'='*60}\n완료. reports/probe_*.json 두 파일(또는 위 요약)을 Claude 에게 보여주세요.")

if __name__ == "__main__":
    main()
