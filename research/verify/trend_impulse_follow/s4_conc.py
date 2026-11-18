"""Concentration: by symbol, quarter, day, side; removals; guardian dependence."""
import time
from dataclasses import replace
from vcommon import *
from desk.engine.core import FeedBase
t0=time.time()
market, cells, intents = setup()
s, tr, e, g = wf_val(market, intents)
T=pd.DataFrame(tr); T["entry_time"]=pd.to_datetime(T.entry_time); T["exit_time"]=pd.to_datetime(T.exit_time)
tot=T.pnl.sum()
print("total $%.0f over %d trades" % (tot, len(T)))
bs=T.groupby("symbol").pnl.agg(["sum","count"]).sort_values("sum",ascending=False)
print(bs.round(0).to_string())
best=bs.index[0]
print("\nwithout best symbol (%s): $%.0f = %+.2f%%; without best two: %+.2f%%; without best three: %+.2f%%" % (best, tot-bs["sum"].iloc[0], (tot-bs["sum"].iloc[0])/100, (tot-bs["sum"].iloc[:2].sum())/100, (tot-bs["sum"].iloc[:3].sum())/100))
q=T.groupby(T.exit_time.dt.tz_localize(None).dt.to_period("Q")).pnl.agg(["sum","count"])
print("\nby exit quarter:\n", q.round(0).to_string())
print("without best quarter: %+.2f%%" % ((tot-q["sum"].max())/100))
m=T.groupby(T.exit_time.dt.tz_localize(None).dt.to_period("M")).pnl.sum()
print("by month:", m.round(0).to_dict())
print("without best month %+.2f%%, without best two months %+.2f%%, best three %+.2f%%" % ((tot-m.nlargest(1).sum())/100,(tot-m.nlargest(2).sum())/100,(tot-m.nlargest(3).sum())/100))
d=T.groupby(T.exit_time.dt.floor("D")).pnl.sum().sort_values(ascending=False)
print("\nexit days: %d; best five days: %s" % (len(d), {str(k.date()): round(v) for k,v in d.head(5).items()}))
print("without best 5 exit days: %+.2f%%; without best 10: %+.2f%%; worst five days sum $%.0f" % ((tot-d.head(5).sum())/100, (tot-d.head(10).sum())/100, d.tail(5).sum()))
de=T.groupby(T.entry_time.dt.floor("D")).pnl.sum().sort_values(ascending=False)
print("by ENTRY day: best five %s; without best 5 entry days: %+.2f%%; without best 10: %+.2f%%" % ({str(k.date()): round(v) for k,v in de.head(5).items()}, (tot-de.head(5).sum())/100, (tot-de.head(10).sum())/100))
ts=T.pnl.sort_values(ascending=False)
print("\ntop 5 trades $%.0f, top 10 $%.0f, top 20 $%.0f (of %d); without top 10 trades: %+.2f%%; without top 13 (5%%): %+.2f%%" % (ts.head(5).sum(), ts.head(10).sum(), ts.head(20).sum(), len(T), (tot-ts.head(10).sum())/100, (tot-ts.head(13).sum())/100))
print("largest R: ", T.r.nlargest(8).round(2).tolist())
print("\nby side:\n", T.groupby("side").agg(n=("pnl","size"), pnl=("pnl","sum"), win=("pnl", lambda x:(x>0).mean()), avg_r=("r","mean")).round(3).to_string())
print("by side and quarter:\n", T.pivot_table(index=T.exit_time.dt.tz_localize(None).dt.to_period("Q"), columns="side", values="pnl", aggfunc="sum").round(0).to_string())
print("by exit reason:\n", T.groupby("reason").agg(n=("pnl","size"), pnl=("pnl","sum"), avg_r=("r","mean"), bars=("bars_held","mean")).round(3).to_string())
allowed=set(json.loads((ROOT/"config/coinbase_perps.json").read_text())["kraken_symbols"])
cb=T[T.symbol.isin(allowed)]
print("\npost-hoc Coinbase-listed only: %d trades $%.0f = %+.2f%%; non-Coinbase: %d trades $%.0f (%s)" % (len(cb), cb.pnl.sum(), cb.pnl.sum()/100, len(T)-len(cb), T[~T.symbol.isin(allowed)].pnl.sum(), sorted(set(T.symbol)-allowed)))
cb2=cb[cb.symbol!=best]
print("Coinbase-only and without %s: %+.2f%%; Coinbase-only without best quarter: %+.2f%%" % (best, cb2.pnl.sum()/100, (cb.pnl.sum()-cb.groupby(cb.exit_time.dt.tz_localize(None).dt.to_period("Q")).pnl.sum().max())/100))

# ---- engine re-runs (path-dependent removals) with the same chosen cells
def base_excluding(drop=(), only=None):
    arrays={}
    for sym, a in market.base.arrays.items():
        b=dict(a)
        if sym in drop or (only is not None and sym not in only): b["tradable"]=np.zeros_like(a["tradable"])
        arrays[sym]=b
    return FeedBase(market.base.index, arrays, market.base.helpers)
def show(label, **kw):
    ss,tt,_,_=wf_val(market,intents,**kw); mc=harness.monte_carlo(tt,EQ0)
    print("%-55s ret %+6.2f%% dd %6.2f%% n %3d avg_r %+.3f long $%5.0f short $%5.0f p %.3f" % (label, ss["total_return"]*100, ss["max_dd"]*100, ss["n_trades"], ss["avg_r"], ss.get("long_pnl_usd",0), ss.get("short_pnl_usd",0), mc["p_value_mean_le_0"]), flush=True)
    return ss,tt
print("\nENGINE RE-RUNS, same walk-forward cells")
show("as audited")
show("engine: %s untradable" % best, base=base_excluding(drop={best}))
show("engine: ETH+BTC untradable", base=base_excluding(drop={"PF_ETHUSD","PF_XBTUSD"}))
show("engine: Coinbase-listed only (same cells)", base=base_excluding(only=allowed))
show("engine: Coinbase-listed only, one bar late", base=base_excluding(only=allowed), delay=1)
show("engine: Coinbase-listed only, guardian off", base=base_excluding(only=allowed), risk=replace(Risk(),guardian=False))
print("\nGUARDIAN DEPENDENCE (the Hunter's spec has no such exit)")
show("guardian off (the strategy as specified)", risk=replace(Risk(),guardian=False))
show("guardian off, one bar late", risk=replace(Risk(),guardian=False), delay=1)
for n in (2,3,4,5,6):
    show("guardian: halt after %d losses in a row" % n, risk=replace(Risk(),max_consec_losses=n))
show("guardian: consec-loss rule only off (daily -3%% kept)", risk=replace(Risk(),max_consec_losses=10**6))
show("guardian sticky-free, daily limit 2%", risk=replace(Risk(),daily_loss_limit=0.02))
show("max 3 positions", risk=replace(Risk(),max_positions=3))
print("time", round(time.time()-t0,1))
