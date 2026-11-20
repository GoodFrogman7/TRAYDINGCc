"""Final sanity checks on the design window: one-bar-late, fees doubled, floor variant, short-pile squeeze, mirror (rich breadth short)."""
from engine_check import *
import strats as S, strats2 as S2
from desk.strategies import ta
from desk.strategies.base import Strategy, blank_intents
from desk.engine.core import Costs

class Late(Strategy):
    """Send every order one bar late (intent at t is issued at t+1 with the same prices)."""
    def __init__(self, base):
        self.base = base; self.name = base.name + "_late"; self.max_hold = base.max_hold; self.valid_bars = base.valid_bars; self.params = base.params
    def intents(self, data, p):
        o = self.base.intents(data, p)
        return {s: it.shift(1).fillna({"side": 0, "exit": False}).astype({"side": "int8", "exit": bool}) for s, it in o.items()}

class ShortPile(Strategy):
    """Long: price down >= drop over 24h while OI ROSE >= oi_up and the perp trades below index (shorts opening into the low)."""
    name = "carry_short_pile_squeeze"; max_hold = 24; needs = ("oi",)
    params = {"drop": 0.05, "oi_up": 0.05, "pm_n": 8, "atr_n": 24, "stop_atr": 3.0, "cool": 24}
    def __init__(self, **kw): self.params = {**ShortPile.params, **kw}
    def intents(self, data, p):
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index); atr = ta.atr(df, p["atr_n"]); c = df["close"]; oi = df["oi"]
            raw = ((c / c.shift(24) - 1) <= -p["drop"]) & ((oi / oi.shift(24) - 1) >= p["oi_up"]) & (df["premium"].rolling(p["pm_n"], min_periods=p["pm_n"]).mean() < 0) & atr.notna()
            raw = raw.fillna(False)
            prev = raw.shift(1).rolling(p["cool"], min_periods=1).max().fillna(0).astype(bool)
            sig = raw & ~prev
            it["side"] = np.where(sig, 1, 0).astype(np.int8); it["stop"] = np.where(sig, c - p["stop_atr"] * atr, np.nan)
            out[s] = it
        return out

class RichBreadthShort(Strategy):
    """Mirror of the cascade: short a symbol at an unusual premium when >= k tradable symbols are rich together."""
    name = "mirror_rich_short"; max_hold = 36
    params = {"pm_n": 8, "norm_n": 720, "z": 2.0, "zb": 2.0, "k": 2, "atr_n": 24, "stop_atr": 3.0}
    def intents(self, data, p):
        from desk.data import store
        Z = {}
        for s, df in data.items():
            pm = df["premium"].rolling(p["pm_n"], min_periods=p["pm_n"]).mean()
            Z[s] = (pm - pm.rolling(p["norm_n"], min_periods=p["norm_n"] // 2).median()) / df["premium"].rolling(p["norm_n"], min_periods=p["norm_n"] // 2).std()
        idx = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
        cnt = pd.Series(0, index=idx, dtype="int64")
        for s, df in data.items():
            tr = store.tradable_mask(s, df.index) & ~df["bar_missing"].astype(bool)
            cnt = cnt.add(((Z[s] >= p["zb"]) & tr).astype("int64").reindex(idx, fill_value=0), fill_value=0)
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index); atr = ta.atr(df, p["atr_n"])
            sig = ((Z[s] >= p["z"]) & (cnt.reindex(df.index).fillna(0) >= p["k"]) & atr.notna()).fillna(False)
            it["side"] = np.where(sig, -1, 0).astype(np.int8); it["stop"] = np.where(sig, df["close"] + p["stop_atr"] * atr, np.nan)
            out[s] = it
        return out

rows = []
def add(st, lab, costs=None):
    r = check(st, label=lab, costs=costs); t = r["tdf"]
    if len(t) > 2:
        r["row"]["tR"] = round(t.r.mean() / t.r.std() * np.sqrt(len(t)), 2)
        d = t.groupby(pd.to_datetime(t.entry_time).dt.floor("D")).r.sum()
        r["row"]["days"] = len(d); r["row"]["tDay"] = round(d.mean() / d.std() * np.sqrt(len(d)), 2)
        maj = t.symbol.isin(["PF_XBTUSD", "PF_ETHUSD"])
        r["row"]["majR"] = f"{t.r[maj].mean():.2f}/{int(maj.sum())}"
    rows.append(r); return r
base = lambda **kw: S2.BreadthDiscount(max_hold=36, **{"k": 2, **kw})
r0 = add(base(), "cascade z2 k2 mkt")
add(Late(base()), "cascade one bar late")
add(base(), "cascade fees x2", costs=Costs(fee_mult=2.0))
add(base(), "cascade slip x3", costs=Costs(slip_mult=3.0))
add(Late(S2.BreadthDiscount(max_hold=48, k=5, zb=1.5, who="maj_breadth_only", mode="first")), "majors breadth z1.5 k5 first h48 LATE")
add(S2.BreadthDiscount(max_hold=48, k=4, zb=1.5, who="maj_breadth_only", mode="first"), "majors breadth z1.5 k4")
add(S2.BreadthDiscount(max_hold=48, k=6, zb=1.5, who="maj_breadth_only", mode="first"), "majors breadth z1.5 k6")
add(S2.BreadthDiscount(max_hold=48, k=4, zb=2.0, who="maj_breadth_only", mode="first"), "majors breadth z2 k4")
add(S.Variant("oi", "first", "oi_first", 36), "oi washout first")
add(Late(S.Variant("oi", "first", "oi_first", 36)), "oi washout first LATE")
add(S.Variant("oi", "first", "oi_first", 36), "oi washout fees x2", costs=Costs(fee_mult=2.0))
add(ShortPile(), "short pile -5% oi+5%")
add(ShortPile(oi_up=0.10), "short pile -5% oi+10%")
add(ShortPile(drop=0.03), "short pile -3% oi+5%")
add(ShortPile(drop=0.08), "short pile -8% oi+5%")
add(Late(ShortPile()), "short pile LATE")
add(RichBreadthShort(), "MIRROR rich breadth short z2 k2")
table(rows)
# concentration of the primary idea
t = r0["tdf"]; t["m"] = pd.to_datetime(t.entry_time).dt.strftime("%Y-%m")
g = t.groupby("m").r.agg(["size", "sum"]).round(1)
print("cascade by month (n, sumR):"); print(g.T.to_string())
print("top5 days share of total R:", round(t.groupby(pd.to_datetime(t.entry_time).dt.floor('D')).r.sum().nlargest(5).sum() / t.r.sum(), 2))
print("by symbol:", t.groupby("symbol").r.agg(["size", "mean"]).round(2).sort_values("size", ascending=False).head(12).to_dict("index"))
print("funding pnl per trade (bps of notional):", round((t.get("funding", pd.Series(dtype=float)) / t.notional).mean() * 1e4, 2) if "funding" in t else "n/a", "| cols:", list(t.columns)[:25])
