"""Reproduce the walk-forward validation trades, re-price with the ACTUAL order-book half-spread, one-bar-late,
concentration, long/short, signal-strength buckets, simultaneous exposure."""
import sys, json, pickle
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
from desk.engine.runner import load_market, run_feed
from desk.engine.core import Costs, Risk, attach
from desk.data.store import VALIDATION_END, DESIGN_END
from desk.audit import harness
from desk.strategies.s_cross_weekend_follow_alts import STRATEGY
pd.set_option("display.width", 220); pd.set_option("display.max_columns", 30)

market = load_market(end=VALIDATION_END)
data, base = market.data, market.base
res = json.loads((ROOT / "research/results/cross_weekend_follow_alts.json").read_text())
cells = harness.grid_cells(STRATEGY)
chosen = [c for c in res["wf_chosen"] if c["test_start"] >= "2025-01-01"]
for c in chosen:
    assert cells[c["cell"]] == c["params"], (cells[c["cell"]], c["params"])
used = sorted({c["cell"] for c in chosen})
intents = {k: STRATEGY.intents(data, dict(cells[k])) for k in used}
feeds = {k: attach(base, intents[k]) for k in used}
late = {k: attach(base, {s: df.shift(1) for s, df in intents[k].items()}) for k in used}


def wf(fs, costs=Costs(), risk=Risk()):
    tr = []
    for c in chosen:
        t0, t1 = pd.Timestamp(c["test_start"], tz="UTC"), pd.Timestamp(c["test_end"], tz="UTC")
        r = run_feed(fs[c["cell"]], STRATEGY, t0, t1, costs, risk)
        for t in r["trades"]:
            t = dict(t); t["cell"] = c["cell"]; t["quarter"] = c["test_start"]; tr.append(t)
    return pd.DataFrame(tr)


T = wf(feeds)
csv = pd.read_csv(ROOT / "research/results/trades/cross_weekend_follow_alts.csv")
csv_v = csv[csv["entry_time"] >= "2025-01-01"].reset_index(drop=True)
print("reproduced trades", len(T), "pnl", round(T.pnl.sum(), 2), "| csv validation trades", len(csv_v), "pnl", round(csv_v.pnl.sum(), 2),
      "| max abs pnl diff", float(np.abs(T.pnl.to_numpy() - csv_v.pnl.to_numpy()).max()) if len(T) == len(csv_v) else "LEN DIFF")
print("exit reasons", T.reason.value_counts().to_dict())

half = {}
for s, df in data.items():
    if "bid_10k" in df:
        mid = (df["ask_10k"] + df["bid_10k"]) / 2
        half[s] = ((df["ask_10k"] - df["bid_10k"]) / mid / 2 * 1e4).where(lambda x: x >= 0).reindex(base.index).to_numpy()
idx = base.index


