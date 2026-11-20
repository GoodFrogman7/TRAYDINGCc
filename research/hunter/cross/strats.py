"""Draft strategies for the cross-market lens (research copies; the Auditor re-implements under desk/strategies)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from desk.data import store
from desk.strategies import ta
from desk.strategies.base import Strategy, blank_intents

BTC = "PF_XBTUSD"


def _universe_mask(data):
    return {s: store.tradable_mask(s, df.index) for s, df in data.items()}


class WeekendFollow(Strategy):
    name = "cross_weekend_follow"
    valid_bars = 1
    max_hold = 24
    params = {"look": 48, "thr": 0.005, "stop_atr": 4.0, "sig_hour": 21, "who": "all"}

    def intents(self, data, p):
        b = data[BTC]
        w = b["close"] / b["close"].shift(p["look"]) - 1.0
        is_sig = (b.index.dayofweek == 6) & (b.index.hour == p["sig_hour"])
        sgn = np.sign(w).where(is_sig & (w.abs() >= p["thr"]), 0.0)
        out = {}
        for s, df in data.items():
            if p["who"] == "btc" and s != BTC:
                continue
            if p["who"] == "majors" and s not in (BTC, "PF_ETHUSD"):
                continue
            if p["who"] == "alts" and s == BTC:
                continue
            it = blank_intents(df.index)
            sd = sgn.reindex(df.index).fillna(0.0)
            if p.get("agree"):
                own = np.sign(df["close"] / df["close"].shift(p["look"]) - 1.0)
                sd = sd.where(own == sd, 0.0)
            atr = ta.atr(df, 24)
            ok = atr.notna() & (sd != 0)
            it["side"] = np.where(ok, sd, 0).astype(np.int8)
            it["stop"] = df["close"] - sd * p["stop_atr"] * atr
            out[s] = it
        return out


class RSLeader(Strategy):
    """Long the strongest names of the month's top 10 on trailing L-hour return; daily decision at the 23:00 bar."""
    name = "cross_rs_leader"
    valid_bars = 1
    max_hold = 168
    params = {"L": 336, "top": 2, "stop_k": 2.0, "exit_rank": 5, "abs_filter": True, "breadth_min": 0.0, "ma": 480, "short": False}

    def intents(self, data, p):
        um = _universe_mask(data)
        idx = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
        C = pd.DataFrame({s: df["close"].reindex(idx) for s, df in data.items()})
        U = pd.DataFrame({s: um[s].reindex(idx).fillna(False) for s in data}).astype(bool) & C.notna()
        mom = (C / C.shift(p["L"]) - 1.0).where(U)
        n = mom.notna().sum(axis=1)
        rk_hi = mom.rank(axis=1, ascending=False)
        rk_lo = mom.rank(axis=1, ascending=True)
        ma = C.rolling(p["ma"], min_periods=p["ma"]).mean()
        br = ((C > ma) & U).sum(axis=1) / U.sum(axis=1).astype(float).replace(0.0, np.nan)
        daily = pd.Series(idx.hour == 23, index=idx)
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            dvol = ta.realized_vol(df["close"], 168) * np.sqrt(24.0)
            r_hi, r_lo, m = rk_hi[s].reindex(df.index), rk_lo[s].reindex(df.index), mom[s].reindex(df.index)
            d = daily.reindex(df.index).fillna(False)
            nn = n.reindex(df.index); b = br.reindex(df.index)
            long_ok = d & (nn >= 8) & (r_hi <= p["top"]) & dvol.notna() & (b >= p["breadth_min"])
            if p["abs_filter"]:
                long_ok &= m > 0
            side = np.where(long_ok, 1, 0)
            stop = df["close"] * (1 - p["stop_k"] * dvol)
            ex = d & (r_hi > p["exit_rank"])
            if p["short"]:
                short_ok = d & (nn >= 8) & (r_lo <= p["top"]) & dvol.notna() & (b <= 1 - p["breadth_min"]) & (m < 0)
                side = np.where(short_ok, -1, side)
                stop = np.where(short_ok, df["close"] * (1 + p["stop_k"] * dvol), stop)
                ex = d & (r_hi > p["exit_rank"]) & (r_lo > p["exit_rank"])     # in the middle: neither leg holds
            it["side"] = side.astype(np.int8)
            it["stop"] = stop
            it["exit"] = ex.fillna(False).to_numpy(dtype=bool)
            out[s] = it
        return out


def _wide(data, col):
    idx = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    return pd.DataFrame({s: df[col].reindex(idx) for s, df in data.items()})


class FlushBounce(Strategy):
    """Market-wide down-shock (equal-weight universe basket falls k sigma in one hour, with a liquidation spike) -> long."""
    name = "cross_flush_bounce"
    valid_bars = 1
    max_hold = 12
    params = {"k": 4.0, "liq_mult": 5.0, "stop_atr": 4.0, "who": "all", "vol_n": 168}

    def intents(self, data, p):
        um = _universe_mask(data)
        C = _wide(data, "close")
        U = pd.DataFrame({s: um[s].reindex(C.index).fillna(False) for s in data}).astype(bool) & C.notna()
        r1 = C.pct_change()
        basket = r1.where(U).mean(axis=1)
        z = basket / basket.rolling(p["vol_n"], min_periods=100).std().shift(1)
        sig = (z < -p["k"]) & (U.sum(axis=1) >= 8)
        if p["liq_mult"] > 0:
            liq = (_wide(data, "liq_vol") * C).where(U).sum(axis=1)
            sig &= liq > p["liq_mult"] * liq.rolling(p["vol_n"], min_periods=100).mean().shift(1)
        out = {}
        for s, df in data.items():
            if p["who"] == "alts" and s in (BTC, "PF_ETHUSD"):
                continue
            if p["who"] == "majors" and s not in (BTC, "PF_ETHUSD"):
                continue
            it = blank_intents(df.index)
            atr = ta.atr(df, 24)
            ok = sig.reindex(df.index).fillna(False) & atr.notna()
            it["side"] = np.where(ok, 1, 0).astype(np.int8)
            it["stop"] = df["close"] - p["stop_atr"] * atr
            out[s] = it
        return out


