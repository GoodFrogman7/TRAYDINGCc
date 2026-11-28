"""H16: market-wide down-shock -> 12h bounce, by year / majors vs alts / with market-wide liquidation confirmation.
   H17: BTC 168h breakout -> alts catch up over 24-72h?   H18: alt-vs-BTC weekend relative move -> Monday relative reversal?
   H19: weekend-range breakout on Mon/Tue vs same pattern on other days."""
import numpy as np, pandas as pd
from research.hunter.cross.lib import *

pd.set_option("display.width", 280); pd.set_option("display.max_colwidth", 110)
data, P = panels()
C, O, Hi, Lo, T = P["close"], P["open"], P["high"], P["low"], P["trad"]
allc = list(C.columns); alts = [c for c in allc if c not in (BTC, ETH)]
r1 = C.pct_change(); basket = r1.where(T).mean(axis=1)
z = basket / basket.rolling(168, min_periods=100).std().shift(1)
nmem = T.sum(axis=1)

print("== H16: down-shock -> LONG ==")
liq_usd = (P["liq_vol"] * C).where(T).sum(axis=1)
liq_z = liq_usd / liq_usd.rolling(168, min_periods=100).mean().shift(1)
rows = []
for k in (3.0, 4.0):
    for nm, cond in ((f"z<-{k}", z < -k), (f"z<-{k} & liq>5x avg", (z < -k) & (liq_z > 5)), (f"z<-{k} first in 12h", (z < -k) & ~(z < -k).shift(1, fill_value=False).rolling(12, min_periods=1).max().astype(bool))):
        cond = cond & (nmem >= 8)
        for h in (6, 12, 24):
            for delay in (0, 1):
                F = fwd_from_next_open(O, h, delay)
                for grp, cols in (("all", allc), ("BTC+ETH", [BTC, ETH])):
                    ev = stack_events(pd.DataFrame({a: cond for a in cols}), F[cols], T[cols], 1)
                    r = stats(ev, f"{nm} H={h} d={delay} {grp}"); r["hours"] = int(cond.sum()); r["yr"] = str({kk: v[:2] for kk, v in by_year(ev).items()})
                    rows.append(r)
show(rows)

print("\n== H17: BTC first close above 168h high / below 168h low -> alts in BTC's direction ==")
rows = []
hi = Hi[BTC].shift(1).rolling(168, min_periods=168).max(); lo = Lo[BTC].shift(1).rolling(168, min_periods=168).min()
up = C[BTC] > hi; dn = C[BTC] < lo
upf = up & ~up.shift(1, fill_value=False).rolling(24, min_periods=1).max().astype(bool)
dnf = dn & ~dn.shift(1, fill_value=False).rolling(24, min_periods=1).max().astype(bool)
ahi = Hi.shift(1).rolling(168, min_periods=168).max(); alo = Lo.shift(1).rolling(168, min_periods=168).min()
for h in (24, 72):
    F = fwd_from_next_open(O, h)
    for nm, sig, sgn, lagmask in (("BTC breakout -> long alts", upf, 1, C[alts] < ahi[alts] * 0.97), ("BTC breakdown -> short alts", dnf, -1, C[alts] > alo[alts] * 1.03)):
        ev = stack_events(pd.DataFrame({a: sig for a in alts}), F[alts], T[alts], sgn)
        r = stats(ev, f"{nm} H={h} all alts"); r["yr"] = str({kk: v[:2] for kk, v in by_year(ev).items()}); rows.append(r)
        ev = stack_events(pd.DataFrame({a: sig for a in alts}) & lagmask, F[alts], T[alts], sgn)
        r = stats(ev, f"   laggards (>3% from own 168h extreme) H={h}"); r["yr"] = str({kk: v[:2] for kk, v in by_year(ev).items()}); rows.append(r)
        evb = (sgn * F[BTC])[sig & T[BTC]]
        r = stats(evb, f"   BTC itself H={h}"); r["yr"] = str({kk: v[:2] for kk, v in by_year(evb).items()}); rows.append(r)
show(rows)

print("\n== H18: weekend alt-minus-BTC move -> Monday alt-minus-BTC (fade the weekend relative move) ==")
ts = C.index; t_idx = ts[(ts.dayofweek == 6) & (ts.hour == 21)]
wk = (C / C.shift(48) - 1).loc[t_idx]; rel = wk[alts].sub(wk[BTC], axis=0)
rows = []
for h in (24, 48):
    F = fwd_from_next_open(O, h).loc[t_idx]; Frel = F[alts].sub(F[BTC], axis=0)
    Tm = T[alts].loc[t_idx]
    for thr in (0.0, 0.03):
        m = (rel.abs() > thr) & Tm
        ev = (-np.sign(rel) * Frel).where(m).stack(); ev.index = ev.index.get_level_values(0)
        evraw = (-np.sign(rel) * F[alts]).where(m).stack(); evraw.index = evraw.index.get_level_values(0)
        r = stats(ev, f"fade rel move thr={thr} H={h} (alt-BTC spread)"); r["raw_single_leg_bps"] = round(evraw.mean() * 1e4, 1); r["yr"] = str({kk: v[1] for kk, v in by_year(ev).items()}); rows.append(r)
show(rows)

print("\n== H19: break of the prior 48h range: weekend range broken on Mon/Tue vs the same 48h-range break on other days (BTC, ETH) ==")
rows = []
for sym in (BTC, ETH):
    for dayset, nm in (((0, 1), "Mon/Tue break of Sat-Sun range"), ((3, 4), "Thu/Fri break of Tue-Wed range")):
        d0 = dayset[0]
        # reference range: the two calendar days before day d0 (fixed for the two trading days)
        day = C.index.floor("D")
        dly_hi = Hi[sym].groupby(day).max(); dly_lo = Lo[sym].groupby(day).min()
        ref_hi = pd.concat([dly_hi.shift(1), dly_hi.shift(2)], axis=1).max(axis=1); ref_lo = pd.concat([dly_lo.shift(1), dly_lo.shift(2)], axis=1).min(axis=1)
        ref_hi2 = pd.concat([dly_hi.shift(2), dly_hi.shift(3)], axis=1).max(axis=1); ref_lo2 = pd.concat([dly_lo.shift(2), dly_lo.shift(3)], axis=1).min(axis=1)
        dow = C.index.dayofweek
        rh = pd.Series(np.where(dow == d0, ref_hi.reindex(day).values, np.where(dow == dayset[1], ref_hi2.reindex(day).values, np.nan)), index=C.index)
        rl = pd.Series(np.where(dow == d0, ref_lo.reindex(day).values, np.where(dow == dayset[1], ref_lo2.reindex(day).values, np.nan)), index=C.index)
        up = (C[sym] > rh); dn = (C[sym] < rl)
        wkid = (C.index - pd.to_timedelta((dow - d0) % 7, unit="D")).floor("D")
        upf = up & (up.groupby(wkid).cumsum() == 1); dnf = dn & (dn.groupby(wkid).cumsum() == 1)
        for h in (24, 48):
            F = fwd_from_next_open(O[[sym]], h)[sym]
            ev = pd.concat([F[upf & T[sym]], -F[dnf & T[sym]]]).sort_index()
            r = stats(ev, f"{sym[3:6]} {nm} H={h}", by_day=False); r["yr"] = str({kk: v[:2] for kk, v in by_year(ev).items()})
            r["long_bps"] = round(F[upf & T[sym]].mean() * 1e4, 1); r["short_bps"] = round(-F[dnf & T[sym]].mean() * 1e4, 1); rows.append(r)
show(rows)
