"""(1) Truncation test of the four would-trade drafts (intents at T must not change when later bars are removed).
(2) Final design-window engine numbers for the exact defaults returned to the desk."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import strats as S, engine_check as E
from desk.data import store
from desk.engine.core import Costs, Risk

FINAL = [
    ("flow_weekend_dump_short", S.WeekendDumpShort, dict(z=0.75, hour=21, stop_atr=3.0, dirn=-1), 24, 1),
    ("flow_stress_bid", S.StressBid, dict(z_btc=3.0, v_btc=3.0, z_alt=-1.0, stop_atr=3.0), 24, 1),
    ("flow_liquidity_vacuum_fade", S.LiquidityVacuumFade, dict(sp_mult=3.0, drop_atr=2.0, stop_atr=-0.08), 24, 1),
    ("flow_hot_breakdown_limit_fade", S.HotVolBreakdownFade, dict(n=48, rank_min=0.7, limit_atr=1.5, stop_atr=3.0, tp_atr=2.0), 12, 3),
    ("flow_weekend_pump_long (near-miss)", S.WeekendDumpShort, dict(z=0.75, hour=21, stop_atr=3.0, dirn=1), 24, 1),
    ("flow_btc_liq_flush (near-miss)", S.BtcLiqFlush, dict(z=3.0, liq_q=0.99, stop_atr=4.0), 12, 1),
    ("flow_air_pocket_fade (near-miss)", S.AirPocketFade, dict(z=3.0, vmax=4.0, stop_atr=2.5), 12, 1),
]
data = E.market().data
cut = pd.Timestamp("2024-03-10 13:00", tz="UTC")
trunc = {s: df[df.index <= cut] for s, df in data.items() if (df.index <= cut).any()}
print("== truncation test at", cut)
for nm, cls, p, mh, vb in FINAL[:4]:
    st = cls(); pp = {**st.params, **p}
    full = st.intents(data, pp); part = st.intents(trunc, pp)
    bad = 0
    for s, it in part.items():
        a = full[s].loc[it.index]
        for c in ("side", "limit", "stop", "tp", "trail", "exit"):
            x, y = a[c].to_numpy(dtype=float), it[c].to_numpy(dtype=float)
            sig = (a["side"].to_numpy() != 0) | (it["side"].to_numpy() != 0) if c != "side" else np.ones(len(x), bool)
            bad += int((~np.isclose(x[sig], y[sig], equal_nan=True)).sum())
    print(f"  {nm}: mismatches {bad}")
print("\n== final defaults, design window, all costs, Guardian on")
rows = []
for nm, cls, p, mh, vb in FINAL:
    st = cls(); st.valid_bars = vb
    rows.append(E.check(st, p, label=nm, max_hold=mh))
    st = cls(); st.valid_bars = vb
    rows.append(E.check(st, p, label="   fees x2", max_hold=mh, costs=Costs(fee_mult=2.0)))
E.table(rows)
out = os.path.join(os.path.dirname(__file__), "tables"); os.makedirs(out, exist_ok=True)
df = pd.DataFrame([r["row"] for r in rows])
df.insert(0, "source", "Kraken Futures public API"); df.insert(1, "asof_bar_cutoff_utc", store.manifest()["asof_bar_cutoff_utc"])
df.insert(2, "window", "DESIGN (< 2025-01-01), desk engine, all costs, Guardian on")
df.to_csv(os.path.join(out, "engine_defaults.csv"), index=False)
