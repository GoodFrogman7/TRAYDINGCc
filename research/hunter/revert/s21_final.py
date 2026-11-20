"""Final candidates through the desk engine on the DESIGN window: default, one-bar-late, fees x2, grid neighbourhood,
plus a causality (truncation) self-check of the intents."""
import itertools, numpy as np, pandas as pd
from pathlib import Path
from harness import *
from final import *
from desk.engine.core import Costs, Risk
m = market()
ALL = []
for s in FINAL:
    print(f"\n################ {s.name}  params={s.params} max_hold={s.max_hold}")
    rows = []
    base = run(s, {})
    rows.append(line(base, "default"))
    rows.append(line(run(s, {}, delay=1), "entry one bar late"))
    rows.append(line(run(s, {}, costs=Costs(fee_mult=2.0)), "fees x2"))
    rows.append(line(run(s, {}, costs=Costs(slip_mult=2.0)), "slippage x2"))
    rows.append(line(run(s, {}, risk=Risk(guardian=False)), "guardian off (diagnostic)"))
    if s.name == "revert_premium_fade":
        rows.append(line(run(s, {"sides": "long"}), "long leg only"))
        rows.append(line(run(s, {"sides": "short"}), "short leg only"))
        rows.append(line(run(s, {}, costs=Costs(funding_mult=0.0)), "funding ignored"))
    keys = list(s.grid)
    prof = 0; cells = 0
    for vals in itertools.product(*[s.grid[k] for k in keys]):
        pp = dict(zip(keys, vals))
        r = run(s, pp); cells += 1; prof += r["summary"]["total_return"] > 0
        rows.append(line(r, "grid " + " ".join(f"{k}={v}" for k, v in pp.items())))
    show(rows)
    ALL += [{"idea": s.name, **r} for r in rows]
    print(f"grid cells profitable in design: {prof}/{cells}")
    t = trades_df(base)
    print("exit reasons:", base["summary"]["exit_reasons"], "| distinct entry days:", t.entry_time.dt.floor("D").nunique(),
          "| trades/month:", round(len(t) / 32, 1), "| worst trade R:", round(t.r.min(), 2), "| p05 R:", round(t.r.quantile(.05), 2),
          "| worst net bps:", round(t.net_bps.min()), "| p05 net bps:", round(t.net_bps.quantile(.05)))
    print("by year/side:"); print(t.groupby(["year", "side"]).agg(n=("r", "size"), sumR=("r", "sum"), avgR=("r", "mean"), win=("r", lambda x: (x > 0).mean()), gross_bps=("ret_bps", "mean"), net_bps=("net_bps", "mean")).round(2).to_string())
    se = t.r.std(ddof=1) / np.sqrt(len(t)); print(f"avg R {t.r.mean():.3f}  t-stat(trades) {t.r.mean()/se:.2f}")
    dR = t.groupby(t.entry_time.dt.floor("D")).r.sum(); print(f"t-stat clustered by entry day: {dR.mean()/(dR.std(ddof=1)/np.sqrt(len(dR))):.2f}  (days={len(dR)})")
    # truncation check: intents on data cut at T equal intents on full history at T
    bad = 0; chk = 0
    for T in (pd.Timestamp("2023-06-01", tz="UTC"), pd.Timestamp("2024-03-15", tz="UTC")):
        cut = {k: v[v.index < T] for k, v in m.data.items() if (v.index < T).any()}
        a = s.intents(cut, s.params); b = s.intents(m.data, s.params)
        for k in a:
            x = a[k].tail(200); y = b[k].reindex(x.index)
            chk += x.size; bad += int((~((x == y) | (x.isna() & y.isna()))).to_numpy().sum())
    print(f"truncation check: {bad} mismatches in {chk} values")

pd.DataFrame(ALL).round(4).to_csv(Path(__file__).with_name("final_engine_tables.csv"), index=False)