def reprice(T, label):
    T = T.copy()
    ie = idx.get_indexer(pd.DatetimeIndex(T.entry_time)); ix = idx.get_indexer(pd.DatetimeIndex(T.exit_time))
    rows = []
    for (j, t), a, b in zip(T.iterrows(), ie, ix):
        s = t.symbol; h = half[s]; sl = base.arrays[s]["slip_bps"]
        mult_x = 2.0 if t.reason == "stop" else 1.0
        mod_e, mod_x = sl[a], sl[b] * mult_x
        # the fill is at the open of bar a = the boundary between rows a-1 and a
        e_prev, e_same, e_next = h[a - 1], h[a], h[min(a + 1, len(h) - 1)]
        if t.reason == "stop":           # the stop fills INSIDE bar b
            x_prev, x_same, x_next = np.nan, h[b], h[min(b + 1, len(h) - 1)]
        elif t.reason == "end_of_data":  # closed at the close of the last bar
            x_prev, x_same, x_next = h[b], np.nan, np.nan
        else:
            x_prev, x_same, x_next = h[b - 1], h[b], h[min(b + 1, len(h) - 1)]
        fair_e = np.nanmean([e_prev, e_same]) if not np.all(np.isnan([e_prev, e_same])) else mod_e
        fair_x = (np.nanmean([x_prev, x_same]) if not np.all(np.isnan([x_prev, x_same])) else mod_x / mult_x) * mult_x
        worst_e = np.nanmax([e_prev, e_same, e_next]) if not np.all(np.isnan([e_prev, e_same, e_next])) else mod_e
        worst_x = (np.nanmax([x_prev, x_same, x_next]) if not np.all(np.isnan([x_prev, x_same, x_next])) else mod_x / mult_x) * mult_x
        ne, nx = t.qty * t.entry_price, t.qty * t.exit_price
        rows.append(dict(mod_e=mod_e, mod_x=mod_x, fair_e=fair_e, fair_x=fair_x, worst_e=worst_e, worst_x=worst_x,
                         notional=ne,
                         d_fair=-(ne * (fair_e - mod_e) + nx * (fair_x - mod_x)) / 1e4,
                         d_worst=-(ne * (worst_e - mod_e) + nx * (worst_x - mod_x)) / 1e4,
                         nan_e=bool(np.isnan(h[a - 1]) and np.isnan(h[a]))))
    R = pd.DataFrame(rows, index=T.index)
    T = pd.concat([T, R], axis=1)
    T["pnl_fair"] = T.pnl + T.d_fair; T["pnl_worst"] = T.pnl + T.d_worst
    print(f"\n[{label}] trades {len(T)}  modelled pnl ${T.pnl.sum():.0f} ({T.pnl.sum()/100:.2f}%)")
    print("  entry half-spread bps  modelled mean/median %.2f/%.2f | actual (mean of the two bars around the fill) %.2f/%.2f | worst of 3 bars %.2f/%.2f"
          % (T.mod_e.mean(), T.mod_e.median(), T.fair_e.mean(), T.fair_e.median(), T.worst_e.mean(), T.worst_e.median()))
    print("  exit  half-spread bps  modelled mean/median %.2f/%.2f | actual %.2f/%.2f | worst of 3 bars %.2f/%.2f"
          % (T.mod_x.mean(), T.mod_x.median(), T.fair_x.mean(), T.fair_x.median(), T.worst_x.mean(), T.worst_x.median()))
    print("  share of entries where actual > modelled: %.0f%%; max actual entry bps %.1f; missing book rows at entry: %d"
          % (100 * (T.fair_e > T.mod_e).mean(), T.fair_e.max(), int(T.nan_e.sum())))
    print("  slippage $ modelled %.0f | actual %.0f | worst-of-3 %.0f" % (
        ((T.mod_e * T.notional + T.mod_x * T.qty * T.exit_price) / 1e4).sum(),
        ((T.fair_e * T.notional + T.fair_x * T.qty * T.exit_price) / 1e4).sum(),
        ((T.worst_e * T.notional + T.worst_x * T.qty * T.exit_price) / 1e4).sum()))
    print("  RE-PRICED total: actual costs $%.0f (%.2f%%) | worst-of-3-bars $%.0f (%.2f%%)"
          % (T.pnl_fair.sum(), T.pnl_fair.sum() / 100, T.pnl_worst.sum(), T.pnl_worst.sum() / 100))
    return T


T = reprice(T, "as audited")
L = reprice(wf(late), "one bar late")
print("\none-bar-late + fees doubled + actual costs: $%.0f" % (L.pnl_fair.sum() - L.fees.sum()))
print("as audited + fees doubled + actual costs: $%.0f" % (T.pnl_fair.sum() - T.fees.sum()))

# time-of-week profile of the actual half spread vs the trailing-median model (validation window, traded symbols)
print("\nactual half-spread at Sunday 21:00/22:00 and Monday 21:00/22:00 vs all hours (median bps, validation window)")
for s in sorted(T.symbol.unique()):
    df = data[s]; df = df[df.index >= DESIGN_END]
    hs = pd.Series(half[s], index=idx).reindex(df.index)
    sun = hs[(hs.index.dayofweek == 6) & (hs.index.hour.isin([21, 22]))]; mon = hs[(hs.index.dayofweek == 0) & (hs.index.hour.isin([21, 22]))]
    print(f"  {s:<12} all {hs.median():.2f}  sun21-22 {sun.median():.2f} (p90 {sun.quantile(.9):.2f})  mon21-22 {mon.median():.2f} (p90 {mon.quantile(.9):.2f})  coverage {hs.notna().mean():.2f}")

# -------------------------------------------------- simultaneous entries / gross
g = T.groupby("entry_time").agg(n=("symbol", "size"), gross=("notional", "sum"), pnl=("pnl", "sum"))
print("\nentry events", len(g), "entries per event", g.n.value_counts().sort_index().to_dict(),
      "| share of trades entering together with another: %.0f%%" % (100 * (T.groupby("entry_time").symbol.transform("size") > 1).mean()))
print("position notional $: median %.0f, p10 %.0f, p90 %.0f, max %.0f | largest gross at one hour $%.0f (%.2fx equity)"
      % (T.notional.median(), T.notional.quantile(.1), T.notional.quantile(.9), T.notional.max(), g.gross.max(), g.gross.max() / 1e4))
print("entry weekday/hour", pd.DatetimeIndex(T.entry_time).strftime("%a %H").value_counts().to_dict())

