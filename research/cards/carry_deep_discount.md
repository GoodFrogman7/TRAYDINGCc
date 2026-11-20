# carry_deep_discount

**Verdict:** PASSED every gate. Score 17/25. Regime it needs: **wild**.

## The idea
Buy the first hour a perp's 8h average premium is both 2 standard deviations below its own 30-day norm and at least 5 bps below index.

## Why the edge exists
A sustained perp discount means sellers are paying up to get out through the perp (liquidations, panic hedging) while longs are paid funding, and the gap closes when the forced flow stops.

**Who is on the losing side:** Forced and panicked perp sellers who accept a price below the spot index.

## Exact rules
- **Entry:** pm = premium.rolling(8, min_periods=8).mean(); med = pm.rolling(720, min_periods=360).median(); sd = premium.rolling(720, min_periods=360).std() (raw hourly premium); zs = (pm - med)/sd. raw[t] = (zs[t] <= -z) AND (pm[t] <= -floor_bp/1e4) AND ATR(24) not NaN. Signal only on the first qualifying bar: raw[t] is True and raw was False on every one of the previous 24 bars (raw.shift(1).rolling(24, min_periods=1).max() == 0). Long at market on the open of t+1.
- **Stop:** close[t] - stop_atr * ta.atr(df, 24)[t]  (default 3.0 ATR)
- **Exit:** Time stop only: close at 36 bars. No take-profit, no trail.
- **Limit order life:** 1 bar(s). **Time stop:** 36 bars.
- **Default parameters:** `{"pm_n": 8, "norm_n": 720, "z": 2.0, "floor_bp": 5.0, "cool": 24, "atr_n": 24, "stop_atr": 3.0}`
- **Code:** `desk/strategies/s_carry_deep_discount.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | +4.0% | -62.2% | -23.5% |
| Max drawdown | -5.7% | -74.4% | -51.3% |
| Return / drawdown (annual) | 0.51 | -0.61 | -0.33 |
| Sharpe | 0.47 | -0.84 | -0.41 |

- Trades: **92**, win rate 42%, average trade +0.09R, profit factor 1.22
- Fees paid $76, funding paid $-46 (negative = received), gross P&L $431
- **Worst month:** -2.0%. **Longest losing streak:** 6 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +13.4%, max drawdown -5.7%, 137 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +0.43% | 2 |
| 2024-01-01 | +3.40% | 9 |
| 2024-04-01 | -0.14% | 10 |
| 2024-07-01 | +5.19% | 11 |
| 2024-10-01 | +0.55% | 13 |
| 2025-01-01 | +2.39% | 19 |
| 2025-04-01 | +5.21% | 27 |
| 2025-07-01 | -0.15% | 10 |
| 2025-10-01 | -1.32% | 23 |
| 2026-01-01 | -1.69% | 10 |
| 2026-04-01 | -0.43% | 3 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | +3.4% | -6.1% |
| Slippage doubled | +3.4% | -6.0% |
| Funding doubled | +4.0% | -5.7% |
| All costs doubled | +2.6% | -6.5% |
| Entered one bar late | +4.4% | -4.1% |
| Guardian switched off | +4.2% | -5.8% |
| No costs at all | +5.1% | -5.2% |

**Nearby settings:** 78% of 9 parameter combinations were profitable on the unseen window (median +0.6%, worst -1.5%, best +4.3%).

**Monte Carlo** (5000 reshuffles of the 92 unseen trades): 5th percentile return -6.6%, median +3.9%, chance of losing money 28%, bad-case drawdown -9.9%.

**Luck check:** p = 0.307 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | +1.3% | +5.1% |
| bull | 86 | +1.1% | +4.9% |
| chop | 322 | +1.5% | +1.8% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -3.9% | -6.8% |
| trending | 217 | +5.9% | +9.9% |
| wild | 76 | +2.0% | +9.7% |

**The market that breaks it:** ranging state (-6.8% annualised over 209 days).

**Earliest warning sign it is fading:** Trade count drops below ~3 a month, or 2022-style results (flat or negative after costs) for two consecutive quarters while the market is not in a bear.

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
| 2 | 4 | 2 | 4 | 5 | 17/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
Same bet as carry_cascade_discount on the big days, without the breadth check that removed the coin-specific losers (those lost 156 bps on average in 2022); do not run both at full risk. Flat in the 2022 bear before stops. BTC/ETH contribute nothing. z=2.5 is the weakest cell (avgR 0.14-0.17) between two better ones, which smells of noise. If the venue's premium behaviour changes (tighter arbitrage, different funding formula) the 5 bps floor stops firing.
