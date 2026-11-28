"""Is it just exposure? Random-entry placebos with the same symbol-months, direction, stop and holding period.
A: standalone trade-by-trade simulator (no guardian, no portfolio caps), 500 draws.
B: the desk engine itself (guardian on, same folds), random intents, N draws."""
import sys, time
from dataclasses import replace
from vcommon import *
from desk.strategies import ta
from desk.engine.core import blank_intents
t0=time.time()
NB=int(sys.argv[1]) if len(sys.argv)>1 else 150
market, cells, intents = setup()
idx=market.base.index; A=market.base.arrays
atr={s: ta.atr(df,24).reindex(idx).to_numpy() for s,df in market.data.items()}
trend={s: np.sign(ta.ret(df["close"],336).shift(1)).reindex(idx).to_numpy() for s,df in market.data.items()}
month=(idx.year*100+idx.month).to_numpy()
folds=[(idx.searchsorted(pd.Timestamp(c["test_start"],tz="UTC")), idx.searchsorted(pd.Timestamp(c["test_end"],tz="UTC")), cells[c["cell"]]["stop_atr"]) for c in CHOSEN if pd.Timestamp(c["test_start"],tz="UTC")>=DESIGN_END]
def fold_of(i):
    for f0,f1,sa in folds:
        if f0<=i<f1: return f0,f1,sa
    return None
FEE=0.0005
def sim(sym, side, t):
    """signal at close of bar t -> pnl in $ for a $50-risk trade, engine fill rules, no guardian"""
    a=A[sym]; i=t+1; f=fold_of(i)
    if f is None: return np.nan
    f0,f1,sa=f
    at=atr[sym][t]; c=a["c"][t]
    if not (at>0): return np.nan
    stop=c-side*sa*at
    px=a["o"][i]*(1+side*a["slip_bps"][i]/1e4)
    dist=(px-stop)*side
    if not dist>0 or dist/px<0.002 or dist/px>0.25: return np.nan
    qty=min(50.0/dist, 10000.0/px)
    j1=min(i+72, f1)                       # bars i..j1-1 are held
    lo=a["l"][i:j1]; hi=a["h"][i:j1]; op=a["o"][i:j1]
    hit=(lo<=stop) if side>0 else (hi>=stop)
    fund=(side*qty*op*a["funding"][i:j1])
    if hit.any():
        k=int(np.argmax(hit)); gap=(k>0) and ((op[k]<=stop) if side>0 else (op[k]>=stop))
        ex=(op[k] if gap else stop)*(1-side*2*a["slip_bps"][i+k]/1e4); fu=fund[:k+1].sum()
    elif i+72<f1:
        ex=a["o"][i+72]*(1-side*a["slip_bps"][i+72]/1e4); fu=fund.sum()
    else:
        ex=a["c"][f1-1]*(1-side*a["slip_bps"][f1-1]/1e4); fu=fund.sum()
    return side*qty*(ex-px)-qty*(px+ex)*FEE-fu

# reference trade lists
s_on, tr_on, _, _ = wf_val(market, intents)
s_off, tr_off, _, _ = wf_val(market, intents, risk=replace(Risk(), guardian=False))
def prep(tr):
    T=pd.DataFrame(tr); T["i"]=[idx.get_loc(pd.Timestamp(x)) for x in T.entry_time]; T["t"]=T.i-1; T["m"]=month[T.i.to_numpy()]
    return T
Toff=prep(tr_off); Ton=prep(tr_on)
real=np.array([sim(r.symbol,int(r.side),int(r.t)) for r in Toff.itertuples()])
print("standalone simulator on the %d real guardian-off trades: $%.0f (engine guardian-off: $%.0f)" % (len(Toff), np.nansum(real), Toff.pnl.sum()))
print("  real longs $%.0f (n %d), real shorts $%.0f (n %d)" % (np.nansum(real[Toff.side.to_numpy()>0]), (Toff.side>0).sum(), np.nansum(real[Toff.side.to_numpy()<0]), (Toff.side<0).sum()))

