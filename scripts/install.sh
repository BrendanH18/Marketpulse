#!/bin/bash
# Install MarketPulse.app on macOS from a GitHub Release.
#
#   curl -fsSL https://github.com/BrendanH18/Marketpulse/releases/latest/download/install.sh | bash
#   bash install.sh --version v2.2.0
#
# The app is ad-hoc signed, not notarized (see docs/install.md). Browsers quarantine what they
# download and macOS blocks quarantined apps Apple hasn't notarized; curl doesn't quarantine, so
# this script installs without a security prompt. In exchange it checks what it downloaded:
# the zip must match the release's SHA256SUMS, and the app inside must be MarketPulse, the
# requested version, and carry an intact signature. Nothing is installed if any check fails.
#
# Every command runs from main(), at the end of the file, so a download cut short runs nothing.
set -euo pipefail

REPO="BrendanH18/Marketpulse"
APP="MarketPulse.app"
BUNDLE_ID="dev.marketpulse.app"
MIN_MACOS=14
TMP=""   # download folder
STAGE="" # unpack folder, next to the installed app

cleanup() { # keeps the exit status, which bash 3.2 would otherwise take from the trap
    local status=$?
    if [ -n "$TMP" ]; then rm -rf "$TMP"; fi
    if [ -n "$STAGE" ]; then
        # Interrupted between moving the old app aside and the new one in: put the old one back.
        if [ -d "$STAGE/previous.app" ] && [ ! -e "$STAGE/../$APP" ]; then
            mv "$STAGE/previous.app" "$STAGE/../$APP" || true
        fi
        rm -rf "$STAGE"
    fi
    exit "$status"
}

usage() {
    cat <<EOF
Install MarketPulse.app from a GitHub Release.

Usage: install.sh [--version vX.Y.Z] [--dir FOLDER] [--no-open]

  --version vX.Y.Z  Install this release (default: the latest release).
  --dir FOLDER      Install into FOLDER (default: ~/Applications).
  --no-open         Don't open the app after installing.
  --base-url URL    Download from a mirror of https://github.com/$REPO/releases
                    (same layout: URL/latest, URL/download/<tag>/<file>). The checksums
                    come from the mirror too, so only use a mirror you trust.
  -h, --help        Show this help.

Your portfolio in ~/.marketpulse is never touched. Reinstalling or upgrading replaces only the app.
EOF
}

say() { printf '%s\n' "$*"; }
die() {
    printf 'MarketPulse install: %s\n' "$*" >&2
    exit 1
}

fetch() { # fetch URL FILE
    curl --fail --silent --show-error --location --retry 3 --proto-redir =https --output "$2" "$1"
}

detect_arch() {
    local arch
    arch=$(uname -m)
    # A shell running under Rosetta reports x86_64 on Apple silicon; install the native app.
    if [ "$arch" = x86_64 ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || true)" = 1 ]; then
        arch=arm64
    fi
    case "$arch" in
        arm64 | x86_64) printf '%s' "$arch" ;;
        *) die "unsupported Mac architecture: $arch" ;;
    esac
}

latest_tag() { # latest_tag BASE_URL: follow the /latest redirect to .../tag/vX.Y.Z
    local url
    url=$(curl --fail --silent --show-error --location --retry 3 --proto-redir =https \
        --head --output /dev/null --write-out '%{url_effective}' "$1/latest") ||
        die "couldn't look up the latest release at $1/latest."
    case "$url" in
        */tag/*) printf '%s' "${url##*/tag/}" ;;
        *) die "couldn't find the latest release (got $url). Pass --version vX.Y.Z." ;;
    esac
}

plist_value() { # plist_value APP KEY
    plutil -extract "$2" raw -o - "$1/Contents/Info.plist" 2>/dev/null || true
}

app_is_running() { # app_is_running APP_PATH
    # Not `ps | grep -q`: grep exits at the first match, and pipefail then reports ps's SIGPIPE.
    # Not pgrep -f, which takes a regex; the path is matched literally.
    local processes
    processes=$(ps -Ao command=)
    case "$processes" in
        *"$1/Contents/"*) return 0 ;;
        *) return 1 ;;
    esac
}

