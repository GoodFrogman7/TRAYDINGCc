"""Engine check of the signal-hour sensitivity (the strategy's own code, only the weekly bar changed in a scratch subclass)."""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
from desk.engine.runner import load_market, run_feed
from desk.engine.core import Costs, Risk, attach
from desk.data import store
from desk.data.store import VALIDATION_END
from desk.audit import harness
from desk.strategies import ta
from desk.strategies.common import BTC, ETH, entries, is_weekly_bar, month_code, months_where
from desk.strategies.s_cross_weekend_follow_alts import CrossWeekendFollowAlts, STRATEGY
pd.set_option("display.width", 250)

class Shifted(CrossWeekendFollowAlts):
    DOW, HOUR = 6, 21
    def intents(self, data, p):       # verbatim copy of the module's method except the weekly bar
        out = {}
        look, n_alt = int(p["look"]), int(p["n_alt"])
        btc = data.get(BTC)
        w_btc = btc["close"] / btc["close"].shift(look) - 1.0
        cand_months = months_where(store.universe(), lambda syms: [s for s in syms if s not in (BTC, ETH)][:n_alt])
        for sym, df in data.items():
            atr = ta.atr(df, 24)
            if sym in (BTC, ETH):
                out[sym] = entries(df, None, None, atr); continue
            w = w_btc.reindex(df.index)
            own = df["close"] / df["close"].shift(look) - 1.0
            is_cand = pd.Series(np.isin(month_code(df.index), cand_months.get(sym, [])), index=df.index)
            on = pd.Series(is_weekly_bar(df.index, self.DOW, self.HOUR), index=df.index)
            go = on & is_cand & (w.abs() >= p["thr"]) & (np.sign(own) == np.sign(w))
            out[sym] = entries(df, go & (w > 0), go & (w < 0), p["stop_atr"] * atr)
        return out

market = load_market(end=VALIDATION_END)
res = json.loads((ROOT / "research/results/cross_weekend_follow_alts.json").read_text())
cells = harness.grid_cells(STRATEGY)
chosen = [c for c in res["wf_chosen"] if c["test_start"] >= "2025-01-01"]
used = sorted({c["cell"] for c in chosen})

def wf(dow, hour, fixed_cell=None):
    st = Shifted(); st.DOW, st.HOUR = dow, hour
    feeds = {k: attach(market.base, st.intents(market.data, dict(cells[k]))) for k in (used if fixed_cell is None else [fixed_cell])}
    tr = []
    for c in chosen:
        k = c["cell"] if fixed_cell is None else fixed_cell
        r = run_feed(feeds[k], st, pd.Timestamp(c["test_start"], tz="UTC"), pd.Timestamp(c["test_end"], tz="UTC"), Costs(), Risk())
        tr += r["trades"]
    return pd.DataFrame(tr)

base = wf(6, 21)
print("engine, Sunday 21:00 (the spec): $%.0f, %d trades" % (base.pnl.sum(), len(base)))
names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
out = {}
for dow, hour in [(6, 17), (6, 18), (6, 19), (6, 20), (6, 22), (6, 23), (0, 0), (0, 1), (0, 2), (5, 21), (0, 21)]:
    t = wf(dow, hour); out[(dow, hour)] = t
    d2 = wf(dow, hour, fixed_cell=2)
    print("engine, signal at %s %02d:00: walk-forward cells $%.0f (%d trades) | fixed thr=0/stop 4/n 3: $%.0f (%d)"
          % (names[dow], hour, t.pnl.sum(), len(t), d2.pnl.sum(), len(d2)), flush=True)
d2 = wf(6, 21, fixed_cell=2); print("engine, Sunday 21:00 fixed thr=0/stop 4/n 3: $%.0f (%d)" % (d2.pnl.sum(), len(d2)))
# where does the Sunday 22:00 version lose it?
t = out[(6, 22)].copy()
base["wk"] = pd.DatetimeIndex(base.entry_time).floor("D"); t["wk"] = pd.DatetimeIndex(t.entry_time).floor("D")
m = base.merge(t, on=["wk", "symbol"], how="outer", suffixes=("_21", "_22"))
both = m.pnl_21.notna() & m.pnl_22.notna()
print("\nSunday 22:00 vs 21:00: same weekend+symbol in both: %d (pnl 21h $%.0f vs 22h $%.0f; side differs in %d) | only at 21h: %d ($%.0f) | only at 22h: %d ($%.0f)"
      % (both.sum(), m.pnl_21[both].sum(), m.pnl_22[both].sum(), (m.side_21[both] != m.side_22[both]).sum(),
         (m.pnl_22.isna()).sum(), m.pnl_21[m.pnl_22.isna()].sum(), (m.pnl_21.isna()).sum(), m.pnl_22[m.pnl_21.isna()].sum()))
dd = (m.pnl_22 - m.pnl_21)[both]
print("largest per-trade changes among the common trades:\n", m[both].assign(d=dd).sort_values("d").head(8)[["wk", "symbol", "side_21", "side_22", "pnl_21", "pnl_22", "reason_21", "reason_22", "d"]].round(1))
