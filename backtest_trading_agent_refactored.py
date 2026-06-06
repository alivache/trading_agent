import os
from datetime import timedelta

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

SYMBOL = os.getenv("TRADING_SYMBOL", "AAPL")
PERIOD = os.getenv("BACKTEST_PERIOD", "6mo")
SHORT_WINDOW = int(os.getenv("TRADING_SHORT_WINDOW", "3"))
LONG_WINDOW = int(os.getenv("TRADING_LONG_WINDOW", "5"))
STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "0.02"))
TAKE_PROFIT_PERCENT = float(os.getenv("TAKE_PROFIT_PERCENT", "0.04"))
INITIAL_CAPITAL = float(os.getenv("BACKTEST_INITIAL_CAPITAL", "100000"))
QTY = int(os.getenv("TRADING_QTY", "1"))
HISTORY_LENGTH = int(os.getenv("TRADING_HISTORY_LENGTH", "20"))


def fetch_data(symbol: str, period: str) -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=False)
    if df.empty:
        raise ValueError(f"Nu am putut descărca date pentru {symbol} period={period}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Close"])
    return df


def simple_moving_average(prices, window):
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / window


def backtest(df: pd.DataFrame):
    cash = INITIAL_CAPITAL
    position = 0
    entry_price = None
    last_price = None
    prices = []
    trades = []

    for timestamp, row in df.iterrows():
        price = float(row["Close"])
        last_price = price
        prices.append(price)
        if len(prices) > HISTORY_LENGTH:
            prices.pop(0)

        short_ma = simple_moving_average(prices, SHORT_WINDOW)
        long_ma = simple_moving_average(prices, LONG_WINDOW)

        if position == 0:
            if short_ma is not None and long_ma is not None and short_ma > long_ma:
                position = QTY
                entry_price = price
                cash -= price * QTY
                trades.append({
                    "entry_date": timestamp,
                    "entry_price": price,
                    "exit_date": None,
                    "exit_price": None,
                    "profit": None,
                    "reason": "BUY_SIGNAL"
                })
        else:
            stop_loss = entry_price * (1 - STOP_LOSS_PERCENT)
            take_profit = entry_price * (1 + TAKE_PROFIT_PERCENT)
            sell_signal = short_ma is not None and long_ma is not None and short_ma < long_ma
            exit_reason = None

            if price <= stop_loss:
                exit_reason = "STOP_LOSS"
            elif price >= take_profit:
                exit_reason = "TAKE_PROFIT"
            elif sell_signal:
                exit_reason = "SELL_SIGNAL"

            if exit_reason:
                profit = (price - entry_price) * QTY
                cash += price * QTY
                last_trade = trades[-1]
                last_trade["exit_date"] = timestamp
                last_trade["exit_price"] = price
                last_trade["profit"] = profit
                last_trade["reason"] = exit_reason
                position = 0
                entry_price = None

    if position > 0 and last_price is not None and entry_price is not None:
        profit = (last_price - entry_price) * QTY
        cash += last_price * QTY
        last_trade = trades[-1]
        last_trade["exit_date"] = df.index[-1]
        last_trade["exit_price"] = last_price
        last_trade["profit"] = profit
        last_trade["reason"] = "END_OF_PERIOD"
        position = 0
        entry_price = None

    return {
        "final_cash": cash,
        "return_pct": (cash - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100,
        "trades": trades,
    }


def summary(results):
    trades = results["trades"]
    wins = [t for t in trades if t["profit"] is not None and t["profit"] > 0]
    losses = [t for t in trades if t["profit"] is not None and t["profit"] <= 0]
    total_profit = sum(t["profit"] for t in trades if t["profit"] is not None)
    avg_profit = total_profit / len(trades) if trades else 0
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    print("=== Backtest summary ===")
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
    if trades:
        longest_hold = max(((t["exit_date"] - t["entry_date"]).days for t in trades if t["exit_date"] and t["entry_date"]), default=0)
        print(f"Longest hold (days): {longest_hold}")


def main():
    print("Rulez backtest pentru strategia refactorizată...")
    df = fetch_data(SYMBOL, PERIOD)
    results = backtest(df)
    summary(results)


if __name__ == "__main__":
    main()
