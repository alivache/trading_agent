import os
import time
import logging
from datetime import datetime
from typing import List, Optional

import alpaca_trade_api as tradeapi
from dotenv import load_dotenv

load_dotenv()

SIMBOL = os.getenv("TRADING_SYMBOL", "AAPL")
BASE_URL = os.getenv("ALPACA_BASE_URL")
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
RISK_PERCENT = float(os.getenv("TRADE_RISK_PERCENT", "0.01"))
MAX_TRADE_SIZE_USD = float(os.getenv("MAX_TRADE_SIZE_USD", "2500"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")
SHORT_WINDOW = int(os.getenv("TRADING_SHORT_WINDOW", "3"))
LONG_WINDOW = int(os.getenv("TRADING_LONG_WINDOW", "5"))
TREND_WINDOW = int(os.getenv("TREND_WINDOW", "50"))
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))
STOP_ATR = float(os.getenv("STOP_ATR", "2.0"))
TARGET_ATR = float(os.getenv("TARGET_ATR", "3.0"))
INTERVAL_SECONDS = int(os.getenv("TRADING_INTERVAL", "30"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("trading_agent_refactored_v2.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def create_api_client() -> tradeapi.REST:
    if not (API_KEY and SECRET_KEY and BASE_URL):
        logger.error("Alpaca credentials are missing in environment variables.")
        raise EnvironmentError("Missing Alpaca credentials")
    return tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version="v2")


def ema(values: List[float], window: int) -> Optional[float]:
    if len(values) < window:
        return None
    weights = list(range(1, window + 1))
    window_values = values[-window:]
    return sum(v * w for v, w in zip(window_values, weights)) / sum(weights)


def calculate_atr(high: List[float], low: List[float], close: List[float], period: int) -> Optional[float]:
    if len(close) < period + 1:
        return None
    trs = []
    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period if len(trs) >= period else None


def get_bars(api: tradeapi.REST, symbol: str, limit: int = 100):
    bars = api.get_barset(symbol, "day", limit=limit)
    if symbol not in bars or not bars[symbol]:
        return []
    return bars[symbol]


def build_signals(prices: List[float]) -> dict:
    signal = {"buy": False, "sell": False}
    short_ma = ema(prices, SHORT_WINDOW)
    long_ma = ema(prices, LONG_WINDOW)
    if short_ma is None or long_ma is None:
        return signal
    signal["buy"] = short_ma > long_ma
    signal["sell"] = short_ma < long_ma
    return signal


def trend_is_bullish(prices: List[float]) -> bool:
    trend_ma = ema(prices, TREND_WINDOW)
    return bool(trend_ma and prices[-1] > trend_ma)


def position_size(cash: float, atr: float, price: float) -> int:
    if atr is None or atr <= 0 or price <= 0:
        return 0
    risk_amount = cash * RISK_PERCENT
    size = int(risk_amount / (atr * STOP_ATR))
    max_size = int(MAX_TRADE_SIZE_USD / price)
    return max(0, min(size, max_size))


def format_price(value: float) -> str:
    return f"{value:.2f}"


def submit_order(api: tradeapi.REST, symbol: str, qty: int, side: str) -> None:
    if qty <= 0:
        logger.warning("Order size is zero; skipping %s order for %s", side, symbol)
        return
    if DRY_RUN:
        logger.info("[DRY RUN] %s %d %s", side.upper(), qty, symbol)
        return
    try:
        order = api.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            type="market",
            time_in_force="gtc",
        )
        logger.info("Submitted order: %s", order)
    except Exception as exc:
        logger.error("Order submission failed for %s %s: %s", side, symbol, exc)


def run_agent() -> None:
    api = create_api_client()
    logger.info("Starting trading agent v2 for %s", SIMBOL)
    position_open = False
    entry_price = None
    stop_loss = None
    take_profit = None
    high_since_entry = None

    while True:
        try:
            if not api.get_clock().is_open:
                logger.warning("Market closed. Sleeping 60 seconds.")
                time.sleep(60)
                continue

            bars = get_bars(api, SIMBOL, limit=TREND_WINDOW + 30)
            if len(bars) < TREND_WINDOW + 1:
                logger.error("Not enough bars to calculate indicators.")
                time.sleep(60)
                continue

            closes = [bar.c for bar in bars]
            highs = [bar.h for bar in bars]
            lows = [bar.l for bar in bars]
            current_price = closes[-1]
            current_high = highs[-1]

            atr_value = calculate_atr(highs, lows, closes, ATR_PERIOD)
            trend_ok = trend_is_bullish(closes)
            signals = build_signals(closes)
            position_qty = int(api.get_position(SIMBOL).qty) if api.get_position(SIMBOL) else 0

            logger.info("Price=%s ATR=%s trend=%s buy=%s sell=%s qty=%d",
                        format_price(current_price),
                        format_price(atr_value) if atr_value else "n/a",
                        trend_ok, signals["buy"], signals["sell"], position_qty)

            if position_open:
                high_since_entry = max(high_since_entry, current_high)
                if current_price <= stop_loss or current_price >= take_profit or signals["sell"]:
                    submit_order(api, SIMBOL, position_qty, "sell")
                    logger.info("Exited position at %s - stop=%s target=%s sell=%s",
                                format_price(current_price),
                                format_price(stop_loss),
                                format_price(take_profit),
                                signals["sell"])
                    position_open = False
                    entry_price = None
                    stop_loss = None
                    take_profit = None
                    high_since_entry = None
            else:
                if trend_ok and signals["buy"] and atr_value:
                    cash = float(api.get_account().cash)
                    qty = position_size(cash, atr_value, current_price)
                    if qty > 0:
                        stop_loss = current_price - atr_value * STOP_ATR
                        take_profit = current_price + atr_value * TARGET_ATR
                        submit_order(api, SIMBOL, qty, "buy")
                        entry_price = current_price
                        position_open = True
                        high_since_entry = current_high
                        logger.info("Entered position %s qty=%d stop=%s target=%s",
                                    format_price(current_price), qty,
                                    format_price(stop_loss), format_price(take_profit))
                    else:
                        logger.warning("Position size computed as zero; skipping entry.")

            time.sleep(INTERVAL_SECONDS)
        except Exception as error:
            logger.error("Agent error: %s", error)
            time.sleep(15)


if __name__ == "__main__":
    run_agent()
