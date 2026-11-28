"""Execution realism: modelled slippage vs the ACTUAL $10k half-spread in the bars this strategy trades; engine re-runs
with actual costs, with and without a one-bar delay; clustering; gross exposure; whole-contract sizing."""
from dataclasses import replace
from vcommon import *
t0=time.time()
market, cells, intents = setup()
s, tr, e, g = wf_val(market, intents)
T = pd.DataFrame(tr); T["entry_time"]=pd.to_datetime(T.entry_time); T["exit_time"]=pd.to_datetime(T.exit_time)
idx = market.base.index
half = {}
for sym, df in market.data.items():
    mid=(df["ask_10k"]+df["bid_10k"])/2
    half[sym]=((df["ask_10k"]-df["bid_10k"])/mid/2*1e4).where(lambda x: x>=0).reindex(idx)
rows=[]
for _, t in T.iterrows():
    a=market.base.arrays[t.symbol]; hs=half[t.symbol]
    ie=idx.get_loc(t.entry_time); ix=idx.get_loc(t.exit_time)
    rows.append(dict(sym=t.symbol, reason=t.reason, notional=t.qty*t.entry_price, entry=t.entry_time,
        m_in=a["slip_bps"][ie], r_sig=hs.iloc[ie-1], r_fill=hs.iloc[ie],
        m_out=a["slip_bps"][ix]*(2 if t.reason=="stop" else 1), r_out_prev=hs.iloc[ix-1], r_out=hs.iloc[ix],
        pnl=t.pnl, risk=t.risk_usd))
D=pd.DataFrame(rows)
print("validation trades:", len(D))
print("\nENTRY half-spread bps (one way): modelled vs actual in signal bar vs actual in fill bar")
print(D[["m_in","r_sig","r_fill"]].describe(percentiles=[.5,.75,.9,.95]).round(2).to_string())
print("NaN actual at entry: signal bar %d, fill bar %d ; at exit: %d" % (D.r_sig.isna().sum(), D.r_fill.isna().sum(), D.r_out.isna().sum()))
print("ratio actual/modelled entry: signal bar mean %.2f median %.2f | fill bar mean %.2f median %.2f" % (
    (D.r_sig/D.m_in).mean(), (D.r_sig/D.m_in).median(), (D.r_fill/D.m_in).mean(), (D.r_fill/D.m_in).median()))
print("\nEXIT half-spread bps: modelled (x2 on stops) vs actual in bar before / exit bar")
print(D.groupby("reason")[["m_out","r_out_prev","r_out"]].agg(["mean","median","max"]).round(2).to_string())
for label, cin, cout in [("actual = fill bar / exit bar", D.r_fill.fillna(D.m_in), D.r_out.fillna(D.m_out)),
                         ("actual = worse of the two adjacent bars", np.fmax(D.r_sig, D.r_fill).fillna(D.m_in), np.fmax(D.r_out_prev, D.r_out).fillna(D.m_out)),
                         ("worse-of-two, and stops pay 2x actual", np.fmax(D.r_sig, D.r_fill).fillna(D.m_in), (np.fmax(D.r_out_prev, D.r_out)*np.where(D.reason=="stop",2,1)).fillna(D.m_out))]:
    mod = (D.notional*(D.m_in+D.m_out)/1e4).sum(); act=(D.notional*(cin+cout)/1e4).sum()
    print("%-45s modelled slip $%.0f  actual $%.0f  -> validation return %.2f%% -> %.2f%%" % (label, mod, act, D.pnl.sum()/100, (D.pnl.sum()-(act-mod))/100))

def base_with(kind):
    arrays={}
    for sym, a in market.base.arrays.items():
        b=dict(a); hs=half[sym].to_numpy(); mod=a["slip_bps"]
        act = hs if kind=="bar" else np.fmax(hs, np.concatenate([[np.nan],hs[:-1]]))
        b["slip_bps"]=np.where(np.isnan(act), mod, np.clip(act,0.5,None))
        arrays[sym]=b
    return FeedBase(market.base.index, arrays, market.base.helpers)
print()
for kind in ("bar","worse2"):
    B=base_with(kind)
    for delay in (0,1):
        for cm,cl in ((Costs(),"stops 2x"),):
            ss,tt,_,_=wf_val(market,intents,costs=cm,base=B,delay=delay)
            mc=harness.monte_carlo(tt,EQ0)
            print("engine, ACTUAL half-spread [%s], delay %d bar, %s: ret %+.2f%% dd %.2f%% n %d avg_r %.3f p %.3f" % (kind, delay, cl, ss["total_return"]*100, ss["max_dd"]*100, ss["n_trades"], ss["avg_r"], mc["p_value_mean_le_0"]), flush=True)
