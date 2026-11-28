"""Is the huge first-bar 'basis_c' reversal tradable, or a stale-last-print artifact?
Compare the last traded close with the mark (order-book based) and with the $10k executable ask/bid."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel2.pkl"
p = pd.read_pickle(P)
g = p.groupby("sym", sort=False)
p["n_open"] = g["open"].shift(-1)
p["n_vol"] = g["volume"].shift(-1)
p["basis_c"] = p.close / p.spot_close - 1
p["basis_m"] = p.mark_close / p.spot_close - 1
p["c_vs_mark"] = p.close / p.mark_close - 1
p["mid10"] = (p.bid_10k + p.ask_10k) / 2
t = p[p.tradable & ~p.bar_missing].copy()
print("share of bars with next open == close exactly:", (t.n_open == t.close).mean().round(3))
print("abs(close/mark-1) bps quantiles:", (t.c_vs_mark.abs()*1e4).quantile([.5,.9,.99,.999]).round(1).to_dict())
print("abs(mid10/mark_close-1) bps:", ((t.mid10/t.mark_close-1).abs()*1e4).quantile([.5,.9,.99]).round(1).to_dict())
print("abs(mid10/close-1) bps:", ((t.mid10/t.close-1).abs()*1e4).quantile([.5,.9,.99]).round(1).to_dict())
for lab, m in [("basis_c<-0.4%", t.basis_c<-0.004), ("basis_c>0.4%", t.basis_c>0.004), ("basis_c<-1%", t.basis_c<-0.01)]:
    ev = t[m]
    print(f"\n{lab}: n={len(ev)}  median usd vol of the bar={ev.usd.median():,.0f}  share zero-vol bars={(ev.volume==0).mean():.3f}")
    print("  median bps: close-vs-mark %.1f | mark-vs-spot %.1f | next_open-vs-close %.1f | ask10k-vs-close %.1f | bid10k-vs-close %.1f | n(book)=%d" % (
        ev.c_vs_mark.median()*1e4, ev.basis_m.median()*1e4, (ev.n_open/ev.close-1).median()*1e4,
        (ev.ask_10k/ev.close-1).median()*1e4, (ev.bid_10k/ev.close-1).median()*1e4, ev.ask_10k.notna().sum()))
    print("  by symbol:", ev.groupby("sym").size().sort_values(ascending=False).head(8).to_dict())
# the honest test: same signal but REQUIRE that the mark agrees (close within 10 bps of mark)
t["N1m"] = t["N1"]
for lab, m, sg in [("basis_c<-0.4% & |close-mark|<10bps  long", (t.basis_c<-0.004)&(t.c_vs_mark.abs()<0.001), 1),
                   ("basis_c<-0.4% & close-mark<-30bps   long", (t.basis_c<-0.004)&(t.c_vs_mark<-0.003), 1),
                   ("basis_c>0.4% & |close-mark|<10bps  short", (t.basis_c>0.004)&(t.c_vs_mark.abs()<0.001), -1),
                   ("basis_c>0.4% & close-mark>30bps    short", (t.basis_c>0.004)&(t.c_vs_mark>0.003), -1)]:
    ev = t[m]; x = ev.N1*sg; x4 = ev.N4*sg
    print(f"{lab}: n={len(ev)} N1={x.mean():.2f} (t {cluster_t(x, ev.time.dt.floor('D')):.1f}) N4={x4.mean():.2f} (t {cluster_t(x4, ev.time.dt.floor('D')):.1f}) bps4={(ev.fwd_4*sg).mean()*1e4:.1f}")
