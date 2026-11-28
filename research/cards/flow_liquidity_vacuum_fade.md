# flow_liquidity_vacuum_fade

**Verdict:** FAILED: profit_after_costs, profit_fees_doubled, nearby_settings_hold, beats_holding. Score 9/25. Regime it needs: **wild**.

## The idea
Buy a 4-hour drop of more than 2 ATR only when the $10k order-book spread has blown out to at least 3x its normal level, and hold 24 hours.

## Why the edge exists
When market makers pull quotes the price falls through an empty book further than the selling justifies, and it retraces when quotes return.

**Who is on the losing side:** Stop-market and liquidation sellers who paid for immediacy in an empty book.

## Exact rules
- **Entry:** half = (ask_10k - bid_10k) / (ask_10k + bid_10k), set to NaN where <= 0. rel = half / half.rolling(168, min_periods=48).median().shift(1). At the close of bar t: if rel >= sp_mult AND (close.shift(4) - close) > drop_atr * ta.atr(df, 24): side = +1, market at the next open. No signal while bid_10k / ask_10k or ATR is NaN.
- **Stop:** signal-bar close * (1 - stop_pct): a fixed-percentage disaster stop, NOT an ATR multiple
- **Exit:** Time stop only: max_hold = 24 bars.
- **Limit order life:** 1 bar(s). **Time stop:** 24 bars.
- **Default parameters:** `{"sp_mult": 3.0, "drop_atr": 2.0, "stop_pct": 0.08}`
- **Code:** `desk/strategies/s_flow_liquidity_vacuum_fade.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | -5.1% | -62.2% | -23.5% |
| Max drawdown | -6.8% | -74.4% | -51.3% |
| Return / drawdown (annual) | -0.55 | -0.61 | -0.33 |
| Sharpe | -0.94 | -0.84 | -0.41 |

- Trades: **106**, win rate 42%, average trade -0.10R, profit factor 0.65
- Fees paid $65, funding paid $6 (negative = received), gross P&L $-440
- **Worst month:** -3.2%. **Longest losing streak:** 12 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +10.0%, max drawdown -6.8%, 299 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +10.12% | 43 |
| 2024-01-01 | +1.44% | 55 |
| 2024-04-01 | -4.38% | 33 |
| 2024-07-01 | +3.62% | 29 |
| 2024-10-01 | +4.33% | 33 |
| 2025-01-01 | -3.27% | 31 |
| 2025-04-01 | +0.99% | 22 |
| 2025-07-01 | +0.70% | 35 |
| 2025-10-01 | -3.46% | 13 |
| 2026-01-01 | -0.19% | 4 |
| 2026-04-01 | +0.12% | 1 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | -5.6% | -7.1% |
| Slippage doubled | -5.1% | -6.7% |
| Funding doubled | -5.0% | -6.7% |
| All costs doubled | -5.8% | -7.4% |
| Entered one bar late | +13.7% | -5.5% |
| Guardian switched off | -4.4% | -8.7% |
| No costs at all | -4.0% | -6.0% |

**Nearby settings:** 0% of 27 parameter combinations were profitable on the unseen window (median -7.4%, worst -20.0%, best -2.3%).

**Monte Carlo** (5000 reshuffles of the 106 unseen trades): 5th percentile return -12.8%, median -5.1%, chance of losing money 87%, bad-case drawdown -13.7%.

**Luck check:** p = 0.875 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | -1.3% | -5.2% |
| bull | 86 | -1.9% | -7.9% |
| chop | 322 | -1.9% | -2.2% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -2.1% | -3.7% |
| trending | 217 | -2.0% | -3.4% |
| wild | 76 | -1.0% | -4.9% |

**The market that breaks it:** bull trend (-7.9% annualised over 86 days).

**Earliest warning sign it is fading:** Signals with spread >= 3x whose 12h forward return averages below +30 bps over the last 40 events, or the control group (normal spread, same drop) rising to match it.

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
| 1 | 3 | 3 | 1 | 1 | 9/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
It has never seen a bear market: the only data is the 2023-24 uptrend, where buying dips worked generally. Without the best five of 79 entry days the result is -3.3%. The default sits on a ridge: spread 4x and drop 2.5 ATR are nearly flat, so the +19% is partly a lucky cell. The engine charges the trailing 7-day median spread while the signal fires when the spread is at least 3x that, so real entry cost is higher than modelled (the slippage x3 run is the honest one). BTC and ETH give 83 of 149 trades and almost no profit, because 3x of a 0.3 bps spread is not stress. The fixed 8% stop means a real crash takes the full 0.5% on every position at once. It is unknown whether bid_10k/ask_10k are hour averages or snapshots.