B=base_with("worse2")
ss,tt,_,_=wf_val(market,intents,delay=1,base=B,costs=replace(Costs(),fee_mult=2.0,funding_paid_mult=2.0))
print("engine, ACTUAL worse2 slip + fees x2 + funding paid x2 + one bar late: ret %+.2f%% dd %.2f%%" % (ss["total_return"]*100, ss["max_dd"]*100))
for delay in (0,1,2,3,6,12,24,48):
    ss,tt,_,_=wf_val(market,intents,delay=delay)
    print("engine, MODELLED costs, delay %2d bars: ret %+.2f%% dd %.2f%% n %d" % (delay, ss["total_return"]*100, ss["max_dd"]*100, ss["n_trades"]), flush=True)

# guardian dependence: the live/paper engine uses halt_sticky=True (a human must resume)
for lab, rk in (("guardian off", replace(Risk(), guardian=False)), ("guardian consec=4", replace(Risk(), max_consec_losses=4)),
                ("guardian consec=2", replace(Risk(), max_consec_losses=2)), ("guardian consec=5", replace(Risk(), max_consec_losses=5))):
    ss,tt,_,_=wf_val(market,intents,risk=rk)
    print("%-20s ret %+.2f%% dd %.2f%% n %d" % (lab, ss["total_return"]*100, ss["max_dd"]*100, ss["n_trades"]))

# ---- same-hour clustering and gross exposure
ent=T.groupby("entry_time").size()
print("\nentries: %d in %d distinct hours; hours with >=2 entries: %d (%.0f%% of trades); >=3: %d (%.0f%%); max in one hour: %d" % (
    len(T), len(ent), (ent>=2).sum(), ent[ent>=2].sum()/len(T)*100, (ent>=3).sum(), ent[ent>=3].sum()/len(T)*100, ent.max()))
print("entries at 00:00 UTC (day after a guardian halt / fold start):", int((T.entry_time.dt.hour==0).sum()))
print("entries by distinct UTC day: %d days; top 10 days hold %.0f%% of trades" % (T.entry_time.dt.floor("D").nunique(), T.groupby(T.entry_time.dt.floor("D")).size().nlargest(10).sum()/len(T)*100))
print("gross exposure: max $%.0f (%.2fx equity), mean when invested $%.0f; share of hours invested %.2f" % (g.max(), g.max()/EQ0, g[g>0].mean(), (g>0).mean()))
# max simultaneous positions
ev=[]; 
for _,t in T.iterrows(): ev+= [(t.entry_time,1),(t.exit_time,-1)]
ev=pd.DataFrame(ev,columns=["t","d"]).sort_values(["t","d"]); print("max simultaneous positions:", int(ev.d.cumsum().max()))

# ---- whole-contract sizing on Coinbase (0.01 BTC and 0.1 ETH per contract; other coins' contract sizes not in the repo)
CS={"PF_XBTUSD":0.01,"PF_ETHUSD":0.1}
for sym,cs in CS.items():
    X=T[T.symbol==sym]
    if not len(X): print(sym,"no validation trades"); continue
    n=X.qty/cs; fl=np.floor(n); rd=np.round(n)
    print("%s: %d trades, pnl $%.0f; contract value at entry $%.0f..$%.0f; intended contracts median %.2f min %.2f max %.2f; "
          "rounds to zero (floor): %d trades; risk if rounded to nearest: median $%.0f, range $%.0f..$%.0f (intended $50); "
          "pnl with nearest-contract sizing $%.0f, with floor $%.0f" % (
        sym, len(X), X.pnl.sum(), (cs*X.entry_price).min(), (cs*X.entry_price).max(), n.median(), n.min(), n.max(), int((fl==0).sum()),
        (rd/n*X.risk_usd).median(), (rd/n*X.risk_usd).min(), (rd/n*X.risk_usd).max(), (X.pnl*rd/n).sum(), (X.pnl*fl/n).sum()))
print("time", round(time.time()-t0,1))
D.to_csv(str(Path(__file__).parent/"s3_trade_costs.csv"), index=False)
