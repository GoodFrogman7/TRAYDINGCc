"""Is it just exposure? Random-entry nulls run through the SAME engine, folds, stop (7 ATR24 in every validation fold),
168-bar time stop, Guardian and costs; plus deterministic naive rules."""
from dataclasses import replace
from vcommon import *
from desk.engine.core import Feed, SymbolFeed
from desk.strategies import ta
t0=time.time()
market, cells, intents = setup()
s, tr, e, g = wf_val(market, intents)
T = pd.DataFrame(tr); T["entry_time"]=pd.to_datetime(T.entry_time)
idx=market.base.index; N=len(idx)
VAL=[(pd.Timestamp(c["test_start"],tz="UTC"), pd.Timestamp(c["test_end"],tz="UTC"), c["params"]) for c in CHOSEN if c["test_start"]>="2025"]
assert all(p["stop_atr"]==7.0 for _,_,p in VAL)
blank=attach(market.base, {})
ATR={s_: ta.atr(df,24).reindex(idx).to_numpy() for s_,df in market.data.items()}
CL={s_: market.base.arrays[s_]["c"] for s_ in market.base.arrays}
RK={}; R14={}
for s_,df in market.data.items():
    c=df["close"]; RK[s_]=ta.rolling_rank(ta.efficiency_ratio(c,336),4320).reindex(idx).to_numpy(); R14[s_]=ta.ret(c,336).reindex(idx).to_numpy()
month=(idx.year*100+idx.month).to_numpy()
i_val0=idx.searchsorted(DESIGN_END)

def run_signals(sig, risk=None, costs=None):
    """sig: {symbol: array of global bar positions where a long signal is emitted}"""
    sym={}
    for s_,f in blank.sym.items():
        pos=sig.get(s_)
        if pos is None or not len(pos): sym[s_]=f; continue
        side=np.zeros(N,dtype=np.int8); stop=np.full(N,np.nan)
        pos=np.asarray(pos); ok=~np.isnan(ATR[s_][pos]) & (ATR[s_][pos]>0); pos=pos[ok]
        side[pos]=1; stop[pos]=CL[s_][pos]-7.0*ATR[s_][pos]
        sym[s_]=replace(f, side=side, stop=stop)
    feed=Feed(idx, sym, market.base.helpers)
    parts=[run_feed(feed, STRATEGY, a, b, costs or Costs(), risk or Risk()) for a,b,_ in VAL]
    e_,g_,t_=harness.stitch(parts,EQ0); ss=summarize(e_,t_,EQ0,g_)
    return ss, t_

# sanity: feeding the module's own signals through this path reproduces the audit
own={}
for a,b,p in VAL:
    k=cells.index(p)
    for s_,it in intents[k].items():
        m=(it["side"].reindex(idx).fillna(0).to_numpy()>0) & (idx>=a) & (idx<b)
        own.setdefault(s_,[]).extend(np.nonzero(m)[0])
ss,_=run_signals({k:np.array(v) for k,v in own.items()})
print("sanity (own signals through the null machinery): ret %+.2f%% n %d" % (ss["total_return"]*100, ss["n_trades"]))
REAL=s["total_return"]; REAL_R=s["avg_r"]

# signal bar of each real trade
sigpos=[(t.symbol, idx.get_loc(t.entry_time)-1) for t in T.itertuples()]
trad={s_: market.base.arrays[s_]["tradable"] for s_ in market.base.arrays}
elig_month={}
def pool_month(s_, m):
    k=(s_,m)
    if k not in elig_month:
        elig_month[k]=np.nonzero((month==m) & trad[s_] & ~np.isnan(ATR[s_]))[0]
    return elig_month[k]
uni=store.universe()
val_months=sorted({int(m.replace("-","")) for m in uni if "2025-01"<=m<="2026-05"})
# symbols that could ever have signalled in a month (rank defined), for the unconditional null
def has_hist(s_, m):
    p=pool_month(s_,m); return len(p)>0 and not np.isnan(RK[s_][p[0]])

def summarize_null(name, rets, rs, ns):
    rets=np.array(rets); rs=np.array(rs)
    print("%-62s draws %d | trades median %d | return: mean %+.2f%% median %+.2f%% p05 %+.2f%% p95 %+.2f%% | share >= real (%+.2f%%): %.3f | avg_r mean %+.3f, share >= real (%.3f): %.3f" % (
        name, len(rets), np.median(ns), rets.mean()*100, np.median(rets)*100, np.percentile(rets,5)*100, np.percentile(rets,95)*100, REAL*100, (rets>=REAL).mean(), rs.mean(), REAL_R, (rs>=REAL_R).mean()), flush=True)

