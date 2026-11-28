from engine_check import *
import strats2 as S2
rows = []
def add(lab, hold=36, **kw):
    r = check(S2.BreadthDiscount(max_hold=hold, **kw), label=lab)
    t = r["tdf"]
    if len(t) > 2:
        r["row"]["tR"] = round(t.r.mean() / t.r.std() * np.sqrt(len(t)), 2)
        d = t.groupby(pd.to_datetime(t.entry_time).dt.floor("D")).r.sum()
        r["row"]["days"] = len(d); r["row"]["tDay"] = round(d.mean() / d.std() * np.sqrt(len(d)), 2)
    rows.append(r)
add("own z2 k1 (no breadth) mkt", k=1)
add("own z2 k2 mkt", k=2)
add("own z2 k3 mkt", k=3)
add("own z2 k2 first", k=2, mode="first")
add("own z2 k2 turn", k=2, mode="turn")
add("own z2 k2 mkt hold48", hold=48, k=2)
add("own z2 k2 mkt hold72", hold=72, k=2)
add("own z2 k2 mkt noNeg", k=2, neg=False)
add("own z2.5 k2 mkt", k=2, z=2.5)
add("own z1.5 zb2 k2 mkt", k=2, z=1.5)
add("own z2 k2 stop4", k=2, stop_atr=4.0)
add("own z2 k2 stop2.5", k=2, stop_atr=2.5)
add("majors breadth z2 k3 mkt h48", hold=48, k=3, who="maj_breadth_only")
add("majors breadth z2 k3 first h48", hold=48, k=3, who="maj_breadth_only", mode="first")
add("majors breadth z1.5 k5 first h48", hold=48, k=5, zb=1.5, who="maj_breadth_only", mode="first")
add("all breadth z2 k3 first h48", hold=48, k=3, who="breadth_only", mode="first")
add("all breadth z1.5 k5 first h48", hold=48, k=5, zb=1.5, who="breadth_only", mode="first")
add("all breadth z2 k3 first h36", hold=36, k=3, who="breadth_only", mode="first")
table(rows)
