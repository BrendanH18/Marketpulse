# Configuration and theme inspection

These ten additions under [#126](https://github.com/BrendanH18/Marketpulse/issues/126)
inspect settings and themes offline. They never open the ledger, fetch quotes, or
write the configuration file, and API keys stay redacted as `(set)` in every format.

1. `config get refresh_seconds privacy --json` inspects several settings at once, in the order requested. One key still works as before; repeated keys appear once.
2. `config get --value refresh_seconds` prints only the value, for scripts. With several keys it prints one value per line in request order. Booleans print as `true`/`false`, lists as comma-separated symbols, and a saved API key as `(set)`.
3. `config --csv`, `config get KEY... --csv`, `config defaults --csv` and `config diff --csv` print `key,value` rows with a header, using the same value text as `--value`. An empty diff prints only the header.
4. `config defaults refresh_seconds privacy` restricts factory defaults to the given keys. Without keys every default is shown, as before.
5. `config diff privacy base_currency` restricts the comparison to the given keys. Only those that differ are printed; if none do, text output says "Selected settings match defaults."
6. `config diff --exit-code` exits 1 when any (selected) setting differs from its default and 0 otherwise, like `git diff --exit-code`. Output is unchanged.
7. `config keys --json` prints setting names as a JSON array.
8. `config keys --search quote` keeps names containing the text, ignoring case.
9. `config keys --changed` keeps names whose effective value differs from the default. A saved API key counts as changed; its value is never printed.
10. `theme --json` lists the embedded Omarchy palettes as `{"theme", "current", "themes": [{"name", "label", "mode"}]}`, where `theme` is the configured value (for example `auto`) and `current` the palette it resolves to.

`config validate --quiet` (`-q`) prints no report and gives validity only
through its exit status (0 valid, 1 invalid), for scripts and pre-commit hooks.
As with every command, a file that is not valid TOML still triggers the startup
warning on standard error.

Unknown keys fail with the existing `Unknown setting` error and exit 1 before
anything is printed. `--json` and `--csv` cannot be combined; `--value` cannot
combine with either. `config --json`/`--csv` and `theme --json` apply only without
a subcommand. `keys --search` cannot be blank and combines with `--changed` and
`--json`; no matches print nothing (or `[]` with `--json`) and exit 0.
`validate --quiet` cannot combine with `--json`. `--exit-code` combines with key
restrictions and every output format. Existing defaults are unchanged.
