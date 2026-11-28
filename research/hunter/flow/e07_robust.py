"""Last robustness pass on the two lead ideas: hour profile / looser z for the weekend short, alt threshold for stress bid."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import strats as S, engine_check as E
rows = []
for nm, p in (("short z0.5 h21", dict(z=0.5)), ("short z0.75 h19", dict(z=0.75, hour=19)), ("short z0.75 h20", dict(z=0.75, hour=20)),
              ("short z0.75 h22", dict(z=0.75, hour=22)), ("short z1.0 h20", dict(z=1.0, hour=20)), ("short z1.0 h22", dict(z=1.0, hour=22))):
    st = S.WeekendDumpShort(); rows.append(E.check(st, p, label=nm, max_hold=24))
print("##### weekend short: hour profile"); E.table(rows)
rows = []
for nm, p in (("za 0.0", dict(z_alt=0.0)), ("za -1.5", dict(z_alt=-1.5)), ("v_btc 2", dict(v_btc=2.0)), ("v_btc 4", dict(v_btc=4.0)),
              ("zb2.5 stop4", dict(z_btc=2.5, stop_atr=4.0)), ("zb3.5 stop2.5", dict(z_btc=3.5, stop_atr=2.5))):
    st = S.StressBid(); rows.append(E.check(st, p, label=nm, max_hold=24))
print("\n##### stress bid: extra neighbours"); E.table(rows)
# long/short & symbol concentration of the lead ideas
for cls, p in ((S.WeekendDumpShort, dict(z=0.75)), (S.StressBid, dict())):
    r = E.check(cls(), p, max_hold=24)
    t = r["tdf"]; t["d"] = t.entry_time.astype(str).str[:10]
    byd = t.groupby("d").pnl.sum() / 100
    print(f"\n{cls.name}: entry days {len(byd)}, winning days {(byd>0).mean():.2f}, best 5 days {byd.nlargest(5).round(2).to_dict()}, worst 5 {byd.nsmallest(5).round(2).to_dict()}")
    print("  total %.1f%%, without best 5 days %.1f%%" % (byd.sum(), byd.sum() - byd.nlargest(5).sum()))
    print("  pnl by symbol (%):", (t.groupby("symbol").pnl.sum() / 100).round(1).sort_values(ascending=False).to_dict())
