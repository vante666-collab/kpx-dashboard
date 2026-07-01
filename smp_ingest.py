#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SMP 분석용 일괄 인제스트 — 올린 원본 파일들을 smp_data.json 으로 변환.
브라우저가 못 읽는 .hwp(제약검토서)까지 여기서 추출한다.

사용법:
  python smp_ingest.py [입력폴더 ...]
  (입력폴더 생략 시 이 스크립트가 있는 폴더를 사용)
  결과: 이 스크립트 옆에 smp_data.json 생성 → smp.html?를 열면 자동 로드.

  옵션:
    --dates 2026-07-01,2026-06-24   특정 날짜만 필터
    --source s3                     팀 S3(kpx-epowermarket-data)에서 daily/hourly/marg 자동 backfill
                                    (AWS_ACCESS_KEY_ID/SECRET/DEFAULT_REGION 환경변수 필요, boto3·pandas 설치)
    --s3-cache DIR                  S3 직결 대신, 미리 받아둔 로컬 CSV 폴더에서 읽음
                                    (사내 프록시가 S3 GET을 막을 때: 먼저 `aws s3 sync s3://kpx-epowermarket-data/data ./DIR`)

  하이브리드 원칙: 로컬 업로드 파일이 우선, 비어있는 날짜만 S3 CSV로 채운다.
  제약검토서(HWP)·공급능력표(txt)는 S3에 없으므로 항상 로컬 파일로 보완한다(=④·④-b·⑤ 섹션).

인식하는 파일(파일명 키워드로 판별, 날짜는 파일명/셀에서 추출):
  - 일별 수요 SMP 목록.xlsx           (여러 날 일평균: 육지 평균수요/평균SMP)
  - 금일수요예측 목록_YYMMDD.xlsx     (시간별 수요=순부하)
  - 일간 계통한계가격 목록_YYMMDD.xlsx (시간별 SMP)
  - 가격결정발전기 목록_YYMMDD.xlsx    (시간별 한계발전기)
  - 제약검토서-YYMMDD..._하루전발전계획용.hwp (융통한계·상시/휴전 제약)

S3 CSV 소스(--source s3 / --s3-cache): smp_cache.csv, demand_cache.csv, marginal_gen_cache.csv
  스키마: deal_date(YYYYMMDD), area_div(MAINLAND/JEJU), hh01_val~hh24_val, calc_avg_val
  (marginal_gen_cache는 컬럼 자동탐지 — date/hour/gen_name/smp. 실제 컬럼명이 다르면 로그 확인 후 _detect 후보 보강)
