"""Fragility of the signal hour and of the weakest-signal bucket; top weekends; contract-size distortion."""
import sys, json, pickle
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
from desk.engine.runner import load_market
from desk.data.store import VALIDATION_END
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 200)
market = load_market(end=VALIDATION_END, syms=["PF_XBTUSD", "PF_XRPUSD", "PF_SOLUSD", "PF_DOGEUSD", "PF_ZECUSD", "PF_ADAUSD", "PF_SUIUSD", "PF_LTCUSD", "PF_WIFUSD"])
data = market.data
T = pickle.load(open(HERE / "trades.pkl", "rb"))["T"]
btc = data["PF_XBTUSD"]["close"]
w = btc / btc.shift(48) - 1
sig = pd.DatetimeIndex(T.entry_time) - pd.Timedelta(hours=1)
for d in (-2, -1, 1, 2):
    T[f"w{d:+d}"] = w.reindex(sig + pd.Timedelta(hours=d)).to_numpy()
own = {s: data[s]["close"] / data[s]["close"].shift(48) - 1 for s in T.symbol.unique()}
T["own"] = [own[s].get(t, np.nan) for s, t in zip(T.symbol, sig)]
T["own+1"] = [own[s].get(t + pd.Timedelta(hours=1), np.nan) for s, t in zip(T.symbol, sig)]
T["own-1"] = [own[s].get(t - pd.Timedelta(hours=1), np.nan) for s, t in zip(T.symbol, sig)]
T["survives+1"] = (np.sign(T["w+1"]) == T.side) & (np.sign(T["own+1"]) == T.side)
T["survives-1"] = (np.sign(T["w-1"]) == T.side) & (np.sign(T["own-1"]) == T.side)
print("trades whose signal (BTC sign and own sign) is the SAME one hour later: %d of %d, their pnl $%.0f; trades that would vanish/flip: %d, pnl $%.0f"
      % (T["survives+1"].sum(), len(T), T[T["survives+1"]].pnl.sum(), (~T["survives+1"]).sum(), T[~T["survives+1"]].pnl.sum()))
print("same test one hour earlier: stable %d pnl $%.0f; unstable %d pnl $%.0f"
      % (T["survives-1"].sum(), T[T["survives-1"]].pnl.sum(), (~T["survives-1"]).sum(), T[~T["survives-1"]].pnl.sum()))
both = T["survives+1"] & T["survives-1"]
print("stable both ways: %d trades pnl $%.0f | unstable either way: %d trades pnl $%.0f" % (both.sum(), T[both].pnl.sum(), (~both).sum(), T[~both].pnl.sum()))
ev = T.groupby("entry_time").agg(n=("pnl", "size"), pnl=("pnl", "sum"), side=("side", "first"), w=("w", "first"),
                                 w_m1=("w-1", "first"), w_p1=("w+1", "first"), syms=("symbol", lambda x: ",".join(s[3:-3] for s in x)))
print("\ntop 6 and bottom 4 weekends\n", pd.concat([ev.sort_values("pnl", ascending=False).head(6), ev.sort_values("pnl").head(4)]).round(4))
small = ev[ev.w.abs() < 0.005]
print("\nweekends with |BTC move| < 0.5%%: %d, pnl $%.0f; of these the BTC sign differs one hour earlier or later in %d"
      % (len(small), small.pnl.sum(), ((np.sign(small.w_m1) != np.sign(small.w)) | (np.sign(small.w_p1) != np.sign(small.w))).sum()))
print(small.round(4))
big = T[T.absw > 0.02]
print("\n|BTC move| > 2%% (the thesis case): %d trades on %d weekends, pnl $%.0f; long $%.0f short $%.0f; stopped out %d"
      % (len(big), big.entry_time.nunique(), big.pnl.sum(), big[big.side > 0].pnl.sum(), big[big.side < 0].pnl.sum(), (big.reason == "stop").sum()))
# week-clustered bootstrap, with and without XRP
rng = np.random.default_rng(0)
def boot(tr):
    v = tr.groupby("entry_time").pnl.sum().to_numpy()
    d = rng.choice(v, size=(20000, len(v)), replace=True).sum(axis=1)
    return (d <= 0).mean(), np.percentile(d, 5), np.percentile(d, 95)
print("\nweekend-cluster bootstrap P(total<=0): all %.3f (5%%..95%% $%.0f..$%.0f) | ex-XRP %.3f | |w|>=0.5%% only %.3f | shorts only %.3f | longs only %.3f"
      % (*boot(T), boot(T[T.symbol != "PF_XRPUSD"])[0], boot(T[T.absw >= 0.005])[0], boot(T[T.side < 0])[0], boot(T[T.side > 0])[0]))
# whole-contract sizing: position notional vs contract notional
print("\nposition notional by symbol ($): \n", T.groupby("symbol").notional.describe()[["count", "min", "50%", "max"]].round(0))
T["px"] = T.entry_price
for name, units in {"PF_XRPUSD": 500, "PF_SOLUSD": 5, "PF_DOGEUSD": 5000, "PF_ADAUSD": 1000, "PF_SUIUSD": 500, "PF_LTCUSD": 5}.items():
    t = T[T.symbol == name]
    if not len(t):
        continue
    cn = t.px * units
    k = np.round(t.qty / units)
    err = (k * units / t.qty - 1)
    print(f"  {name} ASSUMED contract {units} coins: contract notional ${cn.min():.0f}-${cn.max():.0f}; wanted contracts median {np.median(t.qty/units):.2f}; "
          f"rounds to zero in {int((k==0).sum())}/{len(t)} trades; risk error of the rest: median |{np.median(np.abs(err[k>0]))*100 if (k>0).any() else float('nan'):.0f}%|, max {np.max(np.abs(err[k>0]))*100 if (k>0).any() else float('nan'):.0f}%")
for step in (100, 250, 500, 1000):
    k = np.round(T.notional / step)
    print(f"  generic contract ${step}: trades rounding to zero {int((k==0).sum())}/{len(T)}; median |size error| {np.median(np.abs(k*step/T.notional-1))*100:.0f}%; p90 {np.percentile(np.abs(k*step/T.notional-1),90)*100:.0f}%")
