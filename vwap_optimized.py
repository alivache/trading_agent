import yfinance as yf
import alpaca_trade_api as tradeapi
import os
import json
import time
import csv
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from datetime import datetime, timezone, date

load_dotenv()

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL")
MAX_TRADE_SIZE_USD = float(os.getenv("MAX_TRADE_SIZE_USD", 1000))
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", 10))

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL)

# ═══════════════════════════════════════
# SETARI
# ═══════════════════════════════════════
ACTIUNI = [
    "AAPL", "MSFT", "NVDA", "AMD", "TSLA",
    "GOOGL", "META", "AMZN", "NFLX", "COIN"
]
INTERVAL_SCANARE = 60
MEMORIE_FILE = "memorie_optimized.json"

STOP_LOSS_PCT = 0.003
TRAILING_STOP_PCT = 0.002
TAKE_PROFIT_PCT = 0.006
MAX_DISTANTA_VWAP = 0.015
MAX_RISC_PORTOFOLIU = 0.01
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
MIN_VOLUM_RATIO = 1.0        # relaxat de la 1.2
MIN_MOMENTUM = 0.0005        # relaxat de la 0.001
CONFIRMARE_CANDLE = False    # dezactivat temporar

trades_azi = 0
data_curenta = datetime.now().date()
pozitii_deschise = {}
raport_generat_azi = False


# ═══════════════════════════════════════
# MEMORIE
# ═══════════════════════════════════════
def incarca_memorie():
    if os.path.exists(MEMORIE_FILE):
        with open(MEMORIE_FILE, "r") as f:
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
    with open(MEMORIE_FILE, "w") as f:
        json.dump(memorie, f, indent=2, default=str)


def log_tranzactie(memorie, simbol, tip, pret, cantitate, profit=None, motiv=None):
    memorie["tranzactii"].append({
        "simbol": simbol,
        "tip": tip,
        "pret": pret,
        "cantitate": cantitate,
        "profit": profit,
        "motiv": motiv,
        "ora": datetime.now().hour,
        "data": datetime.now().isoformat()
    })

    if profit is not None:
        memorie["stats"]["total_profit"] += profit
        if profit > 0:
            memorie["stats"]["wins"] += 1
        else:
            memorie["stats"]["losses"] += 1

        if simbol not in memorie["performanta"]:
            memorie["performanta"][simbol] = {
                "profit": 0, "trades": 0, "wins": 0,
                "max_profit": 0, "max_pierdere": 0
            }
        p = memorie["performanta"][simbol]
        p["profit"] += profit
        p["trades"] += 1
        if profit > 0:
            p["wins"] += 1
            p["max_profit"] = max(p["max_profit"], profit)
        else:
            p["max_pierdere"] = min(p["max_pierdere"], profit)

    salveaza_memorie(memorie)


