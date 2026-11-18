"""Concentration: by symbol, quarter, month, day, trade; removals (static, and engine re-runs for symbol removals)."""
from vcommon import *
t0=time.time()
market, cells, intents = setup()
s, tr, e, g = wf_val(market, intents)
T = pd.DataFrame(tr); T["entry_time"]=pd.to_datetime(T.entry_time); T["exit_time"]=pd.to_datetime(T.exit_time)
tot=T.pnl.sum(); print("total pnl $%.0f over %d trades (all long: %s)" % (tot, len(T), (T.side==1).all()))
bs=T.groupby("symbol").agg(n=("pnl","size"), pnl=("pnl","sum"), win=("pnl",lambda x:(x>0).mean()), avg_r=("r","mean")).sort_values("pnl",ascending=False)
cb=set(json.loads((ROOT/"config/coinbase_perps.json").read_text())["kraken_symbols"]); bs["coinbase"]=[x in cb for x in bs.index]
print(bs.round(2).to_string())
print("symbols profitable: %d of %d" % ((bs.pnl>0).sum(), len(bs)))
print("without best symbol (%s): $%.0f = %+.2f%%" % (bs.index[0], tot-bs.pnl.iloc[0], (tot-bs.pnl.iloc[0])/100))
print("without best two symbols: $%.0f ; without best three: $%.0f" % (tot-bs.pnl.iloc[:2].sum(), tot-bs.pnl.iloc[:3].sum()))
print("non-Coinbase symbols pnl: $%.0f (%d trades); Coinbase-listed only (static): $%.0f = %+.2f%%" % (bs[~bs.coinbase].pnl.sum(), bs[~bs.coinbase].n.sum(), bs[bs.coinbase].pnl.sum(), bs[bs.coinbase].pnl.sum()/100))
q=T.groupby(T.exit_time.dt.to_period("Q")).agg(n=("pnl","size"), pnl=("pnl","sum"), win=("pnl",lambda x:(x>0).mean()))
print("\nby exit quarter\n", q.round(2).to_string())
print("without best quarter: $%.0f = %+.2f%% ; without best two quarters: $%.0f" % (tot-q.pnl.max(), (tot-q.pnl.max())/100, tot-q.pnl.nlargest(2).sum()))
m=T.groupby(T.exit_time.dt.to_period("M")).agg(n=("pnl","size"), pnl=("pnl","sum"))
print("\nby exit month\n", m.round(0).T.to_string())
print("months positive: %d of %d with trades (of 17 calendar months); without best month $%.0f; without best two months $%.0f" % ((m.pnl>0).sum(), len(m), tot-m.pnl.max(), tot-m.pnl.nlargest(2).sum()))
d=T.groupby(T.exit_time.dt.floor("D")).pnl.sum().sort_values(ascending=False)
print("\nexit days: %d; best five days: %s" % (len(d), [(str(k.date()), round(v)) for k,v in d.head(5).items()]))
print("without best 5 exit days: $%.0f = %+.2f%% ; without best 3: $%.0f ; without best 10: $%.0f" % (tot-d.head(5).sum(), (tot-d.head(5).sum())/100, tot-d.head(3).sum(), tot-d.head(10).sum()))
w=T.groupby(T.exit_time.dt.to_period("W")).pnl.sum().sort_values(ascending=False)
print("exit weeks: %d, positive %d; best 3 weeks $%.0f; without best 3 weeks $%.0f" % (len(w),(w>0).sum(), w.head(3).sum(), tot-w.head(3).sum()))
ed=T.groupby(T.entry_time.dt.floor("D")).pnl.sum().sort_values(ascending=False)
print("entry days: %d; best five entry days %s; without them $%.0f" % (len(ed), [(str(k.date()), round(v)) for k,v in ed.head(5).items()], tot-ed.head(5).sum()))
ts=T.sort_values("pnl",ascending=False)
print("\ntop 10 trades:\n", ts.head(10)[["symbol","entry_time","exit_time","reason","r","pnl"]].round(2).to_string())
for k in (3,5,10,15):
    print("without best %d trades (%.0f%% of trades): $%.0f" % (k, k/len(T)*100, tot-ts.pnl.head(k).sum()))
print("winners %d (%.0f%%), sum of winners $%.0f, sum of losers $%.0f; trades with r>2: %d contributing $%.0f" % ((T.pnl>0).sum(), (T.pnl>0).mean()*100, T.pnl[T.pnl>0].sum(), T.pnl[T.pnl<=0].sum(), (T.r>2).sum(), T.pnl[T.r>2].sum()))
# distinct episodes: cluster entries within 7 days of each other
e_=T.sort_values("entry_time"); gap=e_.entry_time.diff()>pd.Timedelta(days=7); e_["ep"]=gap.cumsum()
ep=e_.groupby("ep").agg(start=("entry_time","min"), end=("exit_time","max"), n=("pnl","size"), pnl=("pnl","sum"), syms=("symbol","nunique"))
print("\nepisodes (entries less than 7 days apart):\n", ep.round(0).to_string())
print("episodes %d, positive %d; without best episode $%.0f; without best two $%.0f" % (len(ep),(ep.pnl>0).sum(), tot-ep.pnl.max(), tot-ep.pnl.nlargest(2).sum()))

# engine re-runs with symbols removed (path dependent: guardian and caps re-run)
def base_without(drop=None, keep=None):
    arrays={}
    for sym,a in market.base.arrays.items():
        b=dict(a)
        if (drop and sym in drop) or (keep is not None and sym not in keep): b["tradable"]=np.zeros_like(a["tradable"])
        arrays[sym]=b
    return FeedBase(market.base.index, arrays, market.base.helpers)
print()
for lab,B in (("without "+bs.index[0], base_without(drop={bs.index[0]})), ("without best two", base_without(drop=set(bs.index[:2]))),
              ("without best three", base_without(drop=set(bs.index[:3]))), ("Coinbase-listed only (same chosen params)", base_without(keep=cb)),
              ("BTC+ETH only", base_without(keep={"PF_XBTUSD","PF_ETHUSD"}))):
    ss,tt,_,_=wf_val(market,intents,base=B); mc=harness.monte_carlo(tt,EQ0)
    ss1,_,_,_=wf_val(market,intents,base=B,delay=1)
    print("engine %-45s ret %+.2f%% dd %.2f%% n %d p %.3f | one bar late %+.2f%%" % (lab, ss["total_return"]*100, ss["max_dd"]*100, ss["n_trades"], mc["p_value_mean_le_0"], ss1["total_return"]*100))
# every fixed cell on validation, plus per-quarter
print("\nfixed cells on validation (no re-fitting):")
for k,c in enumerate(cells):
    f=attach(market.base,intents[k]); r=run_feed(f,STRATEGY,DESIGN_END,VALIDATION_END,Costs(),Risk())
    r0=run_feed(f,STRATEGY,DESIGN_END,VALIDATION_END,Costs(),replace_risk) if False else None
    tt=pd.DataFrame(r["trades"]); tt["x"]=pd.to_datetime(tt.exit_time)
    mm=tt.groupby(tt.x.dt.to_period("M")).pnl.sum()
    print(" q %.1f stop %.0f: ret %+.2f%% dd %.2f%% n %d p %.3f | without best two months %+.2f%%" % (c["q"], c["stop_atr"], r["summary"]["total_return"]*100, r["summary"]["max_dd"]*100, r["summary"]["n_trades"], harness.monte_carlo(r["trades"],EQ0)["p_value_mean_le_0"], (tt.pnl.sum()-mm.nlargest(2).sum())/100))
print("time", round(time.time()-t0,1))
