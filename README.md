# Jay Fruit's — WhatsApp Order System

A WhatsApp bot (Meta Cloud API + Groq for free-text order parsing) + a small
web dashboard, backed by Supabase.

**How it works**
1. Customer messages your WhatsApp Business number.
2. Meta sends the message to your `/webhook` endpoint.
3. If it's a greeting, bot replies with today's menu.
4. If it looks like an order ("2kg mango, 1 dozen banana"), Groq parses it
   against your real product list, bot replies with a total, then asks
   UPI vs Cash/UPI-on-delivery via quick-reply buttons.
5. Order is saved to Supabase. You manage it from `/orders` (password protected).

---

## 1. Supabase setup

1. Create a project at supabase.com (free tier is fine).
2. Open the SQL editor, paste and run `schema.sql` from this repo.
3. Edit the seeded `products` rows to match your real fruits/prices —
   either in the SQL before running it, or later from Supabase's Table Editor.
4. Get your Project URL and **service_role** key (Settings → API) —
   NOT the anon/public key, since the bot writes data server-side.

## 2. Groq setup (free-text order parsing)

1. Get a free API key at console.groq.com.
2. That's it — the app uses `llama-3.3-70b-versatile` by default (fast + free tier).

## 3. Meta WhatsApp Cloud API setup

1. Go to developers.facebook.com → create an app → add the "WhatsApp" product.
2. Under WhatsApp → API Setup you'll get:
   - A temporary access token (valid 24h — for testing). For production,
     generate a permanent token via a System User in Meta Business Settings.
   - A **Phone Number ID** (this is what you put in `META_PHONE_NUMBER_ID`).
   - A test WhatsApp number you can message from your own phone to try it out.
3. To go live with your real shop number, verify it under WhatsApp → Phone Numbers.
4. Under WhatsApp → Configuration, set your **Webhook URL** to:
   `https://<your-deployed-domain>/webhook`
   and the **Verify Token** to whatever you set in `META_VERIFY_TOKEN` (any
   random string you choose yourself).
5. Subscribe the webhook to the `messages` field.
6. (Recommended) Copy your App Secret from Settings → Basic, put it in
   `META_APP_SECRET` — this lets the app verify that incoming webhook calls
   really came from Meta.

**Note:** Meta requires the webhook URL to be publicly reachable over HTTPS.
For local testing, use `ngrok http 8000` and put the ngrok URL in Meta's
webhook config temporarily. For real use, deploy this (Railway, Render,
Fly.io — anywhere that runs a Python web service) and use that URL.

## 3.5 If upgrading an existing database (v1 → v2)

Run `migration_v2.sql` in Supabase's SQL editor — it adds all the new columns/tables
(customer address, page tokens, language, cost price, shop settings, order source,
duplicate flag, etc.) without touching your existing data. Safe to run even if some
columns already exist.

If you're starting completely fresh, just run `schema.sql` instead — it includes
everything `migration_v2.sql` does plus the initial table creation.

## 4. Configure and run

```bash
cp .env.example .env
# fill in all values in .env

pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Dashboard: visit `http://localhost:8000/orders` (redirects to login).
Default login is whatever you set as `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`
in `.env` — change these from the defaults before going live.

## 5. Payments — how this actually works right now

The bot sends a `upi://pay` deep link with the exact order amount. Tapping it
opens the customer's UPI app (GPay/PhonePe/Paytm) with the amount filled in.

**Important limitation:** a plain UPI intent link has no webhook — there's no
way for this system to automatically know the payment succeeded. The order
is marked `payment_status = pending` and stays that way until you manually
mark it paid from the dashboard (or just check your bank/UPI app and trust
the customer, like any small shop does today).

If you want automatic payment confirmation later, swap `app/services/upi.py`
for a Razorpay or Cashfree "Payment Link" — both support server-side webhooks
that fire the moment payment lands, so the order can auto-update. That's a
bigger integration (needs a merchant account, KYC, ~2% fee) so I kept this
version to the free UPI-intent approach to start.

