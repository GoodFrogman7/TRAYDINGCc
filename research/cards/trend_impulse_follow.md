# trend_impulse_follow

**Verdict:** PASSED every gate. Score 17/25. Regime it needs: **trending**.

## The idea
After one hourly bar that moves more than 2.5 ATR on more than 3 times normal volume in the direction of the 14-day trend, enter with it and hold up to three days.

## Why the edge exists
A violent high-volume hour in the direction of the trend is a forced or informed repricing that the rest of the market finishes over the next few days.

**Who is on the losing side:** Traders who fade the spike at market, and stops and liquidations of those leaning against the trend.

## Exact rules
- **Entry:** At the close of bar t: a1 = ta.atr(df, 24).shift(1); mv = (close - open) / a1; volr = volume / ta.sma(volume, 168).shift(1); tr = sign(ta.ret(close, L).shift(1)). LONG if mv > k and volr > v and tr > 0. SHORT if mv < -k and volr > v and tr < 0. No signal while any input is NaN. Market order at the next bar's open.
- **Stop:** Long: close[t] - stop_atr*ta.atr(df,24)[t]. Short: close[t] + stop_atr*ta.atr(df,24)[t]. Fixed, never trailed.
- **Exit:** Time stop after 72 bars (max_hold=72) or the protective stop. No take-profit, no signal exit.
- **Limit order life:** 1 bar(s). **Time stop:** 72 bars.
- **Default parameters:** `{"L": 336, "k": 2.5, "v": 3.0, "stop_atr": 3.0}`
- **Code:** `desk/strategies/s_trend_impulse_follow.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | +24.8% | -62.2% | -23.5% |
| Max drawdown | -11.4% | -74.4% | -51.3% |
| Return / drawdown (annual) | 1.58 | -0.61 | -0.33 |
| Sharpe | 0.86 | -0.84 | -0.41 |

- Trades: **268**, win rate 40%, average trade +0.19R, profit factor 1.35
- Fees paid $404, funding paid $71 (negative = received), gross P&L $2,958
- **Worst month:** -4.0%. **Longest losing streak:** 14 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +35.8%, max drawdown -15.1%, 523 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +1.11% | 64 |
| 2024-01-01 | +4.92% | 41 |
| 2024-04-01 | +1.84% | 72 |
| 2024-07-01 | +3.83% | 57 |
| 2024-10-01 | -0.77% | 21 |
| 2025-01-01 | +3.22% | 33 |
| 2025-04-01 | +11.96% | 49 |
| 2025-07-01 | +1.57% | 42 |
| 2025-10-01 | +4.54% | 67 |
| 2026-01-01 | +3.74% | 46 |
| 2026-04-01 | -0.21% | 31 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | +20.8% | -12.4% |
| Slippage doubled | +21.5% | -12.3% |
| Funding doubled | +23.5% | -11.5% |
| All costs doubled | +16.2% | -13.3% |
| Entered one bar late | +22.0% | -17.2% |
| Guardian switched off | +12.2% | -16.9% |
| No costs at all | +32.6% | -10.2% |

**Nearby settings:** 100% of 18 parameter combinations were profitable on the unseen window (median +18.5%, worst +0.1%, best +55.5%).

**Monte Carlo** (5000 reshuffles of the 268 unseen trades): 5th percentile return -8.9%, median +23.5%, chance of losing money 12%, bad-case drawdown -24.2%.

**Luck check:** p = 0.120 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | +3.4% | +13.2% |
| bull | 86 | +5.4% | +22.7% |
| chop | 322 | +16.1% | +18.2% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -6.9% | -12.1% |
| trending | 217 | +35.7% | +60.1% |
| wild | 76 | -4.0% | -19.1% |

**The market that breaks it:** wild state (-19.1% annualised over 76 days).

**Earliest warning sign it is fading:** Mean 24-hour follow-through over the last 50 signals below zero (design +39 bps), or more than 60% of trades ending at the stop (design 48%).

## Final check
| Question | Answer |
|---|---|
| Does it win on data it has never seen, after fees and funding? | yes |
| Across 50+ trades? | yes |
| With fees doubled? | yes |
| Does it hold across nearby settings? | yes |
| Free of look-ahead? | yes |
| Still profitable if every order goes in one bar late? | yes |
| Does it beat simply holding, after costs? | yes |

## Scores (1-5)
| Out-of-sample profit | Max drawdown | Trade count | Losing streak | Bear and chop | Total |
|---|---|---|---|---|---|
| 5 | 2 | 4 | 1 | 5 | 17/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
The drawdown is the problem: -30% of starting equity (about 60 R, trough May 2023) at 0.5% risk, because impulse bars are market-wide and up to ten correlated positions open in the same hour (gross exposure peaked at 2.3x equity). Capping new entries per bar did not fix it reliably (cap 1 -18%, cap 2 -33%, cap 3 -27%). The clustered t-stat is weak and the 72-hour peak sits between two horizons with less than half the edge, so part of the 72-hour number is luck. Coin-specific impulses (BTC quiet in the same hour) did not continue at all (-33 bps, n=223). Win rate is 39% with streaks of 16, which the three-losses Guardian halt punishes (profit is +119% without it). It overlaps with trend_day_follow; do not count them as two independent edges.
