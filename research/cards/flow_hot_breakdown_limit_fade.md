# flow_hot_breakdown_limit_fade

**Verdict:** FAILED: profit_after_costs, profit_fees_doubled, nearby_settings_hold, holds_one_bar_late, beats_holding. Score 8/25. Regime it needs: **wild**.

## The idea
After a close below the 48-hour low while volatility is already expanded, rest a buy limit 1.5 ATR lower for three bars and take profit 2 ATR above the fill.

## Why the edge exists
A breakdown in an already volatile market triggers stops and liquidations that overshoot by more than an ATR, and a resting bid there is paid to supply liquidity to forced sellers.

**Who is on the losing side:** Stop-loss and liquidation sellers who cross the spread at the worst moment of the flush.

## Exact rules
- **Entry:** rank = ta.rolling_rank(ta.bb_width(close, 48, 2.0), 720).shift(1). At the close of bar t: if close < ta.donchian_low(df, n) AND rank > rank_min AND ta.atr(df, 24) not NaN: side = +1 with limit L = close - limit_atr * ta.atr(df, 24). The limit works for 3 bars (valid_bars = 3). All symbols.
- **Stop:** L - 3.0 * ta.atr(df, 24), ATR taken at the signal bar
- **Exit:** Take-profit at L + 2.0 * ta.atr(df, 24); otherwise time stop max_hold = 12 bars after the fill.
- **Limit order life:** 3 bar(s). **Time stop:** 12 bars.
- **Default parameters:** `{"n": 48, "rank_min": 0.7, "limit_atr": 1.5, "stop_atr": 3.0, "tp_atr": 2.0}`
- **Code:** `desk/strategies/s_flow_hot_breakdown_limit_fade.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | -11.0% | -62.2% | -23.5% |
| Max drawdown | -15.8% | -74.4% | -51.3% |
| Return / drawdown (annual) | -0.50 | -0.61 | -0.33 |
| Sharpe | -0.96 | -0.84 | -0.41 |

- Trades: **206**, win rate 51%, average trade -0.11R, profit factor 0.72
- Fees paid $147, funding paid $-3 (negative = received), gross P&L $-953
- **Worst month:** -7.8%. **Longest losing streak:** 15 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): -8.7%, max drawdown -15.8%, 314 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +0.98% | 3 |
| 2024-01-01 | +0.19% | 4 |
| 2024-04-01 | +0.73% | 32 |
| 2024-07-01 | -0.66% | 37 |
| 2024-10-01 | +1.02% | 32 |
| 2025-01-01 | -4.57% | 79 |
| 2025-04-01 | +0.03% | 26 |
| 2025-07-01 | +1.54% | 14 |
| 2025-10-01 | +2.05% | 32 |
| 2026-01-01 | -10.41% | 51 |
| 2026-04-01 | +0.40% | 4 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | -12.4% | -17.1% |
| Slippage doubled | -11.6% | -16.4% |
| Funding doubled | -11.0% | -15.9% |
| All costs doubled | -13.2% | -17.7% |
| Entered one bar late | -7.8% | -13.8% |
| Guardian switched off | -10.2% | -15.4% |
| No costs at all | -8.9% | -14.1% |

**Nearby settings:** 19% of 27 parameter combinations were profitable on the unseen window (median -4.0%, worst -7.7%, best +1.5%).

**Monte Carlo** (5000 reshuffles of the 206 unseen trades): 5th percentile return -27.3%, median -10.6%, chance of losing money 88%, bad-case drawdown -29.6%.

**Luck check:** p = 0.880 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | -2.5% | -9.6% |
| bull | 86 | +0.9% | +3.7% |
| chop | 322 | -9.4% | -10.6% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -6.8% | -11.9% |
| trending | 217 | +0.1% | +0.1% |
| wild | 76 | -4.2% | -20.3% |

**The market that breaks it:** wild state (-20.3% annualised over 76 days).

**Earliest warning sign it is fading:** Win rate of filled trades dropping below 55% over the last 50 trades, or the 4h bounce after expanded-vol breakdowns falling below 30 bps.

## Final check
| Question | Answer |
|---|---|
| Does it win on data it has never seen, after fees and funding? | **no** |
| Across 50+ trades? | yes |
| With fees doubled? | **no** |
| Does it hold across nearby settings? | **no** |
| Free of look-ahead? | yes |
| Still profitable if every order goes in one bar late? | **no** |
| Does it beat simply holding, after costs? | **no** |

## Scores (1-5)
| Out-of-sample profit | Max drawdown | Trade count | Losing streak | Bear and chop | Total |
|---|---|---|---|---|---|
| 1 | 1 | 4 | 1 | 1 | 8/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
The statistics are the strongest of the set but the money is the smallest: 3.3% a year in-sample, and fees doubled halves it. It is a falling-knife catch whose average is 0.22 ATR against a typical 1.6 ATR adverse move, so it only works with maker fills and a quick take-profit; two of the structural neighbours lose (limit 2.0 ATR, hold 24) and a shallower limit of 0.5 ATR loses 16%. Limit fills in the backtest assume a fill whenever price trades 1 bp through the limit, which is optimistic in a collapsing book. 2022 contributed only +0.7%. The Guardian closed 16 trades after loss streaks, and in a multi-day liquidation it will be stopped on every symbol together.
