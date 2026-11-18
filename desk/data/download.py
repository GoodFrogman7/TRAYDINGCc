"""Download and assemble the research dataset from Kraken Futures public APIs.

    python -m desk.data.download            # full build
    python -m desk.data.download --update   # refresh the tail of existing files

What it builds (everything stamped with source + download time in manifest.json):

  data/daily_volume.parquet        daily candles for EVERY PF_ perpetual the charts
                                   API knows, delisted contracts included
  data/universe.json               point-in-time top-N crypto perps per month,
                                   ranked on the trailing 30 days only
  data/kraken_futures/1h/*.parquet one file per symbol that was ever in the universe
  data/manifest.json               sources, timestamps, coverage, funding-model fit

Row convention: index = bar OPEN time (UTC). Every value in row t is known by
the CLOSE of bar t (t + 1h). `funding` in row t is the rate applied during bar t.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from .kraken import BASE, NON_CRYPTO_CATEGORIES, KrakenFutures

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
H1 = DATA / "kraken_futures" / "1h"
HISTORY_START = int(pd.Timestamp("2022-03-01", tz="UTC").timestamp())
TOP_N = 10
RANK_WINDOW_DAYS = 30
MIN_TRADED_DAYS = 20
MAX_REL_FUNDING = 0.005  # per hour, from instrument spec `maxRelativeFundingRate`
ANALYTICS = ["open-interest", "liquidation-volume", "long-short-ratio", "cvd", "slippage"]


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_daily(k: KrakenFutures, symbols: list[str], asof: int, workers: int) -> pd.DataFrame:
    def one(sym: str) -> pd.DataFrame:
        df = k.candles(sym, "trade", "1d", HISTORY_START, asof)
        df = df[df.index < pd.Timestamp(asof // 86400 * 86400, unit="s", tz="UTC")]  # complete days only
        df = df.assign(symbol=sym, dollar_vol=df["volume"] * df["close"])
        return df.reset_index()

    frames = []
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(one, s): s for s in symbols}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                frames.append(f.result())
            except Exception as e:  # a symbol with no candles is not fatal
                print(f"  daily {futs[f]} failed: {e}", file=sys.stderr)
            if i % 100 == 0:
                print(f"  daily candles {i}/{len(symbols)}")
    out = pd.concat([f for f in frames if len(f)], ignore_index=True)
    return out[["symbol", "time", "open", "high", "low", "close", "volume", "dollar_vol"]]


def build_universe(daily: pd.DataFrame, eligible: set[str], asof: int) -> dict[str, list[str]]:
    """Top-N by median daily dollar volume over the 30 days BEFORE each month start."""
    dv = daily.pivot(index="time", columns="symbol", values="dollar_vol")
    dv = dv[[c for c in dv.columns if c in eligible]]
    months = pd.date_range(pd.Timestamp("2022-05-01", tz="UTC"), pd.Timestamp(asof, unit="s", tz="UTC"), freq="MS")
    uni: dict[str, list[str]] = {}
    for m in months:
        win = dv[(dv.index >= m - pd.Timedelta(days=RANK_WINDOW_DAYS)) & (dv.index < m)]
        traded = (win > 0).sum()
        med = win.fillna(0).median()
        med = med[traded >= MIN_TRADED_DAYS].sort_values(ascending=False)
        uni[m.strftime("%Y-%m")] = list(med.index[:TOP_N])
    return uni


def build_symbol(k: KrakenFutures, sym: str, asof: int, first_day: int = HISTORY_START) -> tuple[pd.DataFrame, dict]:
    tr = k.candles(sym, "trade", "1h", first_day, asof)
    if tr.empty:
        return pd.DataFrame(), {"symbol": sym, "rows": 0}
    cut = pd.Timestamp(asof, unit="s", tz="UTC")
    tr = tr[tr.index < cut]
    traded = tr[tr["volume"] > 0]
    if traded.empty:
        return pd.DataFrame(), {"symbol": sym, "rows": 0}
    first, last = traded.index[0], traded.index[-1]
    idx = pd.date_range(first, last, freq="h", tz="UTC", name="time")
    df = tr.reindex(idx)
    df["bar_missing"] = df["close"].isna()
    df["volume"] = df["volume"].fillna(0.0)
    df["close"] = df["close"].ffill()
    for c in ("open", "high", "low"):
        df[c] = df[c].fillna(df["close"])
    s0, s1 = int(first.timestamp()), int(last.timestamp()) + 3600
    for tick in ("mark", "spot"):
        c = k.candles(sym, tick, "1h", s0, s1).reindex(idx)
        if tick == "mark" and c["close"].isna().mean() > 0.02:   # holes: fetch again once
            c = c.combine_first(k.candles(sym, tick, "1h", s0, s1).reindex(idx))
        df[f"{tick}_close"] = c["close"]
        df[f"{tick}_avg"] = c[["open", "high", "low", "close"]].mean(axis=1)
    df["premium"] = (df["mark_avg"] - df["spot_avg"]) / df["spot_avg"]
    df = df.drop(columns=["mark_avg", "spot_avg"])
    try:
        fr = k.funding_history(sym)
    except Exception:
        fr = pd.DataFrame(columns=["funding_rel"], dtype="float64")
    df["funding_actual"] = fr["funding_rel"].reindex(idx) if len(fr) else np.nan
    for kind in ANALYTICS:
        try:
            a = k.analytics(sym, kind, s0, s1)
        except Exception as e:
            print(f"  {sym} analytics {kind} failed: {e}", file=sys.stderr)
            a = pd.DataFrame()
        if len(a):
            a = a.reindex(idx)
            for c in a.columns:
                df[c] = a[c]
    for c in ("oi", "liq_vol", "ls_ratio", "buy_vol", "sell_vol", "bid_10k", "ask_10k", "bid_100k", "ask_100k"):
        if c not in df:
            df[c] = np.nan
    meta = {
        "symbol": sym, "rows": int(len(df)), "first": first.isoformat(), "last": last.isoformat(),
        "missing_bars": int(df["bar_missing"].sum()),
        "delisted": bool(last < cut - pd.Timedelta(days=3)),
    }
    return df, meta


def fit_funding(frames: dict[str, pd.DataFrame]) -> dict:
    """Funding stamped T+1h is derived from the premium during bar T. Fit
    funding[t] = a + k * premium[t-1] (least squares) on the year where actual
    rates exist, then back-fill earlier history with that ESTIMATE (flagged in
    `funding_is_est`). The intercept keeps the estimate unbiased on the fit year."""
    def ols(xv: np.ndarray, yv: np.ndarray) -> tuple[float, float]:
        xm, ym = xv.mean(), yv.mean()
        k = float(((xv - xm) * (yv - ym)).sum() / ((xv - xm) ** 2).sum())
        return float(ym - k * xm), k

    fits, pooled_x, pooled_y = {}, [], []
    for sym, df in frames.items():
        x = df["premium"].shift(1)
        y = df["funding_actual"]
        ok = x.notna() & y.notna() & (y.abs() < MAX_REL_FUNDING * 0.999)
        if ok.sum() < 500:
            continue
        xv, yv = x[ok].to_numpy(), y[ok].to_numpy()
        a, kfit = ols(xv, yv)
        pred = np.clip(a + kfit * xv, -MAX_REL_FUNDING, MAX_REL_FUNDING)
        fits[sym] = {
            "n": int(ok.sum()), "a": a, "k": kfit, "corr": float(np.corrcoef(xv, yv)[0, 1]),
            "mae_per_hour": float(np.abs(pred - yv).mean()),
            "mean_actual_per_hour": float(yv.mean()), "mean_est_per_hour": float(pred.mean()),
        }
        pooled_x.append(xv)
        pooled_y.append(yv)
    if pooled_x:
        pooled_a, pooled_k = ols(np.concatenate(pooled_x), np.concatenate(pooled_y))
    else:
        pooled_a, pooled_k = 0.0, 1.0 / 24.0
    for sym, df in frames.items():
        f = fits.get(sym, {})
        a, kfit = f.get("a", pooled_a), f.get("k", pooled_k)
        est = (a + kfit * df["premium"].shift(1)).clip(-MAX_REL_FUNDING, MAX_REL_FUNDING)
        df["funding_is_est"] = df["funding_actual"].isna()
        df["funding"] = df["funding_actual"].fillna(est).fillna(0.0)
        for c in ("oi", "liq_vol", "ls_ratio", "buy_vol", "sell_vol", "premium"):
            df[c] = df[c].astype("float32")
    return {"pooled_a": pooled_a, "pooled_k": pooled_k, "per_symbol": fits,
            "note": "funding = actual where the venue serves it (about the last year); earlier hours are an "
                    "ESTIMATE a + k*premium(previous hour), clipped to the +/-0.5%/h cap. Symbols with no "
                    "actual history (delisted before the served window) use the pooled fit."}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--only", nargs="*", help="restrict the hourly download to these symbols (debug)")
    ap.add_argument("--update", action="store_true", help="(reserved) currently identical to a full rebuild")
    args = ap.parse_args(argv)
    t0 = time.time()
    k = KrakenFutures()
    asof = int(time.time()) // 3600 * 3600  # only bars that are already closed
    DATA.mkdir(exist_ok=True)
    H1.mkdir(parents=True, exist_ok=True)

    ins = {i["symbol"]: i for i in k.instruments()}
    seen_path = DATA / "symbols_seen.json"   # only ever grows: delisted contracts must not vanish
    seen = set(json.loads(seen_path.read_text())) if seen_path.exists() else set()
    seen |= {s for s in k.chart_symbols("trade") if s.startswith("PF_")} | {s for s in ins if s.startswith("PF_")}
    seen_path.write_text(json.dumps(sorted(seen)))
    chart_syms = sorted(seen)
    non_crypto = {s for s, i in ins.items() if i.get("category") in NON_CRYPTO_CATEGORIES or i.get("tradfi")}
    eligible = set(chart_syms) - non_crypto
    print(f"PF_ symbols in charts API: {len(chart_syms)} | currently listed: {sum(s in ins for s in chart_syms)}"
          f" | delisted: {sum(s not in ins for s in chart_syms)} | non-crypto excluded: {len(non_crypto)}")

    daily = build_daily(k, chart_syms, asof, args.workers)
    daily.to_parquet(DATA / "daily_volume.parquet", index=False, compression="zstd")
    universe = build_universe(daily, eligible, asof)
    members = sorted({s for v in universe.values() for s in v} | {"PF_XBTUSD", "PF_ETHUSD"})
    if args.only:
        members = [m for m in members if m in set(args.only)]
    print(f"universe months: {len(universe)} | distinct members ever in top {TOP_N}: {len(members)}")

    frames: dict[str, pd.DataFrame] = {}
    metas: dict[str, dict] = {}
    with ThreadPoolExecutor(args.workers) as ex:
        traded = daily[daily["volume"] > 0].groupby("symbol")["time"].min()
        first_day = {s: int(traded[s].timestamp()) for s in members if s in traded.index}
        futs = {ex.submit(build_symbol, k, s, asof, first_day.get(s, HISTORY_START)): s for s in members}
        for i, f in enumerate(as_completed(futs), 1):
            s = futs[f]
            df, meta = f.result()
            if len(df):
                frames[s], metas[s] = df, meta
            print(f"  [{i}/{len(members)}] {s}: {meta.get('rows', 0)} bars {meta.get('first', '')[:10]}..{meta.get('last', '')[:10]}")

    funding_fit = fit_funding(frames)
    files = {}
    for s, df in frames.items():
        p = H1 / f"{s}.parquet"
        df.to_parquet(p, compression="zstd")
        cov = {c: {"first": (df[c].first_valid_index().isoformat() if df[c].notna().any() else None),
                   "pct": round(float(df[c].notna().mean()) * 100, 2)}
               for c in ("oi", "liq_vol", "ls_ratio", "buy_vol", "bid_10k", "funding_actual", "mark_close", "spot_close")}
        files[s] = {**metas[s], "sha256": _sha(p), "coverage": cov,
                    "category": (ins.get(s) or {}).get("category", "unknown (delisted)"),
                    "listed_now": s in ins}

    meta_uni = {
        "rule": f"top {TOP_N} crypto perpetuals by median daily USD volume over the {RANK_WINDOW_DAYS} days before "
                f"each month start (>= {MIN_TRADED_DAYS} traded days); ranked across all PF_ contracts incl. delisted",
        "excluded_categories": sorted(NON_CRYPTO_CATEGORIES), "months": universe,
    }
    (DATA / "universe.json").write_text(json.dumps(meta_uni, indent=1))
    manifest = {
        "source": BASE,
        "endpoints": {
            "candles": "/api/charts/v1/{trade|mark|spot}/{symbol}/{1h|1d}",
            "analytics": "/api/charts/v1/analytics/{symbol}/{" + "|".join(ANALYTICS) + "}",
            "funding": "/derivatives/api/v4/historicalfundingrates",
            "instruments": "/derivatives/api/v3/instruments",
        },
        "downloaded_at_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        "asof_bar_cutoff_utc": pd.Timestamp(asof, unit="s", tz="UTC").isoformat(),
        "api_calls": k.calls, "seconds": round(time.time() - t0, 1),
        "symbols_in_charts_api": len(chart_syms),
        "symbols_delisted": sum(s not in ins for s in chart_syms),
        "funding_model": funding_fit,
        "files": files,
    }
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"done: {len(files)} symbols, {k.calls} API calls, {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