"""
import olefile, zlib, struct, json, sys, os, re, glob
import openpyxl

# ───────────────────── 공통 ─────────────────────
def iso_from_name(name):
    m = re.search(r'(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', name)  # 'YYYY년 M월 D일'
    if m: return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r'(\d{2})[_\-.]?(\d{2})[_\-.]?(\d{2})', name)
    if not m: return None
    return f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"

def read_text(fn):
    for enc in ("utf-8","cp949","euc-kr"):
        try:
            with open(fn,encoding=enc) as f: return f.read()
        except Exception: pass
    with open(fn,encoding="utf-8",errors="replace") as f: return f.read()

FUEL_KEYS={"수력","국내탄","원자력","LNG기력","석탄","열병합","유류","LNG복합","비중앙"}
SKIP_NAMES={"합계","비중앙","시운전","기타","제주 기타","공급능력보정","시운전2","발 전 소","설비","용량"}

def parse_supply(fn):
    txt=read_text(fn)
    fuels={}; total=None; changes=[]; constrained=[]
    for line in txt.split("\n"):
        cells=[c.strip() for c in line.split("\t")]
        # 연료원별 합계(헤더): '<연료> 계' 다음 셀 'a / b'(전일실적/금일전망)
        for i,c in enumerate(cells):
            if c.endswith("계") and i+1<len(cells) and "/" in cells[i+1]:
                nm=c[:-1].strip().replace(" ","")
                mv=re.search(r'([\d,]+)\s*/\s*([\d,]+)', cells[i+1])
                if mv and nm in FUEL_KEYS:
                    fuels[nm]=int(mv.group(2).replace(",",""))   # 금일전망
        if cells and cells[0]=="합계" and len(cells)>=4:
            try: total=int(cells[3].replace(",",""))
            except: pass
        # 호기별: 이름, 설비, 전일실적, 금일전망, 증감, [비고]
        if len(cells)>=5 and cells[0] not in SKIP_NAMES:
            try:
                fore=int(cells[3].replace(",","")); chg=int(cells[4].replace(",",""))
            except: continue
            note=cells[5] if len(cells)>=6 else ""
            if "송전제약" in note and cells[0] not in constrained: constrained.append(cells[0])
            if abs(chg)>=300: changes.append({"name":cells[0],"delta":chg,"note":note})
    changes.sort(key=lambda x:-abs(x["delta"]))
    return {"fuels":fuels,"total":total,"constrained":constrained,"changes":changes[:10]}

def hr_of(t):
    t = str(t).strip()
    m = re.match(r'^(\d{1,2})\s*시$', t)
    return int(m.group(1)) if m else None

# ───────────────────── HWP 추출 ─────────────────────
def hwp_text(fn):
    ole = olefile.OleFileIO(fn)
    comp = bool(struct.unpack('<I', ole.openstream('FileHeader').read()[36:40])[0] & 1)
    secs = sorted([e for e in ole.listdir() if len(e)==2 and e[0]=='BodyText' and e[1].startswith('Section')],
                  key=lambda e:int(e[1].replace('Section','')))
    out=[]
    for e in secs:
        d = ole.openstream(e).read()
        if comp: d = zlib.decompress(d, -15)
        out.append(_hwp_section(d))
    ole.close()
    return "\n".join(out)

def _hwp_section(data):
    i=0; n=len(data); t=[]
    while i+4<=n:
        h=struct.unpack('<I',data[i:i+4])[0]; i+=4
        tag=h&0x3FF; sz=(h>>20)&0xFFF
        if sz==0xFFF: sz=struct.unpack('<I',data[i:i+4])[0]; i+=4
        rec=data[i:i+sz]; i+=sz
        if tag==67:  # HWPTAG_PARA_TEXT
            t.append(_hwp_para(rec)); t.append("\n")
    return "".join(t)

def _hwp_para(rec):
    o=[]; j=0; L=len(rec)
    while j+2<=L:
        c=struct.unpack('<H',rec[j:j+2])[0]
        if c in (0,10,13):
            if c in (10,13): o.append("\n")
            j+=2
        elif c in (1,2,3,4,5,6,7,8,9,11,12,14,15,16,17,18,19,20,21,22,23):
            j+=16
        elif 0xD800<=c<=0xDBFF and j+4<=L:
            lo=struct.unpack('<H',rec[j+2:j+4])[0]
            if 0xDC00<=lo<=0xDFFF: o.append(chr(((c-0xD800)<<10)+(lo-0xDC00)+0x10000)); j+=4
            else: j+=2
        else:
            o.append(chr(c)); j+=2
    return "".join(o)

# 제약발전 후보 토큰(가격결정발전기명과 매칭되는 형태)
STANDING_TOKENS = ["별내","동탄열병합","포스코","명품오산","오성","영월"]
OUTAGE_CANDIDATES = ["포천","동두천","파주문산","파주열병합","파주","양주","일산","서울복합","안양","광교","평택","화성"]

def parse_constraint(fn):
    txt = hwp_text(fn)
    lines = [l.strip() for l in txt.split("\n") if l.strip()]
    # (1) 융통전력 한계량 시간별 (carry-forward)
    vals={}; i=0
    while i < len(lines):
        m=re.match(r'^(\d{2}):00$', lines[i])
        if m and i+2<len(lines) and lines[i+1]=='~' and re.match(r'^\d{2}:00$',lines[i+2]):
            hr=int(m.group(1)); j=i+3; lim=None
            while j<len(lines) and not re.match(r'^\d{2}:00$',lines[j]):
                mm=re.search(r'(\d{1,2},\d{3})', lines[j])
                if mm: lim=int(mm.group(1).replace(',',''))
                j+=1
            vals[hr]=lim; i=j
        else:
            i+=1
    last=None; limit={}
    for h in range(24):
        if vals.get(h) is not None: last=vals[h]
        if last is not None: limit[h]=last
    # (2) 상시/휴전 섹션 분리
    hyu = next((i for i,l in enumerate(lines) if l.startswith('휴전')), len(lines))
    standing_txt = " ".join(lines[:hyu])
    outage_txt   = " ".join(lines[hyu:])
    standing = [t for t in STANDING_TOKENS if t in standing_txt]
    # 휴전: '제약대상 발전기' 목록 위주로 추출
    outage=set()
    for i,l in enumerate(lines[hyu:], start=hyu):
        if '제약대상' in l and '발전기' in l:
            chunk=" ".join(lines[i:i+4])
            for t in OUTAGE_CANDIDATES:
                if t in chunk: outage.add(t)
    if not outage:  # fallback: 휴전 섹션 전체에서 후보 검색
        for t in OUTAGE_CANDIDATES:
            if t in outage_txt: outage.add(t)
    # 휴전 설비명(노트)
    fac = re.search(r'(\d+kV\s*[가-힣A-Za-z]+S/S\s*#?\d*\s*M\.?Tr)', outage_txt)
    note = fac.group(1) if fac else ""
    # (3) 휴전 설비 목록(M.Tr/BUS + T/L) + 경기북부 의무운전 대수표 + 발전소별 제약운전 → 검토서 변경점 자동비교
    facilities = _outage_facilities(txt)
    plants, minout = _mustrun_plants(txt)
    return {"limit":limit, "standing":standing, "outage":sorted(outage), "outage_note":note,
            "facilities":facilities,
            "mustrun_weekday":_mustrun_table(txt,"평일"),
            "mustrun_weekend":_mustrun_table(txt,"주말"),
            "mustrun_plants":plants, "mustrun_minout":minout}

# 발전소명 접미사(제약운전 표에서 발전기 토큰 판별)
_PLANT_SUF = ("열병합","복합","화력","파워","양수","원자력","TP","T/P","CC","GT","GPS","IGCC")

def _mustrun_plants(txt):
    """발전소별 제약운전 조건 추출:
       (1) '○ [발전기] 최소출력 이상 운전' + 사유 T/L,  (2) 'N대 이상 운전 [발전기…] 좌동' 표.
       반환: (제약운전 발전기명 set 정렬, [{name,reason(T/L)}] 최소출력 목록)."""
    plants=set(); minout=[]
    # (1) 최소출력 이상 운전 + 사유 설비(T/L)
    for m in re.finditer(r'○\s*([가-힣A-Za-z0-9#,\-\s]{2,20}?)\s*최소출력\s*이상\s*운전', txt):
        nm=re.sub(r'\s+','',m.group(1)).strip()
        if not nm: continue
        tail=txt[m.end():m.end()+140]
        rm=re.search(r'(\d{2,3}kV\s*[가-힣A-Za-z0-9#]+\s*T/L)', tail)
        minout.append({"name":nm, "reason": re.sub(r'\s+',' ',rm.group(1)).strip() if rm else ""})
        plants.add(nm)
    # (2) 'N대 이상 운전 … 좌동' 표: 좌동 앞 발전기 토큰
    for m in re.finditer(r'\d+\s*대\s*이상\s*운전\s+(.+?)\s*좌동', txt, re.S):
        for tok in re.split(r'[\n,]| {2,}', m.group(1)):
            tok=tok.split('(')[0].strip()      # '율촌#1CC(#1,2GT...' → '율촌#1CC'
            if len(tok)<2 or not re.search(r'[가-힣]', tok): continue
            if any(w in tok for w in ("운전","이상","수요","MW","시","대 ",":")): continue
            if tok.endswith(_PLANT_SUF) or re.search(r'#?\d?\s*CC', tok):
                plants.add(re.sub(r'\s+','',tok))
    return sorted(plants), minout

def _outage_facilities(txt):
    """휴전/장기정지 설비: M.Tr/BUS + (스케줄 날짜가 뒤따르는) T/L. 예: 765kV 신가평S/S #1 M.Tr, 154kV 강동천호#2 T/L."""
    facs=[]
    for mm in re.finditer(r'(\d{3})kV\s*([가-힣A-Za-z]+)\s*S/S\s*#?\s*(\d+)\s*(M\.?Tr|BUS)', txt):
        s = "%skV %sS/S #%s %s" % (mm.group(1), mm.group(2), mm.group(3), mm.group(4).replace('MTr','M.Tr'))
        if s not in facs: facs.append(s)
    # T/L 휴전: 설비 뒤에 '날짜(요일)' 스케줄이 오는 것만(고장대비 SPS 언급 제외)
    for mm in re.finditer(r'(\d{2,3})kV\s*([가-힣A-Za-z0-9]+#?\d*)\s*T/L\s+\d{2}/\d{2}\([일월화수목금토]\)', txt):
        s = "%skV %s T/L" % (mm.group(1), mm.group(2))
        if s not in facs: facs.append(s)
    return facs

