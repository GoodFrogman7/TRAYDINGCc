"""Whole-contract sizing on Coinbase (contract sizes from Coinbase's public product list: XRP 500, SOL 5, DOGE 5000,
ADA 1000, SUI 500, LTC 5, ZEC 1 coins). Uses the validation trades' own entry prices only."""
import pickle
from pathlib import Path
import numpy as np, pandas as pd
T = pickle.load(open(Path(__file__).resolve().parent / "trades.pkl", "rb"))["T"]
U = {"PF_XRPUSD": 500, "PF_SOLUSD": 5, "PF_DOGEUSD": 5000, "PF_ADAUSD": 1000, "PF_SUIUSD": 500, "PF_LTCUSD": 5, "PF_ZECUSD": 1}
T = T[T.symbol.isin(U)].copy()
T["units"] = T.symbol.map(U); T["want"] = T.qty / T.units
for mode, f in (("nearest", np.round), ("floor", np.floor), ("at least 1", lambda x: np.maximum(1, np.round(x)))):
    k = f(T.want); scale = k / T.want
    print(f"{mode:<11}: trades skipped {int((k==0).sum())}/{len(T)}; total ${ (T.pnl*scale).sum():.0f} (fractional sizing ${T.pnl.sum():.0f}); "
          f"risk per trade ${ (50*scale[k>0]).min():.0f}..${(50*scale[k>0]).max():.0f}, median ${np.median(50*scale[k>0]):.0f}; "
          f"with actual costs ${(T.pnl_fair*scale).sum():.0f}")
print(T.groupby("symbol").want.describe()[["count", "min", "50%", "max"]].round(2))
