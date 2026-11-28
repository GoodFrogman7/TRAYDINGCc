"""Load and validate config/bot.yaml.

The bot is PAPER ONLY: any `mode` other than `paper` is refused, and so is any
key that looks like a credential. Limits may be tightened in the file but never
loosened beyond the values the backtests used.
"""
from __future__ import annotations

import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..engine.core import Risk
from ..strategies.base import Strategy

BOOK_NAMES = ("champion", "challenger_1", "challenger_2")
STRATEGY_PREFIX = "desk.strategies."
CREDENTIAL_WORDS = ("key", "secret", "token", "password")      # no such key may appear in the config

TOP_KEYS = ("mode", "kill", "account", "champion", "challengers", "guardian", "feed")
ACCOUNT_DEFAULTS = {"equity0": 10_000.0, "risk_per_trade": 0.005}
GUARDIAN_DEFAULTS = {"daily_loss_limit": 0.03, "max_consec_losses": 3, "halt_sticky": False, "max_pos_mult": 1.0,
                     "max_gross_mult": 3.0, "max_positions": 10, "min_stop_pct": 0.002, "max_stop_pct": 0.25}
FEED_DEFAULTS = {"window_bars": 3000, "settle_seconds": 120, "extra_symbols": [], "stale_feed_minutes": 90,
                 "max_clock_skew_seconds": 30, "delist_after_bars": 72, "max_catchup_bars": 2000}
# the loosest value allowed: "max" = may not be above the default, "min" = may not be below it
TIGHTEN_ONLY = {"risk_per_trade": "max", "daily_loss_limit": "max", "max_consec_losses": "max", "max_pos_mult": "max",
                "max_gross_mult": "max", "max_positions": "max", "max_stop_pct": "max", "min_stop_pct": "min",
                # the frozen-feed rule is one of the Guardian's kill conditions, and it rests on a checked clock
                "stale_feed_minutes": "max", "max_clock_skew_seconds": "max"}
INT_KEYS = ("max_consec_losses", "max_positions", "window_bars", "stale_feed_minutes", "max_clock_skew_seconds",
            "delist_after_bars", "max_catchup_bars")


class ConfigError(ValueError):
    """The config file is missing, malformed, or asks for something the bot refuses to do."""


@dataclass(frozen=True)
class BookConfig:
    name: str            # champion | challenger_1 | challenger_2
    module: str          # desk.strategies.<module>
    params: dict         # overrides of the strategy's default parameters


@dataclass(frozen=True)
class BotConfig:
    kill: bool
    risk: Risk
    books: dict          # {book name: BookConfig | None}, keyed by BOOK_NAMES in order
    window_bars: int
    settle_seconds: int
    extra_symbols: tuple
    stale_feed_minutes: int
    max_clock_skew_seconds: int
    delist_after_bars: int
    max_catchup_bars: int


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _refuse_credentials(node, where: str) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if any(w in str(k).lower() for w in CREDENTIAL_WORDS):
                raise ConfigError(f"{where}: the key '{k}' looks like a credential. The paper bot uses only public "
                                  f"market data; credential-like keys are refused.")
            _refuse_credentials(v, f"{where}.{k}")
    elif isinstance(node, list):
        for v in node:
            _refuse_credentials(v, where)


def _section(raw: dict, name: str, defaults: dict) -> dict:
    sec = raw.get(name)
    if sec is None:
        sec = {}
    if not isinstance(sec, dict):
        raise ConfigError(f"'{name}' must be a mapping of settings")
    unknown = sorted(set(map(str, sec)) - set(defaults))
    if unknown:
        raise ConfigError(f"unknown key(s) in '{name}': {', '.join(unknown)}")
    return {**defaults, **sec}


def _number(sec: str, key: str, v, default, positive: bool = True):
    if key in INT_KEYS:
        if not isinstance(v, int) or isinstance(v, bool):
            raise ConfigError(f"{sec}.{key} must be a whole number, got {v!r}")
    elif not _is_number(v):
        raise ConfigError(f"{sec}.{key} must be a number, got {v!r}")
    if (positive and not v > 0) or v < 0:
        raise ConfigError(f"{sec}.{key} must be {'above zero' if positive else 'zero or more'}, got {v!r}")
    how = TIGHTEN_ONLY.get(key)
    if (how == "max" and v > default) or (how == "min" and v < default):
        raise ConfigError(f"{sec}.{key} = {v!r} is looser than the tested value {default!r}: limits may only be "
                          f"tightened ({'at most' if how == 'max' else 'at least'} {default!r})")
    return v


def _import_strategy(module: str) -> Strategy:
    if not isinstance(module, str) or not re.fullmatch(re.escape(STRATEGY_PREFIX) + r"[A-Za-z_][A-Za-z0-9_]*", module):
        raise ConfigError(f"strategy {module!r} must be a module directly under desk.strategies, "
                          f"e.g. desk.strategies.s_name")
    try:
        mod = importlib.import_module(module)
    except Exception as e:
        raise ConfigError(f"cannot import strategy module {module}: {type(e).__name__}: {e}") from e
    strat = getattr(mod, "STRATEGY", None)
    if not isinstance(strat, Strategy):
        raise ConfigError(f"{module} does not expose STRATEGY (a desk.strategies.base.Strategy)")
    return strat


