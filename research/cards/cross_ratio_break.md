# cross_ratio_break

**Verdict:** PASSED every gate. Score 13/25. Regime it needs: **trending**.

## The idea
When an alt's price ratio to BTC breaks its 14-day range, trade the alt in that direction for up to a week, long only when BTC is above its 20-day average and short only when below.

## Why the edge exists
A coin breaking out against BTC is being repriced on its own flow, and relative repricings last days because holders rebalance between coins slowly.

**Who is on the losing side:** Pair traders fading the ratio back to its range, and holders slow to rotate out of the weak coin.

## Exact rules
- **Entry:** For every universe symbol except PF_XBTUSD: ratio = close / PF_XBTUSD close on the same bar. up = ratio[t] > max(ratio[t-N .. t-1]); down = ratio[t] < min(ratio[t-N .. t-1]). First-trigger rule: 'up' counts only if 'up' was False on each of the previous 48 bars (same for 'down'). Long at the next open if first up AND BTC close[t] > SMA(BTC close, 480). Short at the next open if first down AND BTC close[t] < SMA(BTC close, 480).
- **Stop:** long: close[t] * (1 - stop_k * dvol); short: close[t] * (1 + stop_k * dvol); dvol = ta.realized_vol(close, 168) * sqrt(24).
- **Exit:** Time stop only: max_hold = 168 bars. No take-profit, no trailing, no exit signal.
- **Limit order life:** 1 bar(s). **Time stop:** 168 bars.
- **Default parameters:** `{"N": 336, "btc_ma": 480, "stop_k": 2.5, "refractory": 48}`
- **Code:** `desk/strategies/s_cross_ratio_break.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | +7.0% | -62.2% | -23.5% |
| Max drawdown | -13.2% | -74.4% | -51.3% |
| Return / drawdown (annual) | 0.39 | -0.61 | -0.33 |
| Sharpe | 0.32 | -0.84 | -0.41 |

- Trades: **328**, win rate 42%, average trade +0.04R, profit factor 1.12
- Fees paid $153, funding paid $47 (negative = received), gross P&L $904
- **Worst month:** -6.1%. **Longest losing streak:** 23 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +10.0%, max drawdown -14.6%, 494 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +7.16% | 32 |
| 2024-01-01 | -3.12% | 20 |
| 2024-04-01 | -0.87% | 29 |
| 2024-07-01 | -3.77% | 48 |
| 2024-10-01 | +3.52% | 37 |
| 2025-01-01 | +2.80% | 47 |
| 2025-04-01 | -0.40% | 64 |
| 2025-07-01 | +2.49% | 67 |
| 2025-10-01 | -3.82% | 61 |
| 2026-01-01 | +4.35% | 70 |
| 2026-04-01 | +1.61% | 19 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | +5.5% | -13.9% |
| Slippage doubled | +5.9% | -13.6% |
| Funding doubled | +5.9% | -13.8% |
| All costs doubled | +3.5% | -15.1% |
| Entered one bar late | +6.6% | -14.3% |
| Guardian switched off | +11.3% | -11.1% |
| No costs at all | +10.1% | -12.2% |

**Nearby settings:** 67% of 9 parameter combinations were profitable on the unseen window (median +1.5%, worst -5.9%, best +8.4%).

**Monte Carlo** (5000 reshuffles of the 328 unseen trades): 5th percentile return -14.9%, median +6.6%, chance of losing money 31%, bad-case drawdown -23.1%.

**Luck check:** p = 0.335 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | -4.8% | -18.6% |
| bull | 86 | +6.3% | +26.7% |
| chop | 322 | +5.5% | +6.2% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -2.1% | -3.8% |
| trending | 217 | +14.1% | +23.7% |
| wild | 76 | -4.9% | -23.5% |

**The market that breaks it:** wild state (-23.5% annualised over 76 days).

**Earliest warning sign it is fading:** Alt minus BTC forward 72h return after ratio breakouts and breakdowns, averaged over the trailing 60 events, at or below zero (design: +94 and +69 bps), or the short side losing for two consecutive quarters while BTC is below its 480h average.

## Coinbase-listed coins only
Same audit, entries allowed only in coins Coinbase lists today as perpetual-style futures: +2.9%, max drawdown -11.2%, 220 trades, fees doubled +1.5%, one bar late +5.6%, p = 0.448. Gates failed on that set: none. (Today's list applied to history; Coinbase fees, funding and contract sizes are not modelled.)

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
| 3 | 2 | 4 | 1 | 3 | 13/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
Weakest of the tradable four. The edge that is consistent across years is relative to BTC; the engine trades the alt outright, and the BTC-trend gate does not remove the beta (two of three design years lost at the default, the short side lost overall, Sharpe 0.2-0.6 with 12-16% drawdowns). Entries cluster when several alts break against BTC in the same hours, which caused 91 Guardian exits out of 417 trades. It overlaps with cross_rs_leader_long on the long side. Passing 'beats holding the basket' looks unlikely unless validation is a bear market in which alts bleed against BTC.
