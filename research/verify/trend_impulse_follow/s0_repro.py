import time; t0=time.time()
from vcommon import *
market, cells, intents = setup()
print("load+intents", round(time.time()-t0,1), "s; symbols", len(market.data))
s, tr, e, g = wf_val(market, intents)
print("repro wf_validation: ret %.4f dd %.4f n %d avg_r %.4f  (file: %.4f, %d)" % (s["total_return"], s["max_dd"], s["n_trades"], s["avg_r"], RES["wf_validation"]["total_return"], RES["wf_validation"]["n_trades"]))
print("time", round(time.time()-t0,1))
# candles: open[t+1]==close[t]?
for sym in ["PF_XBTUSD","PF_ETHUSD","PF_SOLUSD"]:
    df = market.data[sym]; d = df[~df.bar_missing.astype(bool)]
    eq = np.isclose(d["open"].to_numpy()[1:], d["close"].to_numpy()[:-1], rtol=1e-9)
    print(sym, "open[t+1]==close[t] share", eq.mean().round(5), "bars", len(d), "last bar", d.index[-1])
csv = pd.read_csv(ROOT/"research/results/trades/trend_impulse_follow.csv")
csv = csv[pd.to_datetime(csv.entry_time) >= DESIGN_END]
mine = pd.DataFrame(tr)
print("csv validation trades", len(csv), "sum pnl", csv.pnl.sum().round(2), "mine", len(mine), mine.pnl.sum().round(2))
