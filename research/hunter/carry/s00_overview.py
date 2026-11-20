from lib import *
data = load()
print(len(data), "symbols")
rows = []
for s, df in data.items():
    tr = df["tradable"]
    rows.append(dict(sym=s, first=df.index[0].date(), last=df.index[-1].date(), n=len(df), trad=int(tr.sum()),
                     prem_bp_mean=df["premium"].mean()*1e4, prem_bp_std=df["premium"].std()*1e4,
                     prem_p01=df["premium"].quantile(.01)*1e4, prem_p99=df["premium"].quantile(.99)*1e4,
                     fund_bp_h=df["funding"].mean()*1e4, fund_std=df["funding"].std()*1e4,
                     oi_first=df["oi"].first_valid_index(), ls_first=df["ls_ratio"].first_valid_index(),
                     est=df["funding_is_est"].mean()))
t = pd.DataFrame(rows).sort_values("trad", ascending=False)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
print(t.to_string())
u = store.universe()
for m in sorted(u):
    if m < "2025-01": print(m, u[m])
