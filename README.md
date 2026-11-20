# TRAYDINGCc: crypto research desk and paper-trading bot

A research pipeline and a paper-trading bot for crypto perpetual futures on 1-hour bars.
**Paper trading only.** Nothing here places a real order.

## What is here
| Path | What |
|---|---|
| `desk/data/` | downloader for Kraken Futures public market data (no account, no keys) and loaders |
| `desk/engine/` | one bar-by-bar simulator used by both the backtests and the paper bot |
| `desk/strategies/` | strategy contract, causal indicators, and the strategies under test (`s_*.py`) |
| `desk/audit/` | the audit every strategy gets: walk-forward, stress tests, Monte Carlo, gates, scores |
| `desk/bot/` | hourly paper-trading bot and the Guardian |
| `docs/DATA.md` | what the data is, where it came from, and its limits |
| `docs/PROTOCOL.md` | research rules fixed before any strategy was tested |
| `research/` | Hunter notes, audit results, strategy cards |

## Run it
```bash
pip install -r requirements.txt
python -m desk.data.download        # about 5 minutes, public data only
python -m pytest tests -q
python -m desk.audit.run --ref      # audit the reference template end to end
```

## Ground rules
- Only real market data, each file stamped with source and download time (`data/manifest.json`).
- Every test includes fees, funding, slippage and delisted coins.
- Ideas are designed on data up to 2024-12-31, ranked on 2025-01-01 to 2026-05-17, and the final
  six months are sealed until the finalists are chosen.
- Real money waits for an explicit "go live".
