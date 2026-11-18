"""Independent re-implementation of the entry signal from the SPEC TEXT (plain loops), compared with the module."""
import sys, json, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
from desk.engine.runner import load_market
from desk.data.store import VALIDATION_END
from desk.audit import harness
from desk.strategies.s_cross_weekend_follow_alts import STRATEGY

t0 = time.time()
market = load_market(end=VALIDATION_END)
data = market.data
print("loaded", len(data), "symbols in", round(time.time() - t0, 1), "s; last bar", max(df.index[-1] for df in data.values()))
uni = json.loads((ROOT / "data" / "universe.json").read_text())["months"]
BTC, ETH = "PF_XBTUSD", "PF_ETHUSD"


def my_atr(df, n=24):
    """Wilder ATR written as a loop: first value appears after n true ranges; TR[0] uses high-low only."""
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    out = np.full(len(df), np.nan)
    a = None
    cnt = 0
    for i in range(len(df)):
        tr = h[i] - l[i]
        if i > 0 and not np.isnan(c[i - 1]):
            tr = max(tr, abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        if np.isnan(tr):
            continue
        a = tr if a is None else a + (tr - a) / n
        cnt += 1
        if cnt >= n:
            out[i] = a
    return out


def my_signals(p):
    """{(symbol, time): (side, stop)} straight from the spec text."""
    look, thr, k, n_alt = int(p["look"]), p["thr"], p["stop_atr"], int(p["n_alt"])
    btc = data[BTC]["close"]
    out = {}
    atrs = {}
    for t in btc.index:
        if not (t.dayofweek == 6 and t.hour == 21):
            continue
        t_prev = t - pd.Timedelta(hours=look)
        if t_prev not in btc.index:
            continue
        w = btc[t] / btc[t_prev] - 1.0
        if np.isnan(w) or abs(w) < thr or w == 0:
            continue
        side = 1 if w > 0 else -1
        month = t.strftime("%Y-%m")
        cands = [s for s in uni.get(month, []) if s not in (BTC, ETH)][:n_alt]
        for s in cands:
            df = data.get(s)
            if df is None or t not in df.index or t_prev not in df.index:
                continue
            own = df["close"][t] / df["close"][t_prev] - 1.0
            if np.isnan(own) or own == 0 or (1 if own > 0 else -1) != side:
                continue
            if s not in atrs:
                atrs[s] = pd.Series(my_atr(df, 24), index=df.index)
            a = atrs[s][t]
            if np.isnan(a) or a <= 0:
                continue
            out[(s, t)] = (side, df["close"][t] - side * k * a)
    return out


cells = harness.grid_cells(STRATEGY)
tot_diff = 0
for ci, cell in enumerate(cells):
    mine = my_signals(cell)
    mod = STRATEGY.intents(data, dict(cell))
    theirs = {}
    for s, it in mod.items():
        rows = it[it["side"] != 0]
        for t, r in rows.iterrows():
            theirs[(s, t)] = (int(r["side"]), float(r["stop"]))
        # extra columns must be blank
        assert it["limit"].isna().all() and it["tp"].isna().all() and it["trail"].isna().all() and not it["exit"].any()
    only_mine = sorted(set(mine) - set(theirs)); only_theirs = sorted(set(theirs) - set(mine))
    side_diff = [k for k in set(mine) & set(theirs) if mine[k][0] != theirs[k][0]]
    stop_diff = [k for k in set(mine) & set(theirs) if not np.isclose(mine[k][1], theirs[k][1], rtol=1e-9)]
    tot_diff += len(only_mine) + len(only_theirs) + len(side_diff) + len(stop_diff)
    if ci < 4 or only_mine or only_theirs or side_diff or stop_diff:
        print(ci, {k: cell[k] for k in ("thr", "stop_atr", "n_alt")}, "mine", len(mine), "module", len(theirs),
              "only_mine", len(only_mine), "only_module", len(only_theirs), "side_diff", len(side_diff), "stop_diff", len(stop_diff))
        for k in (only_mine[:5] + only_theirs[:5]):
            print("   ", k, mine.get(k), theirs.get(k))
print("TOTAL DIFFERENCES over", len(cells), "cells:", tot_diff)

# signals on non-tradable rows (module emits, engine blocks?) and on bar_missing rows
cell = cells[2]
mod = STRATEGY.intents(data, dict(cell))
n_sig = n_block = n_missing = 0
for s, it in mod.items():
    rows = it.index[it["side"] != 0]
    a = market.base.arrays[s]
    pos = market.base.index.get_indexer(rows)
    n_sig += len(rows); n_block += int((~a["tradable"][pos]).sum()); n_missing += int(data[s].loc[rows, "bar_missing"].sum())
print("cell 2 signals", n_sig, "blocked by engine tradable mask", n_block, "on bar_missing rows", n_missing)

# open[t+1] == close[t]?
for s in ("PF_XRPUSD", "PF_SOLUSD", "PF_DOGEUSD"):
    df = data[s]; df = df[df.index >= "2025-01-01"]
    d = (df["open"].shift(-1) / df["close"] - 1).abs().dropna()
    print(s, "share of bars with open[t+1]==close[t] (1e-9):", round(float((d < 1e-9).mean()), 4), "max gap bps", round(float(d.max() * 1e4), 2))
