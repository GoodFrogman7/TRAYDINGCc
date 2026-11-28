"""C: extreme positive premium (crowded longs paying up) -> short. Abs level and trailing z; with/without price stall."""
from lib import *
data = load()
def mk(ma, thr, kind, cond=None):
    def f(df, s):
        pm = df["premium"].rolling(ma, min_periods=ma).mean()
        if kind == "abs":
            x = pm * 1e4
        else:
            mu = pm.rolling(720, min_periods=360).median()
            sd = df["premium"].rolling(720, min_periods=360).std()
            x = (pm - mu) / sd
        m = x >= thr
        c = df["close"]
        if cond == "stall":   # last 4h return <= 0 while premium still extreme
            m &= (c / c.shift(4) - 1) <= 0
        if cond == "run":
            m &= (c / c.shift(4) - 1) > 0
        if cond == "up24":
            m &= (c / c.shift(24) - 1) > 0.05
        if cond == "prem_falling":
            m &= df["premium"] < df["premium"].shift(1)
        return -m.astype(int)
    return f
for h in (8, 24):
    print(f"### hold {h}h")
    for ma, thr, kind in ((1, 20, "abs"), (1, 40, "abs"), (8, 20, "abs"), (8, 3, "z"), (24, 15, "abs")):
        for cond in (None, "stall", "run"):
            line(collect(data, mk(ma, thr, kind, cond), h, gap=h), f"prem_ma{ma} {kind}>={thr} [{cond}] -> short {h}h")
