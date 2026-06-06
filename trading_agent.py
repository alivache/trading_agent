import alpaca_trade_api as tradeapi
import time
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# API_KEY = "PKLBDAEPT6P4AMYEFIVB6REBS6"
# SECRET_KEY = "ETzDerRDP8HhKxF9GZCjQhbB2gQP8jS4Fbzdgvuen8WY"
# BASE_URL = "https://paper-api.alpaca.markets"

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL")

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL)

# Setări agent
SIMBOL = "AAPL"        # Acțiunea pe care o urmărim
CANTITATE = 1          # Câte acțiuni cumpărăm/vindem
INTERVAL = 10          # Verifică la fiecare 60 secunde

def get_pret_curent(simbol):
    bara = api.get_latest_bar(simbol)
    return bara.c  # pretul de inchidere

def verifica_pozitie(simbol):
    try:
        pozitie = api.get_position(simbol)
        return int(pozitie.qty)
    except:
        return 0  # Nu avem pozitie deschisa

def agent():
    print(f"🤖 Agent pornit pentru {SIMBOL}")
    print(f"⏰ {datetime.now().strftime('%H:%M:%S')}")
    
    preturi = []  # Istoricul preturilor
    
    while True:
        try:
            pret = get_pret_curent(SIMBOL)
            preturi.append(pret)
            print(f"💰 Pret {SIMBOL}: ${pret}")
            
            # Pastreaza doar ultimele 20 preturi
            if len(preturi) > 20:
                preturi.pop(0)
            
            # Strategie simpla: Moving Average
            if len(preturi) >= 5:
                medie_scurta = sum(preturi[-3:]) / 3   # Media ultimelor 3
                medie_lunga = sum(preturi[-5:]) / 5    # Media ultimelor 5
                
                pozitie = verifica_pozitie(SIMBOL)
                
                if medie_scurta > medie_lunga and pozitie == 0:
                    # Semnal de CUMPARARE
                    api.submit_order(
                        symbol=SIMBOL,
                        qty=CANTITATE,
                        side='buy',
                        type='market',
                        time_in_force='gtc'
                    )
                    print(f"✅ CUMPARAT {CANTITATE} {SIMBOL} la ${pret}")
                
                elif medie_scurta < medie_lunga and pozitie > 0:
                    # Semnal de VANZARE
                    api.submit_order(
                        symbol=SIMBOL,
                        qty=CANTITATE,
                        side='sell',
                        type='market',
                        time_in_force='gtc'
                    )
                    print(f"🔴 VANDUT {CANTITATE} {SIMBOL} la ${pret}")
            
            time.sleep(INTERVAL)
            
        except Exception as e:
            print(f"❌ Eroare: {e}")
            time.sleep(10)

# Porneste agentul
def verifica_bursa():
    clock = api.get_clock()
    if clock.is_open:
        print("✅ Bursa este DESCHISA")
        agent()
    else:
        print(f"❌ Bursa este INCHISA")
        print(f"⏰ Se deschide la: {clock.next_open}")

verifica_bursa()