## 5.5 New in v2 — feature overview

**Bot conversation**
- Delivery address is collected once and reused; customer can say "change my address to ..."
- Order editing: "add 1kg banana" / "remove mango" works on any order not yet Delivered
- Cancellation: "cancel my order"
- Reorder: "same as last time" repeats their most recent order
- Auto language match: replies in Hindi if the customer writes Hindi/Hinglish, English otherwise
- Minimum order value (set in Settings) — orders below it are rejected with an explanation
- Business hours enforcement — orders outside configured hours are politely declined
- Voice notes/images get a clear "please send text" reply instead of being silently ignored
- Status changes made from the dashboard (Confirmed/Out for delivery/Delivered/Cancelled)
  automatically WhatsApp the customer
- Each customer gets a personal link (`/me/<token>`) showing today's menu + their order
  history — the bot mentions this in the greeting message

**Dashboard** (all under `/orders`, `/products`, `/customers`, `/analytics`, `/settings`)
- **New Order** button — log a phone-in order manually (same fields as WhatsApp orders,
  requires a WhatsApp number so the customer still gets confirmation/status messages)
- **Menu page** (`/products`) — toggle items in/out of stock, edit price and cost price
  inline (cost price powers profit tracking)
- **Customers page** — every customer with order count + total spend, click through for
  their full order history
- **Analytics page** — revenue, order count, average order value, profit, best-sellers,
  daily revenue trend, switchable between 7/30/90 day windows
- **Settings page** — set minimum order value and business hours without touching code
- **Search/filter** on the orders list — by status, source (WhatsApp vs phone), or
  phone number/order ID
- **Inline order editing** — add/remove items and edit notes directly from an order card
- **CSV export** (`/export.csv`) — every order line item, for accounting/tax records
- Orders show a **duplicate flag** (⚠) if the same customer ordered again within 5 minutes
  (configurable via `DUPLICATE_ORDER_WINDOW_MINUTES`), so you can catch accidental double-orders

**Daily summary**: `POST /tasks/daily-summary` sends you a WhatsApp message with today's
order count, revenue, and top-selling item. This isn't scheduled automatically inside the
app (keeps things simple/stateless) — point a free external cron service (e.g. cron-job.org)
or Railway's Cron Jobs feature at this URL once a day, e.g. every evening at 10 PM.

## 6. What this does NOT do yet (possible next steps)

- Delivery address collection (bot doesn't currently ask for/save address —
  add a step in `handle_button_reply` if you want it)
- Order editing ("actually make that 3kg not 2kg") — right now each message
  creates a new order; multi-turn edits would need a small conversation-state
  table
- Multiple simultaneous open orders per customer — `get_latest_open_order_for_customer`
  just grabs the most recent one
- WhatsApp catalog/product images — Meta supports rich product messages,
  not used here to keep things simple
- WhatsApp broadcast / daily-specials messages to past customers — needs Meta-approved
  message templates (a separate submission/review process), intentionally deferred
- Quick-reorder as tappable buttons (currently text-based "same as last time") — could
  upgrade to WhatsApp list/button messages showing their last 2-3 distinct orders
- Automatic loyalty/rewards tracking — explicitly skipped per your call earlier

## Project structure

```
app/
  main.py              FastAPI entrypoint
  config.py            env var loading
  db.py                Supabase client
  routers/
    webhook.py         WhatsApp webhook + conversation logic
    dashboard.py        /login, /orders, status updates
  services/
    whatsapp.py         send text / button messages via Meta API
    order_parser.py      Groq free-text -> structured order
    upi.py               UPI deep link builder
    orders.py             DB reads/writes for products, customers, orders
  templates/
    login.html
    orders.html
schema.sql              Supabase table definitions + starter product seed
.env.example
requirements.txt
```
