from engine_check import *
import strats as S
rows = []
for kind, hold, extra in (("oi", 36, {}), ("disc", 36, {}), ("hot", 24, {"don_n": 24, "pm_n": 24})):
    for mode, vb in (("mkt", 1), ("first", 1), ("turn", 1), ("limit", 12)):
        st = S.Variant(kind, mode, f"{kind}_{mode}", hold, valid_bars=vb, **extra)
        r = check(st, label=f"{kind} {mode}")
        t = r["tdf"]
        if len(t):
            r["row"]["tR"] = round(t.r.mean() / t.r.std() * np.sqrt(len(t)), 2)
        rows.append(r)
table(rows)
