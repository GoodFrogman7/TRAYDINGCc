"""H11 deep-dive: does the weekend move continue when TradFi reopens? Signal at close of Sun bar `hr`, enter next open."""
import numpy as np, pandas as pd
from research.hunter.cross.lib import *

pd.set_option("display.width", 250)
data, P = panels()
C, O, T = P["close"], P["open"], P["trad"]
ts = C.index

def study(sig_dow, sig_hr, look, sym=BTC, H=(12, 24, 48), delay=0):
    """signal: return over `look` hours ending at close of bar (dow, hr)."""
    t_idx = ts[(ts.dayofweek == sig_dow) & (ts.hour == sig_hr)]
    w = (C[sym] / C[sym].shift(look) - 1).loc[t_idx]
    out = {}
    for h in H:
        f = fwd_from_next_open(O[[sym]], h, delay)[sym].loc[t_idx]
        d = pd.DataFrame({"w": w, "f": f})[T[sym].loc[t_idx].values].dropna()
        out[h] = d
    return out

print("== BTC: weekend return (48h ending Sun 21:00 bar close) -> follow, by horizon / year / side / delay ==")
rows = []
for delay in (0, 1):
    res = study(6, 21, 48, BTC, delay=delay)
    for h, d in res.items():
        fol = np.sign(d.w) * d.f
        r = stats(fol, f"BTC follow H={h} d={delay}", by_day=False); r["corr"] = round(d.w.corr(d.f), 3); r["spearman"] = round(d.w.corr(d.f, method="spearman"), 3)
        r["yr"] = str({k: v for k, v in by_year(fol).items()})
        rows.append(r)
        if delay == 0:
            for sd, nm in ((1, "up-weekend long"), (-1, "down-weekend short")):
                rows.append({**stats(fol[np.sign(d.w) == sd], f"   {nm} H={h}", by_day=False)})
show(rows)

print("\n== placebo: same test on every day of week (48h return ending 21:00 bar -> next 24h), BTC ==")
rows = []
for dow in range(7):
    d = study(dow, 21, 48, BTC, H=(24,))[24]
    fol = np.sign(d.w) * d.f
    r = stats(fol, f"dow={dow}", by_day=False); r["corr"] = round(d.w.corr(d.f), 3); r["spearman"] = round(d.w.corr(d.f, method="spearman"), 3)
    r["yr"] = str({k: v[1] for k, v in by_year(fol).items()})
    rows.append(r)
show(rows)

print("\n== robustness to signal hour / lookback (BTC, follow 24h) ==")
rows = []
for hr in (17, 19, 21, 23):
    for look in (24, 48, 60):
        d = study(6, hr, look, BTC, H=(24,))[24]
        fol = np.sign(d.w) * d.f
        r = stats(fol, f"Sun {hr}:00 look={look}", by_day=False); r["spearman"] = round(d.w.corr(d.f, method="spearman"), 3)
        big = fol[d.w.abs() > 0.01]; r["n_gt1pct"] = len(big); r["mean_gt1pct"] = round(big.mean() * 1e4, 1); r["hit_gt1pct"] = round((big > 0).mean(), 3)
        rows.append(r)
show(rows)

print("\n== winsorised / outlier check (BTC Sun 21:00, look 48, H 24) ==")
d = study(6, 21, 48, BTC, H=(24,))[24]
fol = (np.sign(d.w) * d.f).sort_values()
print("worst 5:", (fol.head(5) * 1e4).round(0).to_dict())
print("best 5:", (fol.tail(5) * 1e4).round(0).to_dict())
print("mean ex top-5 & bottom-5 (bps):", round(fol.iloc[5:-5].mean() * 1e4, 1), " median:", round(fol.median() * 1e4, 1))

print("\n== each universe member: follow BTC's weekend sign vs own weekend sign, H=24, pooled over tradable symbols ==")
t_idx = ts[(ts.dayofweek == 6) & (ts.hour == 21)]
wb = (C[BTC] / C[BTC].shift(48) - 1).loc[t_idx]
wo = (C / C.shift(48) - 1).loc[t_idx]
wbas = wo.where(T.loc[t_idx]).mean(axis=1)
rows = []
for h in (12, 24, 48):
    for delay in (0, 1):
        F = fwd_from_next_open(O, h, delay).loc[t_idx]
        Tm = T.loc[t_idx]
        for nm, sg in (("BTC sign", pd.DataFrame({c: np.sign(wb) for c in C.columns})), ("own sign", np.sign(wo)), ("basket sign", pd.DataFrame({c: np.sign(wbas) for c in C.columns}))):
            ev = (F * sg).where(Tm).stack()
            ev.index = ev.index.get_level_values(0)
            r = stats(ev, f"{nm} H={h} d={delay}"); r["yr"] = str({k: v[1] for k, v in by_year(ev).items()})
            rows.append(r)
            if h == 24 and delay == 0:
                for thr in (0.01, 0.02):
                    m = wb.abs() > thr if nm != "own sign" else None
                    if m is not None:
                        ev2 = (F * sg).where(Tm)[m.values].stack(); ev2.index = ev2.index.get_level_values(0)
                        r2 = stats(ev2, f"   {nm} |BTC wk|>{thr} H={h}"); r2["yr"] = str({k: v[1] for k, v in by_year(ev2).items()}); rows.append(r2)
show(rows)
