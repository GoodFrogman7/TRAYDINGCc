"""Independent plain-loop re-implementation of the entry signal from the Hunter's TEXT, compared row by row
with the module's intents (all 40 symbols, default cell + 2 other grid cells)."""
import math, time
from vcommon import *
t0=time.time()
market, cells, intents = setup()

def my_signal(df, L, k, v, stop_atr):
    o=df["open"].to_numpy(float); h=df["high"].to_numpy(float); l=df["low"].to_numpy(float)
    c=df["close"].to_numpy(float); vol=df["volume"].to_numpy(float)
    n=len(df); N=24
    # Wilder ATR(24): TR = max(h-l, |h-pc|, |l-pc|); recursive average alpha=1/24, defined after 24 TRs
    atr=[math.nan]*n; a=None; cnt=0
    for i in range(n):
        tr=h[i]-l[i]
        if i>0:
            tr=max(tr, abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        if math.isnan(tr): continue
        a = tr if a is None else a + (tr-a)/N
        cnt+=1
        if cnt>=N: atr[i]=a
    side=np.zeros(n,dtype=int); stop=np.full(n,np.nan)
    csum=np.concatenate([[0.0],np.cumsum(vol)])
    for t in range(n):
        if t<1: continue
        a1=atr[t-1]
        if a1 is None or math.isnan(a1) or a1<=0: continue
        if t-168<0: continue
        vavg=(csum[t]-csum[t-168])/168.0          # mean volume of bars t-168..t-1
        if not vavg>0: continue
        if t-1-L<0: continue
        trend=c[t-1]/c[t-1-L]-1.0                 # 14-day return known before bar t
        mv=(c[t]-o[t])/a1; volr=vol[t]/vavg
        at=atr[t]
        if math.isnan(at) or at<=0: continue
        if mv>k and volr>v and trend>0: side[t]=1; stop[t]=c[t]-stop_atr*at
        elif mv<-k and volr>v and trend<0: side[t]=-1; stop[t]=c[t]+stop_atr*at
    return side, stop

tot_rows=tot_sig=diff_side=diff_stop=0; examples=[]
for ci in (0, 5, 13):
    p=cells[ci]
    for sym, df in market.data.items():
        s, st = my_signal(df, p["L"], p["k"], p["v"], p["stop_atr"])
        it = intents[ci][sym]
        ms = it["side"].to_numpy(); mst = it["stop"].to_numpy()
        d = s != ms
        tot_rows += len(df); tot_sig += int((ms!=0).sum()); diff_side += int(d.sum())
        both = (s!=0)&(ms!=0)
        bad = both & ~np.isclose(st, mst, rtol=1e-7)
        diff_stop += int(bad.sum())
        for i in np.nonzero(d)[0][:3]:
            examples.append((ci, sym, str(df.index[i]), int(s[i]), int(ms[i])))
    print("cell", ci, p, "cum rows", tot_rows, "module signals", tot_sig, "side diffs", diff_side, "stop diffs", diff_stop, flush=True)
print("examples of differences:", examples[:20])
# other checks: any intents columns other than side/stop set? limit/tp/trail/exit must be empty
it0=intents[0]
print("limit set:", sum(int(d["limit"].notna().sum()) for d in it0.values()), "tp set:", sum(int(d["tp"].notna().sum()) for d in it0.values()),
      "trail set:", sum(int(d["trail"].notna().sum()) for d in it0.values()), "exit set:", sum(int(d["exit"].sum()) for d in it0.values()))
# signals on missing bars / zero volume / NaN stops
nm=0; nn=0
for sym, d in it0.items():
    df=market.data[sym]; m=d["side"]!=0
    nm += int((m & df["bar_missing"].astype(bool)).sum()); nn += int((m & d["stop"].isna()).sum())
print("signals on bar_missing rows:", nm, "signals with NaN stop:", nn)
# missing-bar contamination: how many validation signals have a missing bar in the prior 168 bars (volume average) or 24 bars?
tot=cont=0
for sym, d in it0.items():
    df=market.data[sym]; miss=df["bar_missing"].astype(float).rolling(168).sum().shift(1)
    m=(d["side"]!=0)&(d.index>=DESIGN_END)
    tot+=int(m.sum()); cont+=int((m&(miss>0)).sum())
print("validation default-cell signals:", tot, "with >=1 missing bar in prior 168h:", cont)
print("time", round(time.time()-t0,1))
