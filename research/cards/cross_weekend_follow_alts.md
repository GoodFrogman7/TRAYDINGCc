# cross_weekend_follow_alts

**Verdict:** PASSED every gate, then REFUTED by the independent skeptic. Score 16/25. Regime it needs: **trending**.

## The idea
After the same weekend signal, trade the three highest-volume alts of the month for 24 hours in BTC's weekend direction, but only those whose own weekend move agrees with BTC's.

## Why the edge exists
Alts carry the market's weekend direction into Monday with more leverage than the majors, and those already moving with BTC have no coin-specific flow opposing it.

**Who is on the losing side:** Weekend traders fading the move in alts, and holders of alts on the wrong side when Monday desks arrive.

## Exact rules
- **Entry:** Same signal bar and same w as cross_weekend_follow_majors: at the close of the Sunday 21:00 UTC bar, w = PF_XBTUSD close[t]/close[t-48] - 1, require abs(w) >= thr. Candidates = the first n_alt symbols of that month's universe list (store.universe()[YYYY-MM], ordered by 30-day median USD volume) after removing PF_XBTUSD and PF_ETHUSD. Open side = sign(w) in a candidate only if sign(candidate close[t]/close[t-48] - 1) == sign(w). Market at the next open (Sunday 22:00 UTC).
- **Stop:** stop = close[t] - side * stop_atr * ATR(24)[t], ATR = ta.atr(df, 24) on the alt's own bars.
- **Exit:** Time stop only: max_hold = 24 bars (closes at the Monday 22:00 UTC open).
- **Limit order life:** 1 bar(s). **Time stop:** 24 bars.
- **Default parameters:** `{"look": 48, "thr": 0.005, "stop_atr": 5.0, "n_alt": 3}`
- **Code:** `desk/strategies/s_cross_weekend_follow_alts.py`

## Position size
Each trade risks 0.5% of a $10,000 account ($50) between entry and stop. One position's notional is capped at 1x equity and total exposure at 3x. Sizes do not compound.

## Results after fees, funding and slippage
Unseen data, walk-forward, 2025-01-01 to 2026-05-17:

| | Strategy | Hold top-10 basket | Hold BTC |
|---|---|---|---|
| Total return | +8.6% | -62.2% | -23.5% |
| Max drawdown | -4.9% | -74.4% | -51.3% |
| Return / drawdown (annual) | 1.29 | -0.61 | -0.33 |
| Sharpe | 0.97 | -0.84 | -0.41 |

- Trades: **129**, win rate 50%, average trade +0.13R, profit factor 1.45
- Fees paid $161, funding paid $13 (negative = received), gross P&L $1,036
- **Worst month:** -2.5%. **Longest losing streak:** 12 trades.

## Walk-forward
Parameters re-chosen every quarter on the prior 18 months, then traded unseen. All quarters (2023-10-01 to 2026-05-17): +23.9%, max drawdown -8.5%, 265 trades.

| Quarter | Return | Trades |
|---|---|---|
| 2023-10-01 | +10.02% | 47 |
| 2024-01-01 | +2.59% | 37 |
| 2024-04-01 | -0.03% | 17 |
| 2024-07-01 | +2.13% | 21 |
| 2024-10-01 | +0.58% | 14 |
| 2025-01-01 | +1.24% | 22 |
| 2025-04-01 | -0.24% | 25 |
| 2025-07-01 | -0.11% | 13 |
| 2025-10-01 | +2.87% | 26 |
| 2026-01-01 | +5.57% | 28 |
| 2026-04-01 | -0.71% | 15 |

## Stress tests (same unseen window)
| Test | Return | Max drawdown |
|---|---|---|
| Fees doubled | +7.0% | -5.3% |
| Slippage doubled | +7.7% | -5.0% |
| Funding doubled | +8.4% | -4.9% |
| All costs doubled | +5.9% | -5.5% |
| Entered one bar late | +8.6% | -5.3% |
| Guardian switched off | +8.4% | -5.1% |
| No costs at all | +11.3% | -4.4% |

**Nearby settings:** 78% of 27 parameter combinations were profitable on the unseen window (median +2.0%, worst -1.8%, best +15.8%).

**Monte Carlo** (5000 reshuffles of the 129 unseen trades): 5th percentile return -3.5%, median +8.4%, chance of losing money 13%, bad-case drawdown -9.6%.

**Luck check:** p = 0.131 that the average trade is not positive; does NOT survive correction for every idea tested.

## How it behaved by market
| BTC 30-day trend | Days | P&L | Annualised |
|---|---|---|---|
| bear | 94 | +4.7% | +18.3% |
| bull | 86 | +1.3% | +5.4% |
| chop | 322 | +2.6% | +3.0% |

| Market state | Days | P&L | Annualised |
|---|---|---|---|
| ranging | 209 | -0.2% | -0.4% |
| trending | 217 | +6.5% | +11.0% |
| wild | 76 | +2.3% | +11.0% |

**The market that breaks it:** ranging state (-0.4% annualised over 209 days).

**Earliest warning sign it is fading:** Same as the majors version, plus: the alt sleeve's trailing 20-trade average falls below +30 bps gross while the BTC leg is still positive (alts stopped following BTC on Mondays).

