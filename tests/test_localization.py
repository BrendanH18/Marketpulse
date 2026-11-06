"""The Mac app's translations: every localized string in the Swift source has a French entry
that keeps its format specifiers, and the assembled app carries the tables in Contents/Resources."""

import importlib.util
import plistlib
import sys
from pathlib import Path

import pytest

from marketpulse import menubar

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("check_localization", ROOT / "scripts" / "check_localization.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_localization"] = module
    spec.loader.exec_module(module)
    return module


def test_app_strings_are_translated(checker):
    assert checker.check() == []


def test_backend_strings_cover_the_engines_fixed_text(checker):
    """Fixed English text the bridge sends (tax notes, tags, asset classes) has a French entry."""
    from marketpulse.desktop import BACKEND_STRINGS

    table = {k for k, _, _ in checker.parse_strings(menubar.LOCALIZATION_DIR / "fr.lproj" / "Backend.strings")}
    assert sorted(set(BACKEND_STRINGS) - table) == []


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_checker_matches_interpolations_to_specifiers(checker, tmp_path):
    write(
        tmp_path / "src" / "A.swift",
        'Text("Updated \\(when)")\nButton("Delete \\(count) rows") {}\n.help("Saved")\n'
        'let s = String(localized: "Net worth")\nText(verbatim: "TSX")\nText("Missing")\nText("%")\n'
        'Text("Up 5%")\nText("Up \\(n)%")\nText("Down \\(n)%")\n',
    )
    write(
        tmp_path / "loc" / "fr.lproj" / "Localizable.strings",
        '"Updated %@" = "Mis à jour %@";\n"Delete %lld rows" = "Supprimer %lld lignes";\n'
        '/* comment */ "Saved" = "Enregistré";\n"Net worth" = "Valeur nette";\n'
        '"Up 5%" = "Hausse de 5 %";\n"Up %lld%%" = "Hausse de %lld %%";\n"Down %lld%" = "Baisse de %lld %%";\n',
    )
    errors = checker.check(tmp_path / "src", tmp_path / "loc")
    assert errors == [
        "A.swift:6: 'Missing' has no translation in fr.lproj/Localizable.strings",
        "A.swift:10: 'Down %@%' has no translation in fr.lproj/Localizable.strings",
    ]


def test_checker_flags_bad_translations(checker, tmp_path):
    write(tmp_path / "src" / "A.swift", 'Text("A \\(x) of \\(y)")\n')
    write(
        tmp_path / "loc" / "fr.lproj" / "Localizable.strings",
        '"A %@ of %lld" = "%2$lld sur %1$@";\n"B %@" = "B";\n"C" = "";\n"D" = "1";\n"D" = "2";\n',
    )
    errors = checker.check(tmp_path / "src", tmp_path / "loc")
    assert len(errors) == 3
    assert "must keep the format specifiers" in errors[0] and "'B %@'" in errors[0]
    assert "empty translation" in errors[1]
    assert "translated twice" in errors[2]


def test_checker_reports_syntax_errors(checker, tmp_path):
    write(tmp_path / "src" / "A.swift", "")
    write(tmp_path / "loc" / "fr.lproj" / "Localizable.strings", '"A" = "B"\n"C" = "D";\n')
    assert "expected ';'" in checker.check(tmp_path / "src", tmp_path / "loc")[0]


def test_assembled_app_carries_translations(tmp_path):
    binary = write(tmp_path / "MarketPulseBar", "#!/bin/sh\n")
    app = tmp_path / "MarketPulse.app"
    plist = menubar.info_plist("MarketPulse", "dev.marketpulse.test", "1.0", menubar=False)
    menubar.assemble_app(app, binary, plist)
    resources = app / "Contents" / "Resources"
    assert (resources / "en.lproj" / "Localizable.strings").is_file()
    assert (resources / "fr.lproj" / "Localizable.strings").is_file()
    assert (resources / "fr.lproj" / "Backend.strings").is_file()
    with open(app / "Contents" / "Info.plist", "rb") as f:
        info = plistlib.load(f)
    assert info["CFBundleDevelopmentRegion"] == "en"
    assert info["CFBundleLocalizations"] == ["en", "fr"]
