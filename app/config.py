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

WHATSAPP_API_URL = f"https://graph.facebook.com/v20.0/{META_PHONE_NUMBER_ID}/messages"
