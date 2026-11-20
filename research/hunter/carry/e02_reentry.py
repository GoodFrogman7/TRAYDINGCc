from engine_check import *
import strats as S
for strat, lab in ((S.OIWashout(), "oiwash"), (S.DiscountBounce(), "discount"), (S.HotDip(), "hotdip")):
    r = check(strat, label=lab)
    t = r["tdf"].copy()
    t["entry_time"] = pd.to_datetime(t["entry_time"]); t["exit_time"] = pd.to_datetime(t["exit_time"])
    t = t.sort_values(["symbol", "entry_time"])
    prev_exit = t.groupby("symbol")["exit_time"].shift(1)
    prev_reason = t.groupby("symbol")["reason"].shift(1)
    t["re"] = ((t["entry_time"] - prev_exit) <= pd.Timedelta(hours=24)) & (prev_reason == "stop")
    print(lab, "all n", len(t), "gross", round(t.gross_bps.mean(), 1), "avgR", round(t.r.mean(), 3))
    for k, g in t.groupby("re"):
        print(f"   re-entry-after-stop<24h={k}: n={len(g)} gross={g.gross_bps.mean():.1f}bp net={g.net_bps.mean():.1f}bp avgR={g.r.mean():.3f} stop%={(g.reason=='stop').mean():.2f}")
    print("   by exit reason:", t.groupby("reason").agg(n=("r", "size"), avgR=("r", "mean"), gross=("gross_bps", "mean")).round(3).to_dict("index"))
    # concurrency: trades per entry day
    d = t.groupby(t.entry_time.dt.floor("D")).agg(n=("r", "size"), R=("r", "sum"))
    print("   days with >=4 entries:", int((d.n >= 4).sum()), "sum R on those days:", round(d.R[d.n >= 4].sum(), 1), "| other days sum R:", round(d.R[d.n < 4].sum(), 1), "| worst day R:", round(d.R.min(), 2))