main() {
    local version="" dest="$HOME/Applications" open_app=1 base_url="https://github.com/$REPO/releases"
    while [ $# -gt 0 ]; do
        case "$1" in
            --version | --dir | --base-url)
                [ $# -ge 2 ] || die "$1 needs a value (see --help)."
                case "$1" in
                    --version) version="$2" ;;
                    --dir) dest="$2" ;;
                    --base-url) base_url="${2%/}" ;;
                esac
                shift 2
                ;;
            --no-open) open_app=0 && shift ;;
            -h | --help) usage && return 0 ;;
            *) die "unknown option $1 (see --help)." ;;
        esac
    done

    [ "$(uname -s)" = Darwin ] ||
        die "MarketPulse.app is for macOS. The CLI and TUI run anywhere: https://github.com/$REPO#get-started"
    local macos
    macos=$(sw_vers -productVersion)
    [ "${macos%%.*}" -ge "$MIN_MACOS" ] || die "MarketPulse.app needs macOS $MIN_MACOS or later; this Mac has $macos."
    local arch
    arch=$(detect_arch)

    [ -n "$version" ] || version=$(latest_tag "$base_url")
    version="${version#v}"
    # Only plain version strings reach a URL or a path. ([[ =~ ]] matches the whole string; grep
    # would accept one good line of several.)
    local plain='^[0-9]+\.[0-9]+\.[0-9]+([.+-]?[0-9A-Za-z]+)*$'
    [[ $version =~ $plain ]] || die "\"$version\" isn't a version like v2.2.0."
    local tag="v$version" zip="MarketPulse-$version-macos-$arch.zip"

    trap cleanup EXIT
    TMP=$(mktemp -d "${TMPDIR:-/tmp}/marketpulse-install.XXXXXX")

    say "Downloading MarketPulse ${version} for ${arch}…"
    fetch "$base_url/download/$tag/SHA256SUMS" "$TMP/SHA256SUMS" ||
        die "couldn't download SHA256SUMS for $tag. Check that the release exists and has Mac app downloads: https://github.com/$REPO/releases"
    fetch "$base_url/download/$tag/$zip" "$TMP/$zip" ||
        die "couldn't download $zip from release $tag."

    local expected actual
    expected=$(awk -v name="$zip" '$2 == name { n++; hash = $1 } END { if (n == 1) print hash }' "$TMP/SHA256SUMS")
    [[ $expected =~ ^[0-9a-f]{64}$ ]] || die "SHA256SUMS for $tag has no single entry for $zip."
    actual=$(shasum -a 256 "$TMP/$zip" | awk '{ print $1 }')
    [ "$actual" = "$expected" ] ||
        die "$zip doesn't match its checksum in SHA256SUMS (expected $expected, got $actual). Nothing was installed."
    say "Checksum verified: $actual"

    mkdir -p "$dest"
    dest=$(cd "$dest" && pwd -P)
    local target="$dest/$APP"
    if [ -L "$target" ] || { [ -e "$target" ] && [ "$(plist_value "$target" CFBundleIdentifier)" != "$BUNDLE_ID" ]; }; then
        die "$target exists but isn't a MarketPulse app; move it away and run this again."
    fi

    # Unpack next to the target, so the final move is a rename on the same disk.
    STAGE=$(mktemp -d "$dest/.marketpulse-install.XXXXXX")
    ditto -x -k "$TMP/$zip" "$STAGE"
    [ -d "$STAGE/$APP" ] || die "$zip doesn't contain $APP."
    [ "$(plist_value "$STAGE/$APP" CFBundleIdentifier)" = "$BUNDLE_ID" ] || die "$zip doesn't contain MarketPulse."
    [ "$(plist_value "$STAGE/$APP" CFBundleShortVersionString)" = "$version" ] ||
        die "$zip contains MarketPulse $(plist_value "$STAGE/$APP" CFBundleShortVersionString), not $version."
    codesign --verify --deep --strict "$STAGE/$APP" 2>/dev/null || die "$APP's signature doesn't verify; it was changed after it was built."

    if app_is_running "$target"; then
        say "MarketPulse is open. Quit it (⌘Q) to continue; waiting up to 5 minutes…"
        local waited=0
        while app_is_running "$target"; do
            [ "$waited" -lt 300 ] || die "MarketPulse is still open. Quit it and run this again."
            sleep 1
            waited=$((waited + 1))
        done
    fi

    if [ -e "$target" ]; then
        mv "$target" "$STAGE/previous.app"
    fi
    if ! mv "$STAGE/$APP" "$target"; then
        [ ! -e "$STAGE/previous.app" ] || mv "$STAGE/previous.app" "$target"
        die "couldn't move the new app into $dest."
    fi
    say "Installed MarketPulse $version to $target"
    say "Your portfolio stays in ~/.marketpulse. To uninstall, see https://github.com/$REPO/blob/main/docs/install.md#uninstall"

    if [ "$open_app" = 1 ]; then
        open "$target"
    fi
}

main "$@"
