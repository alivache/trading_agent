import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

ACTIUNI_RAW = os.getenv(
    "ACTIUNI",
    "AAPL,MSFT,NVDA,GOOGL,AMZN,NFLX,META,AMD,TSLA,AVGO,CRM,ADBE,ORCL,CSCO,INTC,QCOM,TXN,AMAT,MU,PYPL"
)
ACTIUNI = [s.strip().upper() for s in ACTIUNI_RAW.split(",") if s.strip()]
PERIOD = os.getenv("BACKTEST_PERIOD", "6mo")
INITIAL_CAPITAL = float(os.getenv("BACKTEST_INITIAL_CAPITAL", "100000"))
SHORT_WINDOW = int(os.getenv("TRADING_SHORT_WINDOW", "3"))
LONG_WINDOW = int(os.getenv("TRADING_LONG_WINDOW", "5"))
STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "0.02"))
TAKE_PROFIT_PERCENT = float(os.getenv("TAKE_PROFIT_PERCENT", "0.04"))
QTY = int(os.getenv("TRADING_QTY", "1"))


@dataclass
class Position:
    symbol: str
    entry_date: datetime
    entry_price: float
    qty: int
    stop_loss: float
    take_profit: float
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    reason: Optional[str] = None


def fetch_data(symbol: str, period: str) -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=False)
    if df.empty:
        raise ValueError(f"Nu am putut descărca date pentru {symbol} period={period}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Close"])
    return df


def simple_moving_average(prices: List[float], window: int) -> Optional[float]:
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / window


def build_signal(close_history: List[float]) -> Dict[str, bool]:
    short_ma = simple_moving_average(close_history, SHORT_WINDOW)
    long_ma = simple_moving_average(close_history, LONG_WINDOW)
    return {
        "buy": short_ma is not None and long_ma is not None and short_ma > long_ma,
        "sell": short_ma is not None and long_ma is not None and short_ma < long_ma,
    }


def run_portfolio() -> None:
    data_by_symbol: Dict[str, pd.DataFrame] = {}
    for symbol in ACTIUNI:
        try:
            data_by_symbol[symbol] = fetch_data(symbol, PERIOD)
        except Exception as err:
            print(f"Nu am putut încărca date pentru {symbol}: {err}")

    all_dates = sorted(
        pd.Index(sorted({date for df in data_by_symbol.values() for date in df.index}))
    )

    cash = INITIAL_CAPITAL
    positions: Dict[str, Position] = {}
    closed_trades: List[Position] = []
    price_history: Dict[str, List[float]] = {symbol: [] for symbol in data_by_symbol}

    for current_date in all_dates:
        for symbol, df in data_by_symbol.items():
            if current_date not in df.index:
                continue
            row = df.loc[current_date]
            price = float(row["Close"])
            price_history[symbol].append(price)

            if symbol in positions:
                pos = positions[symbol]
                if price <= pos.stop_loss:
                    pos.exit_date = current_date
                    pos.exit_price = price
                    pos.reason = "STOP_LOSS"
                    cash += price * pos.qty
                    closed_trades.append(pos)
                    del positions[symbol]
                elif price >= pos.take_profit:
                    pos.exit_date = current_date
                    pos.exit_price = price
                    pos.reason = "TAKE_PROFIT"
                    cash += price * pos.qty
                    closed_trades.append(pos)
                    del positions[symbol]
                else:
                    if len(price_history[symbol]) >= LONG_WINDOW:
                        signals = build_signal(price_history[symbol])
                        if signals["sell"]:
                            pos.exit_date = current_date
                            pos.exit_price = price
                            pos.reason = "SELL_SIGNAL"
                            cash += price * pos.qty
                            closed_trades.append(pos)
                            del positions[symbol]
            else:
                if len(price_history[symbol]) >= LONG_WINDOW:
                    signals = build_signal(price_history[symbol])
                    if signals["buy"] and cash >= price * QTY:
                        stop_loss = price * (1 - STOP_LOSS_PERCENT)
                        take_profit = price * (1 + TAKE_PROFIT_PERCENT)
                        positions[symbol] = Position(
                            symbol=symbol,
                            entry_date=current_date,
                            entry_price=price,
                            qty=QTY,
                            stop_loss=stop_loss,
                            take_profit=take_profit,
                        )
                        cash -= price * QTY

    last_prices = {}
    for symbol, df in data_by_symbol.items():
        if not df.empty:
            last_prices[symbol] = float(df["Close"].iloc[-1])

    for symbol, pos in list(positions.items()):
        exit_price = last_prices.get(symbol)
        if exit_price is not None:
            pos.exit_date = max(data_by_symbol[symbol].index)
            pos.exit_price = exit_price
            pos.reason = "END_PERIOD"
            cash += exit_price * pos.qty
            closed_trades.append(pos)
            del positions[symbol]

    final_value = cash
    return_pct = (final_value - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    wins = [t for t in closed_trades if t.exit_price is not None and t.exit_price > t.entry_price]
    losses = [t for t in closed_trades if t.exit_price is not None and t.exit_price <= t.entry_price]
    total_profit = sum((t.exit_price - t.entry_price) * t.qty for t in closed_trades if t.exit_price is not None)
    win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0

    print("=== Portfolio Backtest Simultan ===")
    print(f"Symbols: {', '.join(sorted(data_by_symbol.keys()))}")
    print(f"Initial capital: ${INITIAL_CAPITAL:,.2f}")
    print(f"Final capital: ${final_value:,.2f}")
    print(f"Return: {return_pct:.2f}%")
    print(f"Closed trades: {len(closed_trades)}")
    print(f"Winning trades: {len(wins)}")
    print(f"Losing trades: {len(losses)}")
    print(f"Win rate: {win_rate:.2f}%")
    print(f"Average profit/trade: ${total_profit / len(closed_trades):.2f}" if closed_trades else "No trades")

    trades_by_symbol: Dict[str, List[Position]] = {}
    for trade in closed_trades:
        trades_by_symbol.setdefault(trade.symbol, []).append(trade)

    print("\n=== Rezumat per simbol ===")
    for symbol in sorted(trades_by_symbol.keys()):
        symbol_trades = trades_by_symbol[symbol]
        profit = sum((t.exit_price - t.entry_price) * t.qty for t in symbol_trades)
        print(f"{symbol}: {profit:+.2f} USD, trades={len(symbol_trades)}")


if __name__ == "__main__":
    run_portfolio()
