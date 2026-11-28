import pandas as pd
from eng import show, line
from strats3 import XSMom, TrendDay
from strats4 import QuietTrend, ImpulseCap
pd.set_option("display.width", 250)
print("### QuietTrend, 168-bar time stop")
show(QuietTrend(), [("long only q.8 s5 L336", {}), ("both sides", {"sides": 0}), ("q .7", {"q": 0.7}), ("q .9", {"q": 0.9}), ("s3.5", {"stop_atr": 3.5}), ("s7", {"stop_atr": 7.0}), ("L168", {"L": 168}), ("L720", {"L": 720})])
print("\n### ImpulseCap (with-trend hourly impulse, max entries per bar)")
show(ImpulseCap(), [("cap3", {}), ("cap2", {"cap": 2}), ("cap1", {"cap": 1}), ("cap5", {"cap": 5})], stress=False)
print("\n### XSMom extra cells")
show(XSMom(), [("L168 s8", {"L": 168, "stop_atr": 8.0}), ("L336 s8", {"stop_atr": 8.0})], stress=False)
print("\n### TrendDay extra cells (corners)")
show(TrendDay(), [("k1.5 s3.5", {"k": 1.5, "stop_atr": 3.5}), ("k2.5 s7", {"k": 2.5, "stop_atr": 7.0}), ("k2.5 s3.5 L168", {"k": 2.5, "stop_atr": 3.5, "L": 168}), ("k1.5 s7 L720", {"k": 1.5, "stop_atr": 7.0, "L": 720})], stress=False)
# monthly path + worst stretch for the two leaders
for S, p in ((TrendDay(), {}), (ImpulseCap(), {})):
    o, res = line(S, p)
    eq = res["equity"]; dd = (eq - eq.cummax()) / 10000
    tr = pd.DataFrame(res["trades"])
    print(f"\n{S.name}: maxDD {dd.min():.3f} trough {dd.idxmin()} | peak before {eq[:dd.idxmin()].idxmax()} | worst R {tr.r.min():.2f} best R {tr.r.max():.2f} | mean win R {tr.r[tr.r>0].mean():.2f} mean loss R {tr.r[tr.r<0].mean():.2f}")
    q = eq.resample("QS").last().diff() / 100
    print("quarterly pnl %:", q.round(1).dropna().to_dict().__repr__()[:900])
    print("max concurrent positions approx (gross/10000 max):", round(res["gross"].max() / 10000, 2))
