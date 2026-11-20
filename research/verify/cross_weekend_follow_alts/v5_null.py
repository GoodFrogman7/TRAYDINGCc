"""Is it just exposure? Nulls built with a small stand-alone trade simulator (validated against the engine's trades).
 A. same symbols, same side, same stop multiple, same 24h hold, but entered at a RANDOM hour of the same calendar month
    (one draw per weekend event, so simultaneous entries stay simultaneous)
 B. the identical rule applied at each of the other 167 hour-of-week slots (is the weekend special?)
 C. same Sunday entries, side flipped by a coin per weekend (does the BTC sign carry information?)
 D. same Sundays: always long / always short / no agreement filter
"""
import sys, json, pickle
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
from desk.engine.runner import load_market
from desk.data.store import VALIDATION_END, DESIGN_END
from desk.strategies import ta

market = load_market(end=VALIDATION_END)
data, base = market.data, market.base
idx = base.index; N = len(idx)
A = base.arrays
ATR = {s: ta.atr(df, 24).reindex(idx).to_numpy() for s, df in data.items()}
uni = json.loads((ROOT / "data/universe.json").read_text())["months"]
BTC, ETH = "PF_XBTUSD", "PF_ETHUSD"
res = json.loads((ROOT / "research/results/cross_weekend_follow_alts.json").read_text())
chosen = [c for c in res["wf_chosen"] if c["test_start"] >= "2025-01-01"]
qstart = [pd.Timestamp(c["test_start"], tz="UTC") for c in chosen]
i_val0 = int(idx.searchsorted(DESIGN_END))
month_of = idx.strftime("%Y-%m").to_numpy()


def params_at(i):
    t = idx[i]
    k = max(j for j, q in enumerate(qstart) if q <= t)
    return chosen[k]["params"]


def sim(s, i, side, k):
    """Signal at the close of bar i; returns net pnl in $ or None if the trade cannot be opened."""
    a = A[s]; f = i + 1
    if f + 24 >= N or not (a["tradable"][i] and a["tradable"][f]):
        return None
    atr = ATR[s][i]
    if not atr > 0:
        return None
    stop = a["c"][i] - side * k * atr
    px = a["o"][f] * (1 + side * a["slip_bps"][f] / 1e4)
    dist = (px - stop) * side
    if not dist > 0 or dist / px < 0.002 or dist / px > 0.25:
        return None
    qty = min(50.0 / dist, 10000.0 / px)
    fund = 0.0
    for j in range(f, f + 24):
        if not a["valid"][j]:
            return None
        o = a["o"][j]
        fund += side * qty * o * a["funding"][j]
        hit = a["l"][j] <= stop if side > 0 else a["h"][j] >= stop
        if hit:
            gap = j != f and ((o <= stop) if side > 0 else (o >= stop))
            ex = (o if gap else stop) * (1 - side * 2 * a["slip_bps"][j] / 1e4)
            return side * qty * (ex - px) - 0.0005 * qty * (px + ex) - fund
    j = f + 24
    ex = a["o"][j] * (1 - side * a["slip_bps"][j] / 1e4)
    return side * qty * (ex - px) - 0.0005 * qty * (px + ex) - fund


# ---- validate the simulator on the engine's own trades
T = pickle.load(open(HERE / "trades.pkl", "rb"))["T"]
T["i_sig"] = idx.get_indexer(pd.DatetimeIndex(T.entry_time)) - 1
T["k"] = [params_at(i)["stop_atr"] for i in T.i_sig]
T["sim"] = [sim(s, i, sd, k) for s, i, sd, k in zip(T.symbol, T.i_sig, T.side, T.k)]
ok = T.sim.notna()
print("simulator check: engine $%.1f vs simulator $%.1f on %d/%d trades; max abs diff on time/stop exits $%.4f"
      % (T.pnl[ok].sum(), T.sim[ok].sum(), ok.sum(), len(T),
         (T.pnl - T.sim)[ok & T.reason.isin(["time", "stop"])].abs().max()))
REAL = float(T.sim[ok].sum())
T = T[ok]

rng = np.random.default_rng(12345)
# ---- A. random hour in the same calendar month, same symbols and side, per-event draw
events = [(g.i_sig.iloc[0], list(zip(g.symbol, g.side, g.k))) for _, g in T.groupby("entry_time")]
month_rows = {}
for i, _ in events:
    m = month_of[i]
    if m not in month_rows:
        month_rows[m] = np.nonzero(month_of == m)[0]
        month_rows[m] = month_rows[m][month_rows[m] + 26 < N]
cache = {}
def sim_c(s, i, sd, k):
    key = (s, i, sd, k)
    if key not in cache:
        cache[key] = sim(s, i, sd, k)
    return cache[key]
ND = 1000
totA = np.zeros(ND); nA = np.zeros(ND)
for d in range(ND):
    tot = 0.0; n = 0
    for i, legs in events:
        j = int(rng.choice(month_rows[month_of[i]]))
        for s, sd, k in legs:
            v = sim_c(s, j, sd, k)
            if v is not None:
                tot += v; n += 1
    totA[d] = tot; nA[d] = n
