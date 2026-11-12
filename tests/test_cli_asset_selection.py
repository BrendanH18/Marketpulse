"""Fictional fixed-income inventory selection, entirely offline."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Asset, AssetKind


@pytest.fixture
def assets_cli(store, tracker, monkeypatch, fake):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    fake.offline = True
    for asset in (
        Asset("FIC-LOW", AssetKind.FIXED_INCOME, rate=2, start_date="2024-01-01", maturity_date="2026-01-01"),
        Asset(
            "FIC-HIGH",
            AssetKind.FIXED_INCOME,
            rate=10,
            compounding="monthly",
            start_date="2025-01-01",
            maturity_date="2027-01-01",
        ),
        Asset("FIC-EMPTY", AssetKind.FIXED_INCOME, rate=0),
        Asset("FIC-MANUAL", AssetKind.MANUAL, rate=99, start_date="2024-01-01", maturity_date="2026-01-01"),
        Asset("FIC-MARKET"),
    ):
        store.upsert_asset(asset)
    runner = CliRunner()

    def invoke(*args):
        result = runner.invoke(main, ["asset", "list", *args], catch_exceptions=False)
        assert fake.calls == []
        assert store.snapshots() == []
        return result

    return invoke


@pytest.mark.parametrize(
    ("options", "symbols"),
    [
        (("--exclude-symbol", " fic-low ", "--exclude-symbol", "fic-high"), ["FIC-EMPTY", "FIC-MANUAL", "FIC-MARKET"]),
        (("--min-rate", "2"), ["FIC-HIGH", "FIC-LOW"]),
        (("--max-rate", "2"), ["FIC-EMPTY", "FIC-LOW"]),
        (("--min-rate", "2", "--max-rate", "2"), ["FIC-LOW"]),
        (("--starts-since", "2025-01-01"), ["FIC-HIGH"]),
        (("--starts-until", "2024-01-01"), ["FIC-LOW"]),
        (("--matures-since", "2027-01-01"), ["FIC-HIGH"]),
        (("--matures-until", "2026-01-01"), ["FIC-LOW"]),
        (("--compounding", "MONTHLY"), ["FIC-HIGH"]),
        (("--starts-since", "2024-01-01", "--matures-until", "2026-01-01", "--min-rate", "2"), ["FIC-LOW"]),
    ],
)
def test_asset_filters(assets_cli, options, symbols):
    result = assets_cli(*options, "--json")
    assert result.exit_code == 0, result.output
    assert sorted(row["symbol"] for row in json.loads(result.output)) == symbols


@pytest.mark.parametrize("sort_by", ["rate", "maturity-date"])
@pytest.mark.parametrize("descending", [False, True])
def test_asset_numeric_and_date_order_keep_missing_last(assets_cli, sort_by, descending):
    args = ["--sort", sort_by, "--json"] + (["--descending"] if descending else [])
    rows = json.loads(assets_cli(*args).output)
    known = ["FIC-EMPTY", "FIC-LOW", "FIC-HIGH"] if sort_by == "rate" else ["FIC-LOW", "FIC-HIGH"]
    assert [row["symbol"] for row in rows[: len(known)]] == (list(reversed(known)) if descending else known)
    assert all(row["kind"] != "fixed_income" or not row["maturity_date"] for row in rows[len(known) :])


def test_asset_count_page_csv_and_empty_human(assets_cli):
    assert assets_cli("--min-rate", "2", "--count", "--limit", "1", "--offset", "10").output.strip() == "2"
    page = json.loads(assets_cli("--min-rate", "2", "--sort", "rate", "--limit", "1", "--json", "--page-info").output)
    assert page["total"] == 2 and page["returned"] == 1 and page["next_offset"] == 1
    assert page["items"][0]["symbol"] == "FIC-LOW"
    exported = assets_cli("--matures-until", "2026-01-01", "--csv")
    rows = list(csv.DictReader(io.StringIO(exported.output)))
    assert [row["symbol"] for row in rows] == ["FIC-LOW"]
    assert "No assets match" in assets_cli("--min-rate", "100").output
    assert "FIC-HIGH" in assets_cli("--compounding", "monthly").output


@pytest.mark.parametrize(
    "options",
    [
        ("--exclude-symbol", " "),
        ("--min-rate", "nan"),
        ("--max-rate", "inf"),
        ("--min-rate", "3", "--max-rate", "2"),
        ("--starts-since", "2025-01-01", "--starts-until", "2024-01-01"),
        ("--matures-since", "2027-01-01", "--matures-until", "2026-01-01"),
        ("--starts-since", "2024-02-30"),
        ("--matures-until", "not-a-date"),
        ("--compounding", "daily"),
    ],
)
def test_asset_invalid_filters(assets_cli, options):
    result = assets_cli(*options)
    assert result.exit_code == 2, result.output