# ═══════════════════════════════════════
# EXPORT CSV + RAPORT AUTOMAT
# ═══════════════════════════════════════
def export_csv_automat(memorie):
    tranzactii = memorie["tranzactii"]
    azi = date.today().isoformat()

    inchideri = [
        t for t in tranzactii
        if t["tip"].startswith("close")
        and t.get("profit") is not None
        and t["data"].startswith(azi)
    ]

    if not inchideri:
        print("📊 Nicio tranzactie de exportat azi.")
        return

    CSV_FILE = f"trades_{azi}.csv"
    campuri = [
        "data_intrare", "data_iesire", "simbol", "directie",
        "cantitate", "pret_intrare", "pret_iesire",
        "profit_usd", "profit_pct", "motiv_exit", "ora", "rezultat"
    ]

    rows = []
    for t in inchideri:
        simbol = t["simbol"]
        directie = t["tip"].replace("close_", "")
        pret_intrare = 0

        for d in reversed(tranzactii):
            if d["simbol"] == simbol and d["tip"] == f"open_{directie}":
                if d["data"] < t["data"]:
                    pret_intrare = d["pret"]
                    break

        profit = t["profit"]
        profit_pct = (
            (profit / (pret_intrare * t["cantitate"]) * 100)
            if pret_intrare > 0 else 0
        )

        rows.append({
            "data_intrare": "N/A",
            "data_iesire": t["data"],
            "simbol": simbol,
            "directie": directie.upper(),
            "cantitate": t["cantitate"],
            "pret_intrare": round(pret_intrare, 4),
            "pret_iesire": round(t["pret"], 4),
            "profit_usd": round(profit, 2),
            "profit_pct": round(profit_pct, 2),
            "motiv_exit": t.get("motiv", ""),
            "ora": t.get("ora", ""),
            "rezultat": "WIN" if profit > 0 else "LOSS"
        })

    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campuri)
        writer.writeheader()
        writer.writerows(rows)

    wins = [r for r in rows if r["rezultat"] == "WIN"]
    losses = [r for r in rows if r["rezultat"] == "LOSS"]
    profit_total = sum(r["profit_usd"] for r in rows)
    win_rate = len(wins) / len(rows) if rows else 0

    print(f"\n{'=' * 50}")
    print(f"📊 RAPORT ZILNIC — {azi}")
    print(f"{'=' * 50}")
    print(f"  🔄 Total trades:  {len(rows)}")
    print(f"  ✅ Wins:          {len(wins)}")
    print(f"  ❌ Losses:        {len(losses)}")
    print(f"  🎯 Win rate:      {win_rate:.1%}")
    print(f"  💰 Profit total:  ${profit_total:.2f}")

    if wins:
        best = max(wins, key=lambda x: x["profit_usd"])
        print(f"  🏆 Cel mai bun:   {best['simbol']} ${best['profit_usd']} ({best['profit_pct']}%)")
    if losses:
        worst = min(losses, key=lambda x: x["profit_usd"])
        print(f"  💀 Cel mai prost: {worst['simbol']} ${worst['profit_usd']} ({worst['profit_pct']}%)")

    print(f"  💾 CSV salvat:    {CSV_FILE}")
    print(f"{'=' * 50}\n")


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
        df.index = df.index.tz_localize("UTC")
    df_azi = df[df.index.date == azi]
    if df_azi.empty:
        df_azi = df
    typical_price = (df_azi["High"] + df_azi["Low"] + df_azi["Close"]) / 3
    vwap = (typical_price * df_azi["Volume"]).cumsum() / df_azi["Volume"].cumsum()
    return vwap.iloc[-1]


