"""Offline discovery filters compose on fictional account and transfer rows."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType


@pytest.fixture
def discovery(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    first = store.add_account(Account(name="Maple", type=AccountType.TFSA, institution='Fictional, "North"'))
    second = store.add_account(Account(name="Birch", type=AccountType.RRSP, institution="Fictional South"))
    hidden = store.add_account(Account(name="Secret", archived=True, institution="Hidden institution"))
    for account, kind, day, symbol, target in [
        (first, TxnType.BUY, "2024-01-01", "AAA", None),
        (second, TxnType.BUY, "2024-04-02", "BBB", None),
        (first, TxnType.DEPOSIT, "2024-07-03", "", None),
        (first, TxnType.TRANSFER, "2024-10-06", "AAA", second),
        (hidden, TxnType.BUY, "2024-01-01", "SECRET", None),
        (first, TxnType.TRANSFER, "2024-01-01", "AAA", hidden),
    ]:
        store.add_transaction(
            Transaction(
                account.saved_id,
                kind,
                day,
                symbol,
                quantity=1,
                price=10,
                amount=10,
                currency="CAD",
                target_account_id=target.saved_id if target else None,
            )
        )
    fake.offline = True
    before = len(fake.calls)
    runner = CliRunner()

    def invoke(*args):
        result = runner.invoke(main, ["activity", *args], catch_exceptions=False)
        assert len(fake.calls) == before
        return result

    return invoke


def rows(invoke, *args):
    result = invoke("--json", *args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def ids(invoke, *args):
    return [r["id"] for r in rows(invoke, *args)]


def test_symbols_include_any_and_intersect_existing_filters(discovery):
    assert ids(discovery, "--symbols", " aaa ") == [4, 1]
    assert ids(discovery, "--symbols", "aaa", "--symbols", "BbB") == [4, 2, 1]
    assert ids(discovery, "--symbols", "aaa", "--symbol", "BBB") == []
    assert ids(discovery, "--symbols", "aaa", "--exclude-symbol", "AAA") == []


def test_account_exclusions_hide_both_transfer_ends(discovery):
    assert ids(discovery, "--exclude-account", "birch") == [3, 1]
    assert ids(discovery, "--exclude-account", "RRSP", "--exclude-account", "1") == []
    assert ids(discovery, "--exclude-account", "Maple") == [2]


def test_source_account_type_and_institution_filters(discovery):
    assert ids(discovery, "--account-type", "tfsa") == [4, 3, 1]
    assert ids(discovery, "--institution", ' fictional, "NORTH" ') == [4, 3, 1]
    assert ids(discovery, "--institution", "Fictional") == []
    assert ids(discovery, "--account-type", "rrsp", "--institution", 'Fictional, "North"') == []


def test_symbol_presence_and_transfer_target(discovery):
    assert ids(discovery, "--has-symbol") == [4, 2, 1]
    assert ids(discovery, "--no-symbol") == [3]
    assert ids(discovery, "--target-account", "birch") == [4]
    assert ids(discovery, "--target-account", "RRSP", "--account", "Maple") == [4]
    assert ids(discovery, "--target-account", "Maple") == []


def test_quarter_weekday_and_composition(discovery):
    assert ids(discovery, "--quarter", "1") == [1]
    assert ids(discovery, "--quarter", "2") == [2]
    assert ids(discovery, "--quarter", "3") == [3]
    assert ids(discovery, "--quarter", "4") == [4]
    assert ids(discovery, "--weekday", "MON") == [1]
    assert ids(discovery, "--weekday", "sun") == [4]
    assert ids(discovery, "--weekday", "sun", "--quarter", "1") == []
    assert discovery("--quarter", "1", "--count", "--offset", "100").output == "1\n"


def test_weekday_and_institution_summaries_are_filtered_before_paging(discovery):
    assert rows(discovery, "--summary", "weekday", "--limit", "1", "--offset", "99") == [
        {"group": "mon", "count": 1},
        {"group": "sun", "count": 1},
        {"group": "tue", "count": 1},
        {"group": "wed", "count": 1},
    ]
    assert rows(discovery, "--summary", "institution", "--summary-sort", "count") == [
        {"group": 'Fictional, "North"', "count": 3},
        {"group": "Fictional South", "count": 1},
    ]
    result = discovery("--summary", "institution", "--csv", "--quarter", "1")
    assert list(csv.DictReader(io.StringIO(result.output))) == [{"group": 'Fictional, "North"', "count": "1"}]
    assert discovery("--summary", "weekday", "--quarter", "1").exit_code == 0
    assert rows(discovery, "--summary", "institution", "--year", "2030") == []


@pytest.mark.parametrize(
    "args",
    [
        ("--quarter", "0"),
        ("--quarter", "5"),
        ("--weekday", "monday"),
        ("--account-type", "unknown"),
    ],
)
def test_invalid_discovery_options(discovery, args):
    assert discovery(*args).exit_code == 2


@pytest.mark.parametrize("flag", ["--exclude-account", "--target-account"])
@pytest.mark.parametrize("ref", ["missing", "Secret"])
def test_unknown_and_archived_references_fail_clearly(discovery, flag, ref):
    result = discovery(flag, ref, "--json")
    assert result.exit_code != 0
    assert f"No active account '{ref}'." in result.output


def test_blank_institution_text_has_specific_label(store, tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    account = store.add_account(Account(name="Fictional blank institution"))
    store.add_transaction(Transaction(account.saved_id, TxnType.DEPOSIT, "2024-01-01", amount=10, currency="CAD"))
    result = CliRunner().invoke(main, ["activity", "--summary", "institution"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "(no institution)" in result.output
    assert "(no symbol)" not in result.output
