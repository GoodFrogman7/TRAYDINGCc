"""What the paper bot did: a 24-hour (or weekly) summary, the promotion check, paper next to backtest.

    python -m desk.bot.report [--state state] [--hours 24] [--json]      # --hours 168 = weekly

Read-only: it reads the state directory and research/results, and changes nothing.
The promotion check only flags a challenger; a person edits config/bot.yaml.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pandas as pd

from . import paper
from .config import BOOK_NAMES
from .feed import HOUR, utc
from .guardian import to_jsonable
from .paper import STATE

BACKTEST_WINDOWS = ("wf_validation", "default_validation")     # first one present in the results file is shown


def _load_book(state_dir: Path, name: str):
    """(engine state, fingerprint, started_bar) or None if the book has no readable state file."""
    try:
        st, fp, started, _ = paper._parse_state(Path(state_dir) / f"{name}.json", name)
        return st, fp, started
    except Exception:
        return None


def _equity(state_dir: Path, name: str) -> pd.Series:
    """The book's committed equity rows as a series indexed by bar time."""
    raw = paper.read_committed(state_dir, "equity", name)
    if not raw.strip():
        return pd.Series(dtype="float64")
    df = pd.read_csv(io.BytesIO(raw))
    s = pd.Series(df["equity"].to_numpy(dtype="float64"), index=pd.to_datetime(df["time"], utc=True))
    return s[~s.index.duplicated(keep="last")].sort_index()


def _pnl_since(eq: pd.Series, equity0: float, start: pd.Timestamp) -> float:
    """Change in equity from bar `start` (or from the book's own start, if later) to its last row."""
    if eq.empty:
        return 0.0
    before = eq[eq.index <= start]
    return float(eq.iloc[-1] - (before.iloc[-1] if len(before) else equity0))


def _winning_days(eq: pd.Series, equity0: float, now: pd.Timestamp) -> tuple[int, int]:
    """(winning days, finished days): a UTC day wins when its last equity is above the previous day's."""
    done = eq[eq.index < now.floor("D")]
    if done.empty:
        return 0, 0
    closes = done.groupby(done.index.floor("D")).last()
    prev = closes.shift(1)
    prev.iloc[0] = equity0
    return int((closes > prev).sum()), int(len(closes))


def promotion(state_dir=STATE, days: int = 7, now=None) -> dict:
    """Is a challenger ready to replace the champion? Ready = at least `days` winning days, P&L since its
    start above zero, and that P&L above the champion's over the same days."""
    state_dir = Path(state_dir)
    now = paper._now() if now is None else utc(now)
    champ = _load_book(state_dir, "champion")
    champ_eq = _equity(state_dir, "champion") if champ else pd.Series(dtype="float64")
    out = {"days_required": days, "champion": None, "challengers": {}}
    if champ:
        st, fp, started = champ
        out["champion"] = {"strategy": fp["name"], "started_bar": started,
                           "pnl": float(st.equity - fp["equity0"])}
    for name in BOOK_NAMES[1:]:
        book = _load_book(state_dir, name)
        if not book:
            continue
        st, fp, started = book
        eq = _equity(state_dir, name)
        won, n = _winning_days(eq, fp["equity0"], now)
        pnl = float(st.equity - fp["equity0"])
        champ_pnl = _pnl_since(champ_eq, champ[1]["equity0"], utc(started)) if champ else 0.0
        if won < days:
            why = f"{won} of {days} winning days so far"
        elif not pnl > 0:
            why = f"{won} winning days, but its P&L since start is not positive ({pnl:+,.2f})"
        elif not pnl > champ_pnl:
            why = f"{won} winning days, but its P&L ({pnl:+,.2f}) does not beat the champion's over the same days " \
                  f"({champ_pnl:+,.2f})"
        else:
            why = f"{won} winning days and P&L {pnl:+,.2f} against the champion's {champ_pnl:+,.2f}: " \
                  f"ready to be considered for promotion"
        out["challengers"][name] = {
            "strategy": fp["name"], "started_bar": started, "days": n, "winning_days": won, "pnl": pnl,
            "champion_pnl_same_days": champ_pnl, "ready": won >= days and pnl > 0 and pnl > champ_pnl, "why": why}
    return out