print("\nA. random hour, same symbol-months/side/stop/hold (%d draws): mean $%.0f, median $%.0f, 5%%..95%% $%.0f..$%.0f | real $%.0f | share of draws >= real: %.3f | avg trades per draw %.0f"
      % (ND, totA.mean(), np.median(totA), np.percentile(totA, 5), np.percentile(totA, 95), REAL, (totA >= REAL).mean(), nA.mean()))
print("   real minus the null's mean (what the timing adds over plain exposure): $%.0f" % (REAL - totA.mean()))


# ---- B. the identical rule at every hour-of-week slot
def rule_total(dow, hour, filt=True, force_side=0):
    c_btc = A[BTC]["c"]
    rows = np.nonzero((idx.dayofweek == dow) & (idx.hour == hour))[0]
    rows = rows[(rows >= i_val0 - 1) & (rows + 26 < N)]
    tot, n, per_event = 0.0, 0, []
    for i in rows:
        if idx[i + 1] < DESIGN_END:
            continue
        p = params_at(i + 1) if idx[i] >= DESIGN_END else chosen[0]["params"]
        w = c_btc[i] / c_btc[i - 48] - 1
        if not np.isfinite(w) or w == 0 or abs(w) < p["thr"]:
            continue
        side = int(np.sign(w)) if not force_side else force_side
        ev = 0.0
        for s in [x for x in uni.get(month_of[i], []) if x not in (BTC, ETH)][: int(p["n_alt"])]:
            if s not in A:
                continue
            own = A[s]["c"][i] / A[s]["c"][i - 48] - 1
            if filt and not (np.isfinite(own) and np.sign(own) == np.sign(w)):
                continue
            v = sim(s, i, side, p["stop_atr"])
            if v is not None:
                tot += v; n += 1; ev += v
        per_event.append(ev)
    return tot, n

real_slot = rule_total(6, 21)
print("\nB. rule re-run by my simulator at Sunday 21:00: $%.0f, %d trades (engine: $862, 129)" % real_slot)
slots = {(d, h): rule_total(d, h) for d in range(7) for h in range(24)}
tots = np.array([v[0] for v in slots.values()])
rank = int((tots > real_slot[0]).sum()) + 1
print("   all 168 hour-of-week slots: mean $%.0f, median $%.0f, share profitable %.0f%%, p5..p95 $%.0f..$%.0f, best $%.0f"
      % (tots.mean(), np.median(tots), 100 * (tots > 0).mean(), np.percentile(tots, 5), np.percentile(tots, 95), tots.max()))
print("   Sunday 21:00 ranks %d of 168 (%.1f%% of slots do as well or better)" % (rank, 100 * (tots >= real_slot[0]).mean()))
names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
print("   neighbours: " + ", ".join(f"{names[d]} {h:02d}: ${slots[(d, h)][0]:.0f}" for d, h in [(6, 15), (6, 17), (6, 18), (6, 19), (6, 20), (6, 21), (6, 22), (6, 23), (0, 0), (0, 1), (0, 3)]))
print("   by signal day (mean over 24 hours): " + ", ".join(f"{names[d]} ${np.mean([slots[(d, h)][0] for h in range(24)]):.0f}" for d in range(7)))
wk = np.array([slots[(d, h)][0] for d in (5, 6) for h in range(24)]); wd = np.array([slots[(d, h)][0] for d in range(5) for h in range(24)])
print("   weekend-signal slots (Sat+Sun) mean $%.0f vs weekday slots mean $%.0f" % (wk.mean(), wd.mean()))

# ---- C. same Sunday entries, side by coin flip per weekend
both = [[(sim_c(s, i, +1, k), sim_c(s, i, -1, k)) for s, sd, k in legs] for i, legs in events]
realsides = [legs[0][1] for _, legs in events]
totC = np.zeros(5000)
for d in range(5000):
    flips = rng.integers(0, 2, len(events))
    totC[d] = sum((v[0] if fl else v[1]) or 0.0 for ev, fl in zip(both, flips) for v in ev)
print("\nC. same weekends and symbols, side by coin flip per weekend (5000 draws): mean $%.0f, p5..p95 $%.0f..$%.0f | real $%.0f | share >= real %.3f"
      % (totC.mean(), np.percentile(totC, 5), np.percentile(totC, 95), REAL, (totC >= REAL).mean()))
allL = sum((v[0] or 0.0) for ev in both for v in ev); allS = sum((v[1] or 0.0) for ev in both for v in ev)
print("   same trades all LONG $%.0f | all SHORT $%.0f" % (allL, allS))

# ---- D. Sunday variants
print("\nD. Sunday 21:00, no agreement filter: $%.0f (%d trades) | always long, no filter: $%.0f (%d) | always short, no filter: $%.0f (%d)"
      % (*rule_total(6, 21, filt=False), *rule_total(6, 21, filt=False, force_side=1), *rule_total(6, 21, filt=False, force_side=-1)))
