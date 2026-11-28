"""Scratch check (offline): the engine mechanisms the bot spec leans on behave as the spec says.
Run from the repo root: PYTHONPATH=. python research/builder/probe_engine_hooks.py"""
import dataclasses
import json

import numpy as np
import pandas as pd

from desk.engine.core import Costs, Engine, Risk, State, attach, blank_intents, make_base

idx = pd.date_range("2026-10-01", periods=60, freq="h", tz="UTC", name="time")
px = 100 + np.arange(60) * 0.1
df = pd.DataFrame({"open": px, "high": px + 0.5, "low": px - 0.5, "close": px + 0.05, "funding": 0.0}, index=idx)
it = blank_intents(idx)
it.loc[idx[0], ["side", "stop"]] = [1, 90.0]
it.loc[idx[30], ["side", "limit", "stop"]] = [1, 50.0, 40.0]           # a resting limit that never fills
base = make_base({"X": df}, slip_bps=2.0)
feed = attach(base, {"X": it})


def reload(e):
    return State.from_json(json.loads(json.dumps(e.state.to_json())))


# 1. flatten for a strategy swap: exit_pending + one bar of blank intents -> engine sells at that bar's open
e = Engine(Costs(), Risk(), log_events=True); e.run(feed, 0, 5)
st = reload(e)
for p in st.positions.values():
    p.exit_pending = "strategy_swap"
e2 = Engine(Costs(), Risk(), state=st, log_events=True); e2.run(attach(base, {}), 5, 6)
print("swap:", e2.trades[0]["reason"], e2.trades[0]["exit_time"], "flat:", not e2.state.positions)

# 2. manual kill: _halt cancels orders and flags exits; halt_sticky keeps it across a UTC day; resume() clears it
e = Engine(Costs(), Risk(), valid_bars=50, log_events=True); e.run(feed, 0, 32)
st = reload(e); print("before kill: positions", list(st.positions), "orders", list(st.orders))
k = Engine(Costs(), dataclasses.replace(Risk(), halt_sticky=True), state=st, log_events=True)
k._halt("manual kill", st.last_time, 0)
k.run(feed, 32, 60)                                                       # crosses midnight twice
print("killed:", [ev["event"] for ev in k.events], "| halted after 2 day changes:", k.state.halted,
      "| exit reason:", k.trades[0]["reason"], "| positions", list(k.state.positions))
k.resume(); print("resumed:", not k.state.halted)

# 3. frozen-feed halt is not sticky: entries come back on the first bar of a UTC day after halt_day
e = Engine(Costs(), Risk(), state=reload(e), log_events=True)
day = int(idx[32].timestamp() // 86400)
e._halt("frozen data feed", e.state.last_time, day); e.run(feed, 32, 60)
print("frozen: halted at end", e.state.halted, "| halt_day", day, "| last bar day", int(idx[59].timestamp() // 86400))

# 4. a held symbol with an invalid bar is closed as delisted; a held symbol absent from the feed is a KeyError
e = Engine(Costs(), Risk(), log_events=True); e.run(feed, 0, 5)
other = df.copy(); short = df.iloc[:5]
e3 = Engine(Costs(), Risk(), state=reload(e)); e3.run(attach(make_base({"X": short, "Y": other}, slip_bps=2.0), {}), 5, 6)
print("invalid bar:", e3.trades[0]["reason"])
try:
    Engine(Costs(), Risk(), state=reload(e)).run(attach(make_base({"Y": other}, slip_bps=2.0), {}), 5, 6)
except KeyError as err:
    print("absent symbol: KeyError", err)
print("event with NaN:", json.dumps([ev for ev in k.events + e.events if ev["event"] == "order_cancelled"][:1]),
      "| order_created has reason:", any("reason" in ev for ev in Engine(Costs(), Risk(), log_events=True).events))
ev = Engine(Costs(), Risk(), log_events=True); ev.run(feed, 0, 2)
print("order_created event:", ev.events[0])
try:
    json.dumps(ev.events[0], allow_nan=False)
except ValueError as err:
    print("strict JSON refuses engine event:", err)
