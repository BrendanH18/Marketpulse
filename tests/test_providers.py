"""Alpha Vantage as the fallback provider, against a fake transport that copies its replies
(fictional prices, a made-up key). Also: the key never leaves the engine."""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.config import Config
from marketpulse.desktop import snapshot
from marketpulse.market import FALLBACK_AFTER, MarketData, MarketError
from marketpulse.providers import ALPHA_VANTAGE_URL, AlphaVantage, make_fallback, provider_label, redact

KEY = "FICTIONALKEY123"


class FakeAlphaVantage:
    """Speaks Alpha Vantage's GLOBAL_QUOTE and CURRENCY_EXCHANGE_RATE replies (always HTTP 200)."""

    def __init__(self) -> None:
        self.quotes: dict[str, dict] = {}
        self.rates: dict[tuple[str, str], str] = {}
        self.refusal: dict | None = None
        self.raise_error: str | None = None
        self.calls: list[dict] = []

    def set_quote(self, av_symbol: str, price: str, prev: str, day: str = "2026-11-04") -> None:
        self.quotes[av_symbol] = {
            "01. symbol": av_symbol,
            "02. open": prev,
            "03. high": price,
            "04. low": prev,
            "05. price": price,
            "06. volume": "797346",
            "07. latest trading day": day,
            "08. previous close": prev,
            "09. change": "0.7500",
            "10. change percent": "1.6797%",
        }

    def get_json(self, url, params):
        assert url == ALPHA_VANTAGE_URL
        self.calls.append(dict(params))
        if self.raise_error:
            raise MarketError(self.raise_error)
        if self.refusal:
            return self.refusal
        if params["function"] == "GLOBAL_QUOTE":
            return {"Global Quote": self.quotes.get(params["symbol"], {})}
        if params["function"] == "CURRENCY_EXCHANGE_RATE":
            pair = (params["from_currency"], params["to_currency"])
            if pair not in self.rates:
                return {"Error Message": "Invalid API call."}
            return {
                "Realtime Currency Exchange Rate": {
                    "1. From_Currency Code": pair[0],
                    "2. From_Currency Name": "Fictional",
                    "3. To_Currency Code": pair[1],
                    "4. To_Currency Name": "Fictional",
                    "5. Exchange Rate": self.rates[pair],
                    "6. Last Refreshed": "2026-11-05 21:06:50",
                    "7. Time Zone": "UTC",
                    "8. Bid Price": self.rates[pair],
                    "9. Ask Price": self.rates[pair],
                }
            }
        raise AssertionError(f"unexpected function {params['function']}")


@pytest.fixture
def av() -> FakeAlphaVantage:
    t = FakeAlphaVantage()
    t.set_quote("XEQT.TRT", "45.4000", "44.6500")
    t.set_quote("AAPL", "201.5000", "199.0000")
    t.rates[("USD", "CAD")] = "1.39770000"
    t.rates[("BTC", "USD")] = "70000.00"
    return t


def test_listing_symbols_map_from_yahoo():
    assert AlphaVantage.listing("XEQT.TO") == ("XEQT.TRT", "CAD")
    assert AlphaVantage.listing("ABC.V") == ("ABC.TRV", "CAD")
    assert AlphaVantage.listing("AAPL") == ("AAPL", "USD")
    assert AlphaVantage.listing("BRK-B") == ("BRK-B", "USD")
    for unsupported in ("^GSPC", "GC=F", "VOD.L", "RY.NE"):
        assert AlphaVantage.listing(unsupported) is None


def test_quotes_parse_listings_rates_and_misses(av):
    provider = AlphaVantage(KEY, av)
    quotes, errors = provider.quotes(["XEQT.TO", "AAPL", "USDCAD=X", "BTC-USD", "NOPE", "^GSPC"])
    x = quotes["XEQT.TO"]
    assert (x.price, x.prev_close, x.currency, x.day_high, x.volume) == (45.4, 44.65, "CAD", 45.4, 797346)
    close = datetime(2026, 11, 4, 16, tzinfo=ZoneInfo("America/New_York")).timestamp()
    assert x.market_time == close and x.market_state == "CLOSED" and x.fetched_at > 0
    assert quotes["AAPL"].currency == "USD"
    fx = quotes["USDCAD=X"]
    assert (fx.price, fx.prev_close, fx.currency, fx.instrument_type) == (1.3977, 1.3977, "CAD", "CURRENCY")
    assert fx.market_time == datetime(2026, 11, 5, 21, 6, 50, tzinfo=ZoneInfo("UTC")).timestamp()
    assert quotes["BTC-USD"].instrument_type == "CRYPTOCURRENCY"
    assert errors == {"NOPE": "symbol not found", "^GSPC": "not covered by Alpha Vantage"}
    assert {c["apikey"] for c in av.calls} == {KEY}
    assert [c["symbol"] for c in av.calls if c["function"] == "GLOBAL_QUOTE"] == ["XEQT.TRT", "AAPL", "NOPE"]


@pytest.mark.parametrize("field", ["Error Message", "Information", "Note"])
def test_refusals_raise_without_the_key(av, field):
    av.refusal = {field: f"the parameter apikey={KEY} is invalid or over the 25 requests per day limit"}
    with pytest.raises(MarketError) as e:
        AlphaVantage(KEY, av).quotes(["XEQT.TO"])
    assert KEY not in str(e.value) and "Alpha Vantage" in str(e.value) and "***" in str(e.value)


def test_transport_errors_are_scrubbed(av):
    av.raise_error = f"network error: Failed to perform https://www.alphavantage.co/query?apikey={KEY}"
    with pytest.raises(MarketError) as e:
        AlphaVantage(KEY, av).quotes(["AAPL"])
    assert KEY not in str(e.value)


