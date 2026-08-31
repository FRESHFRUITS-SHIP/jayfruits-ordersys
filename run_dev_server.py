"""
Merged runner — real dashboard + fake WhatsApp chat UI, ONE process.

Why this exists: previously the dashboard (app.main:app) and the fake chat
UI (fake_whatsapp_ui.py) ran as two separate processes, so a status change
in the dashboard tried to send a REAL WhatsApp message (and 401'd, since
you disconnected the number) instead of showing up in the fake chat room.

This script patches app.services.whatsapp's send functions BEFORE anything
else in your app gets imported, then imports your real `app` (dashboard +
webhook routes, unchanged) and adds the fake chat UI on top of it at /chat.
Because everything shares one process now, ANY code path that sends a
WhatsApp message — a customer message, a dashboard status change, a manual
notification — gets intercepted and shown in the chat room, in near
real time (the page polls for new messages).

Place this file in your project root (jayfruits-ordersys/), next to app/.

Usage:
    cd jayfruits-ordersys
    python run_dev_server.py
    -> Dashboard:      http://127.0.0.1:8000/orders   (same as before)
    -> Fake WhatsApp:  http://127.0.0.1:8000/chat
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

FAKE_NUMBER = "911234500000"  # keep this the same as before so existing test orders/customer stay linked

outbox: list[dict] = []  # never cleared — index-based polling picks up new entries


async def mock_send_text(to, body):
    outbox.append({"type": "text", "to": to, "body": body})


async def mock_send_buttons(to, body, buttons):
    outbox.append({
        "type": "buttons", "to": to, "body": body,
        "buttons": [{"id": bid, "title": title} for bid, title in buttons],
    })


async def mock_send_image(to, image_url, caption=None):
    outbox.append({"type": "image", "to": to, "url": image_url, "caption": caption})


async def mock_send_list_menu(to, body_text, button_text, sections, footer=None):
    outbox.append({
        "type": "list", "to": to, "body": body_text,
        "button_text": button_text, "sections": sections, "footer": footer,
    })


# ---- CRITICAL: patch app.services.whatsapp's functions BEFORE importing
# anything else from the app. Every other module does
# `from app.services.whatsapp import send_text` (etc) — Python resolves
# that name lookup against whatsapp.py's current module dict at import
# time, so as long as we patch here first, every downstream module
# (conversation/*, notifications.py, orders.py, dashboard.py) picks up
# the mocked versions automatically, with zero changes to those files. ----
import app.services.whatsapp as _wa
_wa.send_text = mock_send_text
_wa.send_buttons = mock_send_buttons
_wa.send_image = mock_send_image
_wa.send_list_menu = mock_send_list_menu

# Now import your real app — dashboard, webhook routes, everything —
# unchanged. Its internal imports of send_text/etc will now resolve to
# the mocks above.
from app.main import app  # noqa: E402
from app.conversation.router import handle_text_message, handle_button_reply  # noqa: E402


class TextIn(BaseModel):
    text: str


class ButtonIn(BaseModel):
    id: str


fake_chat_router = APIRouter()


@fake_chat_router.post("/api/fake-chat/send")
async def api_send(payload: TextIn):
    try:
        await handle_text_message(FAKE_NUMBER, payload.text)
    except Exception as e:
        outbox.append({"type": "error", "body": f"⚠️ Exception: {e}"})
    return {"ok": True, "since": len(outbox)}


@fake_chat_router.post("/api/fake-chat/button")
async def api_button(payload: ButtonIn):
    try:
        await handle_button_reply(FAKE_NUMBER, payload.id)
    except Exception as e:
        outbox.append({"type": "error", "body": f"⚠️ Exception: {e}"})
    return {"ok": True, "since": len(outbox)}


@fake_chat_router.get("/api/fake-chat/poll")
async def api_poll(since: int = 0):
    return JSONResponse({"items": outbox[since:], "since": len(outbox)})


@fake_chat_router.get("/chat", response_class=HTMLResponse)
async def chat_page():
    return HTML_PAGE


HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Jay Fruits — Fake WhatsApp Test UI</title>
<style>
  body { margin:0; font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#e5ddd5; }
  #header { background:#075e54; color:white; padding:14px 18px; font-size:16px; font-weight:600; display:flex; justify-content:space-between; align-items:center; }
  #header a { color:#cfe; font-size:12px; text-decoration:underline; }
  #chat { max-width:480px; margin:0 auto; height:calc(100vh - 130px); overflow-y:auto; padding:14px; }
  .bubble { background:white; border-radius:8px; padding:10px 12px; margin:8px 0; max-width:85%; box-shadow:0 1px 1px rgba(0,0,0,0.1); white-space:pre-wrap; font-size:14px; line-height:1.4; }
  .bubble.me { background:#dcf8c6; margin-left:auto; }
  .bubble.system { background:#fff3cd; margin:8px auto; text-align:center; font-size:12px; max-width:90%; }
  .buttons { display:flex; flex-direction:column; gap:6px; margin-top:8px; }
  .buttons button, .list-btn { background:white; border:1px solid #128c7e; color:#128c7e; border-radius:6px; padding:8px; cursor:pointer; font-size:13px; }
  .buttons button:hover, .list-btn:hover { background:#128c7e; color:white; }
  .list-row { display:block; width:100%; text-align:left; margin-top:4px; }
  img.msgimg { max-width:100%; border-radius:6px; margin-top:6px; }
  .error { color:#c0392b; font-weight:600; }
  #inputbar { max-width:480px; margin:0 auto; display:flex; padding:10px; background:#f0f0f0; }
  #inputbar input { flex:1; padding:10px; border-radius:20px; border:1px solid #ccc; outline:none; }
  #inputbar button { margin-left:8px; padding:10px 16px; border-radius:20px; border:none; background:#075e54; color:white; cursor:pointer; }
</style>
</head>
<body>
<div id="header">
  <span>🍉 Jay Fruits — Fake WhatsApp (dashboard notifications show up here too)</span>
  <a href="/orders" target="_blank">Open dashboard →</a>
</div>
<div id="chat"></div>
<div id="inputbar">
  <input id="msgInput" placeholder="Type a message..." autofocus>
  <button onclick="sendText()">Send</button>
</div>

<script>
const chat = document.getElementById('chat');
let lastSeen = 0;

function scrollDown() { chat.scrollTop = chat.scrollHeight; }

function addBubble(html, cls) {
  const div = document.createElement('div');
  div.className = 'bubble' + (cls ? ' ' + cls : '');
  div.innerHTML = html;
  chat.appendChild(div);
  scrollDown();
}

function renderItems(items) {
  for (const item of items) {
    if (item.type === 'text') {
      addBubble(escapeHtml(item.body));
    } else if (item.type === 'buttons') {
      let html = escapeHtml(item.body) + '<div class="buttons">';
      for (const b of item.buttons) {
        html += `<button onclick="tapButton('${escapeAttr(b.id)}')">${escapeHtml(b.title)}</button>`;
      }
      html += '</div>';
      addBubble(html);
    } else if (item.type === 'list') {
      let html = escapeHtml(item.body) + '<div class="buttons">';
      html += `<div style="font-weight:600;margin-top:6px;">[ ${escapeHtml(item.button_text)} ]</div>`;
      for (const section of (item.sections || [])) {
        html += `<div style="font-weight:600;margin-top:6px;font-size:12px;color:#666;">${escapeHtml(section.title||'')}</div>`;
        for (const row of (section.rows || [])) {
          html += `<button class="list-row" onclick="tapButton('${escapeAttr(row.id)}')">${escapeHtml(row.title)}${row.description ? ' — ' + escapeHtml(row.description) : ''}</button>`;
        }
      }
      if (item.footer) html += `<div style="font-size:11px;color:#888;margin-top:6px;">${escapeHtml(item.footer)}</div>`;
      html += '</div>';
      addBubble(html);
    } else if (item.type === 'image') {
      addBubble(`<img class="msgimg" src="${item.url}">` + (item.caption ? '<br>' + escapeHtml(item.caption) : ''));
    } else if (item.type === 'error') {
      addBubble(`<span class="error">${escapeHtml(item.body)}</span>`);
    }
  }
}

function escapeHtml(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function escapeAttr(s) {
  return (s || '').replace(/'/g, "\\'");
}

async function sendText() {
  const input = document.getElementById('msgInput');
  const text = input.value.trim();
  if (!text) return;
  addBubble(escapeHtml(text), 'me');
  input.value = '';
  await fetch('/api/fake-chat/send', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({text})
  });
}

async function tapButton(id) {
  addBubble('<i>(tapped: ' + escapeHtml(id) + ')</i>', 'me');
  await fetch('/api/fake-chat/button', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({id})
  });
}

async function pollLoop() {
  try {
    const res = await fetch('/api/fake-chat/poll?since=' + lastSeen);
    const data = await res.json();
    if (data.items && data.items.length) {
      renderItems(data.items);
    }
    lastSeen = data.since;
  } catch (e) { /* ignore transient poll errors */ }
  setTimeout(pollLoop, 1200);
}

document.getElementById('msgInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendText();
});

addBubble('System ready. Messages sent here, or triggered by dashboard status changes, will appear below.', 'system');
pollLoop();
</script>
</body>
</html>
"""

app.include_router(fake_chat_router)

if __name__ == "__main__":
    print("Dashboard:      http://127.0.0.1:8000/orders")
    print("Fake WhatsApp:  http://127.0.0.1:8000/chat")
    uvicorn.run(app, host="127.0.0.1", port=8000)