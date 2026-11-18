import sys, runpy
from pathlib import Path
HERE = Path(__file__).resolve().parent
src = (HERE / "v7_hourshift.py").read_text().split("base = wf(6, 21)")[0]
exec(src)
def byq(t):
    q = pd.PeriodIndex(pd.DatetimeIndex(t.entry_time).tz_localize(None), freq="Q")
    return t.groupby(q).pnl.agg(["size", "sum"]).round(0)
for hour in (21, 22):
    a = wf(6, hour); b = wf(6, hour, fixed_cell=2)
    print("Sunday", hour, "walk-forward cells\n", byq(a).T, "\nfixed cell 2\n", byq(b).T)
    print(a.reason.value_counts().to_dict(), b.reason.value_counts().to_dict())
