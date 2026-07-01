"""
SK이노베이션 E&S 임원 대시보드 KPI 요약을 Telegram으로 발송.

사용법:
  # 1) chat_id 확인 (봇에게 /start 보낸 뒤 실행)
  python send_kpi_telegram.py --get-chat-id

  # 2) KPI 요약 발송
  python send_kpi_telegram.py

환경변수:
  TELEGRAM_BOT_TOKEN  BotFather가 발급한 토큰 (필수)
  TELEGRAM_CHAT_ID    수신할 채팅 ID (--get-chat-id 로 확인)
"""
import os
import sys
import json
import ssl
import urllib.request
import urllib.parse
from datetime import datetime

SUPABASE_URL = "https://ygpjkepepqnqzsxqblzb.supabase.co"
SUPABASE_KEY = "sb_publishable_9Zw_bcVZAI11gC49UMqWkg_Adz5MH1H"
DASHBOARD_URL = "https://sk-es-dashboard-1780105054.netlify.app"

# 사내망 TLS 인증서 폐기 검증 우회용 (CRYPT_E_NO_REVOCATION_CHECK 대응).
# 필요 없으면 SSL_VERIFY=1 환경변수로 활성화.
_VERIFY = os.environ.get("SSL_VERIFY", "0") == "1"
_CTX = ssl.create_default_context()
if not _VERIFY:
    _CTX.check_hostname = False
    _CTX.verify_mode = ssl.CERT_NONE


def _http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, context=_CTX, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_post(url, data):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, context=_CTX, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_kpi():
    url = f"{SUPABASE_URL}/rest/v1/kpi_cards?select=*&order=id"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    return _http_get(url, headers)


def format_message(rows):
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"📊 *SK이노베이션 E&S 임원 대시보드*", f"_{today} 기준_", ""]
    for r in rows:
        arrow = "▲" if r.get("trend") == "up" else "▼"
        value = r.get("value")
        unit = r.get("unit") or ""
        try:
            value_str = f"{float(value):,.2f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            value_str = str(value)
        yoy = r.get("yoy_change") or ""
        metric = r.get("metric") or ""
        lines.append(f"• *{metric}*: {value_str} {unit}  {arrow} {yoy}")
    lines.append("")
    lines.append(f"🔗 [대시보드 열기]({DASHBOARD_URL})")
    return "\n".join(lines)


def get_chat_id(token):
    data = _http_get(f"https://api.telegram.org/bot{token}/getUpdates")
    if not data.get("ok"):
        print("getUpdates 실패:", data)
        sys.exit(1)
    seen = {}
    for u in data.get("result", []):
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None:
            continue
        title = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
        seen[cid] = f"{chat.get('type')} · {title}"
    if not seen:
        print("수신된 메시지가 없습니다. 봇에게 /start 또는 아무 메시지나 먼저 보내고 다시 실행하세요.")
        return
    print("발견된 chat_id 목록:")
    for cid, label in seen.items():
        print(f"  {cid}   ({label})")


def send_message(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = _http_post(url, {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": "false",
    })
    if not resp.get("ok"):
        print("발송 실패:", resp)
        sys.exit(2)
    print("발송 완료. message_id:", resp["result"]["message_id"])


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("환경변수 TELEGRAM_BOT_TOKEN 이 설정되어 있지 않습니다.")
        sys.exit(1)

    if "--get-chat-id" in sys.argv:
        get_chat_id(token)
        return

    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        print("환경변수 TELEGRAM_CHAT_ID 이 설정되어 있지 않습니다.")
        print("먼저 'python send_kpi_telegram.py --get-chat-id' 로 확인하세요.")
        sys.exit(1)

    rows = fetch_kpi()
    text = format_message(rows)
    send_message(token, chat_id, text)


if __name__ == "__main__":
    main()
