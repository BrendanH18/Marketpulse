# Configuration productivity tools

These ten additions complete items 21–30 of [issue #108](https://github.com/BrendanH18/Marketpulse/issues/108).
Configuration commands run offline and do not open the ledger. The examples use
fictional settings. Set `MARKETPULSE_CONFIG` to a scratch file when experimenting.

21. **Export redacted settings as JSON:** `marketpulse config --json`. The output
    is the effective configuration after loading defaults. API keys are always
    replaced by `(set)`; an unset key is an empty string. Invalid legacy nonfinite
    floating-point values appear as `null` so the output remains valid JSON.
22. **Inspect one setting:** `marketpulse config get refresh_seconds --json`.
    Returns an object containing just the requested key; omit `--json` for text.
    `get quote_api_key` remains redacted.
23. **Inspect factory defaults:** `marketpulse config defaults --json`. This
    neither creates a missing file nor changes your preferences.
24. **Inspect deviations from defaults:** `marketpulse config diff --json`.
    Only changed effective settings are returned. API keys stay redacted, and
    an unchanged configuration produces `{}`. Text output is also available.
25. **Discover accepted keys:** `marketpulse config keys`. One setting name per
    line supports shell completion scripts and simple discovery.
26. **Reset one setting:** `marketpulse config reset refresh_seconds`. All other
    values, including a saved API key, are preserved. There is no reset-all
    command. API keys must be managed using `provider key` or `provider clear`.
27. **Preview a setting change:** `marketpulse config set --dry-run base_currency usd`.
    Runs the same parsing and validation as a real write and previews normalized
    `USD`, without creating or modifying a file. Secret values are refused by
    `config set` with and without `--dry-run`.
28. **Validate the raw file:** `marketpulse config validate --json`. Checks TOML
    syntax, known keys, types and supported values, returning `{"ok": true,
    "issues": []}` and exit 0 on success, or issues and exit 1 on failure. No
    file is written, no source values are printed, and a missing file is valid
    because defaults apply. Unlike normal loading, validation flags unknown and
    wrong-typed settings that the loader ignores, and fractional refresh seconds
    that normal loading truncates. Syntax errors use a generic diagnostic to
    avoid exposing a secret from the file. Invalid UTF-8 and nonfinite integer
    values remain diagnosable without crashing the loader.
29. **Reject invalid currency identifiers:** `marketpulse config set base_currency '12$'`
    now fails without saving. A code must contain exactly three ASCII letters;
    lowercase input is still normalized to uppercase. This checks spelling
    format, not whether a currency is supported by a quote provider.
30. **Validate the terminal choice:** `marketpulse config set terminal wezterm`.
    Accepted values are `auto`, `ghostty`, `iterm`, `terminal`, `kitty`, and
    `wezterm`. Unsupported values fail before saving, and `config validate`
    diagnoses them in a manually edited file.

The inspection commands describe effective settings; `validate` examines the raw
file. A partially invalid file can therefore show defaulted values when inspected
while failing validation. JSON goes to standard output; loader warnings go to
standard error. None of these commands changes financial calculations.
