"""(a) placebo without forward-looking month matching: follow the 14-day trend at random tradable hours;
(b) the same placebo comparison on the walk-forward quarters BEFORE validation; (c) Coinbase whole-contract sizing;
(d) luck arithmetic."""
import time
from dataclasses import replace
from vcommon import *
from desk.strategies import ta
t0=time.time()
market, cells, intents = setup()
idx=market.base.index; A=market.base.arrays
atr={s: ta.atr(df,24).reindex(idx).to_numpy() for s,df in market.data.items()}
trend={s: np.sign(ta.ret(df["close"],336).shift(1)).reindex(idx).to_numpy() for s,df in market.data.items()}
month=(idx.year*100+idx.month).to_numpy()
def mk_folds(pred):
    return [(idx.searchsorted(pd.Timestamp(c["test_start"],tz="UTC")), idx.searchsorted(pd.Timestamp(c["test_end"],tz="UTC")), cells[c["cell"]]["stop_atr"], c["cell"]) for c in CHOSEN if pred(pd.Timestamp(c["test_start"],tz="UTC"))]
FEE=0.0005
def sim(sym, side, t, folds):
    a=A[sym]; i=t+1
    f=next((f for f in folds if f[0]<=i<f[1]), None)
    if f is None: return np.nan
    f0,f1,sa,_=f; at=atr[sym][t]
    if not (at>0): return np.nan
    stop=a["c"][t]-side*sa*at; px=a["o"][i]*(1+side*a["slip_bps"][i]/1e4); dist=(px-stop)*side
    if not dist>0 or dist/px<0.002 or dist/px>0.25: return np.nan
    qty=min(50.0/dist, 10000.0/px); j1=min(i+72,f1)
    lo=a["l"][i:j1]; hi=a["h"][i:j1]; op=a["o"][i:j1]
    hit=(lo<=stop) if side>0 else (hi>=stop); fund=side*qty*op*a["funding"][i:j1]
    if hit.any():
        k=int(np.argmax(hit)); gap=(k>0) and ((op[k]<=stop) if side>0 else (op[k]>=stop))
        ex=(op[k] if gap else stop)*(1-side*2*a["slip_bps"][i+k]/1e4); fu=fund[:k+1].sum()
    elif i+72<f1: ex=a["o"][i+72]*(1-side*a["slip_bps"][i+72]/1e4); fu=fund.sum()
    else: ex=a["c"][f1-1]*(1-side*a["slip_bps"][f1-1]/1e4); fu=fund.sum()
    return side*qty*(ex-px)-qty*(px+ex)*FEE-fu
def engine_trades(folds, risk):
    out=[]
    feeds={}
    for f0,f1,sa,k in folds:
        if k not in feeds: feeds[k]=attach(market.base, intents[k])
        out+=run_feed(feeds[k], STRATEGY, idx[f0], idx[f1-1]+pd.Timedelta(hours=1), Costs(), risk)["trades"]
    T=pd.DataFrame(out); T["i"]=[idx.get_loc(pd.Timestamp(x)) for x in T.entry_time]; T["t"]=T.i-1; T["m"]=month[T.i.to_numpy()]
    return T