def _mustrun_table(txt, key):
    """경기북부 발전기 '평일'/'주말' 제약 대수표 → [[from_hr,to_hr,n], ...]"""
    m = re.search(r'경기북부\s*발전기\s*'+key+r'\s*제약(.*?)(?:경기북부\s*발전기|대수\s*산정|○ 대수|$)', txt, re.S)
    if not m: return []
    out=[]
    for mm in re.finditer(r'(\d{1,2})\s*시\s*~\s*(\d{1,2})\s*시\s*(\d+)\s*대', m.group(1)):
        out.append([int(mm.group(1)), int(mm.group(2)), int(mm.group(3))])
    return out

# ───────────────────── XLSX 파서 ─────────────────────
def ws_rows(fn):
    return list(openpyxl.load_workbook(fn, data_only=True).active.iter_rows(values_only=True))

def parse_daily(fn):
    out=[]
    for r in ws_rows(fn)[2:]:
        d=r[0]
        if not hasattr(d,'year'): continue
        smp=r[9]; dem=r[3]
        if smp is None: continue
        out.append({"d":f"{d.year:04d}-{d.month:02d}-{d.day:02d}",
                    "smp":round(float(smp),2),
                    "dem":round(float(dem)/1000,3) if dem else None})
    out.sort(key=lambda x:x["d"])
    return out

