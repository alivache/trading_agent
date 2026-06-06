import os
from typing import List

from dotenv import load_dotenv

load_dotenv()

ACTIUNI_RAW = os.getenv(
    "ACTIUNI",
    "AAPL,MSFT,NVDA,GOOGL,AMZN,NFLX,META,AMD,TSLA,AVGO,CRM,ADBE,ORCL,CSCO,INTC,QCOM,TXN,AMAT,MU,PYPL",
)
ACTIUNI = [s.strip().upper() for s in ACTIUNI_RAW.split(",") if s.strip()]

import backtest_trading_agent_refactored_v2 as backtest_v2


def main():
    results = []
    for symbol in ACTIUNI:
        print(f"\n=== Backtest v2 pentru {symbol} ===")
        backtest_v2.SYMBOL = symbol
        df = backtest_v2.fetch_data(symbol, backtest_v2.PERIOD)
        result = backtest_v2.backtest(df)
        backtest_v2.summary(result)
        results.append(
            {
                "symbol": symbol,
                "return_pct": result["return_pct"],
                "trades": len([t for t in result["trades"] if t.get("profit") is not None]),
            }
        )

    print("\n=== Rezumat top 20 backtest v2 ===")
    for r in results:
        print(f"{r['symbol']}: {r['return_pct']:.2f}% ({r['trades']} trades)")


if __name__ == "__main__":
    main()
