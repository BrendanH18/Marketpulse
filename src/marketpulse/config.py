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

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or config_path()
        cfg = cls()
        if not path.is_file():
            return cfg
        try:
            raw = tomllib.loads(path.read_text())
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
        tmp.write_text("\n".join(lines) + "\n")
        os.replace(tmp, path)
        return path


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
