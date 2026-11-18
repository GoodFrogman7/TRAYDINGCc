"""PAPER ONLY: nothing under desk/bot can place an order or carry a credential, and the only
network traffic is unauthenticated GET requests to the venue's public market-data API."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pandas as pd
import pytest
import yaml

from desk.bot import config as C
from desk.bot import feed as F
from desk.bot import paper
from desk.data import store
from test_bot_fakes import BTC, ETH, FakeVenue, HOUR, PARAMS, World, make_frames, no_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("no_network")
ROOT = Path(__file__).resolve().parents[1]
BOT = sorted((ROOT / "desk" / "bot").glob("*.py"))
WORKFLOW = ROOT / ".github" / "workflows" / "paper-bot.yml"

# anything that places, changes or cancels a real order, moves money, or signs a request
ORDER_WORDS = r"send_?order|edit_?order|cancel_?order|cancel_?all|batch_?order|place_?order|create_?order|" \
              r"new_?order|withdraw|transfer|leverage_?preferences|/api/v3/orders"
AUTH_WORDS = r"api[_-]?key|api[_-]?sec|authent|authoriz|nonce|hmac|signature|bearer|private|" \
             r"environ|getenv|keyring|dotenv|\.netrc"
WRITE_VERBS = r"\.post\(|\.put\(|\.delete\(|\.patch\(|\.request\(|method\s*=|urlopen|http\.client|httpx|aiohttp|" \
              r"websocket|socket\."
SECRET_WORDS = r"secret|token|password|passwd"
ALLOWED_IMPORTS = {"__future__", "argparse", "concurrent", "dataclasses", "importlib", "io", "json", "math", "os",
                   "pathlib", "re", "time", "traceback", "numpy", "pandas", "yaml"}
PUBLIC_PATHS = re.compile(r"/api/charts/v1/(trade|mark|spot)/PF_[A-Z0-9]+USD/1h"
                          r"|/api/charts/v1/analytics/PF_[A-Z0-9]+USD/[a-z-]+"
                          r"|/derivatives/api/v4/historicalfundingrates"
                          r"|/derivatives/api/v3/(tickers|instruments)")


def test_the_bot_package_has_the_five_modules_of_the_spec():
    assert [p.name for p in BOT] == ["__init__.py", "config.py", "feed.py", "guardian.py", "paper.py", "report.py"]


@pytest.mark.parametrize("path", BOT, ids=lambda p: p.name)
def test_no_order_or_credential_strings_in_the_bot(path):
    text = path.read_text()
    for pattern in (ORDER_WORDS, AUTH_WORDS, WRITE_VERBS):
        hit = re.search(pattern, text, flags=re.IGNORECASE)
        assert hit is None, f"{path.name} contains {hit.group(0)!r}"
    # the words for credentials appear exactly once in the whole package: in the list of config keys to REFUSE
    for n, line in enumerate(text.splitlines(), 1):
        if re.search(SECRET_WORDS, line, flags=re.IGNORECASE):
            assert path.name == "config.py" and line.startswith("CREDENTIAL_WORDS = "), f"{path.name}:{n}: {line}"


@pytest.mark.parametrize("path", BOT, ids=lambda p: p.name)
def test_the_bot_imports_no_network_library(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:                      # relative: inside desk
                continue
            names = [node.module]
        else:
            continue
        for name in names:
            assert name.split(".")[0] in ALLOWED_IMPORTS, f"{path.name} imports {name}"


def test_only_feed_reaches_the_market_data_client():
    users = [p.name for p in BOT if "KrakenFutures" in p.read_text()]
    assert users == ["feed.py"]
    assert sorted(n for n in vars(F.KrakenSource) if not n.startswith("_")) == ["bars", "server_time"]


def test_the_market_data_client_only_knows_get():
    text = (ROOT / "desk" / "data" / "kraken.py").read_text()
    assert ".get(url" in text
    for pattern in (ORDER_WORDS, WRITE_VERBS, r"api[_-]?key|\bauthent\b|authoriz|hmac|nonce|signature"):
        assert re.search(pattern, text, flags=re.IGNORECASE) is None, pattern
    assert re.findall(r"headers\[[^\]]+\]", text) == ['headers["User-Agent"]']        # the only header it sets


def test_live_mode_is_refused_and_processes_nothing(tmp_path):
    cfg = tmp_path / "bot.yaml"
    for mode in ("live", "real", "Paper", "paper-live", ""):
        cfg.write_text(f"mode: {mode}\n")
        with pytest.raises(C.ConfigError):
            C.load_config(cfg)

    class NeverAsked:
        def server_time(self):
            raise AssertionError("a refused config must not reach the venue")
        bars = server_time

    cfg.write_text("mode: live\nchampion: {strategy: desk.strategies.ref_donchian}\n")
    hb = paper.tick(cfg, tmp_path / "state", now=pd.Timestamp("2026-11-18 14:07", tz="UTC"), source=NeverAsked())
    assert hb["ok"] is False and hb["mode"] == "paper" and hb["books"] == {}
    assert sorted(p.name for p in (tmp_path / "state").iterdir()) == ["alerts.jsonl", "heartbeat.json"]


def test_shipped_config_is_paper_with_no_strategy_and_no_credentials():
    raw = yaml.safe_load((ROOT / "config" / "bot.yaml").read_text())
    assert raw["mode"] == "paper" and raw["kill"] is False
    assert raw["champion"] is None and raw["challengers"] == []
    assert not re.search(SECRET_WORDS + "|" + AUTH_WORDS, (ROOT / "config" / "bot.yaml").read_text(),
                         flags=re.IGNORECASE)
    C.load_config(ROOT / "config" / "bot.yaml")


def test_a_whole_tick_with_the_real_source_sends_only_public_get_requests(tmp_path, monkeypatch):
    """The live code path end to end (KrakenSource -> KrakenFutures -> requests), against a fake venue."""
    monkeypatch.setattr(store, "DATA", tmp_path / "data")
    try:
        w = World(tmp_path, window=60)
        w.write_universe(["2026-07"], members=[BTC, ETH])
        w.write_config(champion={"strategy": "desk.strategies.ref_donchian", "params": PARAMS})
        frames = {s: df.iloc[:200] for s, df in make_frames(n=200).items() if s in (BTC, ETH)}
        venue = FakeVenue(frames)
        venue.install(monkeypatch)
        hbs = []
        for k in (150, 151, 152):
            now = w.bar(k) + HOUR + pd.Timedelta(minutes=7)
            venue.server_time = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            hbs.append(paper.tick(w.config, w.state, now=now))                 # no source given: the real one
    finally:
        store.universe.cache_clear()
    assert all(hb["ok"] and hb["feed"]["usable"] and hb["feed"]["symbols"] == 2 for hb in hbs), hbs[-1]
    assert hbs[-1]["books"]["champion"]["status"] == "ok" and hbs[-1]["books"]["champion"]["lag_bars"] == 0
    assert hbs[-1]["feed"]["feed_time"] == w.bar(152).isoformat()
    assert len(venue.requests) > 30
    for r in venue.requests:
        assert r["method"] == "GET"
        assert r["url"].startswith("https://futures.kraken.com/")
        assert PUBLIC_PATHS.fullmatch(r["url"].replace("https://futures.kraken.com", "")), r["url"]
        assert set(r["kw"]) <= {"params", "timeout", "allow_redirects"}        # no body, no extra headers
        assert set(map(str.lower, r["headers"])) <= {"user-agent", "accept-encoding", "accept", "connection"}
        assert set(r["params"]) <= {"from", "to", "since", "interval", "symbol"}


def test_the_workflow_uses_no_credentials_and_cannot_overlap():
    text = WORKFLOW.read_text()
    assert not re.search(SECRET_WORDS + "|" + ORDER_WORDS + r"|api[_-]?key|\benv:", text, flags=re.IGNORECASE)
    wf = yaml.safe_load(text)
    on = wf.get("on", wf.get(True))                  # YAML reads the bare word `on` as true
    assert on["schedule"] == [{"cron": "7 * * * *"}] and "workflow_dispatch" in on
    assert wf["concurrency"] == {"group": "paper-bot", "cancel-in-progress": False}
    steps = wf["jobs"]["tick"]["steps"]
    runs = [s.get("run", "") for s in steps]
    tick = next(i for i, r in enumerate(runs) if "desk.bot.paper tick" in r)
    assert "if" not in steps[tick] and "continue-on-error" not in steps[tick]   # a failed tick fails the job
    later = steps[tick + 1:]
    assert len(later) == 2 and all(s.get("if") == "always()" for s in later)    # report and save even after a failure
    assert "desk.bot.report" in later[0]["run"] and "state/report.md" in later[0]["run"]
    assert "*.lock" in later[1]["run"] and "*.tmp" in later[1]["run"] and "bot-state" in later[1]["run"]
    assert any(s.get("with", {}).get("ref") == "bot-state" and s["with"].get("path") == "state" for s in steps)
    assert any("requirements.txt" in r for r in runs)
