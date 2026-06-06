import os
from dotenv import load_dotenv
import alpaca_trade_api as tradeapi

load_dotenv()

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL")

print(f"API KEY:  {API_KEY[:8]}...")
print(f"BASE URL: {BASE_URL}")

try:
    api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL)
    account = api.get_account()
    print(f"\n✅ Conectat! Sold: ${account.cash}")
except Exception as e:
    print(f"\n❌ Eroare: {e}")