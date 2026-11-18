"""Neighbourhood check (not optimisation): does every nearby setting hold on the design window, after costs?"""
from engine_check import *
import strats as S, itertools, time
def grid(kind, mode, hold, g, vb=1, **fixed):
    rows = []
    keys = list(g)
    for vals in itertools.product(*[g[k] for k in keys]):
        prm = dict(zip(keys, vals)); prm.update(fixed)
        st = S.Variant(kind, mode, f"{kind}_{mode}", hold, valid_bars=vb, **prm)
        r = check(st, label=f"{kind}/{mode} " + " ".join(f"{k}={v}" for k, v in zip(keys, vals)))
        t = r["tdf"]
        r["row"]["tR"] = round(t.r.mean() / t.r.std() * np.sqrt(len(t)), 2) if len(t) > 2 else np.nan
        rows.append(r)
    table(rows)
    rets = [r["row"].get("ret", 0) for r in rows]
    print(f"   profitable cells: {sum(x > 0 for x in rets)}/{len(rets)}  median ret {np.median(rets):.1f}%\n")
t0 = time.time()
grid("disc", "first", 36, {"z": [2.0, 2.5, 3.0], "stop_atr": [2.5, 3.0, 4.0]})
grid("disc", "turn", 36, {"z": [2.0, 2.5, 3.0], "arm": [6, 12, 24]})
grid("oi", "first", 36, {"oi_drop": [0.10, 0.15, 0.20], "don_n": [48, 72, 96]})
grid("hot", "first", 24, {"thr_bp": [3.0, 5.0, 8.0], "don_n": [12, 24, 48]}, pm_n=24)
print("secs", round(time.time() - t0))
