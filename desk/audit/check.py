"""Design-window check for a strategy module. Shows NO validation results.

    python -m desk.audit.check s_my_idea [s_other ...]

Use this while implementing a strategy: it loads bars before 2025-01-01 only,
runs the look-ahead test, times one intents() call, validates the intent
frames, and backtests the default parameters on the design window. Whoever
writes a strategy must not see how it does on unseen data.
"""
from __future__ import annotations

import importlib
import sys
import time

import numpy as np

from ..data.store import DESIGN_END
from ..engine.core import INTENT_COLS
from ..engine.runner import load_market, run_feed, prepare
from .harness import grid_cells, leak_test


def check(name: str, market) -> bool:
    mod = importlib.import_module(f"desk.strategies.{name}")
    st = mod.STRATEGY
    ok = True
    for attr in ("name", "idea", "cause", "loser", "regime"):
        if not getattr(st, attr):
            print(f"  FAIL missing attribute: {attr}")
            ok = False
    if st.regime not in ("trending", "ranging", "wild"):
        print(f"  FAIL regime must be trending|ranging|wild, got {st.regime!r}")
        ok = False
    cells = grid_cells(st)
    t = time.time()
    it = st.intents(market.data, dict(st.params))
    dt = time.time() - t
    n_sig = 0
    for s, df in it.items():
        if list(df.columns) != INTENT_COLS and set(INTENT_COLS) - set(df.columns):
            print(f"  FAIL {s}: intent columns {list(df.columns)} != {INTENT_COLS}")
            ok = False
            break
        if not df.index.equals(market.data[s].index):
            print(f"  FAIL {s}: intent index differs from the data index")
            ok = False
            break
        side = df["side"].to_numpy()
        sig = side != 0
        n_sig += int(sig.sum())
        stop = df["stop"].to_numpy(dtype="float64")
        if np.isnan(stop[sig]).any():
            print(f"  FAIL {s}: {int(np.isnan(stop[sig]).sum())} entry signals without a stop")
            ok = False
        ref = np.where(np.isnan(df["limit"].to_numpy(dtype="float64")), market.data[s]["close"].to_numpy(),
                       df["limit"].to_numpy(dtype="float64"))
        wrong = sig & ~((ref - stop) * side > 0)
        if wrong.any():
            print(f"  FAIL {s}: {int(wrong.sum())} signals with the stop on the wrong side of the entry")
            ok = False
    lt = leak_test(st, market.data)
    if not lt["passed"]:
        print(f"  FAIL look-ahead test: {lt['mismatches']} mismatches, e.g. {lt['examples'][:2]}")
        ok = False
    r = run_feed(prepare(st, None, market), st, None, DESIGN_END)["summary"]
    print(f"  {name}: cells {len(cells)}, intents() {dt:.1f}s, raw signals {n_sig}, look-ahead test "
          f"{'pass' if lt['passed'] else 'FAIL'}")
    print(f"  design window, default params, after costs: trades {r['n_trades']}, return {r['total_return']:+.1%}, "
          f"max dd {r['max_dd']:.1%}, win {r.get('win_rate', 0):.0%}, avg R {r.get('avg_r', 0):+.2f}, "
          f"exits {r.get('exit_reasons', {})}")
    if dt > 6:
        print(f"  WARN intents() is slow ({dt:.1f}s per call x {len(cells)} cells); vectorise it")
    if r["n_trades"] == 0:
        print("  FAIL no trades on the design window")
        ok = False
    print("  RESULT:", "OK" if ok else "NOT OK")
    return ok


def main(argv: list[str] | None = None) -> int:
    names = [n.removesuffix(".py").split("/")[-1] for n in (argv if argv is not None else sys.argv[1:])]
    if not names:
        raise SystemExit(__doc__)
    market = load_market(end=DESIGN_END)      # nothing after the design window is in memory
    good = True
    for n in names:
        print(n)
        try:
            good &= check(n, market)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  RESULT: NOT OK ({type(e).__name__}: {e})")
            good = False
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
