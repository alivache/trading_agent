import yfinance as yf
import alpaca_trade_api as tradeapi
import os
import json
import time
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from datetime import datetime, timezone
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import joblib
import warnings
warnings.filterwarnings('ignore')

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
MEMORIE_FILE = "memorie_level3.json"
MODEL_FILE = "model_trading.pkl"
SCALER_FILE = "scaler_trading.pkl"
MIN_SAMPLES_ANTRENARE = 20  # Minim trades înainte să folosim ML

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
        "features_history": [],  # Date pentru antrenare ML
        "performanta": {},
        "stats": {"total_profit": 0, "wins": 0, "losses": 0},
        "model_stats": {"antrenat": False, "accuracy": 0, "samples": 0}
    }

def salveaza_memorie(memorie):
    with open(MEMORIE_FILE, 'w') as f:
        json.dump(memorie, f, indent=2, default=str)

def log_tranzactie(memorie, simbol, tip, pret, cantitate,
                   features=None, profit=None, motiv=None):
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

    # Salvează features pentru antrenare ML
    if features and profit is not None:
        memorie["features_history"].append({
            "features": features,
            "rezultat": 1 if profit > 0 else 0  # 1=win, 0=loss
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
# MACHINE LEARNING
# ═══════════════════════════════════════
def extrage_features(simbol, df, vwap, ema8, rsi3):
    """
    Extrage toate caracteristicile relevante pentru ML
    Acestea sunt inputurile pe care modelul le va folosi
    """
    preturi = df['Close'].tolist()
    volume = df['Volume'].tolist()
    pret_curent = preturi[-1]

    # Indicatori de bază
    distanta_vwap = (pret_curent - vwap) / vwap
    distanta_ema8 = (pret_curent - ema8) / ema8

    # Momentum pe diferite perioade
    momentum_5 = (preturi[-1] - preturi[-6]) / preturi[-6] if len(preturi) >= 6 else 0
    momentum_10 = (preturi[-1] - preturi[-11]) / preturi[-11] if len(preturi) >= 11 else 0
    momentum_20 = (preturi[-1] - preturi[-21]) / preturi[-21] if len(preturi) >= 21 else 0

    # Volatilitate
    ret = pd.Series(preturi[-20:]).pct_change().dropna()
    volatilitate = ret.std() if len(ret) > 0 else 0

    # Volum relativ
    vol_recent = sum(volume[-3:]) / 3 if len(volume) >= 3 else volume[-1]
    vol_mediu = sum(volume[-20:]) / 20 if len(volume) >= 20 else volume[-1]
    volum_ratio = vol_recent / vol_mediu if vol_mediu > 0 else 1

    # Poziție în intervalul zilnic
    high_zi = max(df['High'].tolist()[-50:]) if len(df) >= 50 else max(df['High'].tolist())
    low_zi = min(df['Low'].tolist()[-50:]) if len(df) >= 50 else min(df['Low'].tolist())
    pozitie_zi = (pret_curent - low_zi) / (high_zi - low_zi) if high_zi != low_zi else 0.5

    # Ora din zi (pattern-uri temporale)
    ora = datetime.now().hour
    ora_normalizata = ora / 24.0

    return [
        rsi3 / 100,           # RSI normalizat
        distanta_vwap,        # Distanța față de VWAP
        distanta_ema8,        # Distanța față de EMA8
        momentum_5,           # Momentum 5 perioade
        momentum_10,          # Momentum 10 perioade
        momentum_20,          # Momentum 20 perioade
        volatilitate,         # Volatilitate
        volum_ratio,          # Raport volum
        pozitie_zi,           # Poziție în intervalul zilnic
        ora_normalizata       # Ora din zi
    ]

def antreneaza_model(memorie):
    """Antrenează Random Forest pe datele acumulate"""
    history = memorie["features_history"]

    if len(history) < MIN_SAMPLES_ANTRENARE:
        print(f"  🧠 ML: {len(history)}/{MIN_SAMPLES_ANTRENARE} samples pentru antrenare")
        return None, None

    X = [h["features"] for h in history]
    y = [h["rezultat"] for h in history]

    X = np.array(X)
    y = np.array(y)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=5,
        random_state=42,
        class_weight='balanced'
    )
    model.fit(X_scaled, y)

    # Calculează accuracy pe datele de antrenare
    accuracy = model.score(X_scaled, y)

    # Salvează modelul
    joblib.dump(model, MODEL_FILE)
    joblib.dump(scaler, SCALER_FILE)

    memorie["model_stats"]["antrenat"] = True
    memorie["model_stats"]["accuracy"] = accuracy
    memorie["model_stats"]["samples"] = len(history)
    salveaza_memorie(memorie)

    print(f"  🧠 Model antrenat! Accuracy={accuracy:.1%} | Samples={len(history)}")
    return model, scaler

def incarca_model():
    """Încearcă să încarce modelul salvat"""
    if os.path.exists(MODEL_FILE) and os.path.exists(SCALER_FILE):
        try:
            model = joblib.load(MODEL_FILE)
            scaler = joblib.load(SCALER_FILE)
            return model, scaler
        except:
            return None, None
    return None, None

def predict_succes(model, scaler, features):
    """
    Returnează probabilitatea că tranzacția va fi profitabilă
    """
    if model is None or scaler is None:
        return 0.5  # Fără model — probabilitate neutră

    try:
        X = np.array(features).reshape(1, -1)
        X_scaled = scaler.transform(X)
        proba = model.predict_proba(X_scaled)[0][1]  # Probabilitate win
        return proba
    except:
        return 0.5

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
    df = yf.download(simbol, period="2d", interval="5m", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

# ═══════════════════════════════════════
# SEMNAL STRATEGIE + ML
# ═══════════════════════════════════════
def analizeaza_semnal(simbol, memorie, model, scaler):
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

        # Extrage features pentru ML
        features = extrage_features(simbol, df, vwap, ema8, rsi3)
        probabilitate_ml = predict_succes(model, scaler, features)

        info = {
            "pret": pret_curent,
            "ema8": ema8,
            "rsi3": rsi3,
            "vwap": vwap,
            "distanta_vwap": distanta_vwap,
            "probabilitate_ml": probabilitate_ml,
            "features": features
        }

        # Filtru distanță VWAP
        if distanta_vwap > MAX_DISTANTA_VWAP:
            return None, info

        semnal_tehnic = None

        # LONG
        if (pret_curent > vwap and pret_curent > ema8 and rsi3 < 30):
            semnal_tehnic = "long"

        # SHORT
        if (pret_curent < vwap and pret_curent < ema8 and rsi3 > 70):
            semnal_tehnic = "short"

        if semnal_tehnic is None:
            return None, info

        # ── FILTRU ML: dacă avem model, cere confirmare
        if model is not None:
            prag_ml = 0.55  # Minim 55% probabilitate de succes
            if probabilitate_ml < prag_ml:
                print(f"  🧠 {simbol}: semnal {semnal_tehnic} RESPINS de ML "
                      f"(prob={probabilitate_ml:.0%} < {prag_ml:.0%})")
                return None, info
            else:
                print(f"  🧠 {simbol}: semnal {semnal_tehnic} CONFIRMAT de ML "
                      f"(prob={probabilitate_ml:.0%})")

        return semnal_tehnic, info

    except Exception as e:
        print(f"  ❌ Eroare analiză {simbol}: {e}")
        return None, {}

# ═══════════════════════════════════════
# VERIFICARE EXIT
# ═══════════════════════════════════════
def verifica_exit(simbol, pret_intrare, directie):
    try:
        df = get_date(simbol)
        if df.empty:
            return False, None

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
    except:
        return False, None

# ═══════════════════════════════════════
# TRANZACȚIONARE
# ═══════════════════════════════════════
def deschide_pozitie(simbol, directie, pret, cantitate, features, memorie):
    global trades_azi
    try:
        side = 'buy' if directie == 'long' else 'sell'
        api.submit_order(
            symbol=simbol, qty=cantitate,
            side=side, type='market', time_in_force='gtc'
        )
        emoji = "✅" if directie == "long" else "🔻"
        print(f"  {emoji} {directie.upper()} {cantitate}x {simbol} @ ${pret:.2f}")

        pozitii_deschise[simbol] = {
            "directie": directie,
            "pret_intrare": pret,
            "cantitate": cantitate,
            "features": features
        }
        trades_azi += 1
        log_tranzactie(memorie, simbol, f"open_{directie}", pret, cantitate)

    except Exception as e:
        print(f"  ❌ Eroare deschidere {simbol}: {e}")

def inchide_pozitie(simbol, motiv, memorie):
    if simbol not in pozitii_deschise:
        return
    pozitie = pozitii_deschise[simbol]
    try:
        df = get_date(simbol)
        pret_curent = df['Close'].iloc[-1]

        if pozitie["directie"] == "long":
            api.submit_order(symbol=simbol, qty=pozitie["cantitate"],
                             side='sell', type='market', time_in_force='gtc')
            profit = (pret_curent - pozitie["pret_intrare"]) * pozitie["cantitate"]
        else:
            api.submit_order(symbol=simbol, qty=pozitie["cantitate"],
                             side='buy', type='market', time_in_force='gtc')
            profit = (pozitie["pret_intrare"] - pret_curent) * pozitie["cantitate"]

        emoji = "🟢" if profit > 0 else "🔴"
        print(f"  {emoji} ÎNCHIS {simbol} | {motiv} | Profit: ${profit:.2f}")

        # Salvează features + rezultat pentru antrenare ML
        log_tranzactie(memorie, simbol, f"close_{pozitie['directie']}",
                       pret_curent, pozitie["cantitate"],
                       features=pozitie.get("features"),
                       profit=profit, motiv=motiv)

        del pozitii_deschise[simbol]

    except Exception as e:
        print(f"  ❌ Eroare închidere {simbol}: {e}")

# ═══════════════════════════════════════
# DISPLAY
# ═══════════════════════════════════════
def afiseaza_stats(memorie):
    stats = memorie["stats"]
    total = stats["wins"] + stats["losses"]
    rata = stats["wins"] / total if total > 0 else 0
    model_stats = memorie["model_stats"]

    print(f"\n📊 STATS: Profit=${stats['total_profit']:.2f} | "
          f"Win rate={rata:.1%} | Trades={total}")

    if model_stats["antrenat"]:
        print(f"🧠 MODEL: Accuracy={model_stats['accuracy']:.1%} | "
              f"Samples={model_stats['samples']}")
    else:
        samples = len(memorie["features_history"])
        print(f"🧠 MODEL: Se acumulează date... "
              f"{samples}/{MIN_SAMPLES_ANTRENARE} samples")

# ═══════════════════════════════════════
# AGENT PRINCIPAL
# ═══════════════════════════════════════
def agent():
    global trades_azi, data_curenta

    print("🤖 VWAP + RSI(3) + EMA(8) — Nivel 3 Machine Learning")
    print(f"💰 Max trade: ${MAX_TRADE_SIZE_USD} | Max trades/zi: {MAX_TRADES_PER_DAY}")
    print(f"🧠 Min samples pentru ML: {MIN_SAMPLES_ANTRENARE}")
    print("-" * 50)

    memorie = incarca_memorie()
    model, scaler = incarca_model()

    if model:
        print(f"✅ Model ML încărcat din fișier!")
    else:
        print(f"⏳ Fără model ML — se acumulează date...")

    ciclu = 0
    antrenare_ciclu = 10  # Reantrenează la fiecare 10 cicluri

    while True:
        try:
            if datetime.now().date() != data_curenta:
                data_curenta = datetime.now().date()
                trades_azi = 0
                print("🔄 Zi nouă — reset counter")

            print(f"\n⏰ {datetime.now().strftime('%H:%M:%S')} | "
                  f"Ciclu #{ciclu} | "
                  f"Trades azi: {trades_azi}/{MAX_TRADES_PER_DAY} | "
                  f"Poziții: {len(pozitii_deschise)}")

            clock = api.get_clock()
            if not clock.is_open:
                print(f"❌ Bursa închisă. Se deschide la: {clock.next_open}")
                time.sleep(300)
                continue

            # ── REANTRENEAZĂ MODELUL periodic
            if ciclu % antrenare_ciclu == 0 and ciclu > 0:
                print("\n🧠 Reantrenez modelul ML...")
                model, scaler = antreneaza_model(memorie)

            # ── EXIT poziții deschise
            for simbol in list(pozitii_deschise.keys()):
                poz = pozitii_deschise[simbol]
                exit_acum, motiv = verifica_exit(
                    simbol, poz["pret_intrare"], poz["directie"]
                )
                if exit_acum:
                    inchide_pozitie(simbol, motiv, memorie)

            # ── CAUTĂ NOI INTRĂRI
            if trades_azi < MAX_TRADES_PER_DAY:
                print(f"\n🔍 Scanez {len(ACTIUNI)} acțiuni...")

                # Sortează acțiunile după probabilitate ML dacă avem model
                candidati = []
                for simbol in ACTIUNI:
                    if simbol in pozitii_deschise:
                        continue

                    semnal, info = analizeaza_semnal(simbol, memorie, model, scaler)

                    if info:
                        prob = info.get("probabilitate_ml", 0.5)
                        print(f"  {simbol}: P=${info.get('pret', 0):.2f} | "
                              f"RSI={info.get('rsi3', 0):.1f} | "
                              f"ML={prob:.0%} | "
                              f"Semnal={'🟢 LONG' if semnal == 'long' else '🔴 SHORT' if semnal == 'short' else '⏳ none'}")

                    if semnal:
                        candidati.append((simbol, semnal, info))

                # Sortează după probabilitate ML — cele mai sigure primul
                candidati.sort(key=lambda x: x[2].get("probabilitate_ml", 0.5), reverse=True)

                for simbol, semnal, info in candidati:
                    if trades_azi >= MAX_TRADES_PER_DAY:
                        break
                    cantitate = int(MAX_TRADE_SIZE_USD / info["pret"])
                    if cantitate >= 1:
                        deschide_pozitie(simbol, semnal, info["pret"],
                                        cantitate, info.get("features"), memorie)

            afiseaza_stats(memorie)
            ciclu += 1
            time.sleep(INTERVAL_SCANARE)

        except Exception as e:
            print(f"❌ Eroare generală: {e}")
            time.sleep(30)

def start():
    clock = api.get_clock()
    if clock.is_open:
        print("✅ Bursa DESCHISĂ!")
        agent()
    else:
        print(f"❌ Bursa ÎNCHISĂ — se deschide la: {clock.next_open}")
        if input("Pornesc și aștept? (da/nu): ").lower() == "da":
            agent()

start()