def _book(name: str, entry) -> BookConfig | None:
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise ConfigError(f"{name} must be null or a mapping like {{strategy: desk.strategies.s_name, params: {{}}}}")
    unknown = sorted(set(map(str, entry)) - {"strategy", "params"})
    if unknown:
        raise ConfigError(f"unknown key(s) in {name}: {', '.join(unknown)}")
    if "strategy" not in entry:
        raise ConfigError(f"{name} needs a 'strategy' (a module under desk.strategies)")
    params = entry.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ConfigError(f"{name}.params must be a mapping")
    strat = _import_strategy(entry["strategy"])
    extra = sorted(set(map(str, params)) - set(strat.params))
    if extra:
        raise ConfigError(f"{name}: strategy {entry['strategy']} has no parameter(s) {', '.join(extra)} "
                          f"(it defines: {', '.join(sorted(strat.params)) or 'none'})")
    return BookConfig(name=name, module=entry["strategy"], params=dict(params))


def load_config(path="config/bot.yaml") -> BotConfig:
    path = Path(path)
    try:
        text = path.read_text()
    except FileNotFoundError as e:
        raise ConfigError(f"config file not found: {path}") from e
    except OSError as e:
        raise ConfigError(f"cannot read config file {path}: {e}") from e
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigError(f"{path} is not valid YAML: {e}") from e
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must be a mapping of settings")
    _refuse_credentials(raw, "config")
    unknown = sorted(set(map(str, raw)) - set(TOP_KEYS))
    if unknown:
        raise ConfigError(f"unknown key(s) in {path.name}: {', '.join(unknown)}")
    if "mode" not in raw:
        raise ConfigError("'mode' is required and must be 'paper'")
    if raw["mode"] != "paper":
        raise ConfigError(f"mode {raw['mode']!r} is refused: this bot only trades on paper (mode: paper)")
    kill = raw.get("kill", False)
    if not isinstance(kill, bool):
        raise ConfigError(f"kill must be true or false, got {kill!r}")

    acc = _section(raw, "account", ACCOUNT_DEFAULTS)
    grd = _section(raw, "guardian", GUARDIAN_DEFAULTS)
    fd = _section(raw, "feed", FEED_DEFAULTS)
    for k, v in acc.items():
        _number("account", k, v, ACCOUNT_DEFAULTS[k])
    if not isinstance(grd["halt_sticky"], bool):
        raise ConfigError(f"guardian.halt_sticky must be true or false, got {grd['halt_sticky']!r}")
    for k, v in grd.items():
        if k != "halt_sticky":
            _number("guardian", k, v, GUARDIAN_DEFAULTS[k])
    if not grd["min_stop_pct"] < grd["max_stop_pct"]:
        raise ConfigError("guardian.min_stop_pct must be below guardian.max_stop_pct")
    extra = fd["extra_symbols"]
    if extra is None:
        extra = []
    if not isinstance(extra, list) or not all(isinstance(s, str) and s for s in extra):
        raise ConfigError("feed.extra_symbols must be a list of symbols, e.g. [PF_SOLUSD]")
    for k, v in fd.items():
        if k != "extra_symbols":
            _number("feed", k, v, FEED_DEFAULTS[k], positive=k not in ("settle_seconds", "max_clock_skew_seconds"))

    challengers = raw.get("challengers")
    if challengers is None:
        challengers = []
    if not isinstance(challengers, list):
        raise ConfigError("challengers must be a list (at most two entries)")
    if len(challengers) > 2:
        raise ConfigError(f"at most two challengers are allowed, got {len(challengers)}")
    entries = [raw.get("champion")] + challengers + [None, None]
    books = {name: _book(name, entries[i]) for i, name in enumerate(BOOK_NAMES)}

    risk = Risk(equity0=float(acc["equity0"]), risk_per_trade=float(acc["risk_per_trade"]),
                max_pos_mult=float(grd["max_pos_mult"]), max_gross_mult=float(grd["max_gross_mult"]),
                max_positions=int(grd["max_positions"]), min_stop_pct=float(grd["min_stop_pct"]),
                max_stop_pct=float(grd["max_stop_pct"]), daily_loss_limit=float(grd["daily_loss_limit"]),
                max_consec_losses=int(grd["max_consec_losses"]), halt_sticky=bool(grd["halt_sticky"]))
    return BotConfig(kill=kill, risk=risk, books=books, window_bars=fd["window_bars"],
                     settle_seconds=fd["settle_seconds"], extra_symbols=tuple(extra),
                     stale_feed_minutes=fd["stale_feed_minutes"],
                     max_clock_skew_seconds=fd["max_clock_skew_seconds"],
                     delist_after_bars=fd["delist_after_bars"], max_catchup_bars=fd["max_catchup_bars"])


def load_strategy(book: BookConfig) -> tuple[Strategy, dict]:
    """The strategy object and its full parameter set (defaults overridden by the config)."""
    strat = _import_strategy(book.module)
    return strat, {**strat.params, **book.params}


def fingerprint(book: BookConfig, strategy: Strategy, params: dict, equity0: float) -> dict:
    """What a book was started with. Any difference retires the book and starts a fresh one."""
    return json.loads(json.dumps({
        "module": book.module, "name": strategy.name, "params": dict(params),
        "valid_bars": int(strategy.valid_bars), "max_hold": int(strategy.max_hold), "equity0": float(equity0)}))
