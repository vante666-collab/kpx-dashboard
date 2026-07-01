// 육지 SMP 일별 수집기 (collect-forward)
// - 스케줄: 매일 KST 01:30 (= 16:30 UTC) 에 그날의 육지 SMP를 KPX OpenAPI에서 받아 저장
// - 수동: 브라우저/curl 로 /.netlify/functions/smp-collect 호출 시 즉시 1회 수집(시드)
// - 저장: Netlify Blobs (store "smp-history", key "inland") 에 { 'YYYYMMDD': {date,smp,min,max,hours} }
//
// 환경변수: KPX_SERVICE_KEY = data.go.kr 에서 발급받은 인증키(Decoding 키 권장)
//
// 주의: KPX getSmp1hToday 는 "오늘치"만 제공 → 과거 소급 불가. 매일 돌며 축적합니다.

import { getStore } from "@netlify/blobs";

const ENDPOINT = "https://openapi.kpx.or.kr/openapi/smp1hToday/getSmp1hToday";

// 의존성 없는 간단 XML 파서 (<item>…</item> 반복 구조)
function parseItems(xml) {
  const items = [];
  const re = /<item>([\s\S]*?)<\/item>/g;
  let m;
  while ((m = re.exec(xml))) {
    const seg = m[1];
    const get = (t) => {
      const r = new RegExp(`<${t}>([\\s\\S]*?)<\\/${t}>`).exec(seg);
      return r ? r[1].trim() : "";
    };
    items.push({
      tradeDay: get("tradeDay"),
      tradHour: get("tradHour"),
      areaCd: get("areaCd"),
      smp: Number(get("smp")),
    });
  }
  return items;
}

async function collect() {
  const key = Netlify.env.get("KPX_SERVICE_KEY");
  if (!key) throw new Error("KPX_SERVICE_KEY 미설정");

  const u = new URL(ENDPOINT);
  u.searchParams.set("ServiceKey", key);
  u.searchParams.set("areaCd", "1"); // 1=육지, 9=제주

  const r = await fetch(u.toString(), { headers: { Accept: "application/xml" } });
  const xml = await r.text();
  if (!r.ok) throw new Error(`KPX ${r.status}: ${xml.slice(0, 200)}`);

  const code = (/<resultCode>([\s\S]*?)<\/resultCode>/.exec(xml) || [])[1];
  if (code && code !== "00") {
    const msg = (/<resultMsg>([\s\S]*?)<\/resultMsg>/.exec(xml) || [])[1] || "";
    throw new Error(`KPX resultCode ${code} ${msg}`);
  }

  const items = parseItems(xml).filter((i) => i.smp > 0);
  if (!items.length) throw new Error(`SMP 항목 없음: ${xml.slice(0, 200)}`);

  const day = items[0].tradeDay; // YYYYMMDD
  const smps = items.map((i) => i.smp);
  const avg = smps.reduce((a, b) => a + b, 0) / smps.length;
  const rec = {
    date: day,
    smp: Number(avg.toFixed(2)), // 일 평균
    min: Math.min(...smps),
    max: Math.max(...smps),
    hours: smps.length,
  };

  const store = getStore("smp-history");
  const hist = (await store.get("inland", { type: "json" })) || {};
  hist[day] = rec;
  await store.setJSON("inland", hist);

  return { rec, total: Object.keys(hist).length };
}

export default async () => {
  try {
    const out = await collect();
    return new Response(JSON.stringify({ ok: true, ...out }), {
      status: 200,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch (e) {
    console.error(e);
    return new Response(JSON.stringify({ ok: false, error: String(e?.message || e) }), {
      status: 500,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  }
};

// 매일 KST 01:30 (UTC 16:30) — 그날 육지 SMP는 하루전시장에서 이미 확정됨
export const config = { schedule: "30 16 * * *" };