# eligible signal bars per (symbol, month): fill bar tradable, atr known
elig={}; elig_tr={}
def pool(sym, m, side, with_trend):
    key=(sym,m,side,with_trend)
    if key not in elig:
        a=A[sym]; ok=np.zeros(len(idx),bool)
        ok[:-1]=a["tradable"][1:] & (month[1:]==m) & (atr[sym][:-1]>0) & a["valid"][:-1]
        if with_trend: ok &= (trend[sym]==side)
        elig[key]=np.nonzero(ok)[0]
    return elig[key]
rng=np.random.default_rng(12345)
def placebo_A(T, with_trend, n=500):
    tot=np.zeros(n); lg=np.zeros(n); sh=np.zeros(n)
    pools=[pool(r.symbol,int(r.m),int(r.side),with_trend) for r in T.itertuples()]
    sides=T.side.to_numpy(); syms=T.symbol.to_numpy()
    for d in range(n):
        for k in range(len(T)):
            p=pools[k]
            if not len(p): continue
            v=sim(syms[k], int(sides[k]), int(p[rng.integers(len(p))]))
            if v==v:
                tot[d]+=v
                if sides[k]>0: lg[d]+=v
                else: sh[d]+=v
    return tot, lg, sh
def report(label, x, realv):
    print("  %-48s placebo mean $%6.0f sd $%5.0f  p05 $%6.0f p50 $%6.0f p95 $%6.0f | real $%6.0f = percentile %.1f" % (label, x.mean(), x.std(), np.percentile(x,5), np.percentile(x,50), np.percentile(x,95), realv, (x<realv).mean()*100))
rl=np.nansum(real[Toff.side.to_numpy()>0]); rs=np.nansum(real[Toff.side.to_numpy()<0])
for wt,label in ((False,"same symbol-month, same side, random hour"),(True,"same, and hour must agree with 14-day trend")):
    tot,lg,sh=placebo_A(Toff, wt)
    print("A (no guardian) %s, 500 draws:" % label)
    report("all trades", tot, np.nansum(real)); report("longs only", lg, rl); report("shorts only", sh, rs)
    print("   time", round(time.time()-t0,1), flush=True)

# B: engine with guardian, same folds
def run_engine_placebo(T, with_trend):
    its={}
    for sym, grp in T.groupby("symbol"):
        it=blank_intents(idx); side=np.zeros(len(idx),dtype=np.int8); stop=np.full(len(idx),np.nan)
        for r in grp.itertuples():
            p=pool(sym,int(r.m),int(r.side),with_trend)
            if not len(p): continue
            t=int(p[rng.integers(len(p))]); f=fold_of(t+1)
            if f is None: continue
            side[t]=r.side; stop[t]=A[sym]["c"][t]-r.side*f[2]*atr[sym][t]
        it["side"]=side; it["stop"]=stop; its[sym]=it
    feed=attach(market.base, its)
    parts=[run_feed(feed, STRATEGY, idx[f0], idx[f1-1]+pd.Timedelta(hours=1), Costs(), Risk()) for f0,f1,_ in folds]
    e,g,t=harness.stitch(parts,EQ0)
    return sum(x["pnl"] for x in t), len(t), sum(x["pnl"] for x in t if x["side"]>0)
for wt,label in ((False,"same symbol-month, same side, random hour"),(True,"same, and hour must agree with 14-day trend")):
    res=np.array([run_engine_placebo(Ton, wt) for _ in range(NB)])
    x=res[:,0]
    print("B (engine, guardian ON) %s, %d draws: avg trades %.0f" % (label, NB, res[:,1].mean()))
    report("all trades", x, Ton.pnl.sum()); report("longs only", res[:,2], Ton[Ton.side>0].pnl.sum())
    print("   time", round(time.time()-t0,1), flush=True)
