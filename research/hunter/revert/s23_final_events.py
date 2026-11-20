"""Event-study tables for the FINAL signals, exactly as coded in final.py.
Forward return = open[t+1+h]/open[t+1]-1 (signal at close of t, entry next open), delayed = one bar later.
Also the same on MARK prices (mark[t+h]/mark[t]-1) because Kraken's candle open is always the previous last print.
Counted only on tradable bars. 'dedup' keeps the first signal per symbol per holding window (what one-position-per-symbol allows)."""
import numpy as np, pandas as pd
from lib import *
import final as F
data = load()
H = {"revert_premium_fade": 8, "revert_oi_wipe": 12, "revert_cascade": 12, "revert_liq_flush": 12}
PAR = {"revert_cascade": {"z": 4.5}}
out = []
for s in F.FINAL:
    p = {**s.params, **PAR.get(s.name, {})}
    its = s.intents(data, p)
    h = H[s.name]
    parts = []
    for sym, it in its.items():
        df = data[sym]
        m = it["side"] != 0
        if not m.any():
            continue
        o, mk = df["open"], df["mark_close"]
        x = pd.DataFrame({"time": df.index, "sym": sym, "side": it["side"].to_numpy(),
                          "fwd": (o.shift(-(1+h))/o.shift(-1)-1).to_numpy(), "fwd_d": (o.shift(-(2+h))/o.shift(-2)-1).to_numpy(),
                          "fwd1": (o.shift(-2)/o.shift(-1)-1).to_numpy(),
                          "mfwd": (mk.shift(-h)/mk-1).to_numpy(), "mfwd_d": (mk.shift(-h-1)/mk.shift(-1)-1).to_numpy(),
                          "atrp": (F.ta.atr(df,24)/df["close"]).to_numpy(),
                          "lo": (df["low"].shift(-1)[::-1].rolling(h, min_periods=1).min()[::-1]/o.shift(-1)-1).to_numpy(),
                          "hi": (df["high"].shift(-1)[::-1].rolling(h, min_periods=1).max()[::-1]/o.shift(-1)-1).to_numpy(),
                          "tradable": (store.tradable_mask(sym, df.index) & ~df["bar_missing"].astype(bool)).to_numpy()})
        parts.append(x[m.to_numpy() & x.tradable.to_numpy()])
    ev = pd.concat(parts).sort_values(["sym","time"]).reset_index(drop=True)
    ev["year"] = ev.time.dt.year
    ev["major"] = ev.sym.isin(MAJORS)
    for c in ("fwd","fwd_d","fwd1","mfwd","mfwd_d"):
        ev[c+"_s"] = ev[c]*ev.side
    ev["mae"] = np.where(ev.side>0, ev.lo, -ev.hi)          # worst excursion against the trade over the hold
    dd = dedupe(ev, h)
    def row(lab, g):
        day = g.time.dt.floor("D")
        r = g["fwd_s"].dropna()
        return dict(idea=s.name, split=lab, n=len(g), days=day.nunique(),
                    mean_bps=g.fwd_s.mean()*1e4, med_bps=g.fwd_s.median()*1e4, hit=(g.fwd_s>0).mean(),
                    t=r.mean()/r.std(ddof=1)*np.sqrt(len(r)) if len(r)>2 else np.nan, t_cl=cluster_t(g.fwd_s, day),
                    late_bps=g.fwd_d_s.mean()*1e4, bar1_bps=g.fwd1_s.mean()*1e4,
                    mark_bps=g.mfwd_s.mean()*1e4, mark_late=g.mfwd_d_s.mean()*1e4,
                    N_atr=(g.mfwd_s/g.atrp).mean(), tN_cl=cluster_t(g.mfwd_s/g.atrp, day),
                    mae_p05=g.mae.quantile(.05)*1e4, mae_p01=g.mae.quantile(.01)*1e4, worst_fwd=g.fwd_s.min()*1e4)
    out.append(row(f"all signal bars (h={h})", ev)); out.append(row("dedup (1 per symbol per hold)", dd))
    for y in (2022,2023,2024):
        if (dd.year==y).any(): out.append(row(str(y), dd[dd.year==y]))
    for nm, g in (("long", dd[dd.side>0]), ("short", dd[dd.side<0]), ("majors", dd[dd.major]), ("alts", dd[~dd.major])):
        if len(g): out.append(row(nm, g))
res = pd.DataFrame(out)
with pd.option_context("display.width", 400, "display.float_format", lambda v: f"{v:,.2f}"):
    for nm, g in res.groupby("idea", sort=False):
        print("\n###", nm); print(g.drop(columns="idea").to_string(index=False))
res.round(4).to_csv(__import__("pathlib").Path(__file__).with_name("final_event_tables.csv"), index=False)
