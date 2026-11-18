"""Paper bot against REAL Kraken data, hour by hour, without waiting two days.

The window is downloaded ONCE from the live public API (plain GETs through feed.KrakenSource). The last
HOURS closed hours are then replayed as hourly ticks with the clock set back, each tick being served only
what the venue would have served then (closed bars plus the still-open one). Finally the same bars go
through ONE Engine.run, as a backtest would, and the two results are compared.

    PYTHONPATH=. python research/builder/live_replay.py CONFIG STATE_DIR [HOURS]

Paper only, no account. STATE_DIR must be a scratch directory, never state/.
"""
import json
import sys
import time
from pathlib import Path

import pandas as pd

from desk.bot import feed as F
from desk.bot import paper
from desk.bot.config import load_config, load_strategy
from desk.data import store
from desk.engine.core import Costs, Engine, attach

HOUR = pd.Timedelta(hours=1)


class Recorded:
    """Serves the downloaded frames as the venue would have at `now`."""

    def __init__(self, frames):
        self.frames, self.now = frames, None

    def server_time(self):
        return self.now

    def bars(self, symbol, start, asof):
        df = self.frames[symbol]
        lo, hi = pd.Timestamp(start, unit="s", tz="UTC"), pd.Timestamp(asof, unit="s", tz="UTC") + HOUR
        df = df[(df.index >= lo) & (df.index < hi)]
        if df.empty:
            raise RuntimeError(f"no candles for {symbol}")
        return df.copy()


def main(config, state_dir, hours=48):
    state_dir = Path(state_dir)
    assert state_dir.resolve() != Path("state").resolve(), "use a scratch state directory"
    cfg = load_config(config)
    real_now = pd.Timestamp.now(tz="UTC")
    asof = F.closed_asof(real_now, cfg.settle_seconds)
    start = asof - (cfg.window_bars + hours + 1) * HOUR
    required, context = F.symbols_needed(store.universe(), start, asof, set(), tuple(cfg.extra_symbols))
    live = F.KrakenSource()
    t0 = time.time()
    got = F.fetch(live, required + context, start, asof + HOUR)        # includes the hour that is still open
    print(f"downloaded {len(got.frames)} symbols from the live API in {time.time() - t0:.0f} s "
          f"({live.client.calls} GET requests); failed: {got.errors or 'none'}; venue clock {got.server_time}")
    src = Recorded(got.frames)
    first = asof - hours * HOUR                                         # open time of the first replayed bar
    worst = []
    for k in range(hours):
        src.now = first + (k + 1) * HOUR + pd.Timedelta(minutes=7)      # the tick 7 minutes after bar k closed
        hb = paper.tick(config, state_dir, now=src.now, source=src)
        if not hb["ok"] or hb["alerts"]["warn"]:
            worst.append((hb["tick_utc"], hb["alerts"], hb.get("error")))
    print(f"\nreplayed {hours} hourly ticks, bars {first.isoformat()} .. {(asof - HOUR).isoformat()}")
    print("ticks with warnings or critical alerts:", worst or "none")

    # the same bars through ONE engine run per book, as a backtest does it
    t_last = asof - HOUR
    data, gaps, bad = F.prepare({s: df[df.index < asof] for s, df in got.frames.items()}, t_last, cfg.delist_after_bars)
    base = F.build_base(data, t_last)
    i0 = int(base.index.get_loc(first))
    for name, book in cfg.books.items():
        if book is None:
            continue
        strat, params = load_strategy(book)
        eng = Engine(Costs(), cfg.risk, strat.valid_bars, strat.max_hold, log_events=True)
        eng.run(attach(base, strat.intents({s: df.copy() for s, df in data.items()}, params)), i0, len(base.index))
        doc = json.loads((state_dir / f"{name}.json").read_text())
        ledger = paper.read_log(state_dir, f"ledger_{name}")
        decisions = [d for d in paper.read_log(state_dir, f"decisions_{name}") if d["event"] != "book_started"]
        same_trades = [(t["symbol"], t["entry_time"], t["exit_time"], t["reason"], round(t["pnl"], 6)) for t in ledger] == \
                      [(t["symbol"], t["entry_time"], t["exit_time"], t["reason"], round(t["pnl"], 6)) for t in eng.trades]
        same_events = [(d["time"], d["symbol"], d["event"]) for d in decisions] == \
                      [(e["time"], e["symbol"], e["event"]) for e in eng.events]
        kinds = {}
        for d in decisions:
            kinds[d["event"]] = kinds.get(d["event"], 0) + 1
        print(f"\n{name} {params}: equity {doc['engine']['equity']:.2f} (one engine run: {eng.state.equity:.2f}), "
              f"{len(ledger)} closed trades, {len(doc['engine']['positions'])} open, decisions {kinds}")
        print(f"  hourly ticks == one engine run: trades {same_trades}, decisions {same_events}, "
              f"equity {abs(doc['engine']['equity'] - eng.state.equity) < 1e-6}")
        blocked = {}
        for d in decisions:
            if d["event"] in ("signal_blocked", "order_rejected", "order_cancelled"):
                blocked[(d["event"], d["reason"])] = blocked.get((d["event"], d["reason"]), 0) + 1
        for (ev, why), n in sorted(blocked.items()):
            print(f"  {ev} x{n}: {why}")
        for d in decisions[:4]:
            print("  e.g.", {k: d[k] for k in ("time", "event", "symbol", "reason")}, {k: d.get(k) for k in ("side", "limit", "stop", "price") if d.get(k) is not None})


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 48)
