import os
from dotenv import load_dotenv

load_dotenv()

META_ACCESS_TOKEN = os.environ["META_ACCESS_TOKEN"]
META_PHONE_NUMBER_ID = os.environ["META_PHONE_NUMBER_ID"]
META_VERIFY_TOKEN = os.environ["META_VERIFY_TOKEN"]
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

SHOP_NAME = os.environ.get("SHOP_NAME", "Jay Fruit's")
SHOP_UPI_ID = os.environ.get("SHOP_UPI_ID", "")
SHOP_UPI_PAYEE_NAME = os.environ.get("SHOP_UPI_PAYEE_NAME", SHOP_NAME)
SHOP_WHATSAPP_DISPLAY_NUMBER = os.environ.get("SHOP_WHATSAPP_DISPLAY_NUMBER", "")

DASHBOARD_USERNAME = os.environ.get("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "admin")
DASHBOARD_SECRET_KEY = os.environ.get("DASHBOARD_SECRET_KEY", "dev-secret-change-me")

# Base public URL of this deployed app, used to build customer-facing links
# (e.g. their personal menu/order-history page). Set this to your Railway URL
# once deployed, e.g. https://jayfruits-ordersys.up.railway.app
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")

# Rough delivery ETA quoted to customers at order confirmation time (minutes)
DEFAULT_DELIVERY_ETA_MINUTES = int(os.environ.get("DEFAULT_DELIVERY_ETA_MINUTES", "90"))

# Window within which a repeat order from the same customer gets flagged as
# a possible accidental duplicate (minutes)
DUPLICATE_ORDER_WINDOW_MINUTES = int(os.environ.get("DUPLICATE_ORDER_WINDOW_MINUTES", "5"))

WHATSAPP_API_URL = f"https://graph.facebook.com/v20.0/{META_PHONE_NUMBER_ID}/messages"
