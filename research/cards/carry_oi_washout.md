# carry_oi_washout

**Verdict:** FAILED: profit_after_costs, profit_fees_doubled, nearby_settings_hold, beats_holding. Score 9/25. Regime it needs: **wild**.

## The idea
Buy the first new 72-hour closing low that comes with open interest down 15% or more in 24 hours.

## Why the edge exists
A new low on collapsing open interest is positions being closed or liquidated rather than new shorts being opened, so the selling is exhaustible and stops when the leverage is gone.

**Who is on the losing side:** Leveraged longs closed out at the low and traders who short the breakdown after the fuel is spent.

## Exact rules
- **Entry:** d = oi / oi.shift(24) - 1. raw[t] = (close[t] < ta.donchian_low(df, don_n)[t], the lowest low of the previous don_n bars excluding the current one) AND (d[t] <= -oi_drop) AND ATR(24) not NaN; no signal while oi is NaN. Signal only on the first qualifying bar in 24 (raw False on all of the previous 24 bars). Long at market on the open of t+1.
- **Stop:** close[t] - stop_atr * ta.atr(df, 24)[t]  (3.0 ATR)
- **Exit:** Time stop only: close at 36 bars.
- **Limit order life:** 1 bar(s). **Time stop:** 36 bars.
- **Default parameters:** `{"don_n": 72, "oi_n": 24, "oi_drop": 0.15, "cool": 24, "atr_n": 24, "stop_atr": 3.0}`
- **Code:** `desk/strategies/s_carry_oi_washout.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | -0.6% | -62.2% | -23.5% |
| Max drawdown | -6.2% | -74.4% | -51.3% |
| Return / drawdown (annual) | -0.07 | -0.61 | -0.33 |
| Sharpe | -0.12 | -0.84 | -0.41 |

- Trades: **60**, win rate 48%, average trade -0.02R, profit factor 0.95
- Fees paid $67, funding paid $-9 (negative = received), gross P&L $-3
- **Worst month:** -1.4%. **Longest losing streak:** 9 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +12.6%, max drawdown -7.8%, 217 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +5.25% | 31 |
| 2024-01-01 | +7.10% | 19 |
| 2024-04-01 | -1.06% | 30 |
| 2024-07-01 | -3.78% | 35 |
| 2024-10-01 | +5.74% | 42 |
| 2025-01-01 | -0.95% | 13 |
| 2025-04-01 | +1.50% | 6 |
| 2025-07-01 | -0.43% | 9 |
| 2025-10-01 | -1.88% | 10 |
| 2026-01-01 | -2.00% | 12 |
| 2026-04-01 | +3.16% | 10 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | -1.3% | -6.5% |
| Slippage doubled | -1.3% | -6.5% |
| Funding doubled | -0.7% | -6.2% |
| All costs doubled | -2.0% | -6.8% |
| Entered one bar late | +1.0% | -6.5% |
| Guardian switched off | -0.3% | -5.9% |
| No costs at all | +0.7% | -5.5% |

**Nearby settings:** 33% of 9 parameter combinations were profitable on the unseen window (median -2.3%, worst -7.7%, best +4.5%).

**Monte Carlo** (5000 reshuffles of the 60 unseen trades): 5th percentile return -8.1%, median -0.8%, chance of losing money 56%, bad-case drawdown -9.8%.

**Luck check:** p = 0.562 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | -3.4% | -13.2% |
| bull | 86 | +3.1% | +13.1% |
| chop | 322 | -0.3% | -0.3% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -2.0% | -3.4% |
| trending | 217 | +3.6% | +6.0% |
| wild | 76 | -2.2% | -10.7% |

**The market that breaks it:** bear trend (-13.2% annualised over 94 days).

**Earliest warning sign it is fading:** The control (new 72h low without the OI filter) matches or beats it over a quarter, or stop-out share rises above 45%.

## Final check
| Question | Answer |
|---|---|
| Does it win on data it has never seen, after fees and funding? | **no** |
| Across 50+ trades? | yes |
| With fees doubled? | **no** |
| Does it hold across nearby settings? | **no** |
| Free of look-ahead? | yes |
| Still profitable if every order goes in one bar late? | yes |
| Does it beat simply holding, after costs? | **no** |

## Scores (1-5)
| Out-of-sample profit | Max drawdown | Trade count | Losing streak | Bear and chop | Total |
|---|---|---|---|---|---|
| 1 | 3 | 2 | 2 | 1 | 9/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
Statistically thin: t(R) under 2 and by-day t 1.5 in a pure bull sample; the event-study +205 bps shrinks to 0.18R because 37% of entries go 3 ATR against you first. Never seen a bear market. A third of the losers come from a wide-window setting (96h) going negative in 2023. Overlaps with the cascade idea on the big flush days. OI is a venue statistic that can be restated or lag.
