import yfinance as yf
import alpaca_trade_api as tradeapi
import os
import json
import time
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL")

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL)

# ═══════════════════════════════════════
# SETĂRI AGENT
# ═══════════════════════════════════════
MAX_POZITII = 10
CAPITAL_PE_POZITIE = 1000   # $10,000 per acțiune
STOP_LOSS = 0.03             # Vinde dacă pierzi 3%
TAKE_PROFIT = 0.05           # Vinde dacă câștigi 5%
INTERVAL = 60                # Verifică la fiecare 60 secunde
MEMORIE_FILE = "memorie_agent.json"

# Lista acțiuni de scanat
ACTIUNI_SCANATE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "META", "TSLA", "AMD", "NFLX", "PYPL",
    "JPM", "BAC", "DIS", "UBER", "SPOT",
    "CRM", "SNOW", "PLTR", "COIN", "SQ"
]

# ═══════════════════════════════════════
# MEMORIE — Învață din tranzacții
# ═══════════════════════════════════════
def incarca_memorie():
    if os.path.exists(MEMORIE_FILE):
        with open(MEMORIE_FILE, 'r') as f:
            return json.load(f)
    return {
        "tranzactii": [],
        "performanta_pe_simbol": {},
        "parametri": {
            "stop_loss": STOP_LOSS,
            "take_profit": TAKE_PROFIT
        }
    }

def salveaza_memorie(memorie):
    with open(MEMORIE_FILE, 'w') as f:
        json.dump(memorie, f, indent=2)

def invata_din_tranzactii(memorie):
    """Ajustează parametrii bazat pe performanța trecută"""
    tranzactii = memorie["tranzactii"]
    
    if len(tranzactii) < 5:
        return memorie  # Nu avem suficiente date
    
    # Calculează rata de succes
    profitabile = [t for t in tranzactii if t.get("profit", 0) > 0]
    rata_succes = len(profitabile) / len(tranzactii)
    
    print(f"🧠 Rata succes: {rata_succes:.1%} ({len(profitabile)}/{len(tranzactii)} tranzacții)")
    
    # Ajustează parametrii
    if rata_succes < 0.4:
        # Prea multe pierderi — fii mai conservator
        memorie["parametri"]["stop_loss"] = max(0.02, memorie["parametri"]["stop_loss"] - 0.005)
        memorie["parametri"]["take_profit"] = min(0.08, memorie["parametri"]["take_profit"] + 0.005)
        print(f"⚠️ Ajustare conservatoare: SL={memorie['parametri']['stop_loss']:.1%} TP={memorie['parametri']['take_profit']:.1%}")
    elif rata_succes > 0.6:
        # Merge bine — poți fi mai agresiv
        memorie["parametri"]["stop_loss"] = min(0.05, memorie["parametri"]["stop_loss"] + 0.005)
        memorie["parametri"]["take_profit"] = max(0.03, memorie["parametri"]["take_profit"] - 0.005)
        print(f"✅ Ajustare agresivă: SL={memorie['parametri']['stop_loss']:.1%} TP={memorie['parametri']['take_profit']:.1%}")
    
    return memorie

# ═══════════════════════════════════════
# ANALIZĂ ACȚIUNI
# ═══════════════════════════════════════
def analizeaza_actiune(simbol, memorie):
    """Returnează un scor pentru fiecare acțiune"""
    try:
        df = yf.download(simbol, period="5d", interval="1h", progress=False)
        if df.empty or len(df) < 10:
            return None
        
        preturi = df['Close'].tolist()
        volume = df['Volume'].tolist()
        
        # Calculează indicatori
        medie_scurta = sum(preturi[-3:]) / 3
        medie_lunga = sum(preturi[-10:]) / 10
        momentum = (preturi[-1] - preturi[-10]) / preturi[-10]
        volum_recent = sum(volume[-3:]) / 3
        volum_mediu = sum(volume[-10:]) / 10
        volum_ratio = volum_recent / volum_mediu if volum_mediu > 0 else 1
        
        # Scor bazat pe momentum și volum
        scor = 0
        if medie_scurta > medie_lunga:
            scor += 2  # Trend pozitiv
        if momentum > 0.02:
            scor += 2  # Momentum puternic
        if volum_ratio > 1.5:
            scor += 1  # Volum crescut
            
        # Bonus dacă acțiunea a fost profitabilă în trecut
        perf = memorie["performanta_pe_simbol"].get(simbol, {})
        if perf.get("profit_total", 0) > 0:
            scor += 1
        
        return {
            "simbol": simbol,
            "pret": preturi[-1],
            "momentum": momentum,
            "volum_ratio": volum_ratio,
            "scor": scor
        }
    except Exception as e:
        return None

def selecteaza_portofoliu(memorie):
    """Scanează și alege cele mai bune MAX_POZITII acțiuni"""
    print(f"\n🔍 Scanez {len(ACTIUNI_SCANATE)} acțiuni...")
    rezultate = []
    
    for simbol in ACTIUNI_SCANATE:
        rezultat = analizeaza_actiune(simbol, memorie)
        if rezultat and rezultat["scor"] >= 3:
            rezultate.append(rezultat)
            print(f"  ✅ {simbol}: scor={rezultat['scor']} momentum={rezultat['momentum']:.1%}")
        else:
            print(f"  ❌ {simbol}: scor insuficient")
    
    # Sortează după scor și alege top MAX_POZITII
    rezultate.sort(key=lambda x: x["scor"], reverse=True)
    selectate = rezultate[:MAX_POZITII]
    
    print(f"\n📊 Portofoliu selectat: {[r['simbol'] for r in selectate]}")
    return selectate

