import pandas as pd
from eng import show
from strats3 import TrendDay, XSMom
pd.set_option("display.width", 250)
print("### TrendDay (daily-scale with-trend impulse), 168-bar time stop")
show(TrendDay(), [("default k2 v2 s5 L336", {}), ("k1.5", {"k": 1.5}), ("k2.5", {"k": 2.5}), ("v1.5", {"v": 1.5}), ("v3", {"v": 3.0}), ("s3.5", {"stop_atr": 3.5}), ("s7", {"stop_atr": 7.0}),
                  ("L168", {"L": 168}), ("L720", {"L": 720}), ("long only", {"sides": 1}), ("short only", {"sides": -1}), ("btc agree", {"btc": 1})])
for h in (96, 240):
    s = TrendDay(); s.max_hold = h
    show(s, [(f"hold {h}", {})], stress=False)
print("\n### XSMom weekly, 167-bar time stop")
show(XSMom(), [("default L336 top2 s6", {}), ("L168", {"L": 168}), ("L720", {"L": 720}), ("top1", {"top": 1}), ("top3", {"top": 3}), ("s4", {"stop_atr": 4.0}), ("s8", {"stop_atr": 8.0}),
               ("long only", {"sides": 1}), ("short only", {"sides": -1}), ("dow Wed", {"dow": 2})])
