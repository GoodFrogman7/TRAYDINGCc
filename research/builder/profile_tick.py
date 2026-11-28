"""Scratch (offline): where does one paper tick spend its time? Uses the test doubles.
Run from the repo root: PYTHONPATH=.:tests python research/builder/profile_tick.py"""
import contextlib
import io
import shutil
import tempfile
import time
from pathlib import Path

from desk.bot import feed, paper
from desk.data import store
from test_bot_fakes import World

tmp = Path(tempfile.mkdtemp())
store.DATA = tmp / "data"
store.universe.cache_clear()
w = World(tmp)
spent = {}


def timed(mod, name):
    real = getattr(mod, name)

    def wrap(*a, **k):
        t0 = time.perf_counter()
        try:
            return real(*a, **k)
        finally:
            spent[name] = spent.get(name, 0.0) + time.perf_counter() - t0
    setattr(mod, name, wrap)


for mod, name in ((feed, "fetch"), (feed, "prepare"), (feed, "build_base"), (paper, "_advance"), (paper, "_commit"),
                  (paper, "_load_book"), (paper, "_finish"), (paper, "load_config")):
    timed(mod, name)
with contextlib.redirect_stdout(io.StringIO()):
    w.tick(w.bar(2000))
    spent.clear()
    t0 = time.perf_counter()
    n = 40
    for k in range(2001, 2001 + n):
        w.tick(w.bar(k))
    total = time.perf_counter() - t0
print(f"{n} ticks: {total / n * 1000:.1f} ms each")
for name, s in sorted(spent.items(), key=lambda kv: -kv[1]):
    print(f"  {name:<12} {s / n * 1000:6.1f} ms")
shutil.rmtree(tmp, ignore_errors=True)