def calculeaza_atr(df, perioada=14):
    high = df["High"]
    low = df["Low"]
    close = df["Close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - close).abs(),
        (low - close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(perioada).mean().iloc[-1]


def calculeaza_volum_ratio(volume):
    if len(volume) < 20:
        return 1.0
    vol_recent = sum(volume[-3:]) / 3
    vol_mediu = sum(volume[-20:]) / 20
    return vol_recent / vol_mediu if vol_mediu > 0 else 1.0


def get_date(simbol):
    df = yf.download(simbol, period="2d", interval="5m", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


# ═══════════════════════════════════════
# FILTRE INTRARE — relaxate
# ═══════════════════════════════════════
def verifica_filtre_intrare(df, pret_curent, vwap, ema8, rsi3, directie):
    preturi = df["Close"].tolist()
    volume = df["Volume"].tolist()
    motive_respingere = []

    # Filtru 1: Volum relaxat
    volum_ratio = calculeaza_volum_ratio(volume)
    if volum_ratio < MIN_VOLUM_RATIO:
        motive_respingere.append(f"volum scazut ({volum_ratio:.1f}x)")

    # Filtru 2: Momentum relaxat
    if len(preturi) >= 6:
        momentum = (preturi[-1] - preturi[-6]) / preturi[-6]
        if directie == "long" and momentum < -MIN_MOMENTUM:
            motive_respingere.append(f"momentum negativ ({momentum:.2%})")
        elif directie == "short" and momentum > MIN_MOMENTUM:
            motive_respingere.append(f"momentum pozitiv ({momentum:.2%})")

    # Filtru 3: Confirmare candle — dezactivat
    if CONFIRMARE_CANDLE and len(preturi) >= 2:
        ultima_lumanare = preturi[-1] - preturi[-2]
        if directie == "long" and ultima_lumanare < 0:
            motive_respingere.append("ultima lumanare bearish")
        elif directie == "short" and ultima_lumanare > 0:
            motive_respingere.append("ultima lumanare bullish")

    # Filtru 4: Evita primele 30 min
    ora_ro = datetime.now().hour
    minut = datetime.now().minute
    if ora_ro == 16 and minut < 30:
        motive_respingere.append("primele 30 min de bursa")

    # Filtru 5: Trend pe 2 candle-uri (relaxat de la 3)
    if len(preturi) >= 3:
        if directie == "long":
            trend_ok = all(preturi[-i] > preturi[-i - 1] for i in range(1, 2))
            if not trend_ok:
                motive_respingere.append("trend inconsistent")
        elif directie == "short":
            trend_ok = all(preturi[-i] < preturi[-i - 1] for i in range(1, 2))
            if not trend_ok:
                motive_respingere.append("trend inconsistent")

    return motive_respingere


# ═══════════════════════════════════════
# CALCUL CANTITATE
# ═══════════════════════════════════════
def calculeaza_cantitate(pret, atr):
    try:
        account = api.get_account()
        portofoliu = float(account.portfolio_value)
    except:
        portofoliu = 100000

    risc_max = portofoliu * MAX_RISC_PORTOFOLIU
    stop_loss_dinamic = max(STOP_LOSS_PCT, atr / pret * 1.5)
    cantitate_risc = int(risc_max / (pret * stop_loss_dinamic))
    cantitate_size = int(MAX_TRADE_SIZE_USD / pret)
    cantitate = min(cantitate_risc, cantitate_size)
    return max(1, cantitate), stop_loss_dinamic


# ═══════════════════════════════════════
# SEMNAL STRATEGIE
# ═══════════════════════════════════════
def analizeaza_semnal(simbol):
    try:
        df = get_date(simbol)
        if df.empty or len(df) < 20:
            return None, {}

        preturi_close = df["Close"].tolist()
        pret_curent = preturi_close[-1]

        ema8 = calculeaza_ema(preturi_close, 8)
        rsi3 = calculeaza_rsi(preturi_close, 3)
        vwap = calculeaza_vwap(df)
        atr = calculeaza_atr(df)
        distanta_vwap = abs(pret_curent - vwap) / vwap

        info = {
            "pret": pret_curent,
            "ema8": ema8,
            "rsi3": rsi3,
            "vwap": vwap,
            "atr": atr,
            "distanta_vwap": distanta_vwap,
            "df": df
        }

        if distanta_vwap > MAX_DISTANTA_VWAP:
            return None, info

        semnal = None
        if pret_curent > vwap and pret_curent > ema8 and rsi3 < RSI_OVERSOLD:
            semnal = "long"
        # elif pret_curent < vwap and pret_curent < ema8 and rsi3 > RSI_OVERBOUGHT:
        #     semnal = "short"

        if semnal is None:
            return None, info

        motive_respingere = verifica_filtre_intrare(
            df, pret_curent, vwap, ema8, rsi3, semnal
        )

        if motive_respingere:
            print(f"  RESPINS {simbol}: {', '.join(motive_respingere)}")
            return None, info

        return semnal, info

    except Exception as e:
        print(f"  Eroare analiza {simbol}: {e}")
        return None, {}


# ═══════════════════════════════════════
# EXIT INTELIGENT
# ═══════════════════════════════════════
def verifica_exit(simbol, pret_intrare, directie, pret_max, stop_loss_dinamic):
    try:
        df = get_date(simbol)
        if df.empty:
            return False, None, pret_max

        preturi = df["Close"].tolist()
        pret_curent = preturi[-1]
        rsi3 = calculeaza_rsi(preturi, 3)
        ema8 = calculeaza_ema(preturi, 8)
        vwap = calculeaza_vwap(df)
        variatie = (pret_curent - pret_intrare) / pret_intrare

        if directie == "long":
            pret_max = max(pret_max, pret_curent)
            drawdown = (pret_max - pret_curent) / pret_max

            if drawdown >= TRAILING_STOP_PCT and pret_curent > pret_intrare:
                return True, f"TRAILING STOP (profit={variatie:.2%})", pret_max
            if variatie <= -stop_loss_dinamic:
                return True, f"STOP LOSS ({variatie:.2%})", pret_max
            if variatie >= TAKE_PROFIT_PCT:
                return True, f"TAKE PROFIT ({variatie:.2%})", pret_max
            if rsi3 > 50:
                return True, f"RSI CROSS 50 ({rsi3:.1f})", pret_max
            if pret_curent < vwap * 0.999:
                return True, f"VWAP SPART ({variatie:.2%})", pret_max
            if pret_curent < ema8 * 0.999:
                return True, f"EMA8 SPART ({variatie:.2%})", pret_max

        elif directie == "short":
            pret_max = min(pret_max, pret_curent)
            drawdown = (pret_curent - pret_max) / abs(pret_max)

            if drawdown >= TRAILING_STOP_PCT and pret_curent < pret_intrare:
                return True, f"TRAILING STOP (profit={abs(variatie):.2%})", pret_max
            if variatie >= stop_loss_dinamic:
                return True, f"STOP LOSS ({variatie:.2%})", pret_max
            if variatie <= -TAKE_PROFIT_PCT:
                return True, f"TAKE PROFIT ({abs(variatie):.2%})", pret_max
            if rsi3 < 50:
                return True, f"RSI CROSS 50 ({rsi3:.1f})", pret_max
            if pret_curent > vwap * 1.001:
                return True, f"VWAP SPART ({variatie:.2%})", pret_max
            if pret_curent > ema8 * 1.001:
                return True, f"EMA8 SPART ({variatie:.2%})", pret_max

        return False, None, pret_max

    except Exception as e:
        return False, None, pret_max


# ═══════════════════════════════════════
# TRANZACTIONARE
# ═══════════════════════════════════════
def deschide_pozitie(simbol, directie, pret, cantitate, stop_loss_dinamic, memorie):
    global trades_azi
    try:
        side = "buy" if directie == "long" else "sell"
        api.submit_order(
            symbol=simbol, qty=cantitate,
            side=side, type="market", time_in_force="gtc"
        )
        emoji = "✅" if directie == "long" else "🔻"
        print(f"  {emoji} {directie.upper()} {cantitate}x {simbol} @ ${pret:.2f} | SL={stop_loss_dinamic:.2%}")

        pozitii_deschise[simbol] = {
            "directie": directie,
            "pret_intrare": pret,
            "cantitate": cantitate,
            "pret_max": pret,
            "stop_loss_dinamic": stop_loss_dinamic
        }
        trades_azi += 1
        log_tranzactie(memorie, simbol, f"open_{directie}", pret, cantitate)

    except Exception as e:
        print(f"  Eroare deschidere {simbol}: {e}")


def inchide_pozitie(simbol, motiv, memorie):
    if simbol not in pozitii_deschise:
        return
    pozitie = pozitii_deschise[simbol]
    try:
        df = get_date(simbol)
        pret_curent = df["Close"].iloc[-1]

        if pozitie["directie"] == "long":
            api.submit_order(
                symbol=simbol, qty=pozitie["cantitate"],
                side="sell", type="market", time_in_force="gtc"
            )
            profit = (pret_curent - pozitie["pret_intrare"]) * pozitie["cantitate"]
        else:
            api.submit_order(
                symbol=simbol, qty=pozitie["cantitate"],
                side="buy", type="market", time_in_force="gtc"
            )
            profit = (pozitie["pret_intrare"] - pret_curent) * pozitie["cantitate"]

        emoji = "🟢" if profit > 0 else "🔴"
        print(f"  {emoji} INCHIS {simbol} | {motiv} | Profit: ${profit:.2f}")
        log_tranzactie(
            memorie, simbol, f"close_{pozitie['directie']}",
            pret_curent, pozitie["cantitate"], profit, motiv
        )
        del pozitii_deschise[simbol]

    except Exception as e:
        print(f"  Eroare inchidere {simbol}: {e}")


# ═══════════════════════════════════════
# DISPLAY
# ═══════════════════════════════════════
def afiseaza_stats(memorie):
    stats = memorie["stats"]
    total = stats["wins"] + stats["losses"]
    rata = stats["wins"] / total if total > 0 else 0
    print(f"\n📊 STATS: Profit=${stats['total_profit']:.2f} | "
          f"Win rate={rata:.1%} | Trades={total}")


def afiseaza_pozitii():
    if not pozitii_deschise:
        return
    print("\n📂 POZITII DESCHISE:")
    for simbol, poz in pozitii_deschise.items():
        variatie = 0
        try:
            df = get_date(simbol)
            pret_curent = df["Close"].iloc[-1]
            variatie = (pret_curent - poz["pret_intrare"]) / poz["pret_intrare"]
            if poz["directie"] == "short":
                variatie = -variatie
        except:
            pass
        emoji = "🟢" if variatie > 0 else "🔴"
        print(f"  {emoji} {simbol} {poz['directie'].upper()} | "
              f"Intrare=${poz['pret_intrare']:.2f} | "
              f"P&L={variatie:.2%}")


# ═══════════════════════════════════════
# AGENT PRINCIPAL
# ═══════════════════════════════════════
def agent():
    global trades_azi, data_curenta, raport_generat_azi

    print("🤖 VWAP + RSI(3) + EMA(8) — Strategie Optimizata")
    print(f"💰 Max trade: ${MAX_TRADE_SIZE_USD} | Max trades/zi: {MAX_TRADES_PER_DAY}")
    print(f"🛑 SL={STOP_LOSS_PCT:.1%} | Trailing={TRAILING_STOP_PCT:.1%} | TP={TAKE_PROFIT_PCT:.1%}")
    print(f"🔍 Filtre: Volum>{MIN_VOLUM_RATIO}x | Momentum>{MIN_MOMENTUM:.2%} | Candle={CONFIRMARE_CANDLE}")
    print("-" * 60)

    memorie = incarca_memorie()
    ciclu = 0

    while True:
        try:
            if datetime.now().date() != data_curenta:
                data_curenta = datetime.now().date()
                trades_azi = 0
                raport_generat_azi = False
                print("🔄 Zi noua — reset counter")

            print(f"\n⏰ {datetime.now().strftime('%H:%M:%S')} | "
                  f"Ciclu #{ciclu} | "
                  f"Trades azi: {trades_azi}/{MAX_TRADES_PER_DAY} | "
                  f"Pozitii: {len(pozitii_deschise)}")

            clock = api.get_clock()
            if not clock.is_open:
                ora_acum = datetime.now().hour
                minut_acum = datetime.now().minute
                if ora_acum == 23 and minut_acum < 5 and not raport_generat_azi:
                    print("🔔 Bursa s-a inchis — generez raport si CSV automat...")
                    export_csv_automat(memorie)
                    raport_generat_azi = True

                print(f"❌ Bursa inchisa. Se deschide la: {clock.next_open}")
                time.sleep(300)
                continue

            # EXIT pozitii deschise
            for simbol in list(pozitii_deschise.keys()):
                poz = pozitii_deschise[simbol]
                exit_acum, motiv, pret_max_nou = verifica_exit(
                    simbol,
                    poz["pret_intrare"],
                    poz["directie"],
                    poz["pret_max"],
                    poz["stop_loss_dinamic"]
                )
                pozitii_deschise[simbol]["pret_max"] = pret_max_nou
                if exit_acum:
                    inchide_pozitie(simbol, motiv, memorie)

            # CAUTA NOI INTRARI
            if trades_azi < MAX_TRADES_PER_DAY:
                print(f"\n🔍 Scanez {len(ACTIUNI)} actiuni...")

                for simbol in ACTIUNI:
                    if simbol in pozitii_deschise:
                        continue

                    semnal, info = analizeaza_semnal(simbol)

                    if info and "rsi3" in info:
                        print(f"  {simbol}: P=${info.get('pret', 0):.2f} | "
                              f"RSI={info.get('rsi3', 0):.1f} | "
                              f"VWAP=${info.get('vwap', 0):.2f} | "
                              f"Semnal={'🟢 LONG' if semnal == 'long' else '🔴 SHORT' if semnal == 'short' else '⏳ none'}")

                    if semnal and trades_azi < MAX_TRADES_PER_DAY:
                        cantitate, stop_loss_dinamic = calculeaza_cantitate(
                            info["pret"], info["atr"]
                        )
                        deschide_pozitie(
                            simbol, semnal, info["pret"],
                            cantitate, stop_loss_dinamic, memorie
                        )

            afiseaza_pozitii()
            afiseaza_stats(memorie)

            ciclu += 1
            time.sleep(INTERVAL_SCANARE)

        except Exception as e:
            print(f"❌ Eroare generala: {e}")
            time.sleep(30)


# ═══════════════════════════════════════
# START
# ═══════════════════════════════════════
def start():
    clock = api.get_clock()
    if clock.is_open:
        print("✅ Bursa DESCHISA!")
        agent()
    else:
        print(f"❌ Bursa INCHISA — se deschide la: {clock.next_open}")
        if input("Pornesc si astept? (da/nu): ").lower() == "da":
            agent()


start()