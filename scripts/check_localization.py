"""Check the Mac app's translations against its Swift source.

    uv run --locked python scripts/check_localization.py            # errors only
    uv run --locked python scripts/check_localization.py --unused   # also list unused keys

Without Xcode there is no `genstrings` or String Catalog compiler, so this does their job for
the parts that matter:

- Every string literal the source hands to a localizing API (`Text("…")`, `Button("…")`,
  `.help("…")`, `String(localized: "…")`, and the app's own views listed in `CALLS`) has an
  entry in each translation's `Localizable.strings`. An interpolation `\\(x)` matches any format
  specifier in the key, since its type picks the specifier (%@, %lld, %lf).
- A translation keeps its key's format specifiers (same kinds, same count), or the app would
  read the wrong argument or crash.
- No key appears twice with different translations, and none is empty.

It can't see a string that reaches the screen without a lookup (`Text(verbatim:)`, a `String`
variable passed to `Text`): the French QA run catches those.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "macos" / "MarketPulseBar" / "Sources" / "MarketPulseBar"
LOCALIZATION = ROOT / "macos" / "MarketPulseBar" / "Localization"
DEVELOPMENT = "en"

# SwiftUI initializers whose first string literal is a LocalizedStringKey, plus the app's own
# views and helpers that take one (add yours here when a parameter becomes LocalizedStringKey).
CALLS = {
    "Text",
    "Button",
    "Label",
    "Toggle",
    "Picker",
    "Section",
    "LabeledContent",
    "TextField",
    "SecureField",
    "Menu",
    "Link",
    "GroupBox",
    "DisclosureGroup",
    "Stepper",
    "DatePicker",
    "ContentUnavailableView",
    "ControlGroup",
    "ProgressView",
    "Gauge",
    "LocalizedStringKey",
    "LocalizedStringResource",
}
# Modifiers whose first string literal is localized.
MODIFIERS = {
    "help",
    "accessibilityLabel",
    "accessibilityHint",
    "accessibilityValue",
    "accessibilityInputLabels",
    "navigationTitle",
    "alert",
    "confirmationDialog",
}
# Keyword arguments whose literal is localized wherever they appear (`String(localized: "…")`,
# `Button(…, label: "…")` is not one, so it isn't listed).
KEYWORDS = {"localized"}

SPECIFIER = re.compile(
    r"%(?:\d+\$)?[-+ #0']*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|q|L|z|t|j)?[@dDuUxXoOfFeEgGcCsSpaA]"
)
PLACEHOLDER = "\0"


@dataclass(frozen=True)
class Use:
    key: str  # interpolations replaced by PLACEHOLDER
    file: str
    line: int


def parse_strings(path: Path) -> list[tuple[str, str, int]]:
    """(key, value, line) for each `"key" = "value";` in an old-style .strings file."""
    text = path.read_text(encoding="utf-8")
    entries: list[tuple[str, str, int]] = []
    i, n = 0, len(text)

    def literal(start: int) -> tuple[str, int]:
        out, j = [], start + 1
        while j < n and text[j] != '"':
            if text[j] == "\\" and j + 1 < n:
                c = text[j + 1]
                out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(c, "\\" + c))
                j += 2
            else:
                out.append(text[j])
                j += 1
        if j >= n:
            raise ValueError(f"{path}: unterminated string at offset {start}")
        return "".join(out), j + 1

    def skip(j: int) -> int:
        while j < n:
            if text[j].isspace():
                j += 1
            elif text.startswith("/*", j):
                end = text.find("*/", j + 2)
                if end < 0:
                    raise ValueError(f"{path}: unterminated comment")
                j = end + 2
            elif text.startswith("//", j):
                end = text.find("\n", j)
                j = n if end < 0 else end + 1
            else:
                break
        return j

    while True:
        i = skip(i)
        if i >= n:
            return entries
        line = text.count("\n", 0, i) + 1
        if text[i] != '"':
            raise ValueError(f"{path}:{line}: expected a quoted key")
        key, i = literal(i)
        i = skip(i)
        if i >= n or text[i] != "=":
            raise ValueError(f"{path}:{line}: expected '=' after {key!r}")
        i = skip(i + 1)
        if i >= n or text[i] != '"':
            raise ValueError(f"{path}:{line}: expected a quoted value for {key!r}")
        value, i = literal(i)
        i = skip(i)
        if i >= n or text[i] != ";":
            raise ValueError(f"{path}:{line}: expected ';' after the value for {key!r}")
        i += 1
        entries.append((key, value, line))


def swift_literal(src: str, start: int) -> tuple[str, int] | None:
    """The single-line Swift string literal at src[start] == '"' with each interpolation as
    PLACEHOLDER, and the index after it. None for a multi-line or raw literal."""
    if src.startswith('"""', start):
        return None
    out, j, n = [], start + 1, len(src)
    while j < n:
        c = src[j]
        if c == '"':
            return "".join(out), j + 1
        if c == "\n":
            return None
        if c == "\\" and j + 1 < n:
            nxt = src[j + 1]
            if nxt == "(":
                j = skip_interpolation(src, j + 2)
                out.append(PLACEHOLDER)
                continue
            out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "'": "'", "0": "\0"}.get(nxt, nxt))
            j += 2
            continue
        out.append(c)
        j += 1
    return None


