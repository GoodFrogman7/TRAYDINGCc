# flow_stress_bid

**Verdict:** FAILED: trades_50_plus, profit_after_costs, profit_fees_doubled, nearby_settings_hold, holds_one_bar_late, beats_holding. Score 6/25. Regime it needs: **wild**.

## The idea
When BTC dumps 3 sigma in one hour on a volume surge and an alt barely moves, buy that alt for 24 hours.

## Why the edge exists
An alt that holds while BTC is being sold hard has a resting bid that just absorbed forced selling, so supply is exhausted and it leads once BTC stops falling.

**Who is on the losing side:** Sellers who dumped the alt into that bid, and shorts positioned for it to catch down to BTC.

## Exact rules
- **Entry:** rz(x) = (x/x.shift(1) - 1) / (x/x.shift(1) - 1).rolling(168, min_periods=100).std().shift(1). vol_rel = volume / volume.rolling(168, min_periods=100).median().shift(1). At the close of bar t, for every symbol EXCEPT PF_XBTUSD and PF_ETHUSD: if rz(PF_XBTUSD close) <= -z_btc AND PF_XBTUSD vol_rel >= 3.0 (BTC series reindexed to the symbol's index, missing = no signal) AND rz(symbol close) > z_alt AND ta.atr(df, 24) not NaN: side = +1, market at the next open.
- **Stop:** signal-bar close - stop_atr * ta.atr(df, 24) of the symbol
- **Exit:** Time stop only: max_hold = 24 bars.
- **Limit order life:** 1 bar(s). **Time stop:** 24 bars.
- **Default parameters:** `{"z_btc": 3.0, "z_alt": -1.0, "stop_atr": 3.0}`
- **Code:** `desk/strategies/s_flow_stress_bid.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | -2.6% | -62.2% | -23.5% |
| Max drawdown | -5.5% | -74.4% | -51.3% |
| Return / drawdown (annual) | -0.35 | -0.61 | -0.33 |
| Sharpe | -0.57 | -0.84 | -0.41 |

- Trades: **25**, win rate 28%, average trade -0.21R, profit factor 0.60
- Fees paid $17, funding paid $-3 (negative = received), gross P&L $-250
- **Worst month:** -2.8%. **Longest losing streak:** 7 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +3.7%, max drawdown -11.0%, 118 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +6.99% | 21 |
| 2024-01-01 | +2.49% | 13 |
| 2024-04-01 | -1.86% | 13 |
| 2024-07-01 | +2.28% | 29 |
| 2024-10-01 | -3.59% | 17 |
| 2025-01-01 | -2.47% | 9 |
| 2025-04-01 | +0.00% | 0 |
| 2025-07-01 | +0.00% | 0 |
| 2025-10-01 | -0.53% | 4 |
| 2026-01-01 | -2.03% | 6 |
| 2026-04-01 | +2.38% | 6 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | -2.8% | -5.7% |
| Slippage doubled | -2.9% | -5.7% |
| Funding doubled | -2.7% | -5.6% |
| All costs doubled | -3.1% | -5.8% |
| Entered one bar late | -3.2% | -6.2% |
| Guardian switched off | -2.5% | -5.4% |
| No costs at all | -2.3% | -5.3% |

**Nearby settings:** 19% of 27 parameter combinations were profitable on the unseen window (median -2.1%, worst -22.0%, best +6.6%).

**Monte Carlo** (5000 reshuffles of the 25 unseen trades): 5th percentile return -9.4%, median -2.8%, chance of losing money 74%, bad-case drawdown -10.0%.

**Luck check:** p = 0.747 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | -1.3% | -4.9% |
| bull | 86 | -0.4% | -1.7% |
| chop | 322 | -1.0% | -1.1% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -1.3% | -2.3% |
| trending | 217 | -0.2% | -0.3% |
| wild | 76 | -1.2% | -5.7% |

**The market that breaks it:** wild state (-5.7% annualised over 76 days).

**Earliest warning sign it is fading:** The 4h forward return after signals staying negative over the last 30 signals (already -7 bps in 2024), or stop-outs above 35% of trades.

## Final check
| Question | Answer |
|---|---|
| Does it win on data it has never seen, after fees and funding? | **no** |
| Across 50+ trades? | **no** |
| With fees doubled? | **no** |
| Does it hold across nearby settings? | **no** |
| Free of look-ahead? | yes |
| Still profitable if every order goes in one bar late? | **no** |
| Does it beat simply holding, after costs? | **no** |

## Scores (1-5)
| Out-of-sample profit | Max drawdown | Trade count | Losing streak | Bear and chop | Total |
|---|---|---|---|---|---|
| 1 | 1 | 1 | 1 | 2 | 6/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
Day-clustered t is only about 1.5 and the profit is concentrated: without the best five of 69 entry days the result is -6.8%, and only 46% of entry days make money. 2024, the most recent year, is flat (+0.5%) and negative in several neighbours (stop 2.5 ATR -5.7%, z_alt -1.5 -5.5%), because the first 4 hours turned from +134 bps in 2023 to -7 bps in 2024. It is long alts straight after a BTC dump, so in a sustained crash it buys the last thing to fall. Two symbols (MATIC +8.0%, AVAX +6.7%) supply most of the P&L. An alt that 'held' may simply not have traded that hour on a thin book.
