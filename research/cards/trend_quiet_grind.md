# trend_quiet_grind

**Verdict:** PASSED every gate. Score 16/25. Regime it needs: **trending**.

## The idea
Buy a coin whose 14-day rise has been unusually smooth (efficiency ratio in the top 20% of its own last 180 days) and hold up to a week; long only.

## Why the edge exists
A two-week rise with very little back-and-forth is a patient buyer working a large order, and that buying is usually not finished when the pattern becomes visible.

**Who is on the losing side:** Short sellers and early profit-takers who fade a slow grind because it has gone far without a blow-off.

## Exact rules
- **Entry:** At the close of bar t: er = ta.efficiency_ratio(close, L); rk = ta.rolling_rank(er, 4320); r = ta.ret(close, L); atr = ta.atr(df, 24). LONG if rk >= q and r > 0 and atr is not NaN. Market order at the next bar's open. Evaluated every bar; re-entry after an exit is allowed if the condition still holds. Never short.
- **Stop:** close[t] - stop_atr*atr[t]. Fixed, never trailed.
- **Exit:** Time stop after 168 bars (max_hold=168) or the protective stop. No take-profit, no signal exit.
- **Limit order life:** 1 bar(s). **Time stop:** 168 bars.
- **Default parameters:** `{"L": 336, "q": 0.8, "stop_atr": 5.0}`
- **Code:** `desk/strategies/s_trend_quiet_grind.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | +10.4% | -62.2% | -23.5% |
| Max drawdown | -12.2% | -74.4% | -51.3% |
| Return / drawdown (annual) | 0.62 | -0.61 | -0.33 |
| Sharpe | 0.63 | -0.84 | -0.41 |

- Trades: **135**, win rate 37%, average trade +0.15R, profit factor 1.34
- Fees paid $93, funding paid $49 (negative = received), gross P&L $1,181
- **Worst month:** -4.5%. **Longest losing streak:** 7 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +44.0%, max drawdown -12.2%, 304 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +5.58% | 37 |
| 2024-01-01 | +0.75% | 17 |
| 2024-04-01 | -0.01% | 7 |
| 2024-07-01 | +5.61% | 52 |
| 2024-10-01 | +21.63% | 56 |
| 2025-01-01 | -6.59% | 27 |
| 2025-04-01 | +10.92% | 43 |
| 2025-07-01 | +10.87% | 29 |
| 2025-10-01 | -0.41% | 6 |
| 2026-01-01 | -4.55% | 16 |
| 2026-04-01 | +0.15% | 14 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | +9.5% | -12.4% |
| Slippage doubled | +9.8% | -12.3% |
| Funding doubled | +9.5% | -12.4% |
| All costs doubled | +8.0% | -12.7% |
| Entered one bar late | +10.3% | -11.8% |
| Guardian switched off | +7.4% | -13.8% |
| No costs at all | +12.4% | -11.7% |

**Nearby settings:** 83% of 6 parameter combinations were profitable on the unseen window (median +7.6%, worst -0.0%, best +11.7%).

**Monte Carlo** (5000 reshuffles of the 135 unseen trades): 5th percentile return -14.8%, median +9.4%, chance of losing money 27%, bad-case drawdown -20.7%.

**Luck check:** p = 0.271 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | +0.6% | +2.4% |
| bull | 86 | +6.6% | +27.9% |
| chop | 322 | +3.2% | +3.6% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -10.2% | -17.8% |
| trending | 217 | +21.7% | +36.5% |
| wild | 76 | -1.1% | -5.2% |

**The market that breaks it:** ranging state (-17.8% annualised over 209 days).

**Earliest warning sign it is fading:** Win rate over the last 30 trades under 35% (design 44%), or three or more coins triggering in the same week and then stopping out together.

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
| 3 | 2 | 3 | 3 | 5 | 16/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
It is long only and has only been right in bull years: 2022 lost money in every variant tested, and I have no evidence it does anything but bleed in a bear or sideways market. Net-of-cost avg R is about 1.6 standard errors from zero. The Guardian halt costs more than half the no-Guardian profit (+43% without it). It needs 4656 bars (194 days) of history per coin, so newly listed coins in the top 10 produce no signals for their first six months. Funding is paid on longs for a week at a time ($738 of funding against $325 of fees in design).
