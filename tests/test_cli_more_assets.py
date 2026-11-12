"""The 25 metadata additions in issue #134 use fictional assets and no prices."""

import csv
import io
import json
from dataclasses import asdict

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Asset, AssetClass, AssetKind


@pytest.fixture
def assets_cli(store, tracker, fake, monkeypatch):
    definitions = [
        Asset(
            "FIC-A",
            AssetKind.FIXED_INCOME,
            "Alpha deposit",
            AssetClass.FIXED_INCOME,
            "CAD",
            4.25,
            "annual",
            "2024-01-01",
            "2026-01-01",
        ),
        Asset(
            "FIC-B",
            AssetKind.FIXED_INCOME,
            "Beta deposit",
            AssetClass.FIXED_INCOME,
            "USD",
            5,
            "monthly",
            "2025-01-01",
            "2027-01-01",
        ),
        Asset("FIC-C", AssetKind.FIXED_INCOME, " ", compounding="quarterly"),
        Asset("MAN-A", AssetKind.MANUAL, "Alpha art", AssetClass.ALTERNATIVE, "CAD", start_date="2023-01-01"),
        Asset("MKT-A", AssetKind.MARKET, "Equities", AssetClass.ETF, "USD"),
        Asset("MKT-Z"),
    ]
    for asset in definitions:
        store.upsert_asset(asset)
    before = [asdict(a) for a in store.assets().values()]
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.services.Tracker.valuation", lambda *a, **kw: pytest.fail("Unexpected valuation"))
    monkeypatch.setenv("COLUMNS", "160")
    fake.offline = True
    runner = CliRunner()

    def invoke(*args):
        result = runner.invoke(main, ["asset", *args], catch_exceptions=False)
        assert fake.calls == []
        assert store.snapshots() == []
        assert store.transactions() == []
        assert [asdict(a) for a in store.assets().values()] == before
        return result

    return invoke


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (("--symbols", " fic-a ", "--symbols", "mkt-z"), ["FIC-A", "MKT-Z"]),  # 26
        (("--exclude-currency", " cad ", "--exclude-currency", "usd"), ["FIC-C", "MKT-Z"]),  # 27
        (("--exclude-kind", "FIXED_INCOME", "--exclude-kind", "manual"), ["MKT-A", "MKT-Z"]),  # 28
        (("--exclude-class", "FIXED_INCOME", "--exclude-class", "etf"), ["FIC-C", "MAN-A", "MKT-Z"]),  # 29
        (("--name", " ALPHA "), ["FIC-A", "MAN-A"]),  # 30
        (("--symbol-prefix", " fic- "), ["FIC-A", "FIC-B", "FIC-C"]),  # 31
        (("--symbol-suffix", " -a "), ["FIC-A", "MAN-A", "MKT-A"]),  # 32
        (("--has-name",), ["FIC-A", "FIC-B", "MAN-A", "MKT-A"]),  # 33
        (("--no-name",), ["FIC-C", "MKT-Z"]),
        (("--has-currency",), ["FIC-A", "FIC-B", "MAN-A", "MKT-A"]),  # 34
        (("--no-currency",), ["FIC-C", "MKT-Z"]),
        (("--classified",), ["FIC-A", "FIC-B", "MAN-A", "MKT-A"]),  # 35
        (("--has-start-date",), ["FIC-A", "FIC-B", "MAN-A"]),  # 36
        (("--no-start-date",), ["FIC-C", "MKT-A", "MKT-Z"]),
        (("--has-maturity-date",), ["FIC-A", "FIC-B"]),  # 37
        (("--no-maturity-date",), ["FIC-C", "MAN-A", "MKT-A", "MKT-Z"]),
        (
            (
                "--symbols",
                "FIC-A",
                "--symbols",
                "FIC-B",
                "--exclude-currency",
                "usd",
                "--name",
                "deposit",
                "--has-start-date",
            ),
            ["FIC-A"],
        ),
    ],
)
def test_new_metadata_filters(assets_cli, options, expected):
    result = assets_cli("list", *options, "--json")
    assert result.exit_code == 0, result.output
    assert [r["symbol"] for r in json.loads(result.output)] == expected


@pytest.mark.parametrize(
    ("sort_by", "known"),
    [
        ("start-date", ["FIC-A", "FIC-B"]),  # 38; manual metadata does not imply fixed-income terms.
        ("class", ["MAN-A", "MKT-A", "FIC-A", "FIC-B"]),  # 39
        ("compounding", ["FIC-A", "FIC-B", "FIC-C"]),  # 40
    ],
)
@pytest.mark.parametrize("descending", [False, True])
def test_new_metadata_sort_keeps_missing_last(assets_cli, sort_by, known, descending):
    options = ["--sort", sort_by, "--json"] + (["--descending"] if descending else [])
    rows = json.loads(assets_cli("list", *options).output)
    assert [r["symbol"] for r in rows[: len(known)]] == (list(reversed(known)) if descending else known)
    page = json.loads(assets_cli("list", *options, "--offset", "1", "--limit", "1", "--page-info").output)
    assert page["items"] == rows[1:2]
    assert page["total"] == 6 and page["next_offset"] == 2


