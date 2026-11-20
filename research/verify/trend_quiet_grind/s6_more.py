"""Causal random-delay null, episode-level luck, small diagnostics, universe timing."""
from dataclasses import replace
from vcommon import *
from desk.engine.core import Feed
from desk.strategies import ta
t0=time.time()
market, cells, intents = setup()
s, tr, e, g = wf_val(market, intents)
T = pd.DataFrame(tr); T["entry_time"]=pd.to_datetime(T.entry_time); T["exit_time"]=pd.to_datetime(T.exit_time)
idx=market.base.index; N=len(idx)
VAL=[(pd.Timestamp(c["test_start"],tz="UTC"), pd.Timestamp(c["test_end"],tz="UTC"), c["params"]) for c in CHOSEN if c["test_start"]>="2025"]
blank=attach(market.base, {})
ATR={s_: ta.atr(df,24).reindex(idx).to_numpy() for s_,df in market.data.items()}
CL={s_: market.base.arrays[s_]["c"] for s_ in market.base.arrays}
trad={s_: market.base.arrays[s_]["tradable"] for s_ in market.base.arrays}
def run_signals(sig, risk=None):
    sym={}
    for s_,f in blank.sym.items():
        pos=sig.get(s_)
        if pos is None or not len(pos): sym[s_]=f; continue
        side=np.zeros(N,dtype=np.int8); stop=np.full(N,np.nan); pos=np.asarray(pos)
        side[pos]=1; stop[pos]=CL[s_][pos]-7.0*ATR[s_][pos]; sym[s_]=replace(f, side=side, stop=stop)
    feed=Feed(idx, sym, market.base.helpers)
    parts=[run_feed(feed, STRATEGY, a, b, Costs(), risk or Risk()) for a,b,_ in VAL]
    e_,g_,t_=harness.stitch(parts,EQ0); return summarize(e_,t_,EQ0,g_), t_
sigpos=[(t.symbol, idx.get_loc(t.entry_time)-1) for t in T.itertuples()]
REAL=s["total_return"]
rng=np.random.default_rng(777)
for name,lo,hi in (("A3 causal: each real signal delayed by a random 1..72 h", 1, 72), ("A4 causal: delayed by a random 1..168 h", 1, 168)):
    rets=[]; ns=[]
    for d in range(300):
        sig={}
        for s_,p in sigpos:
            j=min(p+int(rng.integers(lo,hi+1)), N-2)
            if trad[s_][j]: sig.setdefault(s_,[]).append(j)
        ss,_=run_signals({k:np.array(sorted(set(v))) for k,v in sig.items()}); rets.append(ss["total_return"]); ns.append(ss["n_trades"])
    rets=np.array(rets)
    print("%-58s draws 300 | trades median %d | mean %+.2f%% median %+.2f%% p05 %+.2f%% p95 %+.2f%% | share >= real: %.3f" % (name, np.median(ns), rets.mean()*100, np.median(rets)*100, np.percentile(rets,5)*100, np.percentile(rets,95)*100, (rets>=REAL).mean()), flush=True)

# ---- luck at the level the profit actually clusters
def boot(x, n=20000, seed=0):
    r=np.random.default_rng(seed); x=np.asarray(x,float); d=r.choice(x,size=(n,len(x)),replace=True).sum(axis=1); return float((d<=0).mean())
e_=T.sort_values("entry_time"); e_["ep"]=(e_.entry_time.diff()>pd.Timedelta(days=7)).cumsum()
ep=e_.groupby("ep").pnl.sum().to_numpy()
mo=T.groupby([T.exit_time.dt.year,T.exit_time.dt.month]).pnl.sum().to_numpy()
mo17=np.concatenate([mo, np.zeros(17-len(mo))])
print("\nbootstrap P(total <= 0): by exit day %.3f | by exit week %.3f | by exit month (14 with trades) %.3f | by calendar month (17) %.3f | by episode (12) %.3f" % (
    boot(T.groupby(T.exit_time.dt.floor("D")).pnl.sum()), boot(T.groupby(T.exit_time.dt.floor("D")-pd.to_timedelta(T.exit_time.dt.dayofweek,unit="D")).pnl.sum()), boot(mo), boot(mo17), boot(ep)))