def _backtest(results_dir: Path, fp: dict) -> dict | None:
    """The audit's out-of-sample numbers for this strategy, from research/results/<strategy>.json."""
    for stem in (fp["name"], fp["module"].rsplit(".", 1)[-1]):
        path = Path(results_dir) / f"{stem}.json"
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        for window in BACKTEST_WINDOWS:
            w = doc.get(window) if isinstance(doc, dict) else None
            if isinstance(w, dict) and w.get("years"):
                days = float(w["years"]) * 365.25
                audited = doc.get("default_params")       # what the audit ran; None if the file does not say
                return {"file": str(path), "window": window, "years": w["years"],
                        "same_params": audited == fp["params"] if isinstance(audited, dict) else None,
                        "total_return": w.get("total_return"), "trades": w.get("n_trades"),
                        "return_per_day": (w.get("total_return") or 0.0) / days,
                        "trades_per_day": (w.get("n_trades") or 0) / days,
                        "win_rate": w.get("win_rate"), "avg_r": w.get("avg_r"), "max_dd": w.get("max_dd")}
    return None


def _book_report(state_dir: Path, name: str, since: pd.Timestamp, results_dir: Path) -> dict | None:
    book = _load_book(state_dir, name)
    if not book:
        return None
    st, fp, started = book
    equity0 = float(fp["equity0"])
    eq = _equity(state_dir, name)
    closed_by_then = eq[eq.index + HOUR <= since]              # bar time is the open; equity is marked at the close
    base = float(closed_by_then.iloc[-1]) if len(closed_by_then) else equity0
    all_trades = paper.read_log(state_dir, f"ledger_{name}")
    trades = [t for t in all_trades if utc(t["exit_time"]) >= since]
    decisions: dict[str, int] = {}
    refused: dict[str, int] = {}
    for d in paper.read_log(state_dir, f"decisions_{name}", since):
        decisions[d["event"]] = decisions.get(d["event"], 0) + 1
        if d["event"] in ("signal_blocked", "order_rejected"):
            refused[d["reason"]] = refused.get(d["reason"], 0) + 1
    days = 0.0
    if len(eq):
        days = float((eq.index[-1] + HOUR - utc(started)) / pd.Timedelta(days=1))
    dd = float(((eq - eq.cummax().clip(lower=equity0)) / equity0).min()) if len(eq) else 0.0
    total_return = float(st.equity - equity0) / equity0
    return {
        "strategy": fp["name"], "module": fp["module"], "params": fp["params"], "started_bar": started,
        "last_bar": st.last_time or None, "equity0": equity0, "equity": float(st.equity),
        "pnl_total": float(st.equity - equity0), "pnl_period": float(st.equity - base),
        "halted": bool(st.halted), "halt_reason": st.halt_reason,
        "trades": [{"exit_time": t["exit_time"], "entry_time": t["entry_time"], "symbol": t["symbol"],
                    "side": t["side"], "pnl": t["pnl"], "r": t["r"], "reason": t["reason"]} for t in trades],
        "trades_pnl": float(sum(t["pnl"] for t in trades)), "trades_won": sum(t["pnl"] > 0 for t in trades),
        "positions": [{"symbol": p.symbol, "side": p.side, "qty": p.qty, "entry_price": p.entry_price,
                       "entry_time": p.entry_time, "stop": p.stop, "last_price": p.last_price,
                       "unrealised": p.side * p.qty * (p.last_price - p.entry_price),
                       "closing": p.exit_pending} for p in st.positions.values()],
        "orders": [{"symbol": o.symbol, "side": o.side, "limit": o.limit, "stop": o.stop, "created": o.created}
                   for o in st.orders.values()],
        "decisions": decisions, "refused": refused,
        "paper": {"days": days, "total_return": total_return,
                  "return_per_day": total_return / days if days > 0 else 0.0,
                  "trades": len(all_trades), "trades_per_day": len(all_trades) / days if days > 0 else 0.0,
                  "win_rate": sum(t["pnl"] > 0 for t in all_trades) / len(all_trades) if all_trades else None,
                  "avg_r": sum(t["r"] for t in all_trades) / len(all_trades) if all_trades else None,
                  "max_dd": dd},
        "backtest": _backtest(results_dir, fp),
    }


