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
1. No look-ahead: intents computed on data truncated at T equal intents computed on full history at T.
2. At least 50 trades in VALIDATION.
3. VALIDATION net profit > 0 after all costs.
4. Still > 0 with fees doubled.
5. Nearby settings hold: at least 60% of the parameter grid is profitable in VALIDATION.
6. Beats buying and holding the same top-10 basket after costs (return per unit of drawdown), with the
   raw-return comparison shown next to it.

## Scores (1-5 each, thresholds fixed in `desk/audit/scoring.py`)
Out-of-sample profit after costs; max drawdown; trade count; worst losing streak; survival in bear and chop.

## Selection honesty
Testing 20+ ideas guarantees some look good by luck. Each survivor reports a bootstrap p-value for "average
trade > 0" and whether it survives a Holm correction across every idea tested. The HOLDOUT is opened only for
the top three, once; a finalist that loses money there is not crowned.