def parse_hourly_load(fn):
    d={}
    for r in ws_rows(fn)[1:]:
        h=hr_of(r[0])
        if h: d[h]=round(float(r[1])/1000,3)
    return d

def parse_hourly_smp(fn):
    d={}
    for r in ws_rows(fn)[1:]:
        h=hr_of(r[0])
        if h: d[h]=round(float(r[1]),2)
    return d

def parse_smp_avg(fn):
    # 일간 계통한계가격 파일의 '평균' 행 = KPX 공식 일평균 SMP(수요가중). 비어있으면 None.
    for r in ws_rows(fn)[1:]:
        if str(r[0]).strip()=="평균":
            try: return round(float(r[1]),2)
            except (TypeError, ValueError): return None
    return None

def parse_marg(fn):
    hours=[]; mx=None; mn=None
    for r in ws_rows(fn)[1:]:
        t=str(r[0]).strip(); g=str(r[3]).strip() if r[3] else ""
        smp=round(float(r[1]),2) if r[1] is not None else None
        if hr_of(t): hours.append({"hr":hr_of(t),"smp":smp,"gname":g})
        elif t=="최대": mx={"smp":smp,"gname":g}
        elif t=="최소": mn={"smp":smp,"gname":g}
    hours.sort(key=lambda x:x["hr"])
    return {"hours":hours,"max":mx,"min":mn}

# ───────────────────── S3 소스 (하이브리드) ─────────────────────
# 팀 공용 S3(kpx-epowermarket-data)의 CSV로 daily/hourly/marg를 자동 채운다.
# 제약검토서(HWP)·공급능력표(txt)는 이 목록에 없으므로 로컬 파일로 계속 보완한다.
S3_BUCKET = "kpx-epowermarket-data"
S3_REGION = "ap-northeast-2"

def _iso_from_dealdate(v):
    """'20260701' / 20260701 / '2026-07-01' → '2026-07-01'."""
    s = str(v).strip().replace("-", "")
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None

def _s3_client():
    """path-style + 넉넉한 타임아웃 + 사내 프록시 대비 SSL 검증 폴백."""
    import boto3
    from botocore.config import Config
    cfg = Config(connect_timeout=20, read_timeout=120,
                 retries={"max_attempts": 4}, s3={"addressing_style": "path"})
    try:
        return boto3.client("s3", region_name=S3_REGION, config=cfg)
    except Exception:
        # 인증서 검증이 프록시에서 막히면 미검증 컨텍스트로 재시도
        return boto3.client("s3", region_name=S3_REGION, config=cfg, verify=False)