def skip_interpolation(src: str, j: int) -> int:
    """Index just past the ')' closing an interpolation that starts at src[j]."""
    depth = 1
    while j < len(src) and depth:
        c = src[j]
        if c == '"':
            lit = swift_literal(src, j)
            if lit is None:
                return j + 1
            j = lit[1]
            continue
        depth += c == "("
        depth -= c == ")"
        j += 1
    return j


def call_pattern(calls: set[str], modifiers: set[str], keywords: set[str]) -> re.Pattern[str]:
    names = "|".join(sorted(calls))
    mods = "|".join(sorted(modifiers))
    kws = "|".join(sorted(keywords))
    return re.compile(rf'(?:(?<![\w.])(?:{names})\(\s*|\.(?:{mods})\(\s*|\b(?:{kws}):\s*)(?=")')


def source_uses(sources: Path = SOURCES) -> list[Use]:
    pattern = call_pattern(CALLS, MODIFIERS, KEYWORDS)
    uses = []
    for path in sorted(sources.glob("*.swift")):
        src = path.read_text(encoding="utf-8")
        for m in pattern.finditer(src):
            lit = swift_literal(src, m.end())
            if lit is None:
                continue
            key = lit[0]
            if not re.search(r"[A-Za-z]", key.replace(PLACEHOLDER, "")):
                continue  # symbols, numbers and pure interpolations aren't translated
            uses.append(Use(key, path.name, src.count("\n", 0, m.start()) + 1))
    return uses


def key_pattern(key: str) -> re.Pattern[str]:
    """The table keys a source literal can resolve to: each interpolation becomes a format
    specifier, and a literal % is doubled when (and only when) the literal interpolates, as
    Swift does when it builds the key."""
    interpolates = PLACEHOLDER in key
    parts = []
    for i, chunk in enumerate(key.split(PLACEHOLDER)):
        if i:
            parts.append(SPECIFIER.pattern)
        parts.append(re.escape(chunk.replace("%", "%%") if interpolates else chunk))
    return re.compile("".join(parts))


def specifiers(text: str) -> Counter[str]:
    """Format specifiers by kind, ignoring position (%1$@ counts as %@)."""
    return Counter(re.sub(r"^%\d+\$", "%", s) for s in SPECIFIER.findall(text))


def check(sources: Path = SOURCES, localization: Path = LOCALIZATION, *, unused: bool = False) -> list[str]:
    errors: list[str] = []
    uses = source_uses(sources)
    languages = sorted(p.stem for p in localization.glob("*.lproj") if p.stem != DEVELOPMENT)
    if not languages:
        return [f"No translations found in {localization}"]
    for lang in languages:
        for table in sorted((localization / f"{lang}.lproj").glob("*.strings")):
            label = f"{lang}.lproj/{table.name}"
            try:
                entries = parse_strings(table)
            except ValueError as e:
                errors.append(str(e))
                continue
            seen: dict[str, str] = {}
            for key, value, line in entries:
                if key in seen and seen[key] != value:
                    errors.append(f"{label}:{line}: {key!r} is translated twice, differently")
                seen[key] = value
                if not value.strip():
                    errors.append(f"{label}:{line}: {key!r} has an empty translation")
                if specifiers(key) != specifiers(value):
                    errors.append(
                        f"{label}:{line}: {value!r} must keep the format specifiers of {key!r} "
                        f"({sorted(specifiers(key).elements())} vs {sorted(specifiers(value).elements())})"
                    )
            if table.name != "Localizable.strings":
                continue
            patterns = {u.key: key_pattern(u.key) for u in uses}
            missing: dict[str, Use] = {}
            for use in uses:
                if not any(patterns[use.key].fullmatch(k) for k in seen):
                    missing.setdefault(use.key, use)
            for key, use in missing.items():
                shown = key.replace(PLACEHOLDER, "%@")
                errors.append(f"{use.file}:{use.line}: {shown!r} has no translation in {label}")
            if unused:
                for key, _, line in entries:
                    if not any(p.fullmatch(key) for p in patterns.values()):
                        print(f"note: {label}:{line}: {key!r} isn't used by a localizing call this script recognizes")
    return errors


def main() -> int:
    errors = check(unused="--unused" in sys.argv[1:])
    for e in errors:
        print(e)
    uses = source_uses()
    print(f"{len(uses)} localized strings in the source, {len({u.key for u in uses})} distinct; {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
