import pandas as pd
from eng import show
from strats import Pullback, Impulse, BreakoutBull
pd.set_option("display.width", 250)
print("### Pullback (both sides), 24-bar time stop")
show(Pullback(), [("default L336 N48 s2.5", {}), ("N24", {"N": 24}), ("N72", {"N": 72}), ("s2.0", {"stop_atr": 2.0}), ("s3.0", {"stop_atr": 3.0}),
                  ("L168", {"L": 168}), ("L720", {"L": 720}), ("short only", {"sides": -1}), ("long only", {"sides": 1}),
                  ("tp 2.0 atr", {"tp_atr": 2.0})])
print("\n### Impulse, 72-bar time stop")
show(Impulse(), [("default k2.5 v3 s3", {}), ("k3", {"k": 3.0}), ("k2", {"k": 2.0}), ("with-trend only", {"mode": 1}), ("against only", {"mode": -1}), ("s4", {"stop_atr": 4.0})])
print("\n### BreakoutBull, 168-bar time stop")
show(BreakoutBull(), [("default N168 s4", {}), ("N96", {"N": 96}), ("s3", {"stop_atr": 3.0}), ("slow 720", {"slow": 720})])
