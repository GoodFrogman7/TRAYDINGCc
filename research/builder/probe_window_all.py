"""Scratch check (offline, read-only): which registered strategies decide the same on the bot's window
(feed.window_bars, bot symbol set) as on full history? Same comparison as tests/test_bot_window.py,
evaluated at the end of VALIDATION under store.ceiling (the holdout is never read).
Run from the repo root: PYTHONPATH=.:tests python research/builder/probe_window_all.py [window_bars ...]"""
import sys

from desk.data import store
from desk.strategies.base import registry
from test_bot_window import bot_window, compare_intents

windows = [int(a) for a in sys.argv[1:]] or [3000]
asof = store.VALIDATION_END
with store.ceiling(asof):
    full = store.load_all()
    for wb in windows:
        window = bot_window(full, store.universe(), asof, wb)
        print(f"window_bars={wb}: {len(window)} symbols in the bot set, {len(full)} in the dataset")
        for name, strat in sorted(registry().items()):
            p = dict(strat.params)
            try:
                problems = compare_intents(strat.intents({s: df.copy() for s, df in window.items()}, p),
                                           strat.intents(full, p))
            except Exception as e:
                problems = [f"raised {type(e).__name__}: {e}"]
            print(f"  {'OK  ' if not problems else 'DIFF'} {name:<34} needs={strat.needs}"
                  + ("" if not problems else f"  {len(problems)} problem(s), e.g. {problems[0]}"))
