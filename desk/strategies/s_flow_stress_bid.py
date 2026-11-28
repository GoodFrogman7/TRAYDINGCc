"""When BTC dumps hard on volume and an alt barely moves, buy that alt for 24 hours."""
from __future__ import annotations

from . import ta
from .base import Strategy
from .common import BTC, ETH, entries


def _rz(x):
    r = x / x.shift(1) - 1.0
    return r / r.rolling(168, min_periods=100).std().shift(1)


class FlowStressBid(Strategy):
    name = "flow_stress_bid"
    idea = ("When BTC dumps 3 sigma in one hour on a volume surge and an alt barely moves, buy that alt for "
            "24 hours.")
    cause = ("An alt that holds while BTC is being sold hard has a resting bid that just absorbed forced "
             "selling, so supply is exhausted and it leads once BTC stops falling.")
    loser = "Sellers who dumped the alt into that bid, and shorts positioned for it to catch down to BTC."
    regime = "wild"
    valid_bars = 1
    max_hold = 24
    params = {"z_btc": 3.0, "z_alt": -1.0, "stop_atr": 3.0}
    grid = {"z_btc": [2.5, 3.0, 3.5], "z_alt": [-1.5, -1.0, -0.5], "stop_atr": [2.5, 3.0, 4.0]}

    def intents(self, data, p):
        out = {}
        btc = data.get(BTC)
        if btc is not None:
            btc_rz = _rz(btc["close"])
            btc_vr = btc["volume"] / btc["volume"].rolling(168, min_periods=100).median().shift(1)
        for sym, df in data.items():
            atr = ta.atr(df, 24)
            if btc is None or sym in (BTC, ETH):
                out[sym] = entries(df, None, None, atr)
                continue
            long = (btc_rz.reindex(df.index) <= -p["z_btc"]) & (btc_vr.reindex(df.index) >= 3.0) & \
                   (_rz(df["close"]) > p["z_alt"])
            out[sym] = entries(df, long, None, p["stop_atr"] * atr)
        return out


STRATEGY = FlowStressBid()
