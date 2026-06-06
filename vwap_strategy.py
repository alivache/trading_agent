import yfinance as yf
import alpaca_trade_api as tradeapi
import os
import json
import time
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL")
MAX_TRADE_SIZE_USD = float(os.getenv("MAX_TRADE_SIZE_USD", 1000))
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", 10))

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL)

# ═══════════════════════════════════════
# SETĂRI
# ═══════════════════════════════════════
ACTIUNI = [
    "AAPL", "MSFT", "NVDA", "AMD", "TSLA",
    "GOOGL", "META", "AMZN", "NFLX", "COIN"
]
INTERVAL_SCANARE = 60
STOP_LOSS_PCT = 0.003
MAX_DISTANTA_VWAP = 0.015
MEMORIE_FILE = "memorie_vwap.json"

trades_azi = 0
data_curenta = datetime.now().date()
pozitii_deschise = {}

# ═══════════════════════════════════════
# MEMORIE
# ═══════════════════════════════════════
def incarca_memorie():
    if os.path.exists(MEMORIE_FILE):
        with open(MEMORIE_FILE, 'r') as f:
            return json.load(f)
    return {
        "tranzactii": [],
        "performanta": {},
        "stats": {
            "total_profit": 0,
            "wins": 0,
            "losses": 0
        }
    }

def salveaza_memorie(memorie):
    with open(MEMORIE_FILE, 'w') as f:
        json.dump(memorie, f, indent=2, default=str)

def log_tranzactie(memorie, simbol, tip, pret, cantitate, profit=None, motiv=None):
    memorie["tranzactii"].append({
        "simbol": simbol,
        "tip": tip,
        "pret": pret,
        "cantitate": cantitate,
        "profit": profit,
        "motiv": motiv,
        "data": datetime.now().isoformat()
    })

    if profit is not None:
        memorie["stats"]["total_profit"] += profit
        if profit > 0:
            memorie["stats"]["wins"] += 1
        else:
            memorie["stats"]["losses"] += 1

        if simbol not in memorie["performanta"]:
            memorie["performanta"][simbol] = {"profit": 0, "trades": 0}
        memorie["performanta"][simbol]["profit"] += profit
        memorie["performanta"][simbol]["trades"] += 1

    salveaza_memorie(memorie)

# ═══════════════════════════════════════
# ÎNVĂȚARE NIVEL 1
# ═══════════════════════════════════════
def calculeaza_win_rate(memorie, simbol):
    tranzactii_simbol = [
        t for t in memorie["tranzactii"]
        if t["simbol"] == simbol and t.get("profit") is not None
    ]
    if len(tranzactii_simbol) == 0:
        return None
    wins = len([t for t in tranzactii_simbol if t["profit"] > 0])
    return wins / len(tranzactii_simbol)

def ajusteaza_trade_size(memorie, simbol):
    win_rate = calculeaza_win_rate(memorie, simbol)
    perf = memorie["performanta"].get(simbol, {})
    trades = perf.get("trades", 0)

    if trades < 3 or win_rate is None:
        return MAX_TRADE_SIZE_USD

    if win_rate >= 0.6:
        size = MAX_TRADE_SIZE_USD * 1.5
        print(f"  📈 {simbol} win rate={win_rate:.0%} → Trade size MĂRIT: ${size:.0f}")
        return size
    elif win_rate < 0.4:
        size = MAX_TRADE_SIZE_USD * 0.5
        print(f"  📉 {simbol} win rate={win_rate:.0%} → Trade size MICȘORAT: ${size:.0f}")
        return size
    else:
        return MAX_TRADE_SIZE_USD

def simbol_blocat(memorie, simbol):
    win_rate = calculeaza_win_rate(memorie, simbol)
    perf = memorie["performanta"].get(simbol, {})
    trades = perf.get("trades", 0)

    if trades >= 5 and win_rate is not None and win_rate < 0.4:
        print(f"  🚫 {simbol} BLOCAT — win rate={win_rate:.0%} după {trades} trades")
        return True
    return False

def afiseaza_performanta_simboluri(memorie):
    if not memorie["performanta"]:
        return

    print("\n📊 PERFORMANȚĂ PER SIMBOL:")
    print(f"  {'Simbol':<8} {'Trades':<8} {'Profit':<12} {'Win Rate'}")
    print(f"  {'-'*40}")

    for simbol, perf in memorie["performanta"].items():
        win_rate = calculeaza_win_rate(memorie, simbol)
        wr_str = f"{win_rate:.0%}" if win_rate is not None else "N/A"
        emoji = "🟢" if perf["profit"] > 0 else "🔴"
        print(f"  {emoji} {simbol:<8} {perf['trades']:<8} ${perf['profit']:<10.2f} {wr_str}")

# ═══════════════════════════════════════
# INDICATORI
# ═══════════════════════════════════════
def calculeaza_ema(preturi, perioada):
    prices = pd.Series(preturi)
    return prices.ewm(span=perioada, adjust=False).mean().iloc[-1]