# -------------------------------------------------- concentration
tot = T.pnl.sum()
bysym = T.groupby("symbol").agg(n=("pnl", "size"), pnl=("pnl", "sum"), fair=("pnl_fair", "sum"), win=("pnl", lambda x: (x > 0).mean())).sort_values("pnl", ascending=False)
print("\nby symbol\n", bysym.round(2))
byq = T.groupby("quarter").agg(n=("pnl", "size"), pnl=("pnl", "sum"), fair=("pnl_fair", "sum")).round(1)
print("by quarter\n", byq)
T["exit_day"] = pd.DatetimeIndex(T.exit_time).floor("D")
T["event"] = pd.DatetimeIndex(T.entry_time)
byev = T.groupby("event").pnl.sum().sort_values(ascending=False)
print("events (weekends) traded:", len(byev), "winning:", int((byev > 0).sum()), "| top 5 weekends $", byev.head(5).round(0).to_dict())
print("total $%.0f | without best symbol (%s) $%.0f | without best quarter (%s) $%.0f | without best 5 weekends $%.0f | without best 3 weekends $%.0f"
      % (tot, bysym.index[0], tot - bysym.pnl.iloc[0], byq.pnl.idxmax(), tot - byq.pnl.max(), tot - byev.head(5).sum(), tot - byev.head(3).sum()))
byday = T.groupby("exit_day").pnl.sum().sort_values(ascending=False)
print("without best 5 exit days $%.0f (best five days: %s)" % (tot - byday.head(5).sum(), byday.head(5).round(0).to_dict()))
top = T.pnl.sort_values(ascending=False)
print("top 5 trades $%.0f, top 10 trades $%.0f of total $%.0f; without top 10 trades $%.0f" % (top.head(5).sum(), top.head(10).sum(), tot, tot - top.head(10).sum()))
cb = set(json.loads((ROOT / "config/coinbase_perps.json").read_text())["kraken_symbols"])
print("not Coinbase-listed symbols traded:", sorted(set(T.symbol) - cb), "| pnl in Coinbase-listed only $%.0f (%d trades)" % (T[T.symbol.isin(cb)].pnl.sum(), T.symbol.isin(cb).sum()))
print("long: n %d pnl $%.0f win %.0f%% | short: n %d pnl $%.0f win %.0f%%" % (
    (T.side > 0).sum(), T[T.side > 0].pnl.sum(), 100 * (T[T.side > 0].pnl > 0).mean(),
    (T.side < 0).sum(), T[T.side < 0].pnl.sum(), 100 * (T[T.side < 0].pnl > 0).mean()))
print("XRP by side:", T[T.symbol == "PF_XRPUSD"].groupby("side").pnl.agg(["size", "sum"]).round(0).to_dict())
print("same with actual costs: total $%.0f | ex best symbol $%.0f | ex best quarter $%.0f | ex best 5 weekends $%.0f"
      % (T.pnl_fair.sum(), T.pnl_fair.sum() - bysym.fair.iloc[0], T.pnl_fair.sum() - byq.fair.max(),
         T.pnl_fair.sum() - T.groupby("event").pnl_fair.sum().sort_values(ascending=False).head(5).sum()))

# -------------------------------------------------- signal strength: BTC weekend move at the signal bar
btc = data["PF_XBTUSD"]["close"]; w = btc / btc.shift(48) - 1
T["w"] = w.reindex(pd.DatetimeIndex(T.entry_time) - pd.Timedelta(hours=1)).to_numpy()
T["absw"] = T.w.abs()
assert (np.sign(T.w) == T.side).all()
T["bucket"] = pd.cut(T.absw, [0, 0.005, 0.01, 0.02, 1], labels=["<0.5%", "0.5-1%", "1-2%", ">2%"])
print("\nby |BTC weekend move| (the spec's thesis: bigger BTC move = the signal)\n",
      T.groupby("bucket", observed=True).agg(n=("pnl", "size"), pnl=("pnl", "sum"), avg_r=("r", "mean"), win=("pnl", lambda x: (x > 0).mean())).round(3))
print("by cell in force\n", T.groupby("cell").agg(n=("pnl", "size"), pnl=("pnl", "sum")).round(1))
print("trades with |w| >= 0.5pct (the spec DEFAULT threshold): n %d pnl $%.0f ; with |w| < 0.5pct: n %d pnl $%.0f"
      % ((T.absw >= 0.005).sum(), T[T.absw >= 0.005].pnl.sum(), (T.absw < 0.005).sum(), T[T.absw < 0.005].pnl.sum()))
pickle.dump({"T": T, "L": L}, open(HERE / "trades.pkl", "wb"))
