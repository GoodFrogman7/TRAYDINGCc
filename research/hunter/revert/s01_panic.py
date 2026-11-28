"""H1/H3: multi-sigma hourly bars, with and without a volume spike, both directions."""
import numpy as np, pandas as pd
from lib import *
P = "/tmp/claude-0/-home-user-TRAYDINGCc/d3ce332c-4cf3-5943-99d9-c4ab3f89b281/scratchpad/panel.pkl"
p = pd.read_pickle(P)
t = p[p.tradable & ~p.bar_missing].copy()

print("---- grid of z1 buckets: mean fwd (bps) signed as FADE (long after down bar, short after up bar)")
rows=[]
for lo,hi in [(2,3),(3,4),(4,6),(6,99)]:
    for vlab, vm in [("any vol", t.vrel>0), ("vrel>3", t.vrel>3), ("vrel<1", t.vrel<1)]:
        for side, m in [("down->long", (t.z1<-lo)&(t.z1>=-hi)), ("up->short", (t.z1>lo)&(t.z1<=hi))]:
            ev = t[m & vm]
            sg = 1.0 if side.startswith("down") else -1.0
            d = dict(z=f"{lo}-{hi}", vol=vlab, side=side, n=len(ev))
            for h in (1,4,12,24):
                s = stats(ev, f"fwd_{h}", sg)
                d[f"m{h}"]=s.get("mean"); d[f"t{h}"]=s.get("t_cl")
            s = stats(ev, "fwd_4_d", sg); d["m4_delay"]=s.get("mean")
            rows.append(d)
with pd.option_context("display.width", 250, "display.float_format", lambda v: f"{v:,.1f}"):
    print(pd.DataFrame(rows).to_string(index=False))

ev = t[(t.z1<-4)&(t.vrel>3)]
report(ev, hs=(1,4,12,24), sign=1.0, title="PANIC long: z1<-4 & vrel>3", hold=12)
ev = t[(t.z1>4)&(t.vrel>3)]
report(ev, hs=(1,4,12,24), sign=-1.0, title="EUPHORIA short: z1>4 & vrel>3", hold=12)