from math import sqrt
print("episodes: n %d mean $%.0f sd $%.0f t %.2f ; positive %d" % (len(ep), ep.mean(), ep.std(ddof=1), ep.mean()/(ep.std(ddof=1)/sqrt(len(ep))), (ep>0).sum()))
r=T.r.to_numpy(); print("per-trade R: mean %.3f sd %.2f naive t %.2f (ignores clustering); median R %.2f" % (r.mean(), r.std(ddof=1), r.mean()/(r.std(ddof=1)/sqrt(len(r))), np.median(r)))
lb=json.loads((ROOT/"research/results/leaderboard.json").read_text())
rows=lb if isinstance(lb,list) else lb.get("rows", lb.get("strategies", []))
try:
    ps=sorted(float(x.get("p", x.get("p_value"))) for x in rows); print("leaderboard p-values:", ps, "| count <= 0.271:", sum(p<=0.2714 for p in ps), "expected under pure chance: %.1f of %d" % (0.2713*len(ps), len(ps)))
except Exception as ex: print("leaderboard json shape:", type(lb), (list(lb.keys()) if isinstance(lb,dict) else lb[:1]), ex)

# ---- small diagnostics
print("\ntrade 104:", T.loc[104,["symbol","entry_time","exit_time","reason"]].tolist())
gx=T[T.reason=="guardian"]; print("guardian exits %d on %d distinct halt hours / %d distinct UTC days; pnl of guardian exits $%.0f" % (len(gx), gx.exit_time.nunique(), gx.exit_time.dt.floor("D").nunique(), gx.pnl.sum()))
df=market.data["PF_SUIUSD"]; rk=ta.rolling_rank(ta.efficiency_ratio(df["close"],336),4320)
near=rk[(rk-0.7).abs()<1e-9]; print("SUI bars with rank within 1e-9 of 0.7 (float tie at the threshold):", [(str(k), repr(v)) for k,v in near.items()][:5], "| any validation trade entered the bar after:", any((T.symbol=="PF_SUIUSD") & T.entry_time.isin(near.index+pd.Timedelta(hours=1))))
d=RES["default_design"]; v=RES["default_validation"]
print("Hunter's default cell (q0.8, stop 5): design ret %+.1f%% avg_r %+.3f dd %.1f%% | validation ret %+.2f%% avg_r %+.4f dd %.1f%% streak %d" % (d["total_return"]*100,d["avg_r"],d["max_dd"]*100,v["total_return"]*100,v["avg_r"],v["max_dd"]*100,v["longest_losing_streak"]))
print("funding: paid $%.0f on %d trades; if actual funding were 5x the estimate: return %+.2f%%" % (T.funding.sum(), len(T), (T.pnl.sum()-4*T.funding.sum())/100))
est={s_: float(df["funding_is_est"][(df.index>=DESIGN_END)].mean()) for s_,df in market.data.items() if s_ in set(T.symbol)}
print("share of validation hours with ESTIMATED funding (traded symbols): min %.2f max %.2f" % (min(est.values()), max(est.values())))
hrs=0; esth=0
for t in T.itertuples():
    f=market.data[t.symbol]["funding_is_est"]; w=f[(f.index>=t.entry_time)&(f.index<t.exit_time)]; hrs+=len(w); esth+=int(w.sum())
print("position-hours on estimated funding: %.0f%%" % (esth/hrs*100))

# ---- universe timing: recompute months from daily volume of the PRIOR 30 days (rows before VALIDATION_END only)
import pyarrow.parquet as pq, pyarrow as pa
p=ROOT/"data/daily_volume.parquet"
tbl=pq.read_table(p, filters=[("time","<",pa.scalar(VALIDATION_END.to_pydatetime(), type=pq.read_schema(p).field("time").type))])
dd=tbl.to_pandas(); assert dd.time.max()<VALIDATION_END
dv=dd.pivot(index="time", columns="symbol", values="dollar_vol"); uni=store.universe(); have=set(store.symbols())
for m in ("2025-04","2025-05","2025-07","2026-01","2026-05"):
    ms=pd.Timestamp(m+"-01",tz="UTC"); win=dv[(dv.index>=ms-pd.Timedelta(days=30))&(dv.index<ms)]
    med=win.fillna(0).median(); med=med[[c for c in med.index if c in have]].sort_values(ascending=False); top=set(med.index[:10])
    win2=dv[(dv.index>=ms)&(dv.index<ms+pd.DateOffset(months=1))]
    top2=set(win2.fillna(0).median()[[c for c in med.index]].sort_values(ascending=False).index[:10]) if len(win2)>=15 else None
    print(m, "listed == top-10 of the prior 30 days:", set(uni[m])==top, "(overlap %d)"%len(set(uni[m])&top), "| overlap with an in-month ranking:", None if top2 is None else len(set(uni[m])&top2))
print("time", round(time.time()-t0,1))