@pytest.mark.parametrize(
    ("group", "counts"),
    [
        ("kind", {"fixed_income": 3, "manual": 1, "market": 2}),  # 41
        ("currency", {"(unspecified)": 2, "CAD": 2, "USD": 2}),  # 42
        ("class", {"(unclassified)": 2, "alternative": 1, "etf": 1, "fixed_income": 2}),  # 43
        ("compounding", {"(not applicable)": 3, "annual": 1, "monthly": 1, "quarterly": 1}),  # 44
    ],
)
def test_metadata_summaries_in_all_formats(assets_cli, group, counts):
    result = assets_cli("list", "--summary", group, "--json")
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert {r["group"]: r["count"] for r in rows} == counts
    csv_rows = list(csv.DictReader(io.StringIO(assets_cli("list", "--summary", group, "--csv").output)))
    assert {r["group"]: int(r["count"]) for r in csv_rows} == counts
    assert "Matching asset metadata" in assets_cli("list", "--summary", group).output
    empty = assets_cli("list", "--summary", group, "--json", "--symbol", "missing")
    assert json.loads(empty.output) == []


def test_symbol_lines_and_projected_list_exports(assets_cli):
    # 45: raw script lines use the same filtering, ordering and pagination.
    result = assets_cli(
        "list", "--symbols-only", "--symbol-prefix", "FIC", "--descending", "--offset", "1", "--limit", "1"
    )
    assert result.exit_code == 0 and result.output == "FIC-B\n"
    assert assets_cli("list", "--symbols-only", "--symbol", "missing").output == ""
    # 46: projection preserves order, removes duplicate fields, and retains paging metadata.
    options = ["list", "--symbol", "FIC-A", "--fields", "rate", "--fields", "symbol", "--fields", "rate"]
    assert json.loads(assets_cli(*options, "--json").output) == [{"rate": 4.25, "symbol": "FIC-A"}]
    csv_result = assets_cli(*options, "--csv")
    assert list(csv.DictReader(io.StringIO(csv_result.output))) == [{"rate": "4.25", "symbol": "FIC-A"}]
    assert csv_result.output.splitlines()[0] == "rate,symbol"
    page = json.loads(assets_cli(*options, "--json", "--page-info").output)
    assert page["items"] == [{"rate": 4.25, "symbol": "FIC-A"}] and page["total"] == 1
    assert assets_cli("list", "--symbol", "missing", "--fields", "symbol", "--csv").output == "symbol\n"


def test_show_csv_projection_raw_values_and_existence(assets_cli, monkeypatch):
    # 47: full one-row CSV retains the existing JSON metadata schema.
    raw = json.loads(assets_cli("show", "FIC-A", "--json").output)
    exported = list(csv.DictReader(io.StringIO(assets_cli("show", "fic-a", "--csv").output)))
    assert len(exported) == 1 and set(exported[0]) == set(raw)
    assert exported[0]["rate"] == "4.25"
    # 48: show projection works in JSON, CSV and human mode.
    options = ["show", "FIC-A", "--fields", "symbol", "--fields", "rate"]
    assert json.loads(assets_cli(*options, "--json").output) == {"symbol": "FIC-A", "rate": 4.25}
    assert assets_cli(*options, "--csv").output.splitlines()[0] == "symbol,rate"
    monkeypatch.setattr("marketpulse.cli.base.Config.load", classmethod(lambda cls: cls(privacy=True)))
    human = assets_cli(*options).output
    assert "FIC-A" in human and "4.25" not in human and "maturity_date" not in human
    assert json.loads(assets_cli(*options, "--json").output)["rate"] == 4.25
    # 49: raw values stay unmasked for scripts, including enums and absent values.
    assert assets_cli("show", "FIC-A", "--value", "rate").output == "4.25\n"
    assert assets_cli("show", "FIC-A", "--value", "kind").output == "fixed_income\n"
    assert assets_cli("show", "MKT-Z", "--value", "asset_class").output == "\n"
    # 50: --exists has only an exit status; no error text or metadata for missing symbols.
    for symbol, status in ((" fic-a ", 0), ("missing", 1)):
        result = assets_cli("show", symbol, "--exists")
        assert result.exit_code == status and result.output == ""
    assert assets_cli("show", "missing", "--value", "rate").exit_code == 1


@pytest.mark.parametrize(
    "options",
    [
        ("list", "--symbols", " "),
        ("list", "--exclude-currency", " "),
        ("list", "--name", " "),
        ("list", "--symbol-prefix", " "),
        ("list", "--symbol-suffix", " "),
        ("list", "--exclude-kind", "missing"),
        ("list", "--exclude-class", "missing"),
        ("list", "--classified", "--unclassified"),
        ("list", "--fields", "rate"),
        ("list", "--fields", "unknown", "--json"),
        ("list", "--fields", "", "--csv"),
        ("list", "--symbols-only", "--json"),
        ("list", "--symbols-only", "--count"),
        ("list", "--symbols-only", "--csv"),
        ("list", "--symbols-only", "--page-info"),
        ("list", "--summary", "kind", "--limit", "1"),
        ("list", "--summary", "kind", "--offset", "1"),
        ("list", "--summary", "kind", "--sort", "class"),
        ("list", "--summary", "kind", "--descending"),
        ("list", "--summary", "kind", "--count"),
        ("list", "--summary", "kind", "--symbols-only"),
        ("list", "--summary", "kind", "--json", "--page-info"),
        ("list", "--summary", "kind", "--json", "--fields", "symbol"),
        ("show", "FIC-A", "--json", "--csv"),
        ("show", "FIC-A", "--exists", "--json"),
        ("show", "FIC-A", "--value", "rate", "--csv"),
        ("show", "FIC-A", "--exists", "--value", "rate"),
        ("show", "FIC-A", "--exists", "--fields", "rate"),
        ("show", "FIC-A", "--value", "rate", "--fields", "rate"),
        ("show", "FIC-A", "--value", "unknown"),
    ],
)
def test_new_asset_options_reject_ambiguous_or_invalid_requests(assets_cli, options):
    result = assets_cli(*options)
    assert result.exit_code == 2, result.output
