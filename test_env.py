import os
from dotenv import load_dotenv

# Incarca .env
load_dotenv()

print("=== TEST ENV ===")
print(f"API KEY:    {os.getenv('ALPACA_API_KEY')}")
print(f"SECRET KEY: {os.getenv('ALPACA_SECRET_KEY')}")
print(f"BASE URL:   {os.getenv('ALPACA_BASE_URL')}")
print(f"TRADE SIZE: {os.getenv('MAX_TRADE_SIZE_USD')}")
print(f"TRADES/ZI:  {os.getenv('MAX_TRADES_PER_DAY')}")

# Verifica fisierul .env
print("\n=== LOCATIE FISIERE ===")
print(f"Folder curent: {os.getcwd()}")
print(f".env exista: {os.path.exists('.env')}")

# Afiseaza continutul .env
if os.path.exists('.env'):
    print("\n=== CONTINUT .env ===")
    with open('.env', 'r') as f:
        for linie in f.readlines():
            print(repr(linie))
else:
    print("\n❌ Fisierul .env NU a fost gasit!")
