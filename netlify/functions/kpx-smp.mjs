// 전력거래소(KPX/EPSIS) 계통한계가격(SMP) 공공데이터 프록시
// 브라우저 → /.netlify/functions/kpx-smp?op=...&numOfRows=...&startDate=YYYYMMDD&endDate=YYYYMMDD
// 서비스키를 서버에서만 붙여 호출(키 노출 방지) + CORS 우회.
//
// 환경변수 (Netlify Dashboard → Site settings → Environment variables):
//   KPX_SERVICE_KEY  = data.go.kr 에서 발급받은 디코딩 키(Decoding) 권장  ← kpx-power 와 공용
//   SMP_BASE         = (옵션) SMP 데이터셋의 베이스 URL
//                      예: https://apis.data.go.kr/B552115/SmpInfoService
//   SMP_OP           = (옵션) 오퍼레이션명. 예: getSmpInfo
//
// 데이터셋마다 베이스/오퍼레이션/파라미터명이 다릅니다. 본인이 활용신청한
// "한국전력거래소_계통한계가격(SMP)" 류 서비스의 값으로 SMP_BASE·SMP_OP 를 맞추세요.
// 날짜 파라미터명(예: tradeDay, baseDate, startDate)도 클라이언트가 그대로 전달하므로
// smp.html 의 fetch 쿼리스트링만 데이터셋 규격에 맞추면 됩니다.

const DEFAULT_BASE = "https://apis.data.go.kr/B552115/SmpInfoService";
const DEFAULT_OP = "getSmpInfo";

export default async (req) => {
  const key = Netlify.env.get("KPX_SERVICE_KEY");
  if (!key) {
    return json({ error: "KPX_SERVICE_KEY 미설정. Netlify 환경변수에 서비스키를 등록하세요." }, 500);
  }

  const url = new URL(req.url);
  const p = url.searchParams;

  const base = Netlify.env.get("SMP_BASE") || DEFAULT_BASE;
  const op = p.get("op") || Netlify.env.get("SMP_OP") || DEFAULT_OP;

  // data.go.kr 호출 URL 구성
  const target = new URL(`${base.replace(/\/$/, "")}/${op}`);
  target.searchParams.set("serviceKey", key);
  target.searchParams.set("dataType", "JSON");
  target.searchParams.set("returnType", "JSON");
  target.searchParams.set("pageNo", p.get("pageNo") || "1");
  target.searchParams.set("numOfRows", p.get("numOfRows") || "999");

  // 클라이언트가 넘긴 나머지 파라미터(startDate/endDate/tradeDay 등) 전달
  for (const [k, v] of p.entries()) {
    if (["op", "pageNo", "numOfRows"].includes(k)) continue;
    if (v) target.searchParams.set(k, v);
  }

  try {
    const r = await fetch(target.toString(), { headers: { Accept: "application/json" } });
    const text = await r.text();
    if (!r.ok) return json({ error: `KPX ${r.status}`, body: text.slice(0, 500) }, 502);

    let data;
    try {
      data = JSON.parse(text);
    } catch {
      // data.go.kr 가 에러를 XML로 줄 때가 있어 그대로 전달
      return json({ error: "JSON 파싱 실패(서비스키/오퍼레이션 확인)", raw: text.slice(0, 800) }, 502);
    }
    return json(data, 200);
  } catch (e) {
    return json({ error: String(e?.message || e) }, 500);
  }
};

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "public, max-age=300",
    },
  });
}
