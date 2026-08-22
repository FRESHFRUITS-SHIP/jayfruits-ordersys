from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse

from app.config import DASHBOARD_SECRET_KEY, SHOP_NAME
from app.routers import webhook, dashboard, customer_page

app = FastAPI(title="Jay Fruit's — WhatsApp Order System")
app.add_middleware(SessionMiddleware, secret_key=DASHBOARD_SECRET_KEY)

app.include_router(webhook.router)
app.include_router(dashboard.router)
app.include_router(customer_page.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/orders")

@app.get("/debug/secret-check")
async def debug_secret_check():
    """TEMPORARY — remove after debugging."""
    from app.config import META_APP_SECRET, META_ACCESS_TOKEN, META_PHONE_NUMBER_ID
    return {
        "app_secret_is_empty": META_APP_SECRET == "",
        "app_secret_length": len(META_APP_SECRET),
        "access_token_length": len(META_ACCESS_TOKEN),
        "access_token_first10": META_ACCESS_TOKEN[:10] if META_ACCESS_TOKEN else "",
        "access_token_last6": META_ACCESS_TOKEN[-6:] if len(META_ACCESS_TOKEN) > 6 else "",
        "phone_number_id": META_PHONE_NUMBER_ID,
    }


@app.post("/tasks/daily-summary")
async def trigger_daily_summary():
    """
    Sends today's summary (orders, revenue, best-seller) to the shop owner's
    WhatsApp number. Call this once a day — e.g. from a free cron service like
    cron-job.org hitting this URL every evening, or Railway's Cron Jobs feature.
    Not scheduled automatically inside the app itself (keeps the app simple and
    stateless); wire up an external scheduler pointed at this endpoint.
    """
    from app.services import orders as svc
    from app.services.whatsapp import send_text
    from app.config import SHOP_WHATSAPP_DISPLAY_NUMBER

    data = svc.get_analytics(days=1)
    best = data["best_sellers"][0][0] if data["best_sellers"] else "—"
    text = (
        f"📊 *Daily Summary — {SHOP_NAME}*\n\n"
        f"Orders today: {data['total_orders']}\n"
        f"Revenue: ₹{data['total_revenue']:.0f}\n"
        f"Profit: ₹{data['total_profit']:.0f}\n"
        f"Top seller: {best}"
    )
    owner_number = SHOP_WHATSAPP_DISPLAY_NUMBER.replace(" ", "").replace("+", "")
    if owner_number:
        await send_text(owner_number, text)
    return {"status": "sent", "summary": data}


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    """
    Meta requires a public Privacy Policy URL to publish a WhatsApp Business app.
    This is a minimal, honest policy covering what this bot actually does.
    Edit the contact email/address below to your real details before publishing.
    """
    return f"""
    <!DOCTYPE html>
    <html><head><meta charset="UTF-8"><title>Privacy Policy — {SHOP_NAME}</title>
    <style>
      body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 20px; color: #222; line-height: 1.6; }}
      h1 {{ font-size: 22px; }}
      h2 {{ font-size: 16px; margin-top: 28px; }}
    </style></head>
    <body>
      <h1>Privacy Policy — {SHOP_NAME}</h1>
      <p>Last updated: 2026</p>

      <p>{SHOP_NAME} operates a WhatsApp-based ordering service. This page explains what
      information we collect when you message us and how it's used.</p>

      <h2>What we collect</h2>
      <p>When you message our WhatsApp number, we store your WhatsApp phone number and the
      contents of the messages you send us, in order to process and record your fruit orders
      (items, quantities, delivery/payment preference).</p>

      <h2>How we use it</h2>
      <p>Your information is used only to fulfill your order — confirming items, calculating
      totals, arranging delivery or pickup, and payment. We do not sell or share your data with
      third parties for marketing purposes.</p>

      <h2>Third-party services</h2>
      <p>We use Meta's WhatsApp Business API to send and receive messages, and Groq's language
      model API to help interpret order text. Groq processes message text solely to extract
      order details and does not retain it for other purposes on our behalf.</p>

      <h2>Data retention</h2>
      <p>Order and contact records are retained for our normal business record-keeping. You can
      request deletion of your data by messaging us directly.</p>

      <h2>Contact</h2>
      <p>For questions about this policy or your data, contact us via WhatsApp at the number
      you used to place your order, or visit us at Shop 4, Kandivali West, Mumbai.</p>
    </body></html>
    """