def test_redact():
    assert redact("a KEY b KEY", "KEY") == "a *** b ***"
    assert redact("nothing", "") == "nothing"


def test_make_fallback_needs_a_known_provider_and_a_key():
    assert make_fallback(Config()) is None
    assert make_fallback(Config(quote_provider="alphavantage")) is None
    assert make_fallback(Config(quote_provider="nope", quote_api_key=KEY)) is None
    assert isinstance(make_fallback(Config(quote_provider="alphavantage", quote_api_key=KEY)), AlphaVantage)
    assert provider_label("alphavantage") == "Alpha Vantage" and provider_label("yahoo") == "Yahoo Finance"


def test_alpha_vantage_fills_in_when_yahoo_is_down(fake, store, av):
    MarketData(fake, store).quotes(["XEQT.TO"])
    q = store.cached_quotes(["XEQT.TO"])["XEQT.TO"]
    q.fetched_at -= FALLBACK_AFTER + 60
    store.cache_quotes([q])
    fake.offline = True
    quotes, errors = MarketData(fake, store, AlphaVantage(KEY, av)).quotes(["XEQT.TO"])
    assert quotes["XEQT.TO"].source == "alphavantage" and quotes["XEQT.TO"].price == 45.4 and not errors


# ── The key stays private ─────────────────────────────────────────────────────


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "220")
    runner = CliRunner()

    def invoke(*args: str, input: str | None = None):
        return runner.invoke(main, list(args), input=input, catch_exceptions=False)

    return invoke


def test_provider_key_reads_stdin_and_never_prints_it(cli, tracker, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    result = cli("provider", "key", "--", "alphavantage", input=f"  {KEY}\n")
    assert result.exit_code == 0 and KEY not in result.output
    saved = Config.load(path)
    assert (saved.quote_provider, saved.quote_api_key) == ("alphavantage", KEY)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    shown = cli("config")
    assert KEY not in shown.output and "(set)" in shown.output
    # Not through `config set`, where it would sit in shell history and `ps`.
    refused = cli("config", "set", "quote_api_key", KEY)
    assert refused.exit_code == 1 and "provider key" in refused.output

    tracker.config = saved
    payload = json.dumps(snapshot(tracker))
    assert KEY not in payload
    assert '"quote_provider_key_set": true' in payload

    cleared = cli("provider", "clear")
    assert cleared.exit_code == 0
    after = Config.load(path)
    assert (after.quote_provider, after.quote_api_key) == ("", "")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600  # stays owner-only


def test_provider_key_rejects_bad_input(cli):
    assert cli("provider", "key", "alphavantage", input="\n").exit_code == 1
    assert cli("provider", "key", "alphavantage", input="two words\n").exit_code == 1
    assert cli("provider", "key", "nope", input=f"{KEY}\n").exit_code == 2
    assert cli("config", "set", "quote_provider", "nope").exit_code == 1


def test_provider_status_and_test(cli, monkeypatch, av):
    out = cli("provider", "status").output
    assert "Yahoo Finance" in out and "not tried" in out and "No fallback provider" in out
    assert cli("provider", "test").exit_code == 1
    cli("provider", "key", "alphavantage", input=KEY)
    monkeypatch.setattr("marketpulse.cli.make_fallback", lambda config: AlphaVantage(config.quote_api_key, av))
    ok = cli("provider", "test", "XEQT.TO")
    assert ok.exit_code == 0 and "45.40" in ok.output and KEY not in ok.output
    av.refusal = {"Information": f"apikey {KEY} over the daily limit"}
    refused = cli("provider", "test")
    assert refused.exit_code == 1 and "daily limit" in refused.output and KEY not in refused.output
    rows = json.loads(cli("provider", "status", "--json").output)
    assert rows[0]["name"] == "yahoo"


def test_quote_source_and_age_reach_the_bridge(tracker, store):
    from marketpulse.models import Transaction, TxnType

    acct = store.ensure_default_account("CAD")
    store.add_transaction(Transaction(acct.saved_id, TxnType.BUY, "2024-01-02", "XEQT.TO", 3, 30.0, currency="CAD"))
    payload = snapshot(tracker)
    (pos,) = payload["positions"]
    assert pos["quote_source"] == "yahoo" and 0 <= pos["quote_age_seconds"] < 60
    assert [p["name"] for p in payload["providers"]] == ["yahoo"]
    assert payload["providers"][0]["ok"] is True
    assert payload["automation"]["stale_count"] == 0 and payload["automation"]["stale_since"] is None


def test_doctor_reports_yahoo_and_the_fallback_without_the_key(cli, tracker, fake, av, monkeypatch):
    fake.set_quote("SPY", 500.0)
    assert "Yahoo reachable" in cli("doctor").output
    fake.offline = True
    out = cli("doctor").output
    assert "Yahoo unreachable: network error: offline" in out and "fallback quotes" not in out
    tracker.market.fallback = AlphaVantage(KEY, av)
    monkeypatch.setattr(tracker.config, "quote_provider", "alphavantage")
    monkeypatch.setattr(tracker.config, "quote_api_key", KEY)
    out = cli("doctor").output
    assert "Alpha Vantage (not used yet)" in out  # SPY's cached price is recent enough
    av.refusal = {"Information": f"apikey {KEY}: 25 requests per day"}
    q = tracker.store.cached_quotes(["SPY"])["SPY"]
    q.fetched_at -= FALLBACK_AFTER + 60
    tracker.store.cache_quotes([q])
    out = cli("doctor").output
    assert "Alpha Vantage (failing: Alpha Vantage: apikey ***: 25 requests per day)" in out and KEY not in out
