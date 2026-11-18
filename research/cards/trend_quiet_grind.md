# trend_quiet_grind

**Verdict:** PASSED every gate, then REFUTED by the independent skeptic. Score 16/25. Regime it needs: **trending**.

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

## Coinbase-listed coins only
Same audit, entries allowed only in coins Coinbase lists today as perpetual-style futures: +12.0%, max drawdown -10.9%, 136 trades, fees doubled +10.9%, one bar late +7.1%, p = 0.260. Gates failed on that set: none. (Today's list applied to history; Coinbase fees, funding and contract sizes are not modelled.)

## Independent skeptic
**Refuted** (confidence medium). No bug, no look-ahead and realistic costs, but the +10.4% cannot be told apart from luck (p = 0.27): it comes from two rallies (Apr-May and Jul 2025), vanishes if 3 of the 135 trades are removed, and the strategy has lost money since August 2025, so it should not be relied on as champion.

- Code matches the Hunter's rules: yes. Look-ahead found: no.
- Real order-book costs: Costs are not the weakness.

Strongest evidence against:
- Luck cannot be excluded: p = 0.271 (0.31 when resampling the 12 episodes), no Holm survival, and 4 of 15 audited strategies reach p <= 0.271 where chance alone predicts 4.1.
- Two rallies carry everything: Apr-May 2025 and Jul 2025 made +$2,398; the other ten episodes lost -$1,359. Without the best quarter the return is -0.5%, without the best 3 trades of 135 it is -$25, and without the best 5 exit days it is -19.6%.
- It has been losing going into the sealed period: trades exiting from 1 Aug 2025 onward total -$700 (43 trades, 21% winners), and the last three quarters are -0.4%, -4.5% and +0.2%.
- The Hunter's own 'fading' alarm is already on at the end of validation: the last 30 trades won 20% (alarm level 35%, design 44%) for -$440, and the Dec 2025-Jan 2026 episode was 17 trades in 10 coins that lost -$488 together.
- The strategy as the Hunter specified it (q 0.8, stop 5 ATR) did not replicate: +22.6% in design, -0.03% in validation with a -21.8% drawdown and a 13-trade losing streak. The pass rests on the 7-ATR cells the walk-forward picked.
- Random entry hours in the same coin-months do as well or better 53% of the time, and against plain 14-day momentum exposure the smoothness filter is not significant (p about 0.10).
- The result swings by more than its own size on arbitrary changes: shifting signals 3-48 hours gives +5.0% to +23.8%, and the Coinbase re-fit drops from +12.0% to +7.1% when one bar late.
- Single-coin dependence: without ETH the return is +3.4% (p = 0.43); without ETH and SUI it is -0.2%.

Evidence for:
- Implementation is faithful: independent re-implementation matches on 6.6 million rows, and all 135 trades reconcile against raw bars.
- No look-ahead: 3 extra leak-test seeds (357 probes) plus the audit's 349 probes and 191-probe trade replay all clean; universe ranking confirmed to use the prior 30 days.
- Costs are realistic and the result is insensitive to them: +10.25% with actual order-book costs, +10.18% when also one bar late, +8.33% with actual slippage, doubled fees, doubled funding and one bar late.
- It beats blind long exposure: real result is above 99.3% of 300 random coin-month long draws (mean -6.3%), while always-long lost -35.8%.
- Coinbase-listed coins only still pass every gate (+12.0% re-fitted, 136 trades), and BTC and ETH alone made +9.1% (27 trades, p = 0.08).
- 5 of 6 grid cells were profitable in validation (median +7.6%), and the walk-forward over all 11 quarters since Oct 2023 made +44.0%, though 5 of those quarters are inside the Hunter's design window.

What the owner must know:
- My refutation is statistical, not a bug: the code does what the rules say and the costs are fair. The problem is that +10.4% over 17 months is the kind of number chance produces about one time in four, and this desk tested 15 strategies.
- This is a long-only momentum rule that makes money only in a few broad rallies. Expect long stretches of small losses (63% of trades lose; 10 of 12 trade clusters lost or barely broke even) while waiting for a rally that may not come.
- It was losing at the end of the test window (-$700 since August 2025) and its own designer's warning sign (win rate under 35% over the last 30 trades) is already triggered at 20%.
- If it is paper traded anyway, do not treat a profitable six months as proof: one rally decides the outcome. Judge it on whether it loses small outside rallies, and stop if a cluster of 3 or more coins stops out together again.
- The backtest's safety halt resets itself at midnight UTC; the live bot stays halted until you resume it. There were about 9 halts in 17 months, and the halt behaviour changes the result (Guardian off: +7.4%).
- On Coinbase, whole-contract sizing matters for BTC: a $50-risk position wanted 0.65-2.59 contracts, so real risk per BTC trade would be $34-$77, or the trade is skipped. Contract sizes for other coins were not checked, and the Coinbase coin list is today's list applied to the past.
- 81% of position-hours used estimated rather than published funding. The amount is small ($49) and 5x that still leaves +8.45%, but Coinbase's funding and fees differ from Kraken's and were not modelled.
- The account in the backtest does not compound and cannot go broke; drawdown reached -12.2% in the walk-forward and -17% to -22% in neighbouring fixed settings.
- Stray scratch files from my runs (trades.pkl, s3_trade_costs.csv, null_A.npy) briefly landed in the repo root; I moved them into my verify folder and fixed the scripts' paths. Nothing under desk/, data/, docs/, tests/, config/ or research/results was touched, and no bar from 2026-05-18 onward was loaded.

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
