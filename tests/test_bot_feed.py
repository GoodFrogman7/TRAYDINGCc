"""feed.py: which bars are closed, which symbols are fetched, and how raw frames become research-layout frames."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from desk.bot import feed as F
from desk.data import store
from desk.data.download import MAX_REL_FUNDING, fit_funding
from desk.engine.costs import slip_table
from test_bot_fakes import ALTS, BTC, ETH, FakeSource, FakeVenue, HOUR, make_frames, no_network, world  # noqa: F401

pytestmark = pytest.mark.usefixtures("no_network")


def ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


MODEL = {"pooled_a": 1e-6, "pooled_k": 0.04, "per_symbol": {BTC: {"a": 2e-6, "k": 0.05}}}
RESEARCH_COLUMNS = ["open", "high", "low", "close", "volume", "bar_missing", "mark_close", "spot_close", "premium",
                    "funding_actual", "oi", "liq_vol", "ls_ratio", "buy_vol", "sell_vol", "bid_10k", "bid_100k",
                    "ask_10k", "ask_100k", "funding_is_est", "funding"]


# ------------------------------------------------------------------ closed_asof
def test_closed_asof_floors_the_clock_minus_the_settle_time():
    assert F.closed_asof(ts("2026-11-18 14:07:00"), 120) == ts("2026-11-18 14:00")
    assert F.closed_asof(ts("2026-11-18 14:02:00"), 120) == ts("2026-11-18 14:00")
    assert F.closed_asof(ts("2026-11-18 14:01:59"), 120) == ts("2026-11-18 13:00")   # 13:00 bar not settled yet
    assert F.closed_asof(ts("2026-11-18 14:59:59"), 0) == ts("2026-11-18 14:00")
    assert F.closed_asof(ts("2026-11-18 00:00:30"), 120) == ts("2026-11-17 23:00")
    paris = pd.Timestamp("2026-11-18 15:07", tz="Europe/Paris")
    assert F.closed_asof(paris, 120) == ts("2026-11-18 14:00")


# -------------------------------------------------------------- symbols_needed
UNI = {"2026-09": ["PF_OLDUSD", BTC, "PF_AAAUSD"], "2026-10": [BTC, ETH, "PF_AAAUSD", "PF_BBBUSD"],
       "2026-11": [BTC, ETH, "PF_CCCUSD"]}


def test_symbols_needed_required_and_context():
    req, ctx = F.symbols_needed(UNI, ts("2026-10-05"), ts("2026-11-18 14:00"), {"PF_HELDUSD"}, ("PF_XTRAUSD",))
    assert req[:2] == [BTC, ETH]
    assert set(req) == {BTC, ETH, "PF_CCCUSD", "PF_HELDUSD", "PF_XTRAUSD"}
    assert ctx == ["PF_AAAUSD", "PF_BBBUSD"]                # October only: September is outside the window
    assert len(req) == len(set(req)) and not set(req) & set(ctx)


def test_symbols_needed_month_boundaries():
    # at 00:02 on the 1st the newest closed bar still belongs to the old month
    req, ctx = F.symbols_needed(UNI, ts("2026-09-20"), ts("2026-11-01 00:00"), set(), ())
    assert set(req) == {BTC, ETH, "PF_AAAUSD", "PF_BBBUSD"} and ctx == ["PF_OLDUSD"]
    # a month the universe file does not have yet: only the fixed and held symbols are required
    req, ctx = F.symbols_needed(UNI, ts("2026-10-20"), ts("2026-12-01 05:00"), {"PF_CCCUSD"}, ())
    assert req == [BTC, ETH, "PF_CCCUSD"] and ctx == ["PF_AAAUSD", "PF_BBBUSD"]


# ------------------------------------------------------------------------ fetch
def test_fetch_keeps_only_closed_bars_inside_the_window():
    src = FakeSource(make_frames(n=400))
    start, asof = ts("2026-07-03 00:00"), ts("2026-07-10 00:00")
    src.now = asof + pd.Timedelta(minutes=7)
    got = F.fetch(src, [BTC, ETH], start, asof)
    assert not got.errors and got.server_time == src.now and 0.0 <= got.server_time_delay < 1.0
    for s in (BTC, ETH):
        idx = got.frames[s].index
        assert idx[0] == start and idx[-1] == asof - HOUR      # the still-open 00:00 bar was dropped
    assert {c[0] for c in src.calls} == {BTC, ETH}
    assert src.calls[0][1:] == (int(start.timestamp()), int(asof.timestamp()))


def test_fetch_retries_once_and_reports_failures_per_symbol():
    class Flaky(FakeSource):
        def __init__(self, frames):
            super().__init__(frames)
            self.tries = {}

        def bars(self, symbol, start, asof):
            self.tries[symbol] = self.tries.get(symbol, 0) + 1
            if symbol == ETH and self.tries[symbol] == 1:
                raise RuntimeError("blip")
            return super().bars(symbol, start, asof)

        def server_time(self):
            raise RuntimeError("clock endpoint down")

    src = Flaky(make_frames(n=400))
    src.fail = {ALTS[0]}
    got = F.fetch(src, [BTC, ETH, ALTS[0]], ts("2026-07-03"), ts("2026-07-10"))
    assert set(got.frames) == {BTC, ETH}                     # ETH worked on the second try
    assert src.tries[ETH] == 2 and src.tries[ALTS[0]] == 2
    assert list(got.errors) == [ALTS[0]] and "outage" in got.errors[ALTS[0]]
    assert got.server_time is None


def test_fetch_counts_an_empty_window_as_a_failure():
    src = FakeSource(make_frames(n=400))
    src.last_bar[ETH] = ts("2026-07-02 00:00")               # nothing inside the window
    got = F.fetch(src, [BTC, ETH], ts("2026-07-03"), ts("2026-07-10"))
    assert set(got.frames) == {BTC} and ETH in got.errors


# ---------------------------------------------------------------------- prepare
def small(n=200, sym=BTC):
    return make_frames(n=n)[sym]


def test_prepare_gives_the_research_layout_and_the_research_funding():
    raw = small()
    raw.loc[raw.index[:50], "funding_actual"] = np.nan        # funding older than the venue serves
    raw.loc[raw.index[0:3], "premium"] = np.nan
    t_last = raw.index[-1]
    data, gaps, bad = F.prepare({BTC: raw.copy(), ETH: raw.copy()}, t_last, 72, MODEL)
    assert gaps == {} and bad == {}
    for s, (a, k) in {BTC: (2e-6, 0.05), ETH: (1e-6, 0.04)}.items():      # per symbol, else pooled
        df = data[s]
        assert list(df.columns) == RESEARCH_COLUMNS and df.index.name == "time"
        assert df.index.equals(raw.index)
        est = (a + k * raw["premium"].shift(1)).clip(-MAX_REL_FUNDING, MAX_REL_FUNDING)
        want = raw["funding_actual"].fillna(est).fillna(0.0)
        assert np.array_equal(df["funding"].to_numpy(), want.to_numpy())
        assert df["funding_is_est"].tolist() == raw["funding_actual"].isna().tolist()
        assert df["funding"].iloc[0] == 0.0                    # no earlier premium: nothing to estimate from
        for c in ("oi", "liq_vol", "ls_ratio", "buy_vol", "sell_vol", "premium"):
            assert df[c].dtype == np.float32
        assert df["bar_missing"].dtype == bool and df["funding_is_est"].dtype == bool
        assert df["close"].dtype == np.float64


def test_prepare_matches_download_fit_funding_exactly():
    raw = small()
    raw.loc[raw.index[:80], "funding_actual"] = np.nan
    ref = {BTC: raw.copy()}
    fit_funding(ref, cutoff=None)                             # too few rows to fit: falls back to its pooled default
    data, _, _ = F.prepare({BTC: raw.copy()}, raw.index[-1], 72,
                           {"pooled_a": 0.0, "pooled_k": 1.0 / 24.0, "per_symbol": {}})
    pd.testing.assert_frame_equal(data[BTC][ref[BTC].columns], ref[BTC], check_freq=False)


def test_prepare_reads_the_manifest_model_when_none_is_given(world):
    (world.data / "manifest.json").write_text(json.dumps({"funding_model": MODEL}))
    raw = small()
    raw["funding_actual"] = np.nan
    data, _, _ = F.prepare({BTC: raw}, raw.index[-1], 72)
    want = (2e-6 + 0.05 * raw["premium"].shift(1)).clip(-MAX_REL_FUNDING, MAX_REL_FUNDING).fillna(0.0)
    assert np.array_equal(data[BTC]["funding"].to_numpy(), want.to_numpy())
    assert data[BTC]["funding_is_est"].all()


def test_prepare_turns_bad_bars_into_missing_bars():
    raw = small()
    i = raw.index
    raw.loc[i[10], "close"] = np.nan
    raw.loc[i[20], "low"] = 0.0
    raw.loc[i[30], "open"] = -5.0
    raw.loc[i[40], ["high", "low"]] = [90.0, 95.0]
    data, gaps, bad = F.prepare({BTC: raw.copy()}, i[-1], 72, MODEL)
    df = data[BTC]
    assert bad == {BTC: 4} and gaps == {}
    for k in (10, 20, 30, 40):
        row, prev = df.loc[i[k]], raw["close"].iloc[k - 1]
        assert row["bar_missing"] and row["volume"] == 0.0
        assert row["open"] == row["high"] == row["low"] == row["close"] == prev
    assert int(df["bar_missing"].sum()) == 4
    untouched = df.index.difference(i[[10, 20, 30, 40]])
    assert df.loc[untouched, "close"].equals(raw.loc[untouched, "close"])


def test_prepare_drops_leading_bad_bars_and_does_not_count_venue_gaps_as_bad():
    raw = small()
    i = raw.index
    raw.loc[i[0:2], "close"] = np.nan                         # no earlier price to fill from
    raw.loc[i[50], ["open", "high", "low", "close"]] = raw["close"].iloc[49]
    raw.loc[i[50], ["volume", "bar_missing"]] = [0.0, True]   # a gap the venue already flagged
    data, gaps, bad = F.prepare({BTC: raw.drop(index=i[60])}, i[-1], 72, MODEL)   # and an hour with no row at all
    df = data[BTC]
    assert df.index[0] == i[2] and bad == {}
    assert df.loc[i[50], "bar_missing"] and df.loc[i[60], "bar_missing"]
    assert df.loc[i[60], "close"] == raw["close"].iloc[59] and df.loc[i[60], "volume"] == 0.0
    assert len(df) == len(i) - 2 and int(df["bar_missing"].sum()) == 2


def test_prepare_fills_a_short_gap_and_stops_at_a_delisting():
    raw = small()
    i = raw.index
    late, dead = raw.iloc[:-5].copy(), raw.iloc[:-80].copy()
    data, gaps, bad = F.prepare({BTC: raw.copy(), ETH: late, ALTS[0]: dead}, i[-1], 72, MODEL)
    assert gaps == {ETH: 5, ALTS[0]: 80} and bad == {}
    e = data[ETH]
    assert e.index[-1] == i[-1] and len(e) == len(i)
    tail = e.iloc[-5:]
    assert tail["bar_missing"].all() and (tail["volume"] == 0).all()
    last = late["close"].iloc[-1]
    assert (tail[["open", "high", "low", "close"]] == last).all().all()
    assert tail[["mark_close", "spot_close", "premium", "funding_actual", "oi", "bid_10k"]].isna().all().all()
    assert not e["bar_missing"].iloc[:-5].any()
    assert tail["funding_is_est"].all() and np.isfinite(tail["funding"]).all()
    d = data[ALTS[0]]
    assert d.index[-1] == dead.index[-1] and not d["bar_missing"].any()      # ends at its last real bar
    # one hour short of the limit is still a gap, not a delisting
    data, gaps, _ = F.prepare({BTC: raw.iloc[:-71].copy()}, i[-1], 72, MODEL)
    assert gaps == {BTC: 71} and data[BTC].index[-1] == i[-1]


def test_prepare_drops_rows_after_t_last_and_fills_absent_columns():
    raw = small()[["open", "high", "low", "close", "volume"]]
    t_last = raw.index[150]
    data, gaps, bad = F.prepare({BTC: raw, ETH: raw.iloc[160:]}, t_last, 72, MODEL)
    assert set(data) == {BTC}                                 # ETH has nothing at or before t_last
    df = data[BTC]
    assert df.index[-1] == t_last and list(df.columns) == RESEARCH_COLUMNS
    assert df[["mark_close", "oi", "bid_10k", "funding_actual"]].isna().all().all()
    assert not df["bar_missing"].any() and (df["funding"] == 0.0).all() and df["funding_is_est"].all()
    with pytest.raises(ValueError, match="volume"):
        F.prepare({BTC: raw.drop(columns="volume")}, t_last, 72, MODEL)


# ------------------------------------------------------------------- build_base
def test_build_base_matches_the_backtest_market_construction(world):
    frames = {s: df.iloc[:1000] for s, df in make_frames().items() if s in (BTC, ETH, ALTS[0])}
    world.write_universe(["2026-07"], members=[BTC, ALTS[0]])           # August and ETH are outside the universe
    t_last = frames[BTC].index[-1]
    data, _, _ = F.prepare({BTC: frames[BTC], ETH: frames[ETH], ALTS[0]: frames[ALTS[0]].iloc[:-3]}, t_last, 72, MODEL)
    t_cap = t_last - 10 * HOUR
    base = F.build_base(data, t_cap)
    assert base.index[0] == frames[BTC].index[0] and base.index[-1] == t_cap
    july = np.array(base.index.strftime("%Y-%m") == "2026-07")
    assert np.array_equal(base.arrays[BTC]["tradable"], july)
    assert not base.arrays[ETH]["tradable"].any() and base.arrays[ETH]["valid"].all()
    slip = slip_table(data)
    for s in data:
        want = slip[s].reindex(base.index).ffill().bfill().to_numpy()
        assert np.array_equal(base.arrays[s]["slip_bps"], want)
        assert np.array_equal(base.arrays[s]["funding"], data[s]["funding"].reindex(base.index).to_numpy())
    # a missing bar is never tradable, even inside the universe
    base = F.build_base(data, t_last)
    a = base.arrays[ALTS[0]]
    assert a["valid"][-3:].all() and not a["tradable"][-3:].any()
    assert store.tradable_mask(ALTS[0], base.index[:5]).all() and a["tradable"][:5].all()


# ------------------------------------------------------------------ KrakenSource
def test_kraken_source_builds_the_research_frame_with_get_requests_only(monkeypatch):
    frame = make_frames(n=120)[BTC]
    venue = FakeVenue({BTC: frame})
    venue.install(monkeypatch)
    src = F.KrakenSource()
    start, asof = frame.index[24], frame.index[96]
    df = src.bars(BTC, int(start.timestamp()), int(asof.timestamp()))
    assert df.index[0] == start and df.index[-1] == asof - HOUR and len(df) == 72
    assert list(df.columns) == RESEARCH_COLUMNS[:-2]            # everything but funding / funding_is_est
    want = frame.loc[start:asof - HOUR]
    for c in ("open", "high", "low", "close", "volume", "mark_close", "spot_close", "funding_actual", "oi",
              "liq_vol", "ls_ratio", "buy_vol", "sell_vol", "bid_10k", "ask_100k"):
        assert np.allclose(df[c].to_numpy(dtype="float64"), want[c].to_numpy(dtype="float64"), rtol=1e-12), c
    assert not df["bar_missing"].any()
    assert src.server_time() == pd.Timestamp("2026-07-05T00:07:00.123Z")
    assert venue.requests and {r["method"] for r in venue.requests} == {"GET"}
    for r in venue.requests:
        assert r["url"].startswith("https://futures.kraken.com/")
        assert set(r["kw"]) <= {"params", "timeout", "allow_redirects"}        # no body, no auth, no extra headers
        assert set(map(str.lower, r["headers"])) <= {"user-agent", "accept-encoding", "accept", "connection"}
    data, gaps, bad = F.prepare({BTC: df}, asof - HOUR, 72, MODEL)
    assert list(data[BTC].columns) == RESEARCH_COLUMNS and gaps == {} and bad == {}


def test_kraken_source_fails_the_symbol_if_any_request_failed(monkeypatch):
    frame = make_frames(n=120)[BTC]
    venue = FakeVenue({BTC: frame})
    venue.install(monkeypatch)
    src = F.KrakenSource(max_retries=1)
    start, asof = int(frame.index[24].timestamp()), int(frame.index[96].timestamp())
    for path in ("analytics/PF_XBTUSD/open-interest", "historicalfundingrates", "/mark/"):
        venue.fail_paths = (path,)
        with pytest.raises(Exception, match="request"):       # build_symbol alone would have swallowed two of these
            src.bars(BTC, start, asof)
    venue.fail_paths = ("analytics/",)                        # after the first failure nothing more is sent
    venue.requests.clear()
    with pytest.raises(Exception, match="request"):
        src.bars(BTC, start, asof)
    assert sum("analytics" in r["url"] for r in venue.requests) == 1
    venue.fail_paths = ()
    assert len(src.bars(BTC, start, asof)) == 72
    venue.empty = True
    with pytest.raises(Exception, match="no candles|empty"):
        src.bars(BTC, start, asof)
    venue.fail_paths = ("/derivatives/api/v3/",)
    assert src.server_time() is None


def test_fetch_runs_the_real_source_class_against_the_fake_venue(monkeypatch):
    frame = make_frames(n=120)[BTC]
    FakeVenue({BTC: frame}).install(monkeypatch)
    got = F.fetch(F.KrakenSource(), [BTC], frame.index[24], frame.index[96], workers=2)
    assert not got.errors and len(got.frames[BTC]) == 72
    assert got.server_time == pd.Timestamp("2026-07-05T00:07:00.123Z")