def build_report(state_dir=STATE, hours: int = 24, now=None, results_dir="research/results") -> dict:
    """Everything the report shows, as one strict-JSON dict."""
    state_dir = Path(state_dir)
    now = paper._now() if now is None else utc(now)
    since = now - pd.Timedelta(hours=hours)
    st = paper.status(state_dir, now=now)
    hb = st["heartbeat"] or {}
    alerts: dict[str, dict] = {}
    for a in paper.read_log(state_dir, "alerts", since):
        g = alerts.setdefault(a.get("code", "?"), {"level": a.get("level"), "count": 0, "last_utc": None,
                                                   "last_message": None})
        g["count"] += 1
        g["level"], g["last_utc"], g["last_message"] = a.get("level"), a.get("tick_utc"), a.get("message")
    return to_jsonable({
        "generated_utc": now.isoformat(), "hours": hours, "since_utc": since.isoformat(), "mode": "paper",
        "health": {"healthy": st["healthy"], "why": st["why"], "trading": st["trading"],
                   "last_tick_utc": hb.get("tick_utc"),
                   "killed": bool(hb.get("killed")), "feed": hb.get("feed")},
        "books": {name: _book_report(state_dir, name, since, Path(results_dir)) for name in BOOK_NAMES},
        "alerts": alerts,
        "promotion": promotion(state_dir, now=now),
    })


# ------------------------------------------------------------------------ render
def _usd(x) -> str:
    return "n/a" if x is None else f"{x:+,.2f}"


def _pct(x, digits: int = 2) -> str:
    return "n/a" if x is None else f"{100 * x:+.{digits}f}%"


def _side(x) -> str:
    return "long" if x > 0 else "short"


def _book_text(name: str, b: dict | None, hours: int) -> list[str]:
    if b is None:
        return [f"### {name}: no book", ""]
    role = "the bot's trades" if name == "champion" else "shadow book, not the bot's trades"
    out = [f"### {name}: {b['strategy']} ({role})",
           f"- Running since bar {b['started_bar']}; last bar {b['last_bar'] or 'n/a'}.",
           f"- Equity ${b['equity']:,.2f} (started with ${b['equity0']:,.2f}). "
           f"P&L last {hours} hours: {_usd(b['pnl_period'])}. P&L since start: {_usd(b['pnl_total'])}."]
    if b["halted"]:
        out.append(f"- **HALTED by the Guardian: {b['halt_reason']}.** No new entries while halted.")
    out.append(f"- Closed trades in the last {hours} hours: {len(b['trades'])} "
               f"({b['trades_won']} won), together {_usd(b['trades_pnl'])}.")
    for t in b["trades"][-30:]:
        out.append(f"    - {t['exit_time'][:16]} {t['symbol']} {_side(t['side'])}: {_usd(t['pnl'])} "
                   f"({t['r']:+.2f} R), closed by: {t['reason']}")
    if len(b["trades"]) > 30:
        out.append(f"    - ... and {len(b['trades']) - 30} earlier ones (see ledger_{name}.jsonl)")
    if b["positions"]:
        out.append(f"- Open positions: {len(b['positions'])}")
        for p in b["positions"]:
            note = f", being closed ({p['closing']})" if p["closing"] else ""
            out.append(f"    - {p['symbol']} {_side(p['side'])} since {p['entry_time'][:16]}: entry {p['entry_price']:.6g}, "
                       f"stop {p['stop']:.6g}, last {p['last_price']:.6g}, unrealised {_usd(p['unrealised'])}{note}")
    else:
        out.append("- Open positions: none")
    if b["orders"]:
        out.append("- Orders waiting: " + ", ".join(
            f"{o['symbol']} {_side(o['side'])} " + ("at market" if o["limit"] is None else f"limit {o['limit']:.6g}")
            + f" with stop {o['stop']:.6g}" for o in b["orders"]))
    if b["decisions"]:
        out.append("- Decisions logged: " + ", ".join(f"{k} {v}" for k, v in sorted(b["decisions"].items())))
    for why, n in sorted(b["refused"].items(), key=lambda kv: -kv[1]):
        out.append(f"    - refused {n}x: {why}")
    p, bt = b["paper"], b["backtest"]
    out.append(f"- Paper so far: {p['days']:.1f} days, return {_pct(p['total_return'])} "
               f"({_pct(p['return_per_day'], 3)} per day), {p['trades']} trades ({p['trades_per_day']:.2f} per day), "
               f"win rate {_pct(p['win_rate'], 0).lstrip('+')}, average {_r(p['avg_r'])}, "
               f"worst drawdown {_pct(p['max_dd'])}.")
    if bt:
        label = ("Same strategy in the backtest" if bt.get("same_params") is not False else
                 "The backtest of this strategy used OTHER parameters than this book, so it is only a rough guide")
        out.append(f"- {label} ({bt['window']}, {bt['years']} years): return "
                   f"{_pct(bt['total_return'])} ({_pct(bt['return_per_day'], 3)} per day), {bt['trades']} trades "
                   f"({bt['trades_per_day']:.2f} per day), win rate {_pct(bt['win_rate'], 0).lstrip('+')}, "
                   f"average {_r(bt['avg_r'])}, worst drawdown {_pct(bt['max_dd'])}. "
                   f"A few days of paper trading cannot confirm or refute this yet.")
    else:
        out.append(f"- No backtest file for {b['strategy']} in research/results: nothing to compare against.")
    return out + [""]