rng=np.random.default_rng(777)
def rep(label,x,realv): print("  %-58s placebo mean $%6.0f sd $%5.0f p05 $%6.0f p95 $%6.0f | real $%6.0f = percentile %.1f" % (label,x.mean(),x.std(),np.percentile(x,5),np.percentile(x,95),realv,(x<realv).mean()*100), flush=True)
def run_block(name, folds, n=400):
    T=engine_trades(folds, replace(Risk(),guardian=False))
    real=np.array([sim(r.symbol,int(r.side),int(r.t),folds) for r in T.itertuples()])
    sd=T.side.to_numpy()
    print("%s: %d guardian-off trades, engine $%.0f, standalone $%.0f (long $%.0f / short $%.0f)" % (name,len(T),T.pnl.sum(),np.nansum(real),np.nansum(real[sd>0]),np.nansum(real[sd<0])))
    inwin=np.zeros(len(idx),bool)
    for f0,f1,_,_ in folds: inwin[f0:f1]=True
    cache={}
    def pool(sym,m,side,mode):
        key=(sym,m,side,mode)
        if key not in cache:
            a=A[sym]; ok=np.zeros(len(idx),bool)
            ok[:-1]=a["tradable"][1:] & inwin[1:] & (atr[sym][:-1]>0) & a["valid"][:-1]
            if mode in ("month","month_trend"): ok[:-1]&=(month[1:]==m)
            if mode=="month_trend": ok&=(trend[sym]==side)
            if mode=="trend_any": ok&=(trend[sym]!=0)&~np.isnan(trend[sym])
            cache[key]=np.nonzero(ok)[0]
        return cache[key]
    for mode,label in (("month","same symbol-month + side, random hour"),("month_trend","same symbol-month + side, hour agrees with trend"),("trend_any","same symbol, ANY tradable hour in window, side = 14-day trend sign")):
        tot=np.zeros(n); lg=np.zeros(n); sh=np.zeros(n)
        for d in range(n):
            for r in T.itertuples():
                p=pool(r.symbol,int(r.m),int(r.side),mode) if mode!="trend_any" else pool(r.symbol,0,0,mode)
                if not len(p): continue
                t=int(p[rng.integers(len(p))]); side=int(r.side) if mode!="trend_any" else int(trend[r.symbol][t])
                v=sim(r.symbol,side,t,folds)
                if v==v:
                    tot[d]+=v
                    if side>0: lg[d]+=v
                    else: sh[d]+=v
        rep(label+" [all]",tot,np.nansum(real)); rep(label+" [longs]",lg,np.nansum(real[sd>0])); rep(label+" [shorts]",sh,np.nansum(real[sd<0]))
    print("  time",round(time.time()-t0,1),flush=True)
    return T
Tv=run_block("VALIDATION quarters (2025-01..2026-05)", mk_folds(lambda t: t>=DESIGN_END))
Tp=run_block("EARLIER walk-forward quarters (2023-10..2024-12)", mk_folds(lambda t: t<DESIGN_END))

# (c) Coinbase whole-contract sizing on the audited trades
s,tr,e,g=wf_val(market,intents); T=pd.DataFrame(tr)
print("\nCOINBASE WHOLE-CONTRACT SIZING (0.01 BTC and 0.1 ETH per contract)")
for sym,cs in (("PF_XBTUSD",0.01),("PF_ETHUSD",0.1)):
    x=T[T.symbol==sym].copy(); x["contracts"]=x.qty/cs; x["rounded"]=np.round(x.contracts); x["err"]=x.rounded/x.contracts-1
    print("  %s: %d trades, notional $ median %.0f (min %.0f max %.0f); contract ~$%.0f; ideal contracts median %.2f (min %.2f max %.2f); zero-contract trades %d; |size error| mean %.0f%% max %.0f%%; pnl exact $%.0f -> rounded $%.0f; risk per trade after rounding $%.0f..$%.0f" % (
        sym,len(x),(x.qty*x.entry_price).median(),(x.qty*x.entry_price).min(),(x.qty*x.entry_price).max(),(cs*x.entry_price).median(),x.contracts.median(),x.contracts.min(),x.contracts.max(),(x.rounded==0).sum(),x.err.abs().mean()*100,x.err.abs().max()*100,x.pnl.sum(),(x.pnl*x.rounded/x.contracts).sum(),(x.risk_usd*x.rounded/x.contracts).min(),(x.risk_usd*x.rounded/x.contracts).max()))

# (d) luck arithmetic
print("\nLUCK")
p=RES["monte_carlo"]["p_value_mean_le_0"]
print("  audit p (cluster bootstrap) = %.3f; Holm threshold for the best of 15 audited = %.4f, of 32 drafted = %.4f" % (p, 0.05/15, 0.05/32))
print("  chance that the best of 15 independent no-edge ideas shows p <= %.2f: %.0f%%; best of 32: %.0f%%" % (p, (1-(1-p)**15)*100, (1-(1-p)**32)*100))
T["exit_time"]=pd.to_datetime(T.exit_time)
for name,grp in (("exit day",T.exit_time.dt.floor("D")),("exit week",T.exit_time.dt.floor("D")-pd.to_timedelta(T.exit_time.dt.dayofweek,unit="D")),("exit month",T.exit_time.dt.tz_localize(None).dt.to_period("M"))):
    x=T.groupby(grp).pnl.sum(); t_=x.mean()/x.std(ddof=1)*np.sqrt(len(x))
    print("  clustered by %s: n=%d, t=%.2f" % (name,len(x),t_))
print("  trade R: mean %.3f, median %.3f, skew %.2f; win rate %.1f%%" % (T.r.mean(),T.r.median(),T.r.skew(),(T.pnl>0).mean()*100))
print("time",round(time.time()-t0,1))
