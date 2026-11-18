# Data

**Source:** Kraken Futures public market-data API (`https://futures.kraken.com`), no account, no keys.
Exact endpoints, download time, per-file hashes and coverage are in `data/manifest.json`.
Rebuild with `python -m desk.data.download` (about 5 minutes). Parquet files are not committed.

## Files
| Path | What |
|---|---|
| `data/kraken_futures/1h/<SYMBOL>.parquet` | hourly bars for every perpetual that was ever in the monthly top 10 |
| `data/universe.json` | point-in-time top 10 per month |
| `data/daily_volume.parquet` | daily candles for every PF_ perpetual, delisted included (used only to rank the universe) |
| `data/symbols_seen.json` | every PF_ symbol ever seen; only grows, so delisted contracts cannot silently vanish |

## Row convention
Index = bar **open** time, UTC, hourly. Everything in row `t` is known by the **close** of bar `t` (`t + 1h`).

| Column | Meaning | History |
|---|---|---|
| `open high low close` | last-traded price candle | from listing (earliest 2022-03-23) |
| `volume` | base-coin volume traded in the hour | same |
| `bar_missing` | True if the venue served no candle (prices forward-filled, volume 0) | same |
| `mark_close`, `spot_close` | mark price and spot index at the close | same |
| `premium` | hour-average (mark - index) / index | same |
| `funding` | hourly relative funding rate applied during bar `t`; longs pay when positive | same |
| `funding_actual` | the venue's published rate | **about the last 12 months only** |
| `funding_is_est` | True where `funding` is an ESTIMATE `a + k * premium(t-1)` fitted on the actual year | |
| `oi` | open interest (base coin) at the close | from ~2023-03 |
| `liq_vol` | base-coin volume liquidated in the hour | from listing |
| `ls_ratio` | share of accounts net long (0..1) | from ~2023-08 |
| `buy_vol`, `sell_vol` | aggressor buy / sell volume | from listing |
| `bid_10k ask_10k bid_100k ask_100k` | price a $10k / $100k market order would have executed at | from ~2023-08 |

A funding rate stamped `T` applies to `[T, T+1h)` and is set from the premium of the previous hour
(verified by lag correlation), so `funding[t]` is known at the open of bar `t`.

## Universe (survivorship-safe)
Each month's tradable set is the 10 crypto perpetuals with the highest median daily USD volume over the
**30 days before** that month, ranked across every PF_ contract Kraken has listed, delisted ones included.
Tokenised stocks, FX, metals, stablecoins and indices are excluded. A strategy may only open positions in a
symbol during months it is in the set (`store.tradable_mask`); the engine enforces this.

## Known limits
- Funding before roughly 2025-11 is an estimate. Fit quality per symbol is in `manifest.json -> funding_model`.
- Open interest, long/short ratio and order-book slippage do not cover 2022. Strategies needing them are
  tested on the shorter window and say so.
- Kraken's symbol-list endpoint is inconsistent between calls (it sometimes omits delisted contracts); the
  downloader polls it repeatedly and keeps a grow-only list.
