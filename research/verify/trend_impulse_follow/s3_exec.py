"""Execution realism: modelled slippage vs the ACTUAL $10k half-spread in the bars this strategy trades."""
import time, copy
from dataclasses import replace
from vcommon import *
from desk.engine.core import FeedBase
t0=time.time()
market, cells, intents = setup()
s, tr, e, g = wf_val(market, intents)
T = pd.DataFrame(tr)
T["entry_time"]=pd.to_datetime(T.entry_time); T["exit_time"]=pd.to_datetime(T.exit_time)
idx = market.base.index
half = {}
for sym, df in market.data.items():
    mid=(df["ask_10k"]+df["bid_10k"])/2
    half[sym]=((df["ask_10k"]-df["bid_10k"])/mid/2*1e4).where(lambda x: x>=0).reindex(idx)
rows=[]
for _, t in T.iterrows():
    a=market.base.arrays[t.symbol]; hs=half[t.symbol]
    ie=idx.get_loc(t.entry_time); ix=idx.get_loc(t.exit_time)
    # entry fills at open[ie] = close[ie-1]: the order is sent as the signal bar (ie-1) closes
    rows.append(dict(sym=t.symbol, side=t.side, reason=t.reason, notional=t.qty*t.entry_price,
        m_in=a["slip_bps"][ie], r_sig=hs.iloc[ie-1], r_fill=hs.iloc[ie],
        m_out=a["slip_bps"][ix]*(2 if t.reason=="stop" else 1), r_out_prev=hs.iloc[ix-1], r_out=hs.iloc[ix],
        pnl=t.pnl, risk=t.risk_usd,
        px_vs_mark=t.side*(market.data[t.symbol]["close"].reindex(idx).iloc[ie-1]/market.data[t.symbol]["mark_close"].reindex(idx).iloc[ie-1]-1)*1e4))
D=pd.DataFrame(rows)
pd.set_option("display.width",200)
print("validation trades:", len(D), " notional $: median %.0f mean %.0f max %.0f; share capped at $10k: %.2f" % (D.notional.median(), D.notional.mean(), D.notional.max(), (D.notional>9990).mean()))
print("\nENTRY half-spread bps (one way): modelled vs actual in signal bar vs actual in fill bar")
print(D[["m_in","r_sig","r_fill"]].describe(percentiles=[.5,.75,.9,.95]).round(2).to_string())
print("NaN actual at entry: signal bar %d, fill bar %d" % (D.r_sig.isna().sum(), D.r_fill.isna().sum()))
print("ratio actual/modelled entry: signal bar mean %.2f median %.2f | fill bar mean %.2f median %.2f" % (
    (D.r_sig/D.m_in).mean(), (D.r_sig/D.m_in).median(), (D.r_fill/D.m_in).mean(), (D.r_fill/D.m_in).median()))
print("\nEXIT half-spread bps: modelled (x2 on stops) vs actual in exit bar / bar before")
print(D.groupby("reason")[["m_out","r_out_prev","r_out"]].agg(["mean","median"]).round(2).to_string())
# dollar re-pricing, trade by trade (sizes unchanged): extra cost = notional * (actual - modelled)
for label, cin, cout in [("actual = fill bar / exit bar", D.r_fill.fillna(D.m_in), D.r_out.fillna(D.m_out)),
                         ("actual = worse of the two adjacent bars", np.fmax(D.r_sig, D.r_fill).fillna(D.m_in), np.fmax(D.r_out_prev, D.r_out).fillna(D.m_out)),
                         ("worse-of-two, and stops pay 2x actual", np.fmax(D.r_sig, D.r_fill).fillna(D.m_in), (np.fmax(D.r_out_prev, D.r_out)*np.where(D.reason=="stop",2,1)).fillna(D.m_out))]:
    mod = (D.notional*(D.m_in+D.m_out)/1e4).sum(); act=(D.notional*(cin+cout)/1e4).sum()
    print("%-45s modelled slip $%.0f  actual $%.0f  -> validation return %.2f%% -> %.2f%%" % (label, mod, act, D.pnl.sum()/100, (D.pnl.sum()-(act-mod))/100))
print("\nsigned (close - mark) at signal close, bps in trade direction (positive = we pay up vs mark): mean %.1f median %.1f p05 %.1f p95 %.1f" % (
    D.px_vs_mark.mean(), D.px_vs_mark.median(), D.px_vs_mark.quantile(.05), D.px_vs_mark.quantile(.95)))

# ---- full engine re-runs with ACTUAL costs in the slip array (path-dependent: sizing, guardian, stops all re-run)
def base_with(kind):
    arrays={}
    for sym, a in market.base.arrays.items():
        b=dict(a); hs=half[sym].to_numpy(); mod=a["slip_bps"]
        if kind=="bar": act=hs
        else: act=np.fmax(hs, np.concatenate([[np.nan],hs[:-1]]))
        b["slip_bps"]=np.where(np.isnan(act), mod, np.clip(act,0.5,None))
        arrays[sym]=b
    return FeedBase(market.base.index, arrays, market.base.helpers)
out={}
for kind in ("bar","worse2"):
    B=base_with(kind)
    for delay in (0,1):
        for cm,cl in ((Costs(),"stops 2x"),(replace(Costs(),stop_slip_mult=1.0),"stops 1x")):
            ss,tt,_,_=wf_val(market,intents,costs=cm,base=B,delay=delay)
            mc=harness.monte_carlo(tt,EQ0)
            print("engine, actual half-spread [%s], delay %d bar, %s: ret %+.2f%% dd %.2f%% n %d avg_r %.3f p %.3f" % (kind, delay, cl, ss["total_return"]*100, ss["max_dd"]*100, ss["n_trades"], ss["avg_r"], mc["p_value_mean_le_0"]), flush=True)
            out[(kind,delay,cl)]=ss["total_return"]
for delay in (0,1,2,3):
    ss,tt,_,_=wf_val(market,intents,delay=delay)
    print("engine, MODELLED costs, delay %d: ret %+.2f%% dd %.2f%% n %d" % (delay, ss["total_return"]*100, ss["max_dd"]*100, ss["n_trades"]))
ss,tt,_,_=wf_val(market,intents,delay=1,costs=replace(Costs(),fee_mult=2.0,slip_mult=2.0,funding_paid_mult=2.0))
print("engine, all modelled costs x2 AND one bar late: ret %+.2f%% dd %.2f%%" % (ss["total_return"]*100, ss["max_dd"]*100))

# ---- same-hour clustering and gross exposure
ent=T.groupby("entry_time").size()
print("\nentries: %d in %d distinct hours; hours with >=3 entries: %d (%.0f%% of trades); >=5: %d; max in one hour: %d" % (
    len(T), len(ent), (ent>=3).sum(), ent[ent>=3].sum()/len(T)*100, (ent>=5).sum(), ent.max()))
print("entries by distinct UTC day: %d days; top 10 days hold %.0f%% of trades" % (T.entry_time.dt.floor("D").nunique(), T.groupby(T.entry_time.dt.floor("D")).size().nlargest(10).sum()/len(T)*100))
print("gross exposure: max $%.0f (%.2fx equity), mean when invested $%.0f; share of hours invested %.2f" % (g.max(), g.max()/EQ0, g[g>0].mean(), (g>0).mean()))
print("time", round(time.time()-t0,1))
D.to_csv("s3_trade_costs.csv", index=False)