rng=np.random.default_rng(12345); ND=300
# A: same symbol-months, random hours
rets,rs,ns=[],[],[]
for d in range(ND):
    sig={}
    for s_,p in sigpos:
        pool=pool_month(s_, month[p]); sig.setdefault(s_,[]).append(int(rng.choice(pool)))
    ss,_=run_signals({k:np.array(sorted(set(v))) for k,v in sig.items()}); rets.append(ss["total_return"]); rs.append(ss.get("avg_r",0)); ns.append(ss["n_trades"])
summarize_null("A same symbol-MONTH, random hour (same count)", rets, rs, ns); A=np.array(rets)
# A2: same symbol, random hour within +-84h of the real signal
rets,rs,ns=[],[],[]
for d in range(ND):
    sig={}
    for s_,p in sigpos:
        lo=max(p-84,i_val0); hi=min(p+84,N-2); cand=np.arange(lo,hi+1); cand=cand[trad[s_][cand]]
        sig.setdefault(s_,[]).append(int(rng.choice(cand)) if len(cand) else p)
    ss,_=run_signals({k:np.array(sorted(set(v))) for k,v in sig.items()}); rets.append(ss["total_return"]); rs.append(ss.get("avg_r",0)); ns.append(ss["n_trades"])
summarize_null("A2 same symbol, random hour within +-3.5 days of real signal", rets, rs, ns)
# B: unconditional: random month of the window, random universe member with enough history, random hour
rets,rs,ns=[],[],[]
for d in range(ND):
    sig={}
    for _ in sigpos:
        while True:
            m=int(rng.choice(val_months)); ms="%d-%02d"%(m//100,m%100); s_=str(rng.choice(uni[ms]))
            if s_ in trad and has_hist(s_,m): break
        sig.setdefault(s_,[]).append(int(rng.choice(pool_month(s_,m))))
    ss,_=run_signals({k:np.array(sorted(set(v))) for k,v in sig.items()}); rets.append(ss["total_return"]); rs.append(ss.get("avg_r",0)); ns.append(ss["n_trades"])
summarize_null("B random universe symbol-month of the window, random hour", rets, rs, ns)
# C: random hours among bars where the plain 14-day return is positive (no smoothness filter), same symbol-quarter counts
rets,rs,ns=[],[],[]
qpool={}
for d in range(ND):
    sig={}
    for s_,p in sigpos:
        a,b=[(a,b) for a,b,_ in VAL if a<=idx[p+1]<b][0]; k=(s_,a)
        if k not in qpool:
            ia,ib=idx.searchsorted(a),idx.searchsorted(b); c=np.arange(ia,ib-1)
            qpool[k]=c[trad[s_][c] & (R14[s_][c]>0) & ~np.isnan(RK[s_][c])]
        sig.setdefault(s_,[]).append(int(rng.choice(qpool[k])))
    ss,_=run_signals({k:np.array(sorted(set(v))) for k,v in sig.items()}); rets.append(ss["total_return"]); rs.append(ss.get("avg_r",0)); ns.append(ss["n_trades"])
summarize_null("C same symbol-QUARTER, random hour with 14d return > 0", rets, rs, ns)
np.save(str(Path(__file__).parent/"null_A.npy"), A)

# deterministic naive rules, same engine / stop / hold / Guardian
def all_bars(cond):
    out={}
    for s_ in trad:
        m=cond(s_) & (np.arange(N)>=i_val0)
        out[s_]=np.nonzero(m)[0]
    return out
for name,cond in (("always long every universe coin (weekly roll, 7-ATR stop)", lambda s_: trad[s_] & ~np.isnan(RK[s_])),
                  ("14-day return > 0, no smoothness filter", lambda s_: trad[s_] & (R14[s_]>0) & ~np.isnan(RK[s_])),
                  ("smoothness rank >= 0.8 but 14-day return < 0 (smooth FALLS, bought)", lambda s_: trad[s_] & (R14[s_]<0) & (RK[s_]>=0.8)),
                  ("14-day return > 0 and smoothness rank < 0.5 (choppy rises)", lambda s_: trad[s_] & (R14[s_]>0) & (RK[s_]<0.5)),
                  ("14-day return > 0 and rank >= 0.7 (fixed cell)", lambda s_: trad[s_] & (R14[s_]>0) & (RK[s_]>=0.7)),
                  ("14-day return > 0 and rank >= 0.9 (fixed cell)", lambda s_: trad[s_] & (R14[s_]>0) & (RK[s_]>=0.9))):
    ss,tt=run_signals(all_bars(cond)); mc=harness.monte_carlo(tt,EQ0)
    ss2,_=run_signals(all_bars(cond), risk=replace(Risk(),guardian=False))
    print("naive: %-68s ret %+.2f%% dd %.2f%% n %d avg_r %+.3f p %.3f | guardian off %+.2f%%" % (name, ss["total_return"]*100, ss["max_dd"]*100, ss["n_trades"], ss.get("avg_r",0), mc["p_value_mean_le_0"], ss2["total_return"]*100), flush=True)
print("time", round(time.time()-t0,1))
