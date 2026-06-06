import os
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

SYMBOL = os.getenv("TRADING_SYMBOL", "AAPL")
PERIOD = os.getenv("BACKTEST_PERIOD", "6mo")
RISK_PERCENT = float(os.getenv("TRADE_RISK_PERCENT", "0.01"))
MAX_TRADE_SIZE_USD = float(os.getenv("MAX_TRADE_SIZE_USD", "2500"))
SHORT_EMA = int(os.getenv("SHORT_EMA", "12"))
LONG_EMA = int(os.getenv("LONG_EMA", "26"))
TREND_EMA = int(os.getenv("TREND_EMA", "50"))
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))
STOP_ATR = float(os.getenv("STOP_ATR", "2.0"))
TARGET_ATR = float(os.getenv("TARGET_ATR", "4.0"))
INITIAL_CAPITAL = float(os.getenv("BACKTEST_INITIAL_CAPITAL", "100000"))


def fetch_data(symbol: str, period: str) -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=False)
    if df.empty:
        raise ValueError(f"Could not download data for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=["Close"])


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EMA_SHORT"] = ema(df["Close"], SHORT_EMA)
    df["EMA_LONG"] = ema(df["Close"], LONG_EMA)
    df["EMA_TREND"] = ema(df["Close"], TREND_EMA)
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    df["RSI"] = 100 - 100 / (1 + rs)
    macd = ema(df["Close"], 12) - ema(df["Close"], 26)
    df["MACD"] = macd
    df["MACD_SIGNAL"] = ema(macd, 9)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"] - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(ATR_PERIOD).mean()
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


def position_size(cash: float, atr: float, price: float) -> int:
    if atr <= 0 or price <= 0:
        return 0
    risk_amount = cash * RISK_PERCENT
    size = int(risk_amount / (atr * STOP_ATR))
    max_size = int(MAX_TRADE_SIZE_USD / price)
    return max(0, min(size, max_size))


def backtest(df: pd.DataFrame) -> Dict[str, object]:
    df = calculate_indicators(df)
    cash = INITIAL_CAPITAL
    position = 0
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trades = []

    for timestamp, row in df.iterrows():
        price = float(row["Close"])
        if position == 0:
            if row["BUY_SIGNAL"] and not pd.isna(row["ATR"]):
                qty = position_size(cash, float(row["ATR"]), price)
                if qty > 0:
                    entry_price = price
                    position = qty
                    cash -= qty * price
                    stop_loss = price - float(row["ATR"]) * STOP_ATR
                    take_profit = price + float(row["ATR"]) * TARGET_ATR
                    trades.append({
                        "entry_date": timestamp,
                        "entry_price": price,
                        "qty": qty,
                        "exit_date": None,
                        "exit_price": None,
                        "profit": None,
                        "reason": None,
                    })
        else:
            if price <= stop_loss or price >= take_profit or row["SELL_SIGNAL"]:
                profit = (price - entry_price) * position
                cash += position * price
                trade = trades[-1]
                trade["exit_date"] = timestamp
                trade["exit_price"] = price
                trade["profit"] = profit
                trade["reason"] = (
                    "STOP_LOSS"
                    if price <= stop_loss
                    else "TAKE_PROFIT"
                    if price >= take_profit
                    else "SELL_SIGNAL"
                )
                position = 0
                entry_price = None
                stop_loss = None
                take_profit = None

    if position > 0 and entry_price is not None:
        price = float(df["Close"].iloc[-1])
        cash += position * price
        trade = trades[-1]
        trade["exit_date"] = df.index[-1]
        trade["exit_price"] = price
        trade["profit"] = (price - entry_price) * position
        trade["reason"] = "END_PERIOD"

    return {
        "final_cash": cash,
        "return_pct": (cash - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100,
        "trades": trades,
    }


def summary(results: Dict[str, object]) -> None:
    trades = [t for t in results["trades"] if t["profit"] is not None]
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    total_profit = sum(t["profit"] for t in trades)
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    avg_profit = total_profit / len(trades) if trades else 0

    print("=== Backtest v3 summary ===")
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


def main() -> None:
    df = fetch_data(SYMBOL, PERIOD)
    results = backtest(df)
    summary(results)


if __name__ == "__main__":
    main()
