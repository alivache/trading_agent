import os
from datetime import timedelta
from typing import List, Optional

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

SYMBOL = os.getenv("TRADING_SYMBOL", "AAPL")
PERIOD = os.getenv("BACKTEST_PERIOD", "6mo")
RISK_PERCENT = float(os.getenv("TRADE_RISK_PERCENT", "0.01"))
MAX_TRADE_SIZE_USD = float(os.getenv("MAX_TRADE_SIZE_USD", "2500"))
SHORT_WINDOW = int(os.getenv("TRADING_SHORT_WINDOW", "3"))
LONG_WINDOW = int(os.getenv("TRADING_LONG_WINDOW", "5"))
TREND_WINDOW = int(os.getenv("TREND_WINDOW", "50"))
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))
STOP_ATR = float(os.getenv("STOP_ATR", "2.0"))
TARGET_ATR = float(os.getenv("TARGET_ATR", "3.0"))
INITIAL_CAPITAL = float(os.getenv("BACKTEST_INITIAL_CAPITAL", "100000"))


def fetch_data(symbol: str, period: str) -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=False)
    if df.empty:
        raise ValueError(f"Could not download data for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=["Close"])


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


def position_size(cash: float, atr: float, price: float) -> int:
    if atr <= 0 or price <= 0:
        return 0
    risk_amount = cash * RISK_PERCENT
    size = int(risk_amount / (atr * STOP_ATR))
    max_size = int(MAX_TRADE_SIZE_USD / price)
    return max(0, min(size, max_size))


def signal(prices: List[float]) -> dict:
    short_ma = ema(prices, SHORT_WINDOW)
    long_ma = ema(prices, LONG_WINDOW)
    return {
        "buy": short_ma is not None and long_ma is not None and short_ma > long_ma,
        "sell": short_ma is not None and long_ma is not None and short_ma < long_ma,
    }


def bullish_trend(prices: List[float]) -> bool:
    trend_ma = ema(prices, TREND_WINDOW)
    return bool(trend_ma and prices[-1] > trend_ma)


def backtest(df: pd.DataFrame) -> dict:
    cash = INITIAL_CAPITAL
    position = 0
    entry_price = None
    long_price_history: List[float] = []
    trades = []
    stop_loss = None
    take_profit = None

    for i, row in df.iterrows():
        price = float(row["Close"])
        high = float(row["High"])
        low = float(row["Low"])
        long_price_history.append(price)

        if len(long_price_history) < TREND_WINDOW + 1:
            continue

        current_trend = bullish_trend(long_price_history)
        signal_data = signal(long_price_history)
        current_atr = calculate_atr(long_price_history, [float(x) for x in df["Low"][: len(long_price_history)]], long_price_history, ATR_PERIOD)

        if position == 0:
            if current_trend and signal_data["buy"] and current_atr is not None:
                qty = position_size(cash, current_atr, price)
                if qty > 0:
                    entry_price = price
                    position = qty
                    cash -= price * qty
                    stop_loss = price - current_atr * STOP_ATR
                    take_profit = price + current_atr * TARGET_ATR
                    trades.append({
                        "entry_date": i,
                        "entry_price": price,
                        "qty": qty,
                        "exit_date": None,
                        "exit_price": None,
                        "reason": None,
                    })
        else:
            if current_atr is None:
                continue
            if price <= stop_loss or price >= take_profit or signal_data["sell"]:
                profit = (price - entry_price) * position
                cash += price * position
                trade = trades[-1]
                trade["exit_date"] = i
                trade["exit_price"] = price
                trade["reason"] = "STOP_LOSS" if price <= stop_loss else "TAKE_PROFIT" if price >= take_profit else "SELL_SIGNAL"
                trade["profit"] = profit
                position = 0
                entry_price = None
                stop_loss = None
                take_profit = None

    if position > 0 and entry_price is not None:
        price = float(df["Close"].iloc[-1])
        cash += price * position
        trades[-1].update({
            "exit_date": df.index[-1],
            "exit_price": price,
            "reason": "END_PERIOD",
            "profit": (price - entry_price) * position,
        })

    result = {
        "final_cash": cash,
        "return_pct": (cash - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100,
        "trades": trades,
    }
    return result


def summary(results: dict):
    trades = [t for t in results["trades"] if t.get("profit") is not None]
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    total_profit = sum(t["profit"] for t in trades)
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    avg_profit = total_profit / len(trades) if trades else 0

    print("=== Backtest v2 summary ===")
    print(f"Symbol: {SYMBOL}")
    print(f"Period: {PERIOD}")
    print(f"Initial capital: ${INITIAL_CAPITAL:,.2f}")
    print(f"Final cash: ${results['final_cash']:,.2f}")
    print(f"Return: {results['return_pct']:.2f}%")
    print(f"Trades: {len(trades)}")
    print(f"Winning trades: {len(wins)}")
    print(f"Losing trades: {len(losses)}")
    print(f"Win rate: {win_rate:.2f}%")
    print(f"Average profit per trade: ${avg_profit:.2f}")


def main():
    df = fetch_data(SYMBOL, PERIOD)
    results = backtest(df)
    summary(results)


if __name__ == "__main__":
    main()
