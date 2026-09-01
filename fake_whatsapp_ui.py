"""
Fake WhatsApp chat-room UI — connected to your REAL bot code.

Runs a local web page that looks like WhatsApp (message bubbles, quick-reply
buttons, list menus) but never touches Meta's API. It intercepts your real
app.conversation.* handlers' calls to send_text/send_buttons/send_image/
send_list_menu and renders them in the browser instead of sending them
over WhatsApp. Clicking a button in the browser calls handle_button_reply()
exactly like a real button tap would.

Place this file in your project root (jayfruits-ordersys/), next to app/,
then run it and open the printed URL in your browser.

Usage:
    cd jayfruits-ordersys
    pip install fastapi uvicorn --break-system-packages   (if not already installed)
    python fake_whatsapp_ui.py
    -> open http://127.0.0.1:8500 in your browser
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

# ---- a fixed fake customer number, so conversation state (pending_item,
# pending_order, saved name/address) persists across messages in this session,
# exactly like a real customer's WhatsApp number would ----
FAKE_NUMBER = "911234500000"

outbox: list[dict] = []


async def mock_send_text(to, body):
    outbox.append({"type": "text", "body": body})


async def mock_send_buttons(to, body, buttons):
    outbox.append({
        "type": "buttons",
        "body": body,
        "buttons": [{"id": bid, "title": title} for bid, title in buttons],
    })


async def mock_send_image(to, image_url, caption=None):
    outbox.append({"type": "image", "url": image_url, "caption": caption})


async def mock_send_list_menu(to, body_text, button_text, sections, footer=None):
    outbox.append({
        "type": "list",
        "body": body_text,
        "button_text": button_text,
        "sections": sections,
        "footer": footer,
    })


# ---- monkeypatch every conversation module's bound reference to the real
# whatsapp.py functions, so nothing actually calls Meta's API ----
import app.conversation.messages as _m_messages
import app.conversation.onboarding as _m_onboarding
import app.conversation.fulfillment as _m_fulfillment
import app.conversation.order_flow as _m_order_flow
import app.conversation.router as _m_router

for _mod in (_m_messages, _m_onboarding, _m_fulfillment, _m_order_flow, _m_router):
    if hasattr(_mod, "send_text"):
        _mod.send_text = mock_send_text
    if hasattr(_mod, "send_buttons"):
        _mod.send_buttons = mock_send_buttons
    if hasattr(_mod, "send_image"):
        _mod.send_image = mock_send_image
    if hasattr(_mod, "send_list_menu"):
        _mod.send_list_menu = mock_send_list_menu

from app.conversation.router import handle_text_message, handle_button_reply

app = FastAPI()


class TextIn(BaseModel):
    text: str


class ButtonIn(BaseModel):
    id: str


@app.post("/api/send")
async def api_send(payload: TextIn):
    outbox.clear()
    try:
        await handle_text_message(FAKE_NUMBER, payload.text)
    except Exception as e:
        outbox.append({"type": "error", "body": f"⚠️ Exception: {e}"})
    return JSONResponse(outbox)


@app.post("/api/button")
async def api_button(payload: ButtonIn):
    outbox.clear()
    try:
        await handle_button_reply(FAKE_NUMBER, payload.id)
    except Exception as e:
        outbox.append({"type": "error", "body": f"⚠️ Exception: {e}"})
    return JSONResponse(outbox)


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Jay Fruits — Fake WhatsApp Test UI</title>
<style>
  body { margin:0; font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#e5ddd5; }
  #header { background:#075e54; color:white; padding:14px 18px; font-size:16px; font-weight:600; }
  #chat { max-width:480px; margin:0 auto; height:calc(100vh - 130px); overflow-y:auto; padding:14px; }
  .bubble { background:white; border-radius:8px; padding:10px 12px; margin:8px 0; max-width:85%; box-shadow:0 1px 1px rgba(0,0,0,0.1); white-space:pre-wrap; font-size:14px; line-height:1.4; }
  .bubble.me { background:#dcf8c6; margin-left:auto; }
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
<div id="header">🍉 Jay Fruits — Fake WhatsApp Test UI (no real WhatsApp involved)</div>
<div id="chat"></div>
<div id="inputbar">
  <input id="msgInput" placeholder="Type a message..." autofocus>
  <button onclick="sendText()">Send</button>
</div>

<script>
const chat = document.getElementById('chat');

function scrollDown() { chat.scrollTop = chat.scrollHeight; }

function addBubble(html, mine=false) {
  const div = document.createElement('div');
  div.className = 'bubble' + (mine ? ' me' : '');
  div.innerHTML = html;
  chat.appendChild(div);
  scrollDown();
}

function renderOutbox(items) {
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
  addBubble(escapeHtml(text), true);
  input.value = '';
  const res = await fetch('/api/send', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({text})
  });
  const items = await res.json();
  renderOutbox(items);
}

async function tapButton(id) {
  addBubble('<i>(tapped: ' + escapeHtml(id) + ')</i>', true);
  const res = await fetch('/api/button', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({id})
  });
  const items = await res.json();
  renderOutbox(items);
}

document.getElementById('msgInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendText();
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print("Open http://127.0.0.1:8500 in your browser")
    uvicorn.run(app, host="127.0.0.1", port=8500)