def _read_csv_source(fname, s3cache, s3):
    """s3cache 폴더가 있으면 로컬 CSV, 없으면 S3에서 직접 읽어 DataFrame 반환."""
    import pandas as pd
    if s3cache:
        path = os.path.join(s3cache, fname)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        return pd.read_csv(path)
    import io
    last = None
    for _ in range(4):
        try:
            body = s3.get_object(Bucket=S3_BUCKET, Key="data/" + fname)["Body"].read()
            return pd.read_csv(io.BytesIO(body))
        except Exception as e:
            last = e
    raise last

def _detect(cols, cands, contains=True):
    """컬럼명 후보 목록에서 첫 매칭 반환(정확일치 우선, 없으면 부분일치)."""
    low = {c.lower(): c for c in cols}
    for c in cands:
        if c.lower() in low: return low[c.lower()]
    if contains:
        for col in cols:
            cl = col.lower()
            if any(c.lower() in cl for c in cands): return col
    return None

def load_from_s3(data, loadmap, smpmap, officialavg, s3cache=None, date_filter=None, verbose=True):
    """S3/로컬CSV로 daily/hourly/marg를 '빈 곳만' 채운다(로컬 업로드 파일이 우선).
       반환: 처리 요약 문자열 리스트."""
    import pandas as pd
    log = []
    s3 = None if s3cache else _s3_client()
    keep = (lambda dt: (date_filter is None) or (dt in date_filter))

    # (1) smp_cache.csv → 시간별 SMP + 공식 일평균(calc_avg_val)
    try:
        df = _read_csv_source("smp_cache.csv", s3cache, s3)
        if "area_div" in df.columns:
            df = df[df["area_div"] == "MAINLAND"]
        n = 0
        for _, r in df.iterrows():
            dt = _iso_from_dealdate(r.get("deal_date"))
            if not dt or not keep(dt): continue
            d = smpmap.setdefault(dt, {})
            for h in range(1, 25):
                v = r.get("hh%02d_val" % h)
                if pd.notna(v) and h not in d: d[h] = round(float(v), 2)
            av = r.get("calc_avg_val")
            if pd.notna(av): officialavg.setdefault(dt, round(float(av), 2))
            n += 1
        log.append(f"S3 smp_cache: {n}일 시간별 SMP")
    except Exception as e:
        log.append(f"S3 smp_cache 실패: {type(e).__name__}: {e}")

    # (2) demand_cache.csv → 시간별 수요(MW→GW)
    try:
        df = _read_csv_source("demand_cache.csv", s3cache, s3)
        if "area_div" in df.columns:
            df = df[df["area_div"] == "MAINLAND"]
        n = 0
        for _, r in df.iterrows():
            dt = _iso_from_dealdate(r.get("deal_date"))
            if not dt or not keep(dt): continue
            d = loadmap.setdefault(dt, {})
            for h in range(1, 25):
                v = r.get("hh%02d_val" % h)
                if pd.notna(v) and h not in d: d[h] = round(float(v) / 1000, 3)
            n += 1
        log.append(f"S3 demand_cache: {n}일 시간별 수요")
    except Exception as e:
        log.append(f"S3 demand_cache 실패: {type(e).__name__}: {e}")

    # (3) marginal_gen_cache.csv → 한계발전기(컬럼 자동탐지). 로컬 marg가 없는 날만 채움.
    try:
        df = _read_csv_source("marginal_gen_cache.csv", s3cache, s3)
        if "area_div" in df.columns:
            df = df[df["area_div"] == "MAINLAND"]
        cols = list(df.columns)
        c_date = _detect(cols, ["deal_date", "date"])
        c_hour = _detect(cols, ["hour", "hh", "time", "tm", "시간"])
        # 발전기 '이름' 컬럼만 인정(코드 컬럼 gener_cd/eng_cd 제외). 이름이 없으면 marg는 로컬 xlsx 사용.
        name_cols = [c for c in cols if any(k in str(c).lower() for k in ["name", "_nm", "명"])
                     and not str(c).lower().endswith(("_cd", "cd", "code"))]
        c_gen = name_cols[0] if name_cols else None
        c_smp  = _detect(cols, ["smp_prc", "smp", "price", "가격"])
        if not (c_date and c_gen and c_smp):
            log.append(f"S3 marginal_gen: 발전기명 컬럼 없음(코드만: {cols}) → 매핑 필요, marg는 로컬 xlsx 사용")
        elif c_hour and df[c_hour].notna().any():
            byd = {}
            for _, r in df.iterrows():
                dt = _iso_from_dealdate(r.get(c_date))
                if not dt or not keep(dt) or dt in data["marg"]: continue
                try: h = int(re.sub(r"\D", "", str(r.get(c_hour))) or 0)
                except ValueError: continue
                if not (1 <= h <= 24): continue
                sv = r.get(c_smp)
                byd.setdefault(dt, []).append(
                    {"hr": h, "smp": round(float(sv), 2) if pd.notna(sv) else None,
                     "gname": str(r.get(c_gen)).strip()})
            for dt, hrs in byd.items():
                hrs.sort(key=lambda x: x["hr"])
                valid = [x for x in hrs if x["smp"] is not None]
                mx = max(valid, key=lambda x: x["smp"]) if valid else None
                mn = min(valid, key=lambda x: x["smp"]) if valid else None
                data["marg"][dt] = {"date": dt, "hours": hrs,
                    "max": {"smp": mx["smp"], "gname": mx["gname"]} if mx else None,
                    "min": {"smp": mn["smp"], "gname": mn["gname"]} if mn else None}
            log.append(f"S3 marginal_gen: {len(byd)}일(신규) 한계발전기")
        else:
            log.append(f"S3 marginal_gen: 시간 컬럼 미탐지(cols={cols}) → 로컬 xlsx 사용")
    except Exception as e:
        log.append(f"S3 marginal_gen 실패: {type(e).__name__}: {e}")

    if verbose:
        for l in log: print("  ", l)
    return log