class IdioBreakout(Strategy):
    """Coin beats the universe basket by k sigma over 24h (first trigger in 24 bars) -> long, breadth-gated."""
    name = "cross_idio_breakout"
    valid_bars = 1
    max_hold = 168
    params = {"k": 3.0, "stop_k": 2.0, "breadth_min": 0.5, "ma": 200}

    def intents(self, data, p):
        um = _universe_mask(data)
        C = _wide(data, "close")
        U = pd.DataFrame({s: um[s].reindex(C.index).fillna(False) for s in data}).astype(bool) & C.notna()
        r24 = C / C.shift(24) - 1.0
        rel = r24.sub(r24.where(U).mean(axis=1), axis=0)
        zz = rel / rel.rolling(720, min_periods=360).std().shift(24)
        ma = C.rolling(p["ma"], min_periods=p["ma"]).mean()
        br = ((C > ma) & U).sum(axis=1) / U.sum(axis=1).astype(float).replace(0.0, np.nan)
        out = {}
        for s, df in data.items():
            it = blank_intents(df.index)
            cond = (zz[s] > p["k"]).reindex(df.index).fillna(False)
            first = cond & ~cond.shift(1, fill_value=False).rolling(24, min_periods=1).max().astype(bool)
            dvol = ta.realized_vol(df["close"], 168) * np.sqrt(24.0)
            ok = first & dvol.notna() & (br.reindex(df.index) >= p["breadth_min"])
            it["side"] = np.where(ok, 1, 0).astype(np.int8)
            it["stop"] = df["close"] * (1 - p["stop_k"] * dvol)
            it["trail"] = df["close"] * (1 - p["stop_k"] * dvol)
            out[s] = it
        return out


class WeekendAlts(WeekendFollow):
    """Weekend-follow sleeve for the liquid alts: universe ranks 3..n_alt+2, only where the alt's own weekend sign agrees with BTC's."""
    name = "cross_weekend_alts"
    params = {"look": 48, "thr": 0.005, "stop_atr": 5.0, "sig_hour": 21, "n_alt": 3}

    def intents(self, data, p):
        uni = store.universe()
        b = data[BTC]
        w = b["close"] / b["close"].shift(p["look"]) - 1.0
        is_sig = (b.index.dayofweek == 6) & (b.index.hour == p["sig_hour"])
        sgn = np.sign(w).where(is_sig & (w.abs() >= p["thr"]), 0.0)
        out = {}
        for s, df in data.items():
            if s in (BTC, "PF_ETHUSD"):
                continue
            months = df.index.strftime("%Y-%m")
            lst = [[x for x in uni.get(m, []) if x not in (BTC, "PF_ETHUSD")][: p["n_alt"]] for m in pd.unique(months)]
            sel = dict(zip(pd.unique(months), lst))
            inset = pd.Series([s in sel[m] for m in months], index=df.index)
            it = blank_intents(df.index)
            sd = sgn.reindex(df.index).fillna(0.0)
            own = np.sign(df["close"] / df["close"].shift(p["look"]) - 1.0)
            sd = sd.where((own == sd) & inset, 0.0)
            atr = ta.atr(df, 24)
            ok = atr.notna() & (sd != 0)
            it["side"] = np.where(ok, sd, 0).astype(np.int8)
            it["stop"] = df["close"] - sd * p["stop_atr"] * atr
            out[s] = it
        return out


class RatioBreak(Strategy):
    """Alt/BTC ratio breaks its N-bar extreme -> trade the alt in that direction, only with BTC's own trend."""
    name = "cross_ratio_break"
    valid_bars = 1
    max_hold = 168
    params = {"N": 336, "ma": 480, "stop_k": 2.5, "sides": "both", "gate": True}

    def intents(self, data, p):
        b = data[BTC]["close"]
        bma = b.rolling(p["ma"], min_periods=p["ma"]).mean()
        out = {}
        for s, df in data.items():
            if s == BTC:
                continue
            it = blank_intents(df.index)
            bb = b.reindex(df.index)
            ratio = df["close"] / bb
            hi = ratio.shift(1).rolling(p["N"], min_periods=p["N"]).max()
            lo = ratio.shift(1).rolling(p["N"], min_periods=p["N"]).min()
            up, dn = ratio > hi, ratio < lo
            upf = up & ~up.shift(1, fill_value=False).rolling(48, min_periods=1).max().astype(bool)
            dnf = dn & ~dn.shift(1, fill_value=False).rolling(48, min_periods=1).max().astype(bool)
            reg_up = (bb > bma.reindex(df.index)) if p["gate"] else pd.Series(True, index=df.index)
            reg_dn = (bb < bma.reindex(df.index)) if p["gate"] else pd.Series(True, index=df.index)
            dvol = ta.realized_vol(df["close"], 168) * np.sqrt(24.0)
            lg = upf & reg_up & dvol.notna() & (p["sides"] in ("both", "long"))
            sh = dnf & reg_dn & dvol.notna() & (p["sides"] in ("both", "short"))
            it["side"] = np.where(lg, 1, np.where(sh, -1, 0)).astype(np.int8)
            it["stop"] = np.where(sh, df["close"] * (1 + p["stop_k"] * dvol), df["close"] * (1 - p["stop_k"] * dvol))
            out[s] = it
        return out
