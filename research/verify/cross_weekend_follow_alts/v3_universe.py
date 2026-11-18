"""Is each month's universe list really ranked on the 30 days BEFORE the month? Recompute from daily volume
(rows before VALIDATION_END only, filtered at read time)."""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import pandas as pd
from desk.data.store import VALIDATION_END
d = pd.read_parquet(ROOT / "data" / "daily_volume.parquet", filters=[("time", "<", VALIDATION_END)])
assert d["time"].max() < VALIDATION_END
uni = json.loads((ROOT / "data" / "universe.json").read_text())
months = uni["months"]
piv = d.pivot_table(index="time", columns="symbol", values="dollar_vol", aggfunc="last")
BTC, ETH = "PF_XBTUSD", "PF_ETHUSD"
bad = 0; checked = 0; contaminated = 0
for m in sorted(months):
    if not ("2023-04" <= m <= "2026-05"):
        continue
    t0 = pd.Timestamp(m + "-01", tz="UTC")
    win = piv[(piv.index >= t0 - pd.Timedelta(days=30)) & (piv.index < t0)]
    ok = win.notna().sum() >= 20
    med = win.fillna(0).median()[ok].sort_values(ascending=False)
    listed = months[m]
    # my top among the symbols that the file's list could contain (categories excluded by the builder are unknown to me,
    # so compare the ORDER of listed symbols and the top-3 alts)
    mine_order = [s for s in med.index if s in listed]
    alts_listed = [s for s in listed if s not in (BTC, ETH)][:3]
    alts_mine = [s for s in mine_order if s not in (BTC, ETH)][:3]
    # the same computed with the month's OWN data (what a leaky builder would produce)
    win2 = piv[(piv.index >= t0) & (piv.index < t0 + pd.Timedelta(days=30))]
    med2 = win2.fillna(0).median().sort_values(ascending=False)
    alts_future = [s for s in med2.index if s in listed and s not in (BTC, ETH)][:3]
    checked += 1
    if alts_listed != alts_mine:
        bad += 1
        print("MISMATCH", m, alts_listed, alts_mine)
    if alts_listed == alts_future and alts_future != alts_mine:
        contaminated += 1
print("months checked", checked, "top-3-alt mismatches vs prior-30-day ranking:", bad, "| months matching ONLY an in-month ranking:", contaminated)