def calculeaza_rsi(preturi, perioada=3):
    prices = pd.Series(preturi)
    delta = prices.diff()
    castig = delta.where(delta > 0, 0.0)
    pierdere = -delta.where(delta < 0, 0.0)
    avg_castig = castig.rolling(window=perioada).mean().iloc[-1]
    avg_pierdere = pierdere.rolling(window=perioada).mean().iloc[-1]

    if avg_pierdere == 0:
        return 100
    rs = avg_castig / avg_pierdere
    return 100 - (100 / (1 + rs))

def calculeaza_vwap(df):
    azi = datetime.now(timezone.utc).date()

    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')

    df_azi = df[df.index.date == azi]
    if df_azi.empty:
        df_azi = df

    typical_price = (df_azi['High'] + df_azi['Low'] + df_azi['Close']) / 3
    vwap = (typical_price * df_azi['Volume']).cumsum() / df_azi['Volume'].cumsum()
    return vwap.iloc[-1]

def get_date(simbol):
    df = yf.download(simbol, period="1d", interval="5m", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

# ═══════════════════════════════════════
# SEMNAL STRATEGIE
# ═══════════════════════════════════════
def analizeaza_semnal(simbol):
    try:
        df = get_date(simbol)
        if df.empty or len(df) < 15:
            return None, {}

        preturi_close = df['Close'].tolist()
        pret_curent = preturi_close[-1]

        ema8 = calculeaza_ema(preturi_close, 8)
        rsi3 = calculeaza_rsi(preturi_close, 3)
        vwap = calculeaza_vwap(df)

        distanta_vwap = abs(pret_curent - vwap) / vwap

        info = {
            "pret": pret_curent,
            "ema8": ema8,
            "rsi3": rsi3,
            "vwap": vwap,
            "distanta_vwap": distanta_vwap
        }

        # Regula de risc: prea departe de VWAP
        if distanta_vwap > MAX_DISTANTA_VWAP:
            return None, info

        # SEMNAL LONG
        if (pret_curent > vwap and
                pret_curent > ema8 and
                rsi3 < 30):
            return "long", info

        # SEMNAL SHORT
        if (pret_curent < vwap and
                pret_curent < ema8 and
                rsi3 > 70):
            return "short", info

        return None, info

    except Exception as e:
        print(f"  ❌ Eroare analiză {simbol}: {e}")
        return None, {}

# ═══════════════════════════════════════
# VERIFICARE EXIT
# ═══════════════════════════════════════
def verifica_exit(simbol, pret_intrare, directie, memorie):
    try:
        df = get_date(simbol)
        if df.empty:
            return False, "eroare date"

        preturi = df['Close'].tolist()
        pret_curent = preturi[-1]
        rsi3 = calculeaza_rsi(preturi, 3)
        ema8 = calculeaza_ema(preturi, 8)
        vwap = calculeaza_vwap(df)
        variatie = (pret_curent - pret_intrare) / pret_intrare

        if directie == "long":
            if variatie <= -STOP_LOSS_PCT:
                return True, f"STOP LOSS ({variatie:.2%})"
            if rsi3 > 50:
                return True, f"RSI CROSS 50 ({rsi3:.1f})"
            if pret_curent <= vwap or pret_curent <= ema8:
                return True, f"VWAP/EMA TOUCH ({variatie:.2%})"

        elif directie == "short":
            if variatie >= STOP_LOSS_PCT:
                return True, f"STOP LOSS ({variatie:.2%})"
            if rsi3 < 50:
                return True, f"RSI CROSS 50 ({rsi3:.1f})"
            if pret_curent >= vwap or pret_curent >= ema8:
                return True, f"VWAP/EMA TOUCH ({variatie:.2%})"

        return False, None

    except Exception as e:
        return False, None

# ═══════════════════════════════════════
# TRANZACȚIONARE
# ═══════════════════════════════════════
def deschide_pozitie(simbol, directie, pret, cantitate, memorie):
    global trades_azi

    try:
        if directie == "long":
            api.submit_order(
                symbol=simbol, qty=cantitate,
                side='buy', type='market', time_in_force='gtc'
            )
            print(f"  ✅ LONG {cantitate}x {simbol} @ ${pret:.2f}")
        else:
            api.submit_order(
                symbol=simbol, qty=cantitate,
                side='sell', type='market', time_in_force='gtc'
            )
            print(f"  ✅ SHORT {cantitate}x {simbol} @ ${pret:.2f}")

        pozitii_deschise[simbol] = {
            "directie": directie,
            "pret_intrare": pret,
            "cantitate": cantitate
        }
        trades_azi += 1
        log_tranzactie(memorie, simbol, f"open_{directie}", pret, cantitate)

    except Exception as e:
        print(f"  ❌ Eroare deschidere {simbol}: {e}")

def inchide_pozitie(simbol, motiv, memorie):
    if simbol not in pozitii_deschise:
        return

    pozitie = pozitii_deschise[simbol]
    directie = pozitie["directie"]
    pret_intrare = pozitie["pret_intrare"]
    cantitate = pozitie["cantitate"]

    try:
        df = get_date(simbol)
        pret_curent = df['Close'].iloc[-1]

        if directie == "long":
            api.submit_order(
                symbol=simbol, qty=cantitate,
                side='sell', type='market', time_in_force='gtc'
            )
            profit = (pret_curent - pret_intrare) * cantitate
        else:
            api.submit_order(
                symbol=simbol, qty=cantitate,
                side='buy', type='market', time_in_force='gtc'
            )
            profit = (pret_intrare - pret_curent) * cantitate

        emoji = "🟢" if profit > 0 else "🔴"
        print(f"  {emoji} ÎNCHIS {simbol} | {motiv} | Profit: ${profit:.2f}")

        log_tranzactie(memorie, simbol, f"close_{directie}", pret_curent, cantitate, profit, motiv)
        del pozitii_deschise[simbol]

    except Exception as e:
        print(f"  ❌ Eroare închidere {simbol}: {e}")

# ═══════════════════════════════════════
# STATS
# ═══════════════════════════════════════
def afiseaza_stats(memorie):
    stats = memorie["stats"]
    total = stats["wins"] + stats["losses"]
    rata = stats["wins"] / total if total > 0 else 0
    print(f"\n📊 STATS: Profit total=${stats['total_profit']:.2f} | "
          f"Win rate={rata:.1%} | "
          f"Trades={total}")

# ═══════════════════════════════════════
# AGENT PRINCIPAL
# ═══════════════════════════════════════
def agent():
    global trades_azi, data_curenta

    print("🤖 VWAP + RSI(3) + EMA(8) Scalping Agent — Nivel 1 Learning")
    print(f"💰 Max trade: ${MAX_TRADE_SIZE_USD} | Max trades/zi: {MAX_TRADES_PER_DAY}")
    print(f"🛑 Stop Loss: {STOP_LOSS_PCT:.1%} | Max distanță VWAP: {MAX_DISTANTA_VWAP:.1%}")
    print("-" * 50)

    memorie = incarca_memorie()
    ciclu = 0

    while True:
        try:
            # Reset trades la zi nouă
            if datetime.now().date() != data_curenta:
                data_curenta = datetime.now().date()
                trades_azi = 0
                print("🔄 Zi nouă — reset counter trades")

            print(f"\n⏰ {datetime.now().strftime('%H:%M:%S')} | "
                  f"Ciclu #{ciclu} | "
                  f"Trades azi: {trades_azi}/{MAX_TRADES_PER_DAY} | "
                  f"Poziții deschise: {len(pozitii_deschise)}")

            # Verifică bursa
            clock = api.get_clock()
            if not clock.is_open:
                print(f"❌ Bursa închisă. Se deschide la: {clock.next_open}")
                time.sleep(300)
                continue

            # ── VERIFICĂ EXIT pentru pozițiile deschise
            for simbol in list(pozitii_deschise.keys()):
                poz = pozitii_deschise[simbol]
                exit_acum, motiv = verifica_exit(
                    simbol, poz["pret_intrare"], poz["directie"], memorie
                )
                if exit_acum:
                    inchide_pozitie(simbol, motiv, memorie)

            # ── CAUTĂ NOI INTRĂRI
            if trades_azi < MAX_TRADES_PER_DAY:
                print(f"\n🔍 Scanez {len(ACTIUNI)} acțiuni...")

                for simbol in ACTIUNI:
                    if simbol in pozitii_deschise:
                        continue

                    # 🧠 ÎNVĂȚARE: sari peste simboluri blocate
                    if simbol_blocat(memorie, simbol):
                        continue

                    semnal, info = analizeaza_semnal(simbol)

                    if info:
                        print(f"  {simbol}: P=${info.get('pret', 0):.2f} | "
                              f"EMA8=${info.get('ema8', 0):.2f} | "
                              f"RSI3={info.get('rsi3', 0):.1f} | "
                              f"VWAP=${info.get('vwap', 0):.2f} | "
                              f"Semnal={'🟢 LONG' if semnal == 'long' else '🔴 SHORT' if semnal == 'short' else '⏳ none'}")

                    if semnal and trades_azi < MAX_TRADES_PER_DAY:
                        # 🧠 ÎNVĂȚARE: ajustează trade size
                        trade_size = ajusteaza_trade_size(memorie, simbol)
                        cantitate = int(trade_size / info["pret"])
                        if cantitate >= 1:
                            deschide_pozitie(simbol, semnal, info["pret"], cantitate, memorie)

            afiseaza_stats(memorie)
            afiseaza_performanta_simboluri(memorie)

            ciclu += 1
            time.sleep(INTERVAL_SCANARE)

        except Exception as e:
            print(f"❌ Eroare generală: {e}")
            time.sleep(30)

# ═══════════════════════════════════════
# START
# ═══════════════════════════════════════
def start():
    clock = api.get_clock()
    if clock.is_open:
        print("✅ Bursa DESCHISĂ — pornesc agentul!")
        agent()
    else:
        print(f"❌ Bursa ÎNCHISĂ")
        print(f"⏰ Se deschide la: {clock.next_open}")
        print(f"\nPornesc agentul și aștept deschiderea? (da/nu)")
        if input().lower() == "da":
            agent()

start()