# ═══════════════════════════════════════
# TRANZACȚIONARE
# ═══════════════════════════════════════
def get_pozitii_curente():
    try:
        pozitii = api.list_positions()
        return {p.symbol: float(p.avg_entry_price) for p in pozitii}
    except:
        return {}

def cumpara(simbol, pret, memorie):
    try:
        cantitate = int(CAPITAL_PE_POZITIE / pret)
        if cantitate < 1:
            return
        
        api.submit_order(
            symbol=simbol,
            qty=cantitate,
            side='buy',
            type='market',
            time_in_force='gtc'
        )
        print(f"✅ CUMPARAT {cantitate}x {simbol} la ${pret:.2f}")
        
        memorie["tranzactii"].append({
            "simbol": simbol,
            "tip": "cumparare",
            "pret": pret,
            "cantitate": cantitate,
            "data": datetime.now().isoformat()
        })
        salveaza_memorie(memorie)
    except Exception as e:
        print(f"❌ Eroare cumpărare {simbol}: {e}")

def vinde(simbol, cantitate, pret_intrare, pret_curent, motiv, memorie):
    try:
        api.submit_order(
            symbol=simbol,
            qty=cantitate,
            side='sell',
            type='market',
            time_in_force='gtc'
        )
        
        profit = (pret_curent - pret_intrare) * cantitate
        print(f"🔴 VANDUT {simbol} | Motiv: {motiv} | Profit: ${profit:.2f}")
        
        # Salvează în memorie
        if simbol not in memorie["performanta_pe_simbol"]:
            memorie["performanta_pe_simbol"][simbol] = {"profit_total": 0, "tranzactii": 0}
        
        memorie["performanta_pe_simbol"][simbol]["profit_total"] += profit
        memorie["performanta_pe_simbol"][simbol]["tranzactii"] += 1
        
        memorie["tranzactii"].append({
            "simbol": simbol,
            "tip": "vanzare",
            "pret": pret_curent,
            "profit": profit,
            "motiv": motiv,
            "data": datetime.now().isoformat()
        })
        salveaza_memorie(memorie)
    except Exception as e:
        print(f"❌ Eroare vânzare {simbol}: {e}")

# ═══════════════════════════════════════
# AGENT PRINCIPAL
# ═══════════════════════════════════════
def agent():
    print("🤖 Smart Trading Agent pornit!")
    print(f"📊 Max poziții: {MAX_POZITII}")
    print(f"💰 Capital pe poziție: ${CAPITAL_PE_POZITIE}")
    print("-" * 40)
    
    memorie = incarca_memorie()
    ciclu = 0
    
    while True:
        try:
            print(f"\n⏰ {datetime.now().strftime('%H:%M:%S')} | Ciclu #{ciclu}")
            
            # Verifică bursa
            clock = api.get_clock()
            if not clock.is_open:
                print(f"❌ Bursa închisă. Se deschide la: {clock.next_open}")
                time.sleep(300)
                continue
            
            # Învață din tranzacții trecute
            memorie = invata_din_tranzactii(memorie)
            stop_loss = memorie["parametri"]["stop_loss"]
            take_profit = memorie["parametri"]["take_profit"]
            
            # Verifică pozițiile curente — vinde dacă e cazul
            pozitii = get_pozitii_curente()
            for simbol, pret_intrare in pozitii.items():
                try:
                    df = yf.download(simbol, period="1d", interval="5m", progress=False)
                    pret_curent = df['Close'].iloc[-1]
                    variatie = (pret_curent - pret_intrare) / pret_intrare
                    
                    pozitie = api.get_position(simbol)
                    cantitate = int(pozitie.qty)
                    
                    if variatie <= -stop_loss:
                        vinde(simbol, cantitate, pret_intrare, pret_curent, f"STOP LOSS ({variatie:.1%})", memorie)
                    elif variatie >= take_profit:
                        vinde(simbol, cantitate, pret_intrare, pret_curent, f"TAKE PROFIT ({variatie:.1%})", memorie)
                except:
                    continue
            
            # Selectează portofoliu nou dacă avem loc
            pozitii = get_pozitii_curente()
            locuri_libere = MAX_POZITII - len(pozitii)
            
            if locuri_libere > 0:
                portofoliu = selecteaza_portofoliu(memorie)
                for actiune in portofoliu:
                    if actiune["simbol"] not in pozitii and locuri_libere > 0:
                        cumpara(actiune["simbol"], actiune["pret"], memorie)
                        locuri_libere -= 1
            else:
                print(f"📊 Portofoliu plin: {list(pozitii.keys())}")
            
            ciclu += 1
            print(f"\n⏳ Aștept {INTERVAL} secunde...")
            time.sleep(INTERVAL)
            
        except Exception as e:
            print(f"❌ Eroare generală: {e}")
            time.sleep(30)

# ═══════════════════════════════════════
# START
# ═══════════════════════════════════════
def verifica_bursa():
    clock = api.get_clock()
    if clock.is_open:
        print("✅ Bursa este DESCHISA")
        agent()
    else:
        print(f"❌ Bursa este INCHISA")
        print(f"⏰ Se deschide la: {clock.next_open}")
        print(f"\nVrei să pornești agentul acum și să aștepte deschiderea? (da/nu)")
        raspuns = input()
        if raspuns.lower() == "da":
            agent()

verifica_bursa()