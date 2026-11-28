"""Event-study tables for the exact signal definitions in the returned ideas (design window, tradable bars only).
Forward returns: open[t+1] -> open[t+1+h]; 'delay' = one more bar. 'ct' = t-stat on UTC-day-clustered means."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import lib, features as F
from desk.data import store
pd.set_option("display.width", 300); pd.set_option("display.max_rows", 500)


def md(df, index=False):
    """Minimal markdown table (tabulate is not installed)."""
    if index:
        df = df.reset_index()
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(v) for v in r.values) + " |")
    return "\n".join(lines)


P = F.panel()
raw = store.load_design()
btc = P["PF_XBTUSD"]
bs = pd.DataFrame({"btc_spike": (btc.liq > btc.liq_q99) & (btc.liq > 0), "btc_rz": btc.rz, "btc_volrel": btc.vol_rel})
for s, f in P.items():
    m = raw[s]["mark_close"]; mr = m / m.shift(1) - 1
    f["mrz"] = mr / mr.rolling(168, min_periods=100).std().shift(1)
    f["bbw_rank_prev"] = f["bbw_rank"].shift(1)
    f["dn48"] = f["close"] < f["low"].shift(1).rolling(48).min()
    f["up48"] = f["close"] > f["high"].shift(1).rolling(48).max()
    if "half_spread_bps" in f:
        f["sp_rel"] = f["half_spread_bps"] / f["half_spread_bps"].rolling(168, min_periods=48).median().shift(1)
    f["dow"] = f.index.dayofweek; f["hr"] = f.index.hour
    f["wk_z"] = (f["close"] / f["close"].shift(48) - 1) / (f["sd168"] * np.sqrt(48))
X = F.stack(P).join(bs, on="time")
X = X[X.tradable & ~X.miss].copy()
sun = (X.dow == 6) & (X.hr == 21)
defs = {
    "weekend_dump_short (Sun 21h, z<=-0.75) SHORT": (sun & (X.wk_z <= -0.75), -1, (12, 24, 48)),
    "weekend_dump_short (z<=-1.0) SHORT": (sun & (X.wk_z <= -1.0), -1, (12, 24, 48)),
    "weekend_pump_long (Sun 21h, z>=0.75) LONG": (sun & (X.wk_z >= 0.75), 1, (12, 24, 48)),
    "stress_bid (BTC rz<=-3 & vol>=3x, alt rz>-1, ex BTC/ETH) LONG": ((X.btc_rz <= -3) & (X.btc_volrel >= 3) & (X.rz > -1) & ~X.maj, 1, (4, 12, 24)),
    "hot_breakdown (close<48h low, bbw rank>0.7) LONG": (X.dn48 & (X.bbw_rank_prev > 0.7), 1, (4, 12, 24)),
    "mirror: hot breakout UP (close>48h high, rank>0.7) SHORT": (X.up48 & (X.bbw_rank_prev > 0.7), -1, (4, 12, 24)),
    "liquidity_vacuum (spread>=3x, 4h drop>2ATR) LONG": ((X.sp_rel >= 3) & (X.ret4 < -2 * X.atrp), 1, (4, 12, 24)),
    "btc_liq_flush ALL signals LONG": ((X.rz <= -3) & X.btc_spike & (X.btc_rz <= -3), 1, (4, 12, 24)),
    "air_pocket (rz<=-3, mark rz<=-3, vol_rel<=4) LONG": ((X.rz <= -3) & (X.mrz <= -3) & (X.vol_rel <= 4), 1, (4, 12, 24)),
}
rows = []
for nm, (m, d, hs) in defs.items():
    E = X[m]
    for h in hs:
        r = E[f"f{h}"] * d
        s = lib.stats(r, f"{nm} | h={h}"); s["ct"] = lib.cluster_t(E.assign(r=r)); s["days"] = E.time.dt.floor("D").nunique()
        for y in (2022, 2023, 2024):
            g = r[E.year == y]; s[f"y{y}"] = f"{g.mean()*1e4:.0f}/{len(g)}"
        s["delay"] = round((E[f"f{h}d"] * d).mean() * 1e4, 1)
        s["majors"] = f"{(r[E.maj]).mean()*1e4:.0f}/{int(E.maj.sum())}"
        rows.append(s)
T = pd.DataFrame(rows)
T.insert(0, "source", "Kraken Futures public API")
T.insert(1, "asof_bar_cutoff_utc", store.manifest()["asof_bar_cutoff_utc"])
T.insert(2, "window", "DESIGN (< 2025-01-01), tradable bars only")
OUT = os.path.join(os.path.dirname(__file__), "tables")
os.makedirs(OUT, exist_ok=True)
T.to_csv(os.path.join(OUT, "event_study.csv"), index=False)
print(md(T.drop(columns=["source", "asof_bar_cutoff_utc", "window"])))
# first vs later signals for the cascade
Ev = X[(X.rz <= -3) & X.btc_spike & (X.btc_rz <= -3)].sort_values(["sym", "time"]).copy()
gap = Ev.groupby("sym")["time"].diff().dt.total_seconds() / 3600
Ev["first"] = gap.isna() | (gap > 12)
print("\ncascade first vs later signal:")
print(md(Ev.groupby("first").agg(n=("f12", "size"), f4=("f4", lambda s: round(s.mean() * 1e4, 1)), f12=("f12", lambda s: round(s.mean() * 1e4, 1)), days=("time", lambda s: s.dt.floor("D").nunique())), index=True))
# weekend-level stats
for z in (0.75, 1.0):
    E = X[sun & (X.wk_z <= -z)]
    g = E.groupby(E.time.dt.date)["f24"].mean() * -1
    print(f"\nweekend short z<=-{z}: weekends {len(g)}, weekend-level mean {g.mean()*1e4:.0f} bps, median {g.median()*1e4:.0f}, hit {(g>0).mean():.2f}, t {g.mean()/(g.std(ddof=1)/np.sqrt(len(g))):.2f}; by year "
          + str({int(y): f"{v.mean()*1e4:.0f}/{len(v)}" for y, v in g.groupby(pd.to_datetime(g.index).year)}))
E = X[sun & (X.wk_z >= 0.75)]; g = E.groupby(E.time.dt.date)["f24"].mean()
print(f"weekend long z>=0.75: weekends {len(g)}, mean {g.mean()*1e4:.0f} bps, median {g.median()*1e4:.0f}, hit {(g>0).mean():.2f}, t {g.mean()/(g.std(ddof=1)/np.sqrt(len(g))):.2f}; by year "
      + str({int(y): f"{v.mean()*1e4:.0f}/{len(v)}" for y, v in g.groupby(pd.to_datetime(g.index).year)}))
