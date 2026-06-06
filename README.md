# Trading Agent

Acest repository conține un set de scripturi Python pentru backtesting și strategie de trading bazate pe swing trading și indicatori VWAP.

## Conținut

- `trading_agent.py` - script principal pentru agentul de trading
- `backtest.py`, `backtest_swing.py` - fișiere pentru backtesting
- `swing_trading.py`, `swing_final.py`, `swing_hmm.py`, `swing_fara_short.py` - strategii swing
- `vwap_strategy.py`, `vwap_level3.py`, `vwap_optimized.py` - strategii bazate pe VWAP
- `dashboard.py`, `dasboard1.py` - interfețe de monitorizare/raportare
- `log_csv.py` - utilitar pentru scrierea datelor în CSV
- `multi_tf_strategy.py` - strategie multi-timeframe
- `test_conexiune.py`, `test_env.py` - teste simple de conexiune și mediu
- `raport_zilnic.py` - script pentru generare raport zilnic

## Cum se utilizează

1. Configurați mediul Python.
2. Instalați dependențele necesare.
3. Rulați scripturile de backtest sau agentul principal:

```powershell
python trading_agent.py
```

## Notă

Fișierul `.env` este prezent în repo și poate conține setări locale de mediu.

## Git

Repo-ul este inițializat cu un commit inițial și un fișier `.gitignore` pentru proiecte Python.
