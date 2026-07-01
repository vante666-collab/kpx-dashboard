# SMP 자동수집 배포 런북 (collect-forward)

목표: 매일 cron이 육지 SMP를 받아 축적 → `smp.html?live=1` 이 실데이터를 표시.
**과거(예: 6/1) 소급은 불가**, 배포 시점부터 매일 쌓입니다.

구성요소
- `netlify/functions/smp-collect.mjs` — 매일 KST 01:30 수집(+수동 호출 시드). Netlify Blobs 저장.
- `netlify/functions/smp-history.mjs` — 축적분 JSON 제공.
- `smp.html` / `_site/smp.html` — `?live=1` 시 history 읽어 SMP 덮어씀.
- `package.json` — `@netlify/blobs` 의존성.

---

## 1) data.go.kr API 키 발급 (회원님 작업)

1. https://www.data.go.kr 회원가입/로그인
2. "한국전력거래소_계통한계가격조회" 검색 → 데이터셋
   (https://www.data.go.kr/data/15076302/openapi.do)
3. **[활용신청]** 클릭 → 즉시 승인됨
4. 마이페이지 → 오픈API → 인증키에서 **일반 인증키(Decoding)** 복사

> 개발계정 트래픽 한도 100건/일. 하루 1회 수집이라 충분.

## 2) Netlify 환경변수 설정

Site settings → Environment variables 에 추가:

```
KPX_SERVICE_KEY = <위에서 복사한 Decoding 키>
```

(CLI로도 가능: `netlify env:set KPX_SERVICE_KEY "<키>"`)

## 3) 배포

```powershell
netlify login            # 브라우저 인증 (최초 1회)
netlify deploy --prod    # 루트(netlify.toml) 기준 배포
```

배포 시 Netlify가 `package.json`의 `@netlify/blobs`를 자동 설치합니다.

## 4) 첫 데이터 즉시 시드 (cron 기다리지 않고)

```powershell
# 사이트 도메인으로 호출 (수동 1회 수집)
curl https://<your-site>.netlify.app/.netlify/functions/smp-collect
# → {"ok":true,"rec":{"date":"YYYYMMDD","smp":...},"total":1}
```

## 5) 확인

```powershell
curl https://<your-site>.netlify.app/.netlify/functions/smp-history
# → {"YYYYMMDD":{"date":...,"smp":...}}
```

브라우저에서 `https://<your-site>.netlify.app/smp.html?live=1`
→ 상단 배지 **실시간 SMP**, 수집된 날짜의 SMP가 실값으로 표시.

---

## 운영 메모

- cron 스케줄: `smp-collect.mjs` 의 `export const config = { schedule: "30 16 * * *" }` (UTC 16:30 = KST 01:30).
- 며칠 쌓이면 두 날짜 비교(전주대비 등)가 실데이터로 동작.
- 드라이버(연료가·신재생비중·원전가동률)는 무료 일별이 빈약 → 표에서 **수동 입력/보정** 유지.
  자동화하려면 수집기에 KPX 수급·연료원별 발전량 API를 추가(별도 활용신청)하면 됨.
- `smp.html` 수정 시 `_site/smp.html` 에도 복사 필요(배포는 `_site` 발행).
