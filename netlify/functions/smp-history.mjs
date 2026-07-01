// 축적된 육지 SMP 히스토리 제공 (smp-collect 가 저장한 Blobs 읽기)
// GET /.netlify/functions/smp-history  →  { 'YYYYMMDD': {date,smp,min,max,hours}, ... }

import { getStore } from "@netlify/blobs";

export default async () => {
  try {
    const store = getStore("smp-history");
    const hist = (await store.get("inland", { type: "json" })) || {};
    return new Response(JSON.stringify(hist), {
      status: 200,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=300",
      },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e?.message || e) }), {
      status: 500,
      headers: { "Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*" },
    });
  }
};
