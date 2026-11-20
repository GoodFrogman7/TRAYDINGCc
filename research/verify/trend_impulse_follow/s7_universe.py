"""Universe timing: recompute a few months' top-10 from daily volume of the PRIOR 30 days only (rows before VALIDATION_END only)."""
from vcommon import *
import pyarrow.parquet as pq, pyarrow.compute as pc, pyarrow as pa
tbl = pq.read_table(ROOT/"data/daily_volume.parquet", filters=[("time", "<", pa.scalar(VALIDATION_END.to_pydatetime(), type=pq.read_schema(ROOT/"data/daily_volume.parquet").field("time").type))])
d = tbl.to_pandas(); assert d.time.max() < VALIDATION_END
uni = store.universe()
members_ever = set(market_syms := store.symbols())
dv = d.pivot(index="time", columns="symbol", values="dollar_vol")
for m in ("2025-02","2025-06","2025-11","2026-03","2026-05"):
    ms = pd.Timestamp(m+"-01", tz="UTC")
    win = dv[(dv.index >= ms - pd.Timedelta(days=30)) & (dv.index < ms)]
    med = win.fillna(0).median().sort_values(ascending=False)
    listed = uni[m]
    # rank of each listed symbol among symbols that have hourly files (the eligible-category filter is not re-derived here)
    med_e = med[[c for c in med.index if c in members_ever]]
    top = list(med_e.index[:10])
    print(m, "window", win.index.min().date(), "..", win.index.max().date(), "| listed == recomputed top-10 of prior 30d:", set(listed)==set(top), "| overlap", len(set(listed)&set(top)))
    # would a ranking on the month ITSELF differ? (if the file used in-month data, this would match instead)
    win2 = dv[(dv.index >= ms) & (dv.index < ms + pd.DateOffset(months=1))]
    if len(win2) >= 15:
        top2 = list(win2.fillna(0).median()[[c for c in med.index if c in members_ever]].sort_values(ascending=False).index[:10])
        print("      in-month ranking overlap with listed:", len(set(listed)&set(top2)), "of 10")
