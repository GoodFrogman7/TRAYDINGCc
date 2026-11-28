import pandas as pd
from eng import show
from strats import Impulse
from strats2 import PullbackLimit, BreakRetest, StrongMom
pd.set_option("display.width", 250)
W = {"mode": 1}
print("### Impulse WITH trend: robustness (one change at a time)")
show(Impulse(), [("default k2.5 v3 s3 L336 h72", W), ("k2.0", {**W, "k": 2.0}), ("k3.0", {**W, "k": 3.0}), ("v2", {**W, "v": 2.0}), ("v4", {**W, "v": 4.0}),
                 ("s2", {**W, "stop_atr": 2.0}), ("s4", {**W, "stop_atr": 4.0}), ("L168", {**W, "L": 168}), ("L720", {**W, "L": 720})])
for h in (48, 120):
    s = Impulse(); s.max_hold = h
    show(s, [(f"hold {h}", W)], stress=False)
print("\n### PullbackLimit (flush limit with trend), 24-bar time stop")
show(PullbackLimit(), [("default x1 s2.5", {}), ("x0.5", {"x": 0.5}), ("x1.5", {"x": 1.5}), ("s3.5", {"stop_atr": 3.5}), ("tp2", {"tp_atr": 2.0}),
                       ("short only", {"sides": -1}), ("long only", {"sides": 1}), ("N24", {"N": 24}), ("N96", {"N": 96})])
print("\n### BreakRetest, limit at broken level valid 24 bars, 72-bar time stop")
show(BreakRetest(), [("long only N168", {}), ("both sides", {"sides": 0}), ("N96", {"N": 96}), ("N48", {"N": 48}), ("s3.5", {"stop_atr": 3.5}), ("no btc", {"btc": 0})])
print("\n### StrongMom, 168-bar time stop")
show(StrongMom(), [("default rank.7 s5", {}), ("rank .5", {"rank": 0.5}), ("rank .85", {"rank": 0.85}), ("s3.5", {"stop_atr": 3.5}), ("L720", {"L": 720}), ("no btc", {"btc": 0})])
