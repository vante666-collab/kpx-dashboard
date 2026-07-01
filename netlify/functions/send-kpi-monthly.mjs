// Monthly KPI summary → Telegram
// Schedule: 매월 1~7일 중 월요일 09:00 KST (= 00:00 UTC) → "첫째 주 월요일"
// 환경변수 (Netlify Dashboard → Site settings → Environment variables):
//   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

const SUPABASE_URL = "https://ygpjkepepqnqzsxqblzb.supabase.co";
const SUPABASE_KEY = "sb_publishable_9Zw_bcVZAI11gC49UMqWkg_Adz5MH1H";
const DASHBOARD_URL = "https://sk-es-dashboard-1780105054.netlify.app";

async function fetchKpi() {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/kpi_cards?select=*&order=id`, {
    headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}` },
  });
  if (!r.ok) throw new Error(`Supabase ${r.status} ${await r.text()}`);
  return r.json();
}

const htmlEscape = (s) =>
  String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);

function formatMessage(rows) {
  const today = new Date().toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul" });
  const lines = [
    `📊 <b>SK이노베이션 E&amp;S 임원 대시보드</b>`,
    `<i>${htmlEscape(today)} 기준</i>`,
    "",
  ];
  for (const r of rows) {
    const arrow = r.trend === "up" ? "▲" : "▼";
    const value =
      typeof r.value === "number"
        ? r.value.toLocaleString("ko-KR", { maximumFractionDigits: 2 })
        : r.value;
    lines.push(
      `• <b>${htmlEscape(r.metric)}</b>: ${htmlEscape(value)} ${htmlEscape(r.unit || "")}  ${arrow} ${htmlEscape(r.yoy_change || "")}`,
    );
  }
  lines.push("");
  lines.push(`🔗 <a href="${DASHBOARD_URL}">대시보드 열기</a>`);
  return lines.join("\n");
}

async function sendTelegram(token, chatId, text) {
  const r = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      parse_mode: "HTML",
      disable_web_page_preview: false,
    }),
  });
  const data = await r.json();
  if (!data.ok) throw new Error(`Telegram ${JSON.stringify(data)}`);
  return data.result.message_id;
}

export default async () => {
  const token = Netlify.env.get("TELEGRAM_BOT_TOKEN");
  const chatId = Netlify.env.get("TELEGRAM_CHAT_ID");
  if (!token || !chatId) {
    return new Response("Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID", { status: 500 });
  }
  try {
    const rows = await fetchKpi();
    const text = formatMessage(rows);
    const messageId = await sendTelegram(token, chatId, text);
    return new Response(`OK message_id=${messageId}`, { status: 200 });
  } catch (e) {
    console.error(e);
    return new Response(`ERROR: ${e.message}`, { status: 500 });
  }
};

export const config = {
  schedule: "0 0 1-7 * 1",
};