def _r(x) -> str:
    return "n/a" if x is None else f"{x:+.2f} R per trade"


def render(report: dict) -> str:
    """The report as plain Markdown text."""
    h, hours = report["health"], report["hours"]
    out = [f"# Paper bot report: last {hours} hours",
           f"Generated {report['generated_utc'][:16]} UTC. **PAPER TRADING ONLY: no real orders, no real money.**", "",
           "## Health",
           f"- **{'HEALTHY' if h['healthy'] else 'NOT HEALTHY'}**: {h['why']}",
           f"- **Trading**: {h.get('trading') or 'nothing'}",
           f"- Last tick: {h['last_tick_utc'] or 'never'}"]
    feed = h.get("feed") or {}
    if feed:
        out.append(f"- Market data: newest bar {feed.get('feed_time') or 'none yet'}"
                   + (", FROZEN" if feed.get("frozen") else "") + ("" if feed.get("usable") else ", not usable on the last tick"))
    if h["killed"]:
        out.append("- **KILL SWITCH IS ON**: orders cancelled, positions closed, no new entries until it is released.")
    out += ["", "## Books"]
    for name in BOOK_NAMES:
        out += _book_text(name, report["books"].get(name), hours)
    out.append(f"## Alerts in the last {hours} hours")
    if not report["alerts"]:
        out.append("- none")
    order = {"critical": 0, "warn": 1, "info": 2}
    for code, a in sorted(report["alerts"].items(), key=lambda kv: (order.get(kv[1]["level"], 3), kv[0])):
        out.append(f"- {a['level']} `{code}` x{a['count']}, last at {(a['last_utc'] or '')[:16]}: {a['last_message']}")
    promo = report["promotion"]
    out += ["", f"## Promotion check ({promo['days_required']} winning days needed)"]
    if not promo["challengers"]:
        out.append("- no challenger books yet")
    for name, c in promo["challengers"].items():
        out.append(f"- {name} ({c['strategy']}): **{'READY' if c['ready'] else 'not ready'}**. {c['why']}.")
    if any(c["ready"] for c in promo["challengers"].values()):
        out.append("- Promotion is never automatic: a person edits config/bot.yaml (see docs/RUNBOOK.md).")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m desk.bot.report", description="Paper bot report (read-only).")
    ap.add_argument("--state", default=STATE, help="state directory (default: state)")
    ap.add_argument("--hours", type=int, default=24, help="look-back in hours (default 24; 168 = weekly)")
    ap.add_argument("--results", default="research/results", help="audit results directory")
    ap.add_argument("--json", action="store_true", help="print the raw report as JSON")
    args = ap.parse_args(argv)
    rep = build_report(args.state, hours=args.hours, results_dir=args.results)
    print(json.dumps(rep, indent=1, allow_nan=False) if args.json else render(rep), end="" if not args.json else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
