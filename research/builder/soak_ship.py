"""Random soak of the shipped bot on the synthetic test market (no network): hourly ticks mixed with gaps,
symbol outages longer than delist_after_bars, late bars of held symbols, bad prints, clock skew, a lost
heartbeat, kill on/off and challenger reshuffles. Looks for anything the bot did not expect of itself:
tick_error / book_error alerts, duplicate or missing equity rows, a ledger that does not add up.

    PYTHONPATH=.:tests python research/builder/soak_ship.py SCRATCH_DIR [seed] [steps]
"""
import json
import random
import shutil
import sys
from pathlib import Path

import pandas as pd

import test_bot_fakes as T
from desk.bot import paper
from desk.data import store

HOUR = pd.Timedelta(hours=1)
DON = "desk.strategies.ref_donchian"
A = {"strategy": DON, "params": {"n": 6, "atr_n": 6, "stop_atr": 1.5}}
B = {"strategy": DON, "params": {"n": 12, "atr_n": 12, "stop_atr": 2.0}}
C = {"strategy": DON, "params": {"n": 4, "atr_n": 6, "stop_atr": 1.0}}


def main(scratch, seed=1, steps=250):
    root = Path(scratch) / f"seed{seed}"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    store.DATA = root / "data"
    store.universe.cache_clear()
    w = T.World(root)
    rng = random.Random(seed)
    cfg = {"champion": "default", "challengers": [A, B], "kill": False}
    feed = {"delist_after_bars": 5}
    w.write_config(feed=feed, **cfg)
    pristine = {s: df.copy() for s, df in w.frames.items()}
    k, log, bad_codes = 400, [], {}
    for step in range(steps):
        op = rng.choice(["tick"] * 8 + ["gap", "outage", "outage_end", "late", "badprint", "skew", "lose_hb",
                                         "kill", "unkill", "shuffle", "double", "all_down"])
        k += 1
        w.source.skew = pd.Timedelta(0)
        if op == "gap":
            k += rng.randint(2, 30)
        elif op == "outage":
            w.source.fail.add(rng.choice(T.ALTS + (T.ETH,)))
        elif op == "all_down":
            w.source.fail.update(T.SYMBOLS)
        elif op == "outage_end":
            w.source.fail.clear()
        elif op == "late":
            w.source.last_bar[rng.choice(T.ALTS)] = w.bar(k - rng.randint(1, 3))
        elif op == "badprint":
            s = rng.choice(T.ALTS)
            w.frames[s].loc[w.bar(k), ["open", "high", "low", "close"]] *= rng.choice([0.1, 10.0, float("inf"), -1.0])
        elif op == "skew":
            w.source.skew = pd.Timedelta(hours=rng.choice([-3, 3, 2400]))
        elif op == "lose_hb":
            (w.state / "heartbeat.json").unlink(missing_ok=True)
        elif op == "kill":
            w.state.mkdir(exist_ok=True)
            (w.state / "KILL").write_text("x")
        elif op == "unkill":
            (w.state / "KILL").unlink(missing_ok=True)
        elif op == "shuffle":
            cfg["challengers"] = rng.choice([[A, B], [B, A], [B], [A], [B, C], [C, A], []])
            cfg["champion"] = rng.choice(["default", "default", A, None])
            w.write_config(feed=feed, **cfg)
        if op != "late" and rng.random() < 0.5:
            w.source.last_bar.clear()
        hb = w.tick(w.bar(k))
        if op == "double":
            hb = w.tick(w.bar(k), minutes=9.0)
        log.append((step, k, op, hb.get("ok"), hb.get("error")))
        for a in w.alerts():
            if a["tick_utc"] == hb["tick_utc"] and a["code"] in ("tick_error", "book_error", "state_unreadable",
                                                               "log_rollback", "state_too_old"):
                bad_codes.setdefault(a["code"], []).append((step, k, op, a["message"][:300]))
    # settle: everything healthy again, three clean ticks
    w.source.fail.clear(); w.source.last_bar.clear(); w.source.skew = pd.Timedelta(0)
    (w.state / "KILL").unlink(missing_ok=True)
    for _ in range(3):
        k += 1
        hb = w.tick(w.bar(k))
    print(f"seed {seed}: {steps} steps, last bar index {k}, final ok={hb['ok']} feed={hb['feed']['usable']}")
    print("  unexpected alerts:", {c: len(v) for c, v in bad_codes.items()} or "none")
    for c, v in bad_codes.items():
        for row in v[:3]:
            print("   ", c, row)
    counts = {}
    for a in w.alerts():
        counts[a["code"]] = counts.get(a["code"], 0) + 1
    print("  all alerts:", dict(sorted(counts.items())))
    # invariants per live book and per archived book
    dirs = [w.state] + sorted(p for p in (w.state / "archive").glob("*") if p.is_dir() and p.name != "rotated")
    checked = 0
    for d in dirs:
        for sf in sorted(d.glob("ch*.json")):
            doc = json.loads(sf.read_text())
            name = doc["book"]
            eqf = d / f"equity_{name}.csv"
            if not eqf.exists():
                continue
            eq = pd.read_csv(eqf)
            times = pd.to_datetime(eq["time"], utc=True)
            assert times.is_unique, (d, name, "duplicate equity rows")
            assert (times.diff().dropna() == HOUR).all(), (d, name, "gap in equity rows")
            led = T.read_jsonl(d / f"ledger_{name}.jsonl")
            keys = [(t["symbol"], t["entry_time"], t["exit_time"]) for t in led]
            assert len(keys) == len(set(keys)), (d, name, "duplicate trades")
            st = doc["engine"]
            if not st["positions"]:
                realised = sum(t["pnl"] for t in led)
                assert abs(doc["strategy"]["equity0"] + realised - st["equity"]) < 1e-6, (d, name, "ledger != equity",
                                                                                           realised, st["equity"])
            assert abs(float(eq["equity"].iloc[-1]) - st["equity"]) < 1e-6, (d, name, "last equity row != state")
            assert doc["engine"]["last_time"] == eq["time"].iloc[-1], (d, name, "last row is not last_time")
            checked += 1
    print(f"  invariants hold for {checked} book(s) (live + archived); live books:",
          {n: (b["status"], b["positions"], b["halted"]) for n, b in hb["books"].items()})


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1, int(sys.argv[3]) if len(sys.argv) > 3 else 250)
