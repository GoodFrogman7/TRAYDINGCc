"""Independent re-implementation of the entry signal from the spec TEXT (plain loops / numpy, no desk.strategies.ta),
compared row by row with the module's intents for every symbol and every grid cell; then every validation trade is
checked against the raw bars (signal present the bar before, entry price, stop, exit rule, pnl arithmetic)."""
from vcommon import *
t0=time.time()
market, cells, intents = setup()
L, W, A = 336, 4320, 24

def my_signal(df):
    c=df["close"].to_numpy(float); h=df["high"].to_numpy(float); l=df["low"].to_numpy(float); n=len(c)
    er=np.full(n,np.nan); r=np.full(n,np.nan)
    ad=np.abs(np.diff(c))                      # ad[i] = |c[i+1]-c[i]|
    for t in range(L, n):
        path=ad[t-L:t].sum()                   # the L one-bar moves ending at t
        if path>0 and np.isfinite(path): er[t]=abs(c[t]-c[t-L])/path
        r[t]=c[t]/c[t-L]-1.0
    rk=np.full(n,np.nan)
    for t in range(L+W-1, n):
        w=er[t-W+1:t+1]
        if np.isnan(w).any(): continue
        rk[t]=((w<er[t]).sum()+((w==er[t]).sum()+1)/2.0)/W
    atr=np.full(n,np.nan); a=1.0/A; prev=np.nan
    for t in range(n):
        tr=h[t]-l[t]
        if t>0: tr=max(tr, abs(h[t]-c[t-1]), abs(l[t]-c[t-1]))
        prev = tr if t==0 else prev*(1-a)+a*tr
        if t>=A-1: atr[t]=prev
    return er, rk, r, atr

tot_rows=0; diffs={}
MY={}
for sym, df in market.data.items():
    er,rk,r,atr=my_signal(df); MY[sym]=(rk,r,atr)
    for k,cell in enumerate(cells):
        side=((rk>=cell["q"]) & (r>0) & ~np.isnan(atr) & (atr>0)).astype(int)
        stop=np.where(side>0, df["close"].to_numpy()-cell["stop_atr"]*atr, np.nan)
        m=intents[k][sym]
        ds=int((m["side"].to_numpy()!=side).sum())
        both=(side>0)&(m["side"].to_numpy()>0)
        dstop=int((~np.isclose(m["stop"].to_numpy()[both], stop[both], rtol=1e-9)).sum())
        extra=int(m["limit"].notna().sum()+m["tp"].notna().sum()+m["trail"].notna().sum()+m["exit"].sum()+(m["side"]<0).sum())
        tot_rows+=len(df)
        if ds or dstop or extra: diffs[(sym,k)]=(ds,dstop,extra)
print("rows compared (all 40 symbols x 6 cells):", tot_rows, " symbol-cells with any difference:", len(diffs), diffs)
# data hygiene relevant to 'L bars = 14 days'
gaps={s:int((pd.Series(df.index).diff().dropna()!=pd.Timedelta(hours=1)).sum()) for s,df in market.data.items()}
print("symbols with a non-hourly step in the index:", {s:g for s,g in gaps.items() if g})
miss={s:int(df["bar_missing"].sum()) for s,df in market.data.items()}
print("bar_missing rows per symbol (top):", sorted(miss.items(), key=lambda x:-x[1])[:8])
nz={s:int((df["close"]<=0).sum()+df["close"].isna().sum()) for s,df in market.data.items()}
print("non-positive / NaN closes:", sum(nz.values()))

# ---- every validation trade against raw bars
T=pd.read_pickle(str(Path(__file__).parent/"trades.pkl")); T["entry_time"]=pd.to_datetime(T.entry_time); T["exit_time"]=pd.to_datetime(T.exit_time)
uni=store.universe(); idx=market.base.index
def cell_at(ts):
    for c in CHOSEN:
        if pd.Timestamp(c["test_start"],tz="UTC")<=ts<pd.Timestamp(c["test_end"],tz="UTC"): return c
