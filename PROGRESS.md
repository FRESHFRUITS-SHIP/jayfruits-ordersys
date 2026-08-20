# Jay Fruit's — WhatsApp Order System: Setup Summary & Next Steps

## Where things stand

### ✅ Working / confirmed
- **Code**: FastAPI app built — webhook, Groq order parser, Supabase order storage, dashboard — all committed and tested locally.
- **Supabase**: project created, `schema.sql` run, starter product menu seeded.
- **Groq**: API key working. Model updated from the deprecated `llama-3.3-70b-versatile` → **`openai/gpt-oss-120b`** (confirmed available on your account).
- **Meta app**: created, WhatsApp product added.
- **Webhook connectivity**: verified working — Meta's "Test" button successfully triggers your `/webhook` endpoint end-to-end (received → parsed by Groq → reply composed).
- **Bug fixed**: `META_APP_SECRET` had a leftover placeholder string (`your_app_secret`) instead of being truly blank, which broke signature verification → fixed by leaving it empty for local dev.
- **Bug fixed**: Groq model name was deprecated → swapped to `openai/gpt-oss-120b`.

### 🚧 Current blocker
**App is still "unpublished" in Meta.** While unpublished, WhatsApp will only deliver **simulated test payloads** (via the dashboard's "Test" button) to your webhook — real messages sent from a real phone will NOT reach your bot at all. This is why the Test button worked but texting "hi" from your phone did nothing.

**Decision made**: publish the app so real messages work. This is the next concrete step.

### Known values (safe to reference, not secret)
- Meta App ID: `1137464001941394`
- Business ID: `1050991477335926`
- Current test WhatsApp number: `+1 555 674 8421`
- Current Phone Number ID: `1294038587125014` (this has rotated at least once already — expect it may again until you register your real business number in Step 2)
- WhatsApp Business Account ID: `4393503714232429`

### ⚠️ Security note (do this soon)
Real secrets were pasted into this chat earlier: `META_ACCESS_TOKEN`, `GROQ_API_KEY`, `SUPABASE_SERVICE_KEY`, dashboard password. Rotate all of these once things are stable:
- Groq: console.groq.com → API Keys → delete old, create new
- Supabase: Settings → API → regenerate `service_role` key
- Meta: temporary tokens expire in 24h anyway, but once you set up a **permanent token** (System User), that becomes the one to protect
- Dashboard password: change `DASHBOARD_PASSWORD` in `.env`

---

## Next steps — in order

### 1. Publish the Meta app
Go to: `developers.facebook.com/apps/1137464001941394/go_live/`
Likely required: app icon, privacy policy URL, app category. Business verification may or may not be required immediately for WhatsApp messaging specifically — find out when you get there.

### 2. Move code to a private GitHub repo
Currently the code only exists on your local machine (`C:\Users\HP\jayfruits-ordersys`) and in this chat's file output. Before deploying to Railway, it needs to live in a GitHub repo (Railway deploys from GitHub).

Steps:
```bash
cd C:\Users\HP\jayfruits-ordersys
git init
git add .
git commit -m "Initial WhatsApp order system"
```
Then on GitHub:
1. Create a **new private repository** (e.g. `jayfruits-ordersys`) — important: **Private**, not public, since this is real business code
2. Follow GitHub's instructions to push your existing local repo:
```bash
git remote add origin https://github.com/<your-username>/jayfruits-ordersys.git
git branch -M main
git push -u origin main
```

**Important**: make sure `.env` (with real secrets) is NOT committed. Add a `.gitignore`:
```
.env
__pycache__/
*.pyc
```

### 3. Deploy to Railway
1. railway.app → New Project → **Deploy from GitHub repo** → select your private repo (Railway will ask for GitHub access — grant it just for this repo if possible)
2. Railway auto-detects Python. Set the **Start Command**:
   ```
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
3. Under **Variables**, add every value from your local `.env` (with rotated/fresh secrets):
   - `META_ACCESS_TOKEN`, `META_PHONE_NUMBER_ID`, `META_VERIFY_TOKEN`, `META_APP_SECRET`
   - `GROQ_API_KEY`, `GROQ_MODEL=openai/gpt-oss-120b`
   - `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
   - `SHOP_NAME`, `SHOP_UPI_ID`, `SHOP_UPI_PAYEE_NAME`, `SHOP_WHATSAPP_DISPLAY_NUMBER`
   - `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD`, `DASHBOARD_SECRET_KEY`
4. Deploy — Railway gives a permanent URL like `https://jayfruits-ordersys.up.railway.app`

### 4. Point Meta's webhook at the permanent Railway URL
No more ngrok, no more URL rotating on every restart.
- WhatsApp → Configuration → Webhook → Edit
- Callback URL: `https://jayfruits-ordersys.up.railway.app/webhook`
- Verify token: same `META_VERIFY_TOKEN` value
- Verify and save → re-subscribe to `messages`

### 5. Set up a permanent access token
Temporary tokens expire every 24h — annoying for anything beyond testing.
- Create a **System User** in Meta Business Settings
- Generate a permanent token scoped to `whatsapp_business_messaging`
- Update `META_ACCESS_TOKEN` in Railway's Variables with this permanent token

### 6. Re-test the full flow for real
From your actual phone, message the WhatsApp number:
- `hi` → menu
- `2kg mango, 1 dozen banana` → itemized total + payment buttons
- Confirm order shows up on `https://jayfruits-ordersys.up.railway.app/orders`

---

## What we're deferring for now
- Real business phone number registration (Step 2 in Meta's wizard) — can stay on the test number until basic flow is confirmed live
- Razorpay/Cashfree integration for auto-confirmed payments (currently: UPI deep link + manual confirmation)
- Delivery address collection in the conversation flow
- Business verification (Step 3) — only needed for higher message volume / marketing messages later
