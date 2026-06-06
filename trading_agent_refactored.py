import os
import time
import logging
from datetime import datetime
from typing import List, Optional

import alpaca_trade_api as tradeapi
from dotenv import load_dotenv

load_dotenv()

# Configurări
SIMBOL = os.getenv("TRADING_SYMBOL", "AAPL")
QTY = int(os.getenv("TRADING_QTY", "1"))
INTERVAL = int(os.getenv("TRADING_INTERVAL", "30"))
HISTORY_LENGTH = int(os.getenv("TRADING_HISTORY_LENGTH", "20"))
SHORT_WINDOW = int(os.getenv("TRADING_SHORT_WINDOW", "3"))
LONG_WINDOW = int(os.getenv("TRADING_LONG_WINDOW", "5"))
STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "0.02"))
TAKE_PROFIT_PERCENT = float(os.getenv("TAKE_PROFIT_PERCENT", "0.04"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("trading_agent_refactored.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def create_api_client() -> tradeapi.REST:
    if not all([API_KEY, SECRET_KEY, BASE_URL]):
        logger.error("API key, secret key or base URL nu sunt configurate.")
        raise EnvironmentError("Missing Alpaca credentials in environment.")
    return tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version='v2')


def get_latest_price(api: tradeapi.REST, symbol: str) -> Optional[float]:
    try:
        bar = api.get_latest_bar(symbol)
        return float(bar.c)
    except Exception as err:
        logger.error("Eroare la obținerea prețului pentru %s: %s", symbol, err)
        return None


def get_position_quantity(api: tradeapi.REST, symbol: str) -> int:
    try:
        position = api.get_position(symbol)
        return int(position.qty)
    except Exception:
        return 0


def simple_moving_average(prices: List[float], window: int) -> Optional[float]:
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / window


def should_buy(prices: List[float]) -> bool:
    short_ma = simple_moving_average(prices, SHORT_WINDOW)
    long_ma = simple_moving_average(prices, LONG_WINDOW)
    if short_ma is None or long_ma is None:
        return False
    return short_ma > long_ma


def should_sell(prices: List[float]) -> bool:
    short_ma = simple_moving_average(prices, SHORT_WINDOW)
    long_ma = simple_moving_average(prices, LONG_WINDOW)
    if short_ma is None or long_ma is None:
        return False
    return short_ma < long_ma


def submit_order(api: tradeapi.REST, symbol: str, qty: int, side: str) -> None:
    message = f"ORDER {side.upper()} {qty} {symbol}"
    if DRY_RUN:
        logger.info("%s (dry run)", message)
        return
    try:
        order = api.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            type='market',
            time_in_force='gtc'
        )
        logger.info("Order submitted: %s", order)
    except Exception as err:
        logger.error("Eroare la trimiterea ordinului %s: %s", message, err)


def evaluate_exit_levels(entry_price: float) -> dict:
    stop_loss = entry_price * (1 - STOP_LOSS_PERCENT)
    take_profit = entry_price * (1 + TAKE_PROFIT_PERCENT)
    return {
        "stop_loss": stop_loss,
        "take_profit": take_profit
    }


def is_market_open(api: tradeapi.REST) -> bool:
    try:
        clock = api.get_clock()
        return clock.is_open
    except Exception as err:
        logger.error("Eroare la verificarea stării pieței: %s", err)
        return False


def run_agent() -> None:
    api = create_api_client()
    prices: List[float] = []
    last_entry_price: Optional[float] = None

    logger.info("Agent pornit pentru %s", SIMBOL)
    logger.info("Dry run mode: %s", DRY_RUN)

    while True:
        if not is_market_open(api):
            logger.warning("Bursa este închisă. Revin în 60 secunde.")
            time.sleep(60)
            continue

        current_price = get_latest_price(api, SIMBOL)
        if current_price is None:
            time.sleep(10)
            continue

        prices.append(current_price)
        if len(prices) > HISTORY_LENGTH:
            prices.pop(0)

        logger.info("Preț %s: %.2f", SIMBOL, current_price)

        position_qty = get_position_quantity(api, SIMBOL)
        logger.info("Poziție curentă: %d", position_qty)

        if position_qty == 0 and should_buy(prices):
            submit_order(api, SIMBOL, QTY, 'buy')
            last_entry_price = current_price
            if last_entry_price:
                levels = evaluate_exit_levels(last_entry_price)
                logger.info(
                    "Niveluri: stop_loss=%.2f, take_profit=%.2f",
                    levels['stop_loss'], levels['take_profit']
                )

        elif position_qty > 0:
            if should_sell(prices):
                submit_order(api, SIMBOL, QTY, 'sell')
                last_entry_price = None
            elif last_entry_price is not None:
                levels = evaluate_exit_levels(last_entry_price)
                if current_price <= levels['stop_loss']:
                    logger.info("Stop loss atins: %.2f <= %.2f", current_price, levels['stop_loss'])
                    submit_order(api, SIMBOL, QTY, 'sell')
                    last_entry_price = None
                elif current_price >= levels['take_profit']:
                    logger.info("Take profit atins: %.2f >= %.2f", current_price, levels['take_profit'])
                    submit_order(api, SIMBOL, QTY, 'sell')
                    last_entry_price = None

        time.sleep(INTERVAL)


def main() -> None:
    logger.info("Încep agentul de trading refactorizat")
    run_agent()


if __name__ == "__main__":
    main()
