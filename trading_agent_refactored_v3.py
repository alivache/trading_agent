import os
import time
import logging
from datetime import datetime
from typing import Optional

import alpaca_trade_api as tradeapi
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

SYMBOL = os.getenv("TRADING_SYMBOL", "AAPL")
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")
RISK_PERCENT = float(os.getenv("TRADE_RISK_PERCENT", "0.01"))
MAX_TRADE_SIZE_USD = float(os.getenv("MAX_TRADE_SIZE_USD", "2500"))
SHORT_EMA = int(os.getenv("SHORT_EMA", "12"))
LONG_EMA = int(os.getenv("LONG_EMA", "26"))
TREND_EMA = int(os.getenv("TREND_EMA", "50"))
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))
STOP_ATR = float(os.getenv("STOP_ATR", "2.0"))
TARGET_ATR = float(os.getenv("TARGET_ATR", "4.0"))
INTERVAL_SECONDS = int(os.getenv("TRADING_INTERVAL", "30"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("trading_agent_refactored_v3.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def create_api_client() -> tradeapi.REST:
    if not all([API_KEY, SECRET_KEY, BASE_URL]):
        raise EnvironmentError("Missing Alpaca credentials in environment.")
    return tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version="v2")


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EMA_SHORT"] = df["Close"].ewm(span=SHORT_EMA, adjust=False).mean()
    df["EMA_LONG"] = df["Close"].ewm(span=LONG_EMA, adjust=False).mean()
    df["EMA_TREND"] = df["Close"].ewm(span=TREND_EMA, adjust=False).mean()
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    df["RSI"] = 100 - 100 / (1 + rs)
    macd = df["Close"].ewm(span=12, adjust=False).mean() - df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = macd
    df["MACD_SIGNAL"] = macd.ewm(span=9, adjust=False).mean()
    high_low = pd.concat([df["High"] - df["Low"], (df["High"] - df["Close"].shift(1)).abs(), (df["Low"] - df["Close"].shift(1)).abs()], axis=1)
    df["ATR"] = high_low.max(axis=1).rolling(ATR_PERIOD).mean()
    df["TREND_OK"] = df["Close"] > df["EMA_TREND"]
    df["BUY_SIGNAL"] = (
        df["TREND_OK"]
        & (df["EMA_SHORT"] > df["EMA_LONG"])
        & (df["MACD"] > df["MACD_SIGNAL"])
        & df["RSI"].between(42, 68)
    )
    df["SELL_SIGNAL"] = (
        (df["EMA_SHORT"] < df["EMA_LONG"]) | (df["MACD"] < df["MACD_SIGNAL"]) | (df["RSI"] > 75)
    )
    return df


def get_latest_bars(api: tradeapi.REST, symbol: str, limit: int = 100) -> pd.DataFrame:
    barset = api.get_barset(symbol, "day", limit=limit)
    bars = barset[symbol]
    data = [
        {
            "time": bar.t,
            "Open": bar.o,
            "High": bar.h,
            "Low": bar.l,
            "Close": bar.c,
            "Volume": bar.v,
        }
        for bar in bars
    ]
    df = pd.DataFrame(data)
    df.set_index("time", inplace=True)
    return calculate_indicators(df)


def get_position_qty(api: tradeapi.REST, symbol: str) -> int:
    try:
        position = api.get_position(symbol)
        return int(position.qty)
    except Exception:
        return 0


def position_size(cash: float, atr: float, price: float) -> int:
    if atr <= 0 or price <= 0:
        return 0
    risk_amount = cash * RISK_PERCENT
    size = int(risk_amount / (atr * STOP_ATR))
    max_size = int(MAX_TRADE_SIZE_USD / price)
    return max(0, min(size, max_size))


def submit_order(api: tradeapi.REST, symbol: str, qty: int, side: str) -> None:
    if qty <= 0:
        logger.warning("Skipping order with qty=0 for %s", symbol)
        return
    if DRY_RUN:
        logger.info("[DRY RUN] %s %d %s", side.upper(), qty, symbol)
        return
    api.submit_order(symbol=symbol, qty=qty, side=side, type="market", time_in_force="gtc")
    logger.info("Order submitted: %s %d %s", side.upper(), qty, symbol)


def run_agent() -> None:
    api = create_api_client()
    logger.info("Starting trading agent v3 for %s", SYMBOL)
    in_position = False
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    while True:
        try:
            clock = api.get_clock()
            if not clock.is_open:
                logger.warning("Market closed. Sleeping 60 seconds.")
                time.sleep(60)
                continue

            df = get_latest_bars(api, SYMBOL, limit=100)
            if df.empty:
                logger.error("No historical bars available.")
                time.sleep(30)
                continue

            latest = df.iloc[-1]
            cash = float(api.get_account().cash)
            qty = get_position_qty(api, SYMBOL)
            logger.info(
                "Price=%0.2f ATR=%0.2f RSI=%0.2f MACD=%0.2f trend=%s qty=%d",
                latest.Close,
                latest.ATR if not pd.isna(latest.ATR) else 0,
                latest.RSI if not pd.isna(latest.RSI) else 0,
                latest.MACD - latest.MACD_SIGNAL,
                latest.TREND_OK,
                qty,
            )

            if in_position:
                if latest.Close <= stop_loss or latest.Close >= take_profit or latest.SELL_SIGNAL:
                    submit_order(api, SYMBOL, qty, "sell")
                    logger.info("Exit position at %0.2f, reason=%s", latest.Close, "SELL_SIGNAL" if latest.SELL_SIGNAL else "STOP/TP")
                    in_position = False
                    entry_price = None
                    stop_loss = None
                    take_profit = None
            else:
                if latest.BUY_SIGNAL and not pd.isna(latest.ATR):
                    qty_to_buy = position_size(cash, latest.ATR, latest.Close)
                    if qty_to_buy > 0:
                        stop_loss = latest.Close - latest.ATR * STOP_ATR
                        take_profit = latest.Close + latest.ATR * TARGET_ATR
                        submit_order(api, SYMBOL, qty_to_buy, "buy")
                        entry_price = latest.Close
                        in_position = True
                        logger.info(
                            "Enter position %d @%0.2f stop=%0.2f target=%0.2f",
                            qty_to_buy,
                            latest.Close,
                            stop_loss,
                            take_profit,
                        )
                    else:
                        logger.warning("Calculated position size is zero; skipping entry.")

            time.sleep(INTERVAL_SECONDS)
        except Exception as exc:
            logger.error("Agent error: %s", exc)
            time.sleep(15)


if __name__ == "__main__":
    run_agent()
