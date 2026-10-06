# Configuration and troubleshooting

[Back to the README](../README.md) · [User guide](usage.md) · [Data and backups](data.md)

## Settings

Run `marketpulse config` to show settings, `marketpulse config edit` to edit
the TOML file, or set individual values:

```bash
marketpulse config set base_currency USD
marketpulse config set refresh_seconds 60
marketpulse config set default_account "My TFSA"
marketpulse theme set kanagawa
```

The default file is `~/.config/marketpulse/config.toml`. `XDG_CONFIG_HOME` changes
the configuration root; `MARKETPULSE_CONFIG` overrides the complete file path.
The directory is created when settings are saved. Use
[examples/config.toml](../examples/config.toml) as a starting point.

| Key | Default | Purpose |
| --- | --- | --- |
| `theme` | `"auto"` | Active Omarchy theme, or Tokyo Night when no Omarchy theme is found |
| `base_currency` | `"CAD"` | Currency for portfolio totals and reports |
| `refresh_seconds` | `30` | TUI quote refresh interval; CLI setting requires at least 5 seconds |
| `privacy` | `false` | Mask displayed amounts |
| `benchmark` | `"XEQT.TO"` | Stored benchmark preference |
| `chart_period` | `"3mo"` | Initial price-chart range |
| `default_account` | `""` | Fallback account when several accounts exist |
| `market_strip` | See sample config | Symbols in the dashboard market strip |
| `capital_gains_inclusion` | `0.5` | Configurable multiplier used in tax estimates; confirm the value appropriate to your report |
| `menubar_display` | `"day_pct"` | `day_pct`, `day_change`, `net_worth`, or `symbol` |
| `menubar_symbol` | `""` | Symbol for `menubar_display = "symbol"` |
| `terminal` | `"auto"` | Terminal for the macOS companion: `auto`, `ghostty`, `iterm`, `terminal`, `kitty`, or `wezterm` |

The benchmark field is currently stored but is not used to calculate benchmark
performance. The companion also has settings in its own popover.

Unknown TOML keys and values of an incompatible type are ignored. Malformed
TOML produces a warning and falls back to defaults for that process.

## Separate portfolios

`MARKETPULSE_DATA` is a directory, not a database filename. Use an absolute path
when sharing it with the menu bar or scheduled jobs:

```bash
MARKETPULSE_DATA="$HOME/.marketpulse-work" marketpulse
```

The database and its backups are created in that directory. To keep display
settings separate as well, also set `MARKETPULSE_CONFIG` to another TOML file.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `marketpulse: command not found` | For a `uv tool` install, run `uv tool update-shell`, reopen the terminal, and check `uv tool list`. For a pip/venv install, activate the environment first. |
| Several accounts / ambiguous account | Select a full name with `--account`, or set `default_account` |
| Quotes unavailable or stale | Check connectivity, symbol spelling, and `marketpulse doctor`; Yahoo may throttle or change its endpoints |
| Missing history or FX | Review report warnings; cached quotes do not supply missing historical data |
| Configuration changes seem ignored | Check `MARKETPULSE_CONFIG` and `XDG_CONFIG_HOME`, validate TOML types, and restart the app |
| Swift sources not found | The menu bar companion needs an editable source checkout (`uv tool install --editable .`); a git-tag or wheel install does not include the Swift project |
| Swift compiler not found | On macOS, install Xcode Command Line Tools with `xcode-select --install` |
| Menu bar uses an old CLI path | Re-run `marketpulse menubar install` from the current environment |
| Terminal characters look incorrect | Use a UTF-8 locale and a font with Unicode/braille support |

`marketpulse doctor` includes paths, ledger counts, and a market connectivity
check. Review its output for personal information before attaching it to an issue.
