"""Shared pieces of the CLI: the per-invocation `App` context, errors and common options."""

from __future__ import annotations

import hashlib
import io
import json
import sys
from functools import wraps
from typing import TYPE_CHECKING, NoReturn

import click
from rich.console import Console
from rich.text import Text
from rich.theme import Theme as RichTheme

from ..config import Config
from ..models import Account, parse_date
from ..requests import AlreadyRecorded, check_request
from ..themes import OMARCHY_PALETTES, resolve_palette, rich_styles

if TYPE_CHECKING:  # for annotations only; the real imports stay lazy
    from ..db import Store
    from ..services import Tracker

for _stream in (sys.stdout, sys.stderr):
    # Replace unencodable characters instead of crashing on a non-UTF-8 terminal.
    # Only real text streams can be reconfigured (pytest/CliRunner swap in others).
    if isinstance(_stream, io.TextIOWrapper):
        try:
            _stream.reconfigure(errors="replace")
        except ValueError:
            pass


class App:
    """Lazy per-invocation context: config and console are cheap, the tracker
    (database + network client) is only opened by commands that need it."""

    def __init__(self) -> None:
        self.config = Config.load()
        self.palette = resolve_palette(self.config.theme)
        self.console = Console(theme=RichTheme(rich_styles(self.palette)), highlight=False)
        self._tracker: Tracker | None = None
        self.restore_id = ""
        self.request_id: str | None = None
        self.request_fingerprint = ""

    @property
    def tracker(self) -> Tracker:
        if self._tracker is None:
            # Imported here so `marketpulse --help` and friends start instantly.
            from ..services import Tracker

            self._tracker = Tracker.open(self.config)
            # Before this command reads anything: a restore after this point replaces what it read.
            self.restore_id = self._tracker.store.restore_id
        return self._tracker

    @property
    def store(self) -> Store:
        return self.tracker.store

    @property
    def privacy(self) -> bool:
        return self.config.privacy

    def busy(self, message: str):
        return self.console.status(Text(message, style="accent"), spinner="dots")

    def ok(self, message: str) -> None:
        self.console.print(Text("✓ ", style="up") + Text(message))

    def warn(self, message: str) -> None:
        self.console.print(Text("! ", style="warn") + Text(message, style="muted"))

    def title(self, message: str) -> None:
        self.console.print(Text(f"▍{message}", style="title"))

    def account(self, ref: str | None) -> Account:
        store = self.store
        if ref:
            acct = store.get_account(ref)
            if acct is None:
                names = ", ".join(a.name for a in store.accounts()) or "none yet"
                fail(f"No account '{ref}'. Accounts: {names}. Create one with `marketpulse accounts add`.")
            return acct
        if self.config.default_account:
            acct = store.get_account(self.config.default_account)
            if acct is not None:
                return acct
        accounts = store.accounts()
        if not accounts:
            acct = store.ensure_default_account(self.config.base_currency)
            self.warn(f"Created account '{acct.name}' ({acct.type.label}, {acct.currency}).")
            return acct
        if len(accounts) == 1:
            return accounts[0]
        fail(
            "Several accounts — choose one with -a/--account ("
            + ", ".join(a.name for a in accounts)
            + ") or set a default: `marketpulse config set default_account NAME`."
        )


pass_app = click.make_pass_decorator(App, ensure=True)


def fail(message: str) -> NoReturn:
    """Abort the command with a friendly error (exit code 1, no traceback).

    Typed NoReturn so the type checker knows code after `fail()` is
    unreachable, e.g. `if acct is None: fail(...)` narrows acct to Account.
    """
    raise click.ClickException(message)


def date_callback(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Normalize a date option to ISO up front, so a typo is a usage error rather than a traceback."""
    if value is None:
        return None
    try:
        return parse_date(value)
    except ValueError as e:
        raise click.BadParameter(str(e), ctx=ctx, param=param) from None


def retryable(f):
    """Add `--request-id`, so the app can retry a save without recording it twice."""
    original = f

    @wraps(original)
    def requested(*args, **kwargs):
        ctx = click.get_current_context()
        app = ctx.ensure_object(App)
        request_id = kwargs.pop("request_id", None)
        app.request_id = str(request_id) if request_id is not None else None
        if app.request_id is None:
            return original(*args, **kwargs)
        # Fingerprint the user's parsed command, before inferred quotes/currency or
        # current holdings can change. Replays skip resolution and validation entirely.
        intent = json.dumps([ctx.command.name, kwargs], sort_keys=True)
        app.request_fingerprint = hashlib.sha256(intent.encode()).hexdigest()
        try:
            check_request(app.store, app.request_id, app.request_fingerprint)
            return original(*args, **kwargs)
        except AlreadyRecorded as saved:
            app.ok(f"Transaction already recorded (#{saved.transaction_id}).")
        except ValueError as e:
            fail(str(e))

    return click.option("--request-id", type=click.UUID, help="Retry identity for a native transaction save.")(
        requested
    )


def txn_options(f):
    f = retryable(f)
    f = click.option("-m", "--note", default="", help="Free-text note.")(f)
    f = click.option(
        "-d",
        "--date",
        "when",
        default=None,
        callback=date_callback,
        help="YYYY-MM-DD, 'yesterday' or -3d (default: today).",
    )(f)
    f = click.option("-a", "--account", default=None, help="Account name, id or type (e.g. TFSA).")(f)
    return f


def theme_slug(name: str) -> str:
    slug = name.strip().lower().replace(" ", "-")
    if slug in ("auto", "omarchy") or slug in OMARCHY_PALETTES:
        return slug
    fail(f"Unknown theme '{name}'. Run `marketpulse theme` to see them all.")