bad=[]
for j,t in T.iterrows():
    df=market.data[t.symbol]; a=market.base.arrays[t.symbol]
    ie=df.index.get_loc(t.entry_time); ix=df.index.get_loc(t.exit_time); gi=idx.get_loc(t.entry_time); gx=idx.get_loc(t.exit_time)
    c=cell_at(t.entry_time)["params"]; rk,r,atr=MY[t.symbol]; s=ie-1
    if not (rk[s]>=c["q"] and r[s]>0 and atr[s]>0): bad.append((j,"no signal at t-1"))
    if cell_at(df.index[s]) is None or cell_at(df.index[s])["params"]!=c:
        pass  # signal bar before the fold start would be a different cell; engine starts flat so this cannot happen
    if df.index[s] < pd.Timestamp(cell_at(t.entry_time)["test_start"],tz="UTC"): bad.append((j,"signal bar before fold start"))
    if t.symbol not in uni[t.entry_time.strftime("%Y-%m")]: bad.append((j,"not in universe at entry"))
    if t.symbol not in uni[df.index[s].strftime("%Y-%m")]: bad.append((j,"not in universe at signal"))
    st=df["close"].iloc[s]-c["stop_atr"]*atr[s]
    if not np.isclose(st,t.stop0,rtol=1e-9): bad.append((j,"stop0"))
    if not np.isclose(df["open"].iloc[ie]*(1+a["slip_bps"][gi]/1e4), t.entry_price, rtol=1e-9): bad.append((j,"entry price"))
    if not np.isclose(df["open"].iloc[ie], df["close"].iloc[s], rtol=1e-12): bad.append((j,"open!=prev close %.5f"%(df["open"].iloc[ie]/df["close"].iloc[s]-1)))
    lows=df["low"].iloc[ie:ix+1].to_numpy()
    if t.reason=="stop":
        if not (lows[-1]<=t.stop0 and (lows[:-1]>t.stop0).all()): bad.append((j,"stop timing"))
        o=df["open"].iloc[ix]; ref=o if (o<=t.stop0 and ix>ie) else t.stop0
        if not np.isclose(ref*(1-2*a["slip_bps"][gx]/1e4), t.exit_price, rtol=1e-9): bad.append((j,"stop price"))
    else:
        if not (lows[:-1]>t.stop0).all(): bad.append((j,"stop should have hit earlier"))
        if t.reason=="time":
            if not (ix-ie==168 and t.bars_held==168): bad.append((j,"time stop length %d"%(ix-ie)))
            if not np.isclose(df["open"].iloc[ix]*(1-a["slip_bps"][gx]/1e4), t.exit_price, rtol=1e-9): bad.append((j,"time exit price"))
        if t.reason=="guardian":
            if not np.isclose(df["open"].iloc[ix]*(1-a["slip_bps"][gx]/1e4), t.exit_price, rtol=1e-9): bad.append((j,"guardian exit price"))
    q=t.qty; g=q*(t.exit_price-t.entry_price); fee=q*t.entry_price*0.0005+q*t.exit_price*0.0005
    last=ix if t.reason in ("stop",) else ix-1          # funding charged on bars the position is open through
    fund=(q*df["open"].iloc[ie:last+1].to_numpy()*df["funding"].fillna(0).iloc[ie:last+1].to_numpy()).sum()
    if not np.isclose(g,t.pnl_gross,atol=1e-6): bad.append((j,"gross"))
    if not np.isclose(fee,t.fees,atol=1e-6): bad.append((j,"fees"))
    if not np.isclose(fund,t.funding,atol=1e-4): bad.append((j,"funding %.4f vs %.4f"%(fund,t.funding)))
    dist=t.entry_price-t.stop0; want=min(50/dist, 10000/t.entry_price)
    if not (q<=want*(1+1e-9)): bad.append((j,"qty above risk size"))
    if q<want*(1-1e-6): bad.append((j,"qty reduced by gross cap: %.0f%% of intended"%(q/want*100)))
from collections import Counter
print("trade checks failed:", Counter(b[1].split(" %")[0] if "qty reduced" not in b[1] else "qty reduced by gross cap" for b in bad))
print([b for b in bad][:12])
# was a signal present but skipped (in universe, flat, not halted)? count signal bars vs entries
T["notional"]=T.qty*T.entry_price
print("notional $: median %.0f mean %.0f min %.0f max %.0f ; capped at 1x equity: %d trades" % (T.notional.median(), T.notional.mean(), T.notional.min(), T.notional.max(), (T.notional>9990).sum()))
print("stop distance %% of entry: median %.2f p10 %.2f p90 %.2f" % tuple(((T.entry_price-T.stop0)/T.entry_price*100).quantile([.5,.1,.9])))
# history requirement: first signal-capable bar per symbol
print("first bar with a non-NaN rank needs %d bars = %.0f days" % (L+W, (L+W)/24))
print("time", round(time.time()-t0,1))
