"""User configuration (~/.config/marketpulse/config.toml) and data paths."""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

DEFAULT_MARKET_STRIP = ["^GSPC", "^IXIC", "^GSPTSE", "USDCAD=X", "BTC-USD", "GC=F", "^TNX"]
DEFAULT_WATCHLIST = ["XEQT.TO", "VFV.TO", "QQQ", "SPY", "AAPL", "NVDA", "BTC-USD"]


_warned: set[Path] = set()


def data_dir() -> Path:
    base = Path(os.environ.get("MARKETPULSE_DATA") or Path.home() / ".marketpulse")
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    if env := os.environ.get("MARKETPULSE_CONFIG"):
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "marketpulse" / "config.toml"


@dataclass
class Config:
    # Omarchy theme slug, or "auto" to follow the active Omarchy theme (falls back to tokyo-night)
    theme: str = "auto"
    base_currency: str = "CAD"
    refresh_seconds: int = 30
    privacy: bool = False
    benchmark: str = "XEQT.TO"
    chart_period: str = "3mo"
    default_account: str = ""
    market_strip: list[str] = field(default_factory=lambda: list(DEFAULT_MARKET_STRIP))
    capital_gains_inclusion: float = 0.5
    # Menu bar: day_pct | day_change | net_worth | symbol
    menubar_display: str = "day_pct"
    menubar_symbol: str = ""
    # Terminal used to open the TUI from the menu bar: auto | ghostty | iterm | terminal | kitty | wezterm
    terminal: str = "auto"
    # Fallback quote provider used when Yahoo can't be reached ("" = none), and the user's own
    # key for it. Set the key with `marketpulse provider key`; it is never printed or exported.
    quote_provider: str = ""
    quote_api_key: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or config_path()
        cfg = cls()
        if not path.is_file():
            return cfg
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except OSError:
            return cfg
        except tomllib.TOMLDecodeError as e:
            if path not in _warned:  # once per process; nothing worse than silently losing every setting
                _warned.add(path)
                print(f"warning: {path}: {e}; using default settings", file=sys.stderr)
            return cfg
        known = {f.name: f for f in fields(cls)}
        for key, value in raw.items():
            if key not in known:
                continue
            default = getattr(cfg, key)
            if isinstance(default, bool):
                ok = isinstance(value, bool)
            elif isinstance(default, int | float):
                ok = isinstance(value, int | float) and not isinstance(value, bool)
            elif isinstance(default, list):
                ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
            else:
                ok = isinstance(value, str)
            if ok:
                setattr(cfg, key, type(default)(value) if isinstance(default, int | float) else value)
        return cfg

    def save(self, path: Path | None = None) -> Path:
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# MarketPulse configuration", ""]
        for key, value in asdict(self).items():
            lines.append(f"{key} = {_toml_value(value)}")
        tmp = path.with_suffix(".toml.tmp")
        # Owner-only once it holds an API key (and from then on: a removed key leaves no trace
        # worth exposing, and loosening permissions the user may have set isn't ours to do).
        private = bool(self.quote_api_key) or (path.exists() and path.stat().st_mode & 0o077 == 0)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            if private and hasattr(os, "fchmod"):  # O_CREAT's mode doesn't apply to a leftover temp file
                os.fchmod(fh.fileno(), 0o600)
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
        return path

    def redacted(self) -> dict:
        """Every setting, with the API key replaced: for display, logs and bug reports."""
        data = asdict(self)
        if data.get("quote_api_key"):
            data["quote_api_key"] = "(set)"
        return data


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return '"' + "".join(_toml_char(c) for c in str(value)) + '"'


_TOML_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _toml_char(c: str) -> str:
    """One character of a TOML basic string. Control characters must be escaped, or a value
    typed in the app (an account name with a newline) would make the whole file unreadable."""
    if c in _TOML_ESCAPES:
        return _TOML_ESCAPES[c]
    if ord(c) < 0x20 or ord(c) == 0x7F:
        return f"\\u{ord(c):04X}"
    return c