## Coinbase-listed coins only
Same audit, entries allowed only in coins Coinbase lists today as perpetual-style futures: +12.4%, max drawdown -5.1%, 145 trades, fees doubled +10.5%, one bar late +13.0%, p = 0.095. Gates failed on that set: none. (Today's list applied to history; Coinbase fees, funding and contract sizes are not modelled.)

## Independent skeptic
**Refuted** (confidence medium). The code is faithful, causal and its costs are realistic, but the +8.6% is not distinguishable from luck: it is one coin (XRP = 86%), three weekends and two quarters, it loses money exactly where its own thesis says it should win, and it should not be relied on as champion.

- Code matches the Hunter's rules: yes. Look-ahead found: no.
- Real order-book costs: Costs are not the problem.

Strongest evidence against:
- The profit runs opposite to the stated cause. By size of BTC's weekend move: under 0.5%: 20 trades +$594 (avg +0.59R); 0.5-1%: 19 trades +$172; 1-2%: 50 trades +$565; over 2%: 40 trades on 14 weekends -$469 (avg -0.23R, 11 stopped out, shorts -$518). 69% of the profit comes from 10 weekends where BTC had barely moved, and on 3 of those the BTC sign differs one hour earlier or later. The second-best weekend (+$277) was triggered by a BTC move of -0.09%.
- One coin: XRP is $743 of $862. Without it +1.2%, bootstrap p = 0.42.
- A handful of weekends: the best 3 of 52 exceed the whole profit (-$18 without them); without the best 5, -$330. Two quarters carry 98%.
- Not statistically distinguishable from luck: p = 0.131, fails Holm across 15 audited ideas; 10.3% of random-hour same-exposure draws do as well; 20.8% of other hour-of-week slots do as well.
- Fragile to the signal hour: moving the Sunday 21:00 signal by one to five hours gives $492, $81, $196, $392 before and $69, $1, -$689, -$82, $20 after, against $862. The spec hour is the best of ten adjacent hours.
- The BTC direction signal added nothing over being long: always long in the same top-3 alts on the same Sundays made $872 against the strategy's $766 (simulator figures); the strategy's shorts lost $123 at a 41% win rate.
- The spec's own default parameters made +2.3% in validation, with shorts at -$438. Across the grid, the nine thr=0 cells made +5.4% to +15.8%, the nine thr=0.5% cells +0.2% to +3.0%, and the nine thr=1% cells -1.8% to +0.4%. Performance worsens as the signal is required to be stronger.
- The same signal on BTC and ETH (cross_weekend_follow_majors) lost 2.0% in the same window and failed four gates.

Evidence for:
- Implementation is exact: 0 signal differences against an independent re-implementation in all 27 cells; the audited trades reproduce to the cent.
- No look-ahead: 918 truncation probes over three seeds with 0 mismatches, and the universe lists verified as ranked on the prior 30 days for 38 months.
- Execution is realistic: +8.53% with actual order-book costs, +8.57% one bar late with actual costs, +6.95% with fees doubled on top; positions are small against $10k depth and peak gross is 0.73x equity.
- Positive in both the design window (+17.3%, 193 trades) and the unseen window, with a contained drawdown (-4.9%) while the top-10 basket fell 62%.
- Weekend-signal slots as a group did better than weekday slots in validation (mean $462 against -$88), and the real direction beats a coin-flip direction in 94% of draws.

What the owner must know:
- My refutation is of the evidence, not the code. Nothing is broken; the result is simply too thin and too concentrated to trust with money. If the sealed test goes ahead anyway, a positive six months would still be mostly an XRP and long-side result unless the breakdown there looks different.
- If it is paper traded regardless, do it as a watch-list item, not as champion. Things to watch: profit excluding XRP, profit on shorts, and profit on weekends where BTC moved more than 2% (the case the idea is supposed to be about). All three were flat or negative in validation.
- It is one bet per week, up to three coins at once, all entered in the same hour and highly correlated: a wrong weekend costs up to about 1.5% of the account from this strategy alone (the worst weekend was -$158).
- On Coinbase the contracts are whole units: 500 XRP, 5 SOL, 5,000 DOGE. A $50-risk position is often about one contract, so real risk per trade would range from $34 to $94 when rounding to nearest, with 13 of 127 trades skipped; or up to $293 on one trade if at least one contract is always taken. The backtest's fractional sizing cannot be replicated on a $10,000 account.
- Costs and funding were modelled on Kraken; Coinbase's fees, funding and order books differ and were not tested. The Coinbase-subset audit uses today's listing applied to history, which is a forward-looking filter.
- Disclosure: to get Coinbase contract sizes I fetched Coinbase's public product list once. The response also showed today's prices for these coins, which is information from after the validation window. I used only the contract sizes; no dataset bar from 2026-05-18 onward was loaded, and none of the findings above depend on it. The scratch copy was deleted.
- The fourth leak-test seed (2026) had not finished when I reported; its output will be in /home/user/TRAYDINGCc/research/verify/cross_weekend_follow_alts/v2_leak.out.
- My random-exposure nulls use a simplified simulator with no Guardian and no fold-boundary closes; it matches the engine exactly on 127 of 129 trades ($766 against the engine's $788 for those trades), so percentile figures are quoted against $766, not $862.

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
| 3 | 4 | 3 | 1 | 5 | 16/25 |

## Data
Source https://futures.kraken.com (public API), bars up to 2026-11-18T02:00:00+00:00. Funding before about 2025-11 is an estimate from the mark-vs-index premium; slippage before about 2023-08 is an estimate.

## WHY THIS COULD FAIL
This is the same bet as cross_weekend_follow_majors on the same 24 hours, so it adds trade count, not independent evidence; run both and a wrong weekend costs up to 2.5% of equity. Everything fragile about the majors version applies (140 weekends, lookback sensitivity, lumpy quarters, a cause a venue can switch off). The top-3 alt list rotates into meme coins (WIF, PEPE, DOGE in 2024) whose Monday moves are noisier and whose slippage is higher than the model's median. The agreement filter and n_alt were chosen after seeing that the unfiltered ten-symbol version drew down 49%, so there is some selection in the rule itself.
