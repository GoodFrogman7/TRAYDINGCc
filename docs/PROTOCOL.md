# Research protocol (fixed before any strategy was tested)

## Windows
| Window | Dates (UTC) | Who may look |
|---|---|---|
| DESIGN | first bar .. 2024-12-31 | Hunter explores here; parameters are chosen here |
| VALIDATION | 2025-01-01 .. 2026-05-17 | never seen while designing; used to rank |
| HOLDOUT | 2026-05-18 .. last bar | sealed; only the finalists touch it, once |

## Costs in every run
Taker 0.05% / maker 0.02% (Kraken Futures tier 0), hourly funding (actual where published, estimated before),
slippage from the venue's own $10k order-book depth (doubled on stops), delisted coins in the universe.

## Walk-forward
Test quarters from 2023-10-01 to the end of VALIDATION. For each quarter, parameters are re-chosen from the
strategy's grid on the 18 months before it, then traded unseen for the quarter. Reported results are the
stitched test quarters. Ranking uses only the quarters inside VALIDATION.

## Gates (all must pass before anything may trade, even on paper as champion)
1. No look-ahead: intents computed on data truncated at T equal intents computed on full history at T,
   for every parameter combination, with truncation points placed right after rows that act; then every
   reported trade of a strategy that passes the other gates is replayed one by one.
2. At least 50 trades in VALIDATION.
3. VALIDATION net profit > 0 after all costs.
4. Still > 0 with fees doubled.
5. Nearby settings hold: at least 60% of the parameter grid is profitable in VALIDATION.
6. Still > 0 when every order is sent one bar late.
7. Beats buying and holding the same top-10 basket after costs (return per unit of drawdown), with the
   raw-return comparison shown next to it.

## Scores (1-5 each, thresholds fixed in `desk/audit/scoring.py`)
Out-of-sample profit after costs; max drawdown; trade count; worst losing streak; survival in bear and chop.

## Amendments after the independent review (2026-11-18, before any strategy was audited)
An independent review of the engine and harness ran before any strategy result existed. Changes made:
- **Look-ahead test rebuilt.** The first version sampled five truncation points and let a deliberately
  cheating strategy (it peeked one bar ahead) pass every gate with +1,260%. The test now probes every
  parameter combination, cuts right after acting rows, compares every row, uses a fresh strategy object
  and a capped data store per probe, and replays every trade of a gate-passing strategy.
- **Gate 6 added** (one bar late). On this venue's candles every bar opens at the previous close, so
  "market at the next open" fills at the signal bar's own close; an edge that needs that exact price is
  not real.
- **Luck test now resamples whole exit days and whole exit weeks**, not single trades, and reports the
  more cautious p-value. Trades on correlated coins win and lose together.
- **Funding estimate re-fitted without the sealed period.** The first fit used actual rates from inside
  the holdout.
- **Bear-and-chop score uses VALIDATION quarters only**; drawdown and losing-streak scores are 1 when a
  strategy has fewer than 50 validation trades.
- **Fill model tightened:** a take-profit fills at its price, never better; a pending entry is cancelled
  if its fill bar is outside the tradable set; a "target" on the wrong side of the fill is dropped.
- **Benchmark corrected** (it skipped the first hour of every month and hid the cost of getting in).
- **Slippage before order-book history exists** is a fixed estimate (2 bps BTC/ETH, 8 bps others), no
  longer a statistic of later data.
- Known and accepted: the account does not compound and so cannot go broke in a backtest; fold
  boundaries reset the Guardian's counters; resting limits fill with no queue penalty (strategies with
  a high share of maker entries deserve extra suspicion).

## Selection honesty
Testing 20+ ideas guarantees some look good by luck. Each survivor reports a bootstrap p-value for "average
trade > 0" and whether it survives a Holm correction across every idea tested. The HOLDOUT is opened only for
the top three, once; a finalist that loses money there is not crowned.
