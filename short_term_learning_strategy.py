import os
import json
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
import alpaca_trade_api as tradeapi
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL")

SYMBOLS = [s.strip().upper() for s in os.getenv("ACTIUNI", "AAPL,MSFT,NVDA,GOOGL,AMZN,NFLX,META,AMD,TSLA,AVGO,CRM,ADBE,ORCL,CSCO,INTC,QCOM,TXN,AMAT,MU,PYPL").split(",") if s.strip()]
EARNINGS_RAW = os.getenv("EARNINGS", "")
EARNINGS = {}
for item in EARNINGS_RAW.split(","):
    if ":" in item:
        sym, date_str = item.split(":", 1)
        EARNINGS[sym.strip().upper()] = date_str.strip()

MEMORY_FILE = "memorie_short_term.json"
MAX_POSITIONS = int(os.getenv("SHORT_TERM_MAX_POSITIONS", "4"))
CAPITAL_PER_POSITION = float(os.getenv("SHORT_TERM_CAPITAL_PER_POSITION", "1500"))
INTERVAL = int(os.getenv("SHORT_TERM_SCAN_INTERVAL", "60"))
BASE_STOP_LOSS = float(os.getenv("SHORT_TERM_BASE_STOP_LOSS", "0.009"))
MAX_STOP_LOSS = float(os.getenv("SHORT_TERM_MAX_STOP_LOSS", "0.015"))
RISK_REWARD = float(os.getenv("SHORT_TERM_RR", "2.0"))
MIN_SCORE_BASE = int(os.getenv("SHORT_TERM_MIN_SCORE", "3"))
COOLDOWN_MINUTES = int(os.getenv("SHORT_TERM_COOLDOWN_MINUTES", "180"))

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL)


def incarca_memorie():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return {
        "tranzactii": [],
        "performanta": {},
        "cooldown": {},
        "config": {
            "stop_loss": BASE_STOP_LOSS,
            "min_score": MIN_SCORE_BASE,
            "volume_ratio": 1.2,
            "cooldown_minutes": COOLDOWN_MINUTES,
        },
        "stats": {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "profit_total": 0.0,
        },
    }


def salveaza_memorie(memorie):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memorie, f, indent=2)


def parseaza_earnings(simbol):
    if simbol not in EARNINGS:
        return None
    try:
        return datetime.fromisoformat(EARNINGS[simbol]).date()
    except ValueError:
        return None


def simbol_in_cooldown(memorie, simbol):
    if simbol not in memorie["cooldown"]:
        return False
    expirare = datetime.fromisoformat(memorie["cooldown"][simbol])
    return datetime.now() < expirare


def noteaza_cooldown(memorie, simbol):
    expirare = datetime.now() + timedelta(minutes=memorie["config"]["cooldown_minutes"])
    memorie["cooldown"][simbol] = expirare.isoformat()


def calculeaza_ema(series, window):
    return series.ewm(span=window, adjust=False).mean()


