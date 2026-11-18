"""H2 wicks, H4 stretch in range, H5 consecutive bars, H6 low-volume moves, H8 premium dislocation."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel.pkl"
p = pd.read_pickle(P).sort_values(["sym","time"]).reset_index(drop=True)
g = p.groupby("sym", sort=False)
# consecutive same-direction bars (close vs prev close)
def runlen(s):
    sg = np.sign(s.fillna(0).to_numpy()); out = np.zeros(len(sg)); c = 0; prev = 0
    for i, x in enumerate(sg):
        c = c + 1 if (x == prev and x != 0) else (1 if x != 0 else 0); prev = x; out[i] = c * x
    return pd.Series(out, index=s.index)
p["run"] = g["ret1"].transform(runlen)
# premium stats (trailing)
p["prem_z"] = g["premium"].transform(lambda s: (s - s.rolling(168, min_periods=100).mean().shift(1)) / s.rolling(168, min_periods=100).std().shift(1))
p["volsum6"] = g["usd"].transform(lambda s: s.rolling(6).sum())
p["volrel6"] = p["volsum6"] / (6 * p["vmed168"])
p["ret6"] = g["close"].transform(lambda s: s / s.shift(6) - 1)
p["z6"] = p["ret6"] / (p["sig168"] * np.sqrt(6))
p["wick_atr"] = p["lwick"] / p["atr24_prev"]
p["uwick_atr"] = p["uwick"] / p["atr24_prev"]
p["rng_atr"] = p["rng"] / p["atr24_prev"]
p["sma168"] = g["close"].transform(lambda s: s.rolling(168, min_periods=168).mean())
t = p[p.tradable & ~p.bar_missing].copy()

def tab(rules, hs=(1,4,12,24), hy=12):
    rows=[]
    for lab, m, sg in rules:
        ev = t[m]
        d = dict(rule=lab, n=len(ev), days=ev.time.dt.floor("D").nunique())
        for h in hs:
            s = stats(ev, f"fwd_{h}", sg); d[f"m{h}"]=s.get("mean"); d[f"t{h}"]=s.get("t_cl")
        d[f"m{hy}_dly"] = stats(ev, f"fwd_{hy}_d", sg).get("mean")
        for y in (2022,2023,2024):
            d[f"{y}"] = stats(ev[ev.year==y], f"fwd_{hy}", sg).get("mean")
        d["maj"] = stats(ev[ev.major], f"fwd_{hy}", sg).get("mean")
        d["alt"] = stats(ev[~ev.major], f"fwd_{hy}", sg).get("mean")
        rows.append(d)
    with pd.option_context("display.width", 320, "display.float_format", lambda v: f"{v:,.1f}"):
        print(pd.DataFrame(rows).to_string(index=False))

print("\n#### H2 capitulation wicks (lower wick >= k ATR, volume spike) -> long ; upper wick -> short")
tab([
 ("lwick>1.5atr & vrel>3", (t.wick_atr>1.5)&(t.vrel>3), 1),
 ("lwick>2.5atr & vrel>3", (t.wick_atr>2.5)&(t.vrel>3), 1),
 ("lwick>1.5atr & clv>.6 & vrel>3", (t.wick_atr>1.5)&(t.clv>0.6)&(t.vrel>3), 1),
 ("uwick>1.5atr & vrel>3 short", (t.uwick_atr>1.5)&(t.vrel>3), -1),
 ("uwick>2.5atr & vrel>3 short", (t.uwick_atr>2.5)&(t.vrel>3), -1),
])
print("\n#### H5 consecutive same-direction bars -> fade")
tab([
 ("run<=-5 long", t.run<=-5, 1), ("run<=-7 long", t.run<=-7, 1), ("run<=-9 long", t.run<=-9, 1),
 ("run>=5 short", t.run>=5, -1), ("run>=7 short", t.run>=7, -1), ("run>=9 short", t.run>=9, -1),
 ("run<=-6 & z6<-3 long", (t.run<=-6)&(t.z6<-3), 1),
])
print("\n#### H4 stretch from mean in ranging conditions (er48 low) -> fade to mean")
tab([
 ("z48<-2.5 & er48<.15 long", (t.z48<-2.5)&(t.er48.shift(0)<0.15), 1),
 ("z48<-2.5 & er48>.35 long", (t.z48<-2.5)&(t.er48>0.35), 1),
 ("z48<-3 any long", (t.z48<-3), 1),
 ("z48>2.5 & er48<.15 short", (t.z48>2.5)&(t.er48<0.15), -1),
 ("z48>2.5 & er48>.35 short", (t.z48>2.5)&(t.er48>0.35), -1),
 ("z48>3 any short", (t.z48>3), -1),
 ("rsi14<20 long", t.rsi14<20, 1), ("rsi14<15 long", t.rsi14<15, 1),
 ("rsi14>80 short", t.rsi14>80, -1), ("rsi14>85 short", t.rsi14>85, -1),
])
print("\n#### H6 low-volume moves over 6 bars -> fade ; high-volume for contrast")
tab([
 ("z6<-2.5 & volrel6<1 long", (t.z6<-2.5)&(t.volrel6<1.0), 1),
 ("z6<-2.5 & volrel6>3 long", (t.z6<-2.5)&(t.volrel6>3), 1),
 ("z6>2.5 & volrel6<1 short", (t.z6>2.5)&(t.volrel6<1.0), -1),
 ("z6>2.5 & volrel6>3 short", (t.z6>2.5)&(t.volrel6>3), -1),
 ("z6<-4 long any", (t.z6<-4), 1), ("z6>4 short any", (t.z6>4), -1),
])
print("\n#### H8 perp premium dislocation")
tab([
 ("prem_z<-3 long", t.prem_z<-3, 1), ("prem_z<-4 & ret1<0 long", (t.prem_z<-4)&(t.ret1<0), 1),
 ("premium<-0.3% long", t.premium<-0.003, 1), ("premium<-0.5% long", t.premium<-0.005, 1),
 ("prem_z>3 short", t.prem_z>3, -1), ("premium>0.3% short", t.premium>0.003, -1), ("premium>0.5% short", t.premium>0.005, -1),
 ("prem_z<-3 & z1<-3 long", (t.prem_z<-3)&(t.z1<-3), 1),
])
