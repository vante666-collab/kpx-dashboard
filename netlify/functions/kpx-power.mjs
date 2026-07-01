// 전력거래소(KPX) 공공데이터 프록시
// 브라우저 → /.netlify/functions/kpx-power?date=YYYYMMDD&op=...&numOfRows=...
// 서비스키를 서버에서만 붙여 호출(키 노출 방지) + CORS 우회.
//
// 환경변수 (Netlify Dashboard → Site settings → Environment variables):
//   KPX_SERVICE_KEY  = data.go.kr 에서 발급받은 디코딩 키(Decoding) 권장
//   KPX_BASE         = (옵션) 기본 https://apis.data.go.kr/B552115/PowerMarketGenInfo
//   KPX_OP           = (옵션) 기본 getPowerMarketGenInfo  ← 사용하려는 데이터셋의 오퍼레이션명으로 교체
//
// 데이터셋별 오퍼레이션 예:
//   - 전력시장 발전설비 정보 : B552115/PowerMarketGenInfo / getPowerMarketGenInfo
//   - 회원사별 전력거래실적   : 해당 서비스의 베이스/오퍼레이션으로 KPX_BASE·KPX_OP 교체
//   - 발전원별 발전량(계통)   : 해당 서비스의 베이스/오퍼레이션으로 교체

const DEFAULT_BASE = "https://apis.data.go.kr/B552115/PowerMarketGenInfo";
const DEFAULT_OP = "getPowerMarketGenInfo";

export default async (req) => {
  const key = Netlify.env.get("KPX_SERVICE_KEY");
  if (!key) {
    return json({ error: "KPX_SERVICE_KEY 미설정. Netlify 환경변수에 서비스키를 등록하세요." }, 500);
  }

  const url = new URL(req.url);
  const p = url.searchParams;

  const base = Netlify.env.get("KPX_BASE") || DEFAULT_BASE;
  const op = p.get("op") || Netlify.env.get("KPX_OP") || DEFAULT_OP;

  // data.go.kr 호출 URL 구성
  const target = new URL(`${base.replace(/\/$/, "")}/${op}`);
  target.searchParams.set("serviceKey", key);
  target.searchParams.set("dataType", "JSON");
  target.searchParams.set("returnType", "JSON");
  target.searchParams.set("pageNo", p.get("pageNo") || "1");
  target.searchParams.set("numOfRows", p.get("numOfRows") || "500");

  // 클라이언트가 넘긴 나머지 파라미터(date/baseDate/tradeDate/genNm 등) 전달
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