def calculeaza_rsi(series, window=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/window, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1/window, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace({0: 1e-9})
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculeaza_atr(df, window=14):
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def ajusteaza_strategie(memorie):
    total = memorie["stats"]["trades"]
    if total < 10:
        return memorie

    wr = memorie["stats"]["wins"] / total
    if wr < 0.45:
        memorie["config"]["stop_loss"] = max(0.007, memorie["config"]["stop_loss"] - 0.001)
        memorie["config"]["min_score"] = min(5, memorie["config"]["min_score"] + 1)
        memorie["config"]["volume_ratio"] = max(1.3, memorie["config"]["volume_ratio"] + 0.1)
        print(f"⚠️ Ajustare conservatoare: SL={memorie['config']['stop_loss']:.1%} score>={memorie['config']['min_score']} volum>{memorie['config']['volume_ratio']:.2f}")
    elif wr > 0.60:
        memorie["config"]["stop_loss"] = min(0.013, memorie["config"]["stop_loss"] + 0.001)
        memorie["config"]["min_score"] = max(3, memorie["config"]["min_score"] - 1)
        memorie["config"]["volume_ratio"] = min(1.2, memorie["config"]["volume_ratio"] - 0.05)
        print(f"✅ Ajustare mai puțin conservatoare: SL={memorie['config']['stop_loss']:.1%} score>={memorie['config']['min_score']} volum>{memorie['config']['volume_ratio']:.2f}")
    return memorie


def analizeaza_simbol(simbol, memorie):
    if simbol_in_cooldown(memorie, simbol):
        return None

    earnings_date = parseaza_earnings(simbol)
    if earnings_date is not None:
        zile_pana = (earnings_date - datetime.now().date()).days
        if 0 <= zile_pana <= 2:
            return None

    try:
        df15 = yf.download(simbol, period="7d", interval="15m", progress=False)
        df5 = yf.download(simbol, period="2d", interval="5m", progress=False)
        if df15.empty or df5.empty or len(df15) < 30 or len(df5) < 20:
            return None

        close15 = df15["Close"]
        vol15 = df15["Volume"]
        ema10 = calculeaza_ema(close15, 10)
        ema20 = calculeaza_ema(close15, 20)
        rsi = calculeaza_rsi(close15)
        atr15 = calculeaza_atr(df15)

        if pd.isna(ema10.iloc[-1]) or pd.isna(ema20.iloc[-1]) or pd.isna(rsi.iloc[-1]) or pd.isna(atr15.iloc[-1]):
            return None

        pret = close15.iloc[-1]
        momentum = (pret - close15.iloc[-10]) / close15.iloc[-10]
        volum_ratio = vol15.iloc[-1] / vol15.iloc[-10:].mean() if vol15.iloc[-10:].mean() > 0 else 1.0
        score = 0

        if pret > ema10.iloc[-1] > ema20.iloc[-1]:
            score += 3
        if ema10.iloc[-1] > ema20.iloc[-1] and ema10.iloc[-2] > ema20.iloc[-2]:
            score += 1
        if 45 < rsi.iloc[-1] < 60:
            score += 1
        if momentum > 0.015:
            score += 1
        if volum_ratio >= memorie["config"]["volume_ratio"]:
            score += 1
        if pret > ema20.iloc[-1] and close15.iloc[-2] < ema20.iloc[-2]:
            score += 1

        # Confirmare 5m: breakout și volum local
        ultimele5m = df5.tail(6)
        if len(ultimele5m) >= 4:
            close5 = ultimele5m["Close"]
            high5 = ultimele5m["High"]
            volume5 = ultimele5m["Volume"]
            if close5.iloc[-1] > high5.iloc[-4:-1].max() and volume5.iloc[-1] > volume5.iloc[-4:-1].mean() * 1.1:
                score += 1

        if simbol in memorie["performanta"] and memorie["performanta"][simbol].get("profit_total", 0) > 0:
            score += 1

        return {
            "simbol": simbol,
            "pret": pret,
            "score": score,
            "stop_loss": min(MAX_STOP_LOSS, max(BASE_STOP_LOSS, atr15.iloc[-1] / pret * 0.8)),
            "take_profit": min(0.03, max(0.015, min(0.03, (atr15.iloc[-1] / pret * 0.8) * RISK_REWARD))),
            "momentum": momentum,
            "rsi": float(rsi.iloc[-1]),
            "volum_ratio": float(volum_ratio),
        }
    except Exception:
        return None


def selecteaza_tinte(memorie):
    rezultate = []
    for simbol in SYMBOLS:
        rezultat = analizeaza_simbol(simbol, memorie)
        if rezultat is None:
            continue
        if rezultat["score"] >= memorie["config"]["min_score"]:
            rezultate.append(rezultat)

    rezultate.sort(key=lambda x: (x["score"], x["momentum"], x["volum_ratio"]), reverse=True)
    return rezultate[:MAX_POSITIONS]


def get_pozitii_curente():
    try:
        pozitii = api.list_positions()
        return {p.symbol: float(p.avg_entry_price) for p in pozitii}
    except Exception:
        return {}


def cumpara(simbol, pret, sl, tp, memorie):
    cantitate = int(CAPITAL_PER_POSITION / pret)
    if cantitate < 1:
        return
    try:
        api.submit_order(symbol=simbol, qty=cantitate, side="buy", type="market", time_in_force="gtc")
        print(f"✅ CUMPĂR {cantitate}x {simbol} la {pret:.2f} | SL={sl:.2%} TP={tp:.2%}")
        memorie["tranzactii"].append({
            "simbol": simbol,
            "tip": "buy",
            "pret": pret,
            "cantitate": cantitate,
            "stop_loss": sl,
            "take_profit": tp,
            "data": datetime.now().isoformat(),
        })
        salveaza_memorie(memorie)
    except Exception as e:
        print(f"❌ Eroare cumpără {simbol}: {e}")


def vinde(simbol, qty, pret_intrare, pret_curent, motiv, profit, memorie):
    try:
        api.submit_order(symbol=simbol, qty=qty, side="sell", type="market", time_in_force="gtc")
        print(f"🔴 VÂND {simbol} {qty} la {pret_curent:.2f} | {motiv} | Profit: ${profit:.2f}")

        if simbol not in memorie["performanta"]:
            memorie["performanta"][simbol] = {"profit_total": 0.0, "trades": 0}
        memorie["performanta"][simbol]["profit_total"] += profit
        memorie["performanta"][simbol]["trades"] += 1
        memorie["stats"]["trades"] += 1
        memorie["stats"]["profit_total"] += profit
        if profit > 0:
            memorie["stats"]["wins"] += 1
        else:
            memorie["stats"]["losses"] += 1
            noteaza_cooldown(memorie, simbol)

        memorie["tranzactii"].append({
            "simbol": simbol,
            "tip": "sell",
            "pret": pret_curent,
            "qty": qty,
            "profit": profit,
            "motiv": motiv,
            "data": datetime.now().isoformat(),
        })
        salveaza_memorie(memorie)
    except Exception as e:
        print(f"❌ Eroare vânzare {simbol}: {e}")


def verifica_pozitii(memorie):
    pozitii = get_pozitii_curente()
    for simbol, pret_intrare in pozitii.items():
        try:
            df = yf.download(simbol, period="1d", interval="5m", progress=False)
            if df.empty:
                continue
            pret_curent = float(df["Close"].iloc[-1])
            variatie = (pret_curent - pret_intrare) / pret_intrare
            sl = memorie["config"]["stop_loss"]
            tp = sl * RISK_REWARD

            if variatie <= -sl:
                profit = (pret_curent - pret_intrare) * float(api.get_position(simbol).qty)
                vinde(simbol, int(api.get_position(simbol).qty), pret_intrare, pret_curent, f"STOP LOSS {variatie:.1%}", profit, memorie)
            elif variatie >= tp:
                profit = (pret_curent - pret_intrare) * float(api.get_position(simbol).qty)
                vinde(simbol, int(api.get_position(simbol).qty), pret_intrare, pret_curent, f"TAKE PROFIT {variatie:.1%}", profit, memorie)
        except Exception:
            continue


def agent():
    print("🤖 Short-term learning strategy pornită")
    print(f"📌 Max poziții: {MAX_POSITIONS} | Capital per poziție: ${CAPITAL_PER_POSITION:.0f}")
    memorie = incarca_memorie()
    ciclu = 0

    while True:
        try:
            print("\n" + "=" * 60)
            print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Ciclu {ciclu}")
            memorie = ajusteaza_strategie(memorie)

            clock = api.get_clock()
            if not clock.is_open:
                print(f"❌ Bursa închisă. Următoarea deschidere: {clock.next_open}")
                time.sleep(300)
                continue

            verifica_pozitii(memorie)

            pozitii_curente = get_pozitii_curente()
            locuri_libere = MAX_POSITIONS - len(pozitii_curente)
            if locuri_libere > 0:
                tinte = selecteaza_tinte(memorie)
                for tinta in tinte:
                    if tinta["simbol"] in pozitii_curente:
                        continue
                    if locuri_libere <= 0:
                        break
                    if tinta["score"] < memorie["config"]["min_score"]:
                        continue
                    cumpara(tinta["simbol"], tinta["pret"], tinta["stop_loss"], tinta["take_profit"], memorie)
                    locuri_libere -= 1
            else:
                print(f"📌 Portofoliu complet: {', '.join(pozitii_curente.keys())}")

            ciclu += 1
            print(f"⏳ Pauză {INTERVAL}s înainte de următorul ciclu")
            time.sleep(INTERVAL)
        except Exception as e:
            print(f"❌ Eroare agent: {e}")
            time.sleep(30)


if __name__ == "__main__":
    agent()
