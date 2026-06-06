import os
from dotenv import load_dotenv

load_dotenv()
ACTIUNI_RAW = os.getenv("ACTIUNI", "AAPL,MSFT,NVDA,GOOGL,AMZN,NFLX,META,AMD,TSLA,AVGO,CRM,ADBE,ORCL,CSCO,INTC,QCOM,TXN,AMAT,MU,PYPL")
ACTIUNI = [s.strip().upper() for s in ACTIUNI_RAW.split(",") if s.strip()]

from backtest_trading_agent_refactored import fetch_data, backtest, summary


def run_top20():
    results = []
    for simbol in ACTIUNI:
        print(f"\n=== Backtest pentru {simbol} ===")
        os.environ["TRADING_SYMBOL"] = simbol
        data = fetch_data(simbol, "6mo")
        result = backtest(data)
        summary(result)
        results.append({
            "symbol": simbol,
            "return_pct": result["return_pct"],
            "trades": len(result["trades"]),
            "win_rate": (len([t for t in result["trades"] if t["profit"] and t["profit"] > 0]) / len(result["trades"]) * 100) if result["trades"] else 0,
        })
    print("\n=== Rezumat top 20 ===")
    for r in results:
        print(f"{r['symbol']}: {r['return_pct']:.2f}% ({r['trades']} trades, win_rate={r['win_rate']:.1f}%)")


if __name__ == "__main__":
    run_top20()