# ───────────────────── 메인 ─────────────────────
def main():
    here=os.path.dirname(os.path.abspath(__file__))
    args=sys.argv[1:]
    date_filter=None
    if "--dates" in args:
        k=args.index("--dates"); date_filter=set(args[k+1].split(",")); args=args[:k]+args[k+2:]
    use_s3=False
    if "--source" in args:
        k=args.index("--source"); use_s3=(args[k+1].lower()=="s3"); args=args[:k]+args[k+2:]
    s3cache=None
    if "--s3-cache" in args:
        k=args.index("--s3-cache"); s3cache=args[k+1]; use_s3=True; args=args[:k]+args[k+2:]
    dirs=args or [here]
    files=[]
    for d in dirs:
        files += glob.glob(os.path.join(d,"*.xlsx")) + glob.glob(os.path.join(d,"*.hwp")) + glob.glob(os.path.join(d,"*.txt"))
    data={"daily":[], "marg":{}, "hourly":{}, "constraint":{}, "supply":{},
          "mustrun_standing":list(STANDING_TOKENS), "mustrun_outage":[]}
    loadmap={}; smpmap={}; officialavg={}
    for f in files:
        base=os.path.basename(f); dt=iso_from_name(base)
        try:
            if "가격결정발전기" in base and dt:
                m=parse_marg(f); m["date"]=dt; data["marg"][dt]=m
            elif ("일간" in base and "계통한계가격" in base) and dt:
                smpmap[dt]=parse_hourly_smp(f)
                av=parse_smp_avg(f)
                if av is not None: officialavg[dt]=av   # 블랭크 평균행은 S3 공식값을 덮지 않도록

            elif "금일수요예측" in base and dt:
                loadmap[dt]=parse_hourly_load(f)
            elif "일별" in base and "수요" in base:
                data["daily"]=parse_daily(f)
            elif "제약검토서" in base and dt:
                data["constraint"][dt]=parse_constraint(f)
            elif "공급능력" in base and dt:
                data["supply"][dt]=parse_supply(f)
            else:
                continue
            print("OK ", base, dt or "")
        except Exception as e:
            print("ERR", base, "->", e)
    # ★ S3 하이브리드: 로컬 업로드분(위)을 우선하고, 비어있는 날짜만 S3 CSV로 채움
    if use_s3:
        print("S3 소스 로드" + (f" (로컬캐시 {s3cache})" if s3cache else " (직접)") + ":")
        try:
            load_from_s3(data, loadmap, smpmap, officialavg, s3cache=s3cache, date_filter=date_filter)
        except Exception as e:
            print("  S3 로드 실패:", type(e).__name__, e)
    # hourly 병합(load+smp)
    for dt in sorted(set(loadmap)|set(smpmap)):
        L=loadmap.get(dt,{}); S=smpmap.get(dt,{})
        hrs=sorted(set(L)|set(S))
        data["hourly"][dt]=[{"hr":h,"load":L.get(h),"smp":S.get(h)} for h in hrs]
    # 날짜 필터
    if date_filter:
        data["marg"]={k:v for k,v in data["marg"].items() if k in date_filter}
        data["hourly"]={k:v for k,v in data["hourly"].items() if k in date_filter}
        data["constraint"]={k:v for k,v in data["constraint"].items() if k in date_filter}
        data["supply"]={k:v for k,v in data["supply"].items() if k in date_filter}
        data["daily"]=[x for x in data["daily"] if x["d"] in date_filter]
    # ★ 일평균 SMP 산정 우선순위: ① 일간SMP 파일 '평균'행(KPX 공식, 수요가중) → ② 수요(부하)가중평균 → ③ 단순평균
    hmap={x["d"]:x for x in data["daily"]}
    for dt,H in data["hourly"].items():
        pairs=[(h["smp"],h.get("load")) for h in H if h.get("smp") is not None]
        if not pairs: continue
        smps=[s for s,_ in pairs]
        wpairs=[(s,l) for s,l in pairs if l is not None]
        if officialavg.get(dt) is not None:
            avg_smp=officialavg[dt]                                  # ① 공식 평균행
        elif wpairs and sum(l for _,l in wpairs)>0:
            avg_smp=round(sum(s*l for s,l in wpairs)/sum(l for _,l in wpairs),2)  # ② 수요가중
        else:
            avg_smp=round(sum(smps)/len(smps),2)                     # ③ 단순평균
        loads=[l for _,l in wpairs]
        if dt in hmap:
            hmap[dt]["smp"]=avg_smp
            if hmap[dt].get("dem") is None and loads:
                hmap[dt]["dem"]=round(sum(loads)/len(loads),3)
        else:
            data["daily"].append({"d":dt,"smp":avg_smp,
                                  "dem":round(sum(loads)/len(loads),3) if loads else None})
    data["daily"].sort(key=lambda x:x["d"])
    # mustrun_outage = 제약검토서들에서 추출한 합집합 / standing 갱신
    out=set(); std=set(STANDING_TOKENS)
    for c in data["constraint"].values():
        out|=set(c.get("outage",[])); std|=set(c.get("standing",[]))
    data["mustrun_outage"]=sorted(out)
    data["mustrun_standing"]=sorted(std)
    outpath=os.path.join(here,"smp_data.json")
    with open(outpath,"w",encoding="utf-8") as fp:
        json.dump(data,fp,ensure_ascii=False,separators=(",",":"))
    embed_into_html(data, here)
    print(f"\n→ {outpath}")
    print(f"  daily {len(data['daily'])}일 / marg {list(data['marg'])} / hourly {list(data['hourly'])} / constraint {list(data['constraint'])} / supply {list(data['supply'])}")
    print(f"  mustrun_standing {data['mustrun_standing']}")
    print(f"  mustrun_outage   {data['mustrun_outage']}")

def embed_into_html(data, here):
    """smp.html의 EMBEDDED_DATA 줄을 전체 데이터로 교체(파일만 열어도 동작) + _site 복사."""
    blob = "const EMBEDDED_DATA=" + json.dumps(data, ensure_ascii=False, separators=(",",":")) + "; //__EMBEDDED_DATA__"
    htmlpath = os.path.join(here, "smp.html")
    try:
        html = open(htmlpath, encoding="utf-8").read()
        html2 = re.sub(r'(?:var|const)\s+EMBEDDED_DATA=.*?//__EMBEDDED_DATA__', lambda m: blob, html, count=1)
        if html2 == html:
            print("embed WARN: 마커(//__EMBEDDED_DATA__)를 못 찾음")
            return
        open(htmlpath, "w", encoding="utf-8").write(html2)
        site = os.path.join(here, "_site")
        if os.path.isdir(site):
            open(os.path.join(site, "smp.html"), "w", encoding="utf-8").write(html2)
            with open(os.path.join(site, "smp_data.json"), "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, separators=(",",":"))
        print("embedded into smp.html (+_site)")
    except Exception as e:
        print("embed ERR", e)

if __name__=="__main__":
    main()
