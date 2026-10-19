# Install the Mac app

[Back to the README](../README.md) · [Native app guide](desktop.md) · [Data and backups](data.md)

`MarketPulse.app` runs on macOS 14 (Sonoma) or later, on Apple silicon and Intel Macs. It
carries its own copy of the MarketPulse engine, so you don't need Python, Homebrew, or
developer tools. Each [GitHub Release](https://github.com/BrendanH18/Marketpulse/releases)
from the first one after 2.1.0 has the app for both kinds of Mac.

## Install with one command (recommended)

Open **Terminal** (in Applications › Utilities) and paste:

```bash
curl -fsSL https://github.com/BrendanH18/Marketpulse/releases/latest/download/install.sh | bash
```

Piping a script from the internet into `bash` means trusting it, so
[read it first](../scripts/install.sh); it is under 200 lines. The script:

1. picks the build for your Mac (Apple silicon or Intel);
2. downloads that release's zip and its `SHA256SUMS` file with `curl`;
3. refuses to continue unless the zip's SHA-256 matches `SHA256SUMS`, the app inside is
   MarketPulse and the version you asked for, and its signature is intact;
4. installs `MarketPulse.app` into `~/Applications` (the Applications folder in your home
   folder), replacing an older copy, and opens it.

If MarketPulse is open, the script waits for you to quit it. Your portfolio in
`~/.marketpulse` is never touched; installing or upgrading replaces only the app.

To install a particular version, take the script from that release and name the version
(replace `v2.2.0` with the one you want):

```bash
curl -fsSL https://github.com/BrendanH18/Marketpulse/releases/download/v2.2.0/install.sh | bash -s -- --version v2.2.0
```

Other options: `--dir FOLDER` installs somewhere else (for example `--dir /Applications`,
if your account can write there), and `--no-open` doesn't open the app afterwards. Pass
options after `bash -s --`, as above; `bash -s -- --help` lists them all.

Why doesn't macOS ask about this app? Browsers mark the files they download as
"quarantined", and macOS checks quarantined apps with Apple. `curl` doesn't add that mark,
so the checks the script runs take the place of that prompt. See
[why the app is unsigned](#why-the-app-is-unsigned).

## Install from the DMG

1. On the [latest release](https://github.com/BrendanH18/Marketpulse/releases/latest), under
   **Assets**, download the DMG for your Mac: `MarketPulse-<version>-macos-arm64.dmg` for
   Apple silicon (M1 and later), or `-x86_64.dmg` for Intel. Not sure? Choose
   **About This Mac** from the Apple menu: "Chip: Apple M…" means Apple silicon; "Processor: … Intel" means Intel.
2. Optional but recommended: also download `SHA256SUMS` and
   [check the download](#verify-a-download).
3. Open the DMG and drag **MarketPulse** onto the **Applications** shortcut. Open the app
   from Applications, not from the DMG window.
4. macOS stops the first launch because the app isn't notarized by Apple:

   **macOS 15 (Sequoia) and later:**

   1. A dialog says "“MarketPulse” Not Opened" and that Apple could not verify it is free
      of malware. Click **Done** (not Move to Trash).
   2. Open **System Settings** (Apple menu) › **Privacy & Security** and scroll down to
      **Security**. It says "“MarketPulse” was blocked to protect your Mac."
   3. Click **Open Anyway**, then confirm with your password or Touch ID.
   4. In the next dialog, click **Open Anyway** again.

   The button appears only after you try to open the app, and for about an hour
   afterwards. If you don't see it, open MarketPulse again and go back to Privacy & Security.

   **macOS 14 (Sonoma):** Control-click (or right-click) MarketPulse in Applications,
   choose **Open**, then click **Open** in the dialog. The Privacy & Security route
   above also works.

You do this once per installed copy. Updating by dragging a newer DMG's app over the old
one asks again; the [install command](#install-with-one-command-recommended) doesn't.

The zip on each release has the same app; double-click it to unpack, move the app into
Applications, and follow step 4.

## Verify a download

Every release lists a SHA-256 checksum for each file in `SHA256SUMS`. In Terminal, in the
folder you downloaded to (usually `cd ~/Downloads`):

```bash
shasum -a 256 -c SHA256SUMS --ignore-missing
```

Each file you downloaded should print `OK`. Anything else means the download is damaged
or isn't what the release published; delete it and download again.

You can also check that nothing in the installed app changed after it was built:

```bash
codesign --verify --deep --strict ~/Applications/MarketPulse.app && echo intact
```

To not rely on downloads at all, build the app yourself from the release's tag with
`scripts/build_app.py` ([build guide](desktop.md#build-the-standalone-app)), or install
from a checkout with `marketpulse desktop install` ([native app guide](desktop.md)).
[SECURITY.md](../SECURITY.md#releases-and-verifying-downloads) describes how releases are
produced.

## Why the app is unsigned

Apple only lets apps skip its security prompt if they are signed with a paid Apple
Developer ID and notarized (scanned) by Apple. MarketPulse is a free, open-source project
and deliberately doesn't pay for one ([app plan](app-plan.md#decisions)). Its app is
*ad-hoc signed*: the signature proves nothing in the app changed after it was built, but
not who built it.

What you can rely on instead:

- Releases are built only by the project's public, tag-triggered
  [release workflow](../.github/workflows/release.yml) on GitHub's servers, never on
  anyone's own computer. The workflow checks every file before the maintainer publishes it.
- Every file has a published SHA-256 checksum, which the install command checks for you.
- The code is open, and anyone can build the same app from the release's tag.

## Update

Run the [install command](#install-with-one-command-recommended) again; it installs the
latest release over the old app. If you installed from the DMG, your copy is in
`/Applications`: add `-s -- --dir /Applications` after `bash`, or delete that copy so you
don't keep two. MarketPulse makes a daily safety backup while it runs;
to take one first, use **Automation › Back up now** in the app.

## Uninstall

1. If you turned on **Launch at login**, turn it off in the app's **Automation** view
   first. (Already deleted the app? Remove MarketPulse in System Settings › General ›
   **Login Items** — **Login Items & Extensions** on macOS 15 and later.)
2. Quit MarketPulse (⌘Q) and delete the app:

   ```bash
   rm -rf ~/Applications/MarketPulse.app   # the install command's copy
   rm -rf /Applications/MarketPulse.app    # the DMG's copy
   ```

   (or drag it from Applications to the Trash).
3. Remove the app's preferences:

   ```bash
   defaults delete dev.marketpulse.app
   ```

Your portfolio is **kept**: the ledger and backups stay in `~/.marketpulse`, and display
settings in `~/.config/marketpulse/config.toml`, shared with the command line and terminal
interface if you use them. To remove those too, first make sure you have a copy of anything
you want to keep (`~/.marketpulse/backups` holds the backups), then:

```bash
rm -rf ~/.marketpulse ~/.config/marketpulse
```

This deletes your portfolio permanently. If you set `MARKETPULSE_DATA` or
`MARKETPULSE_CONFIG`, your data is in those locations instead.

A checkout install (`marketpulse desktop install` or `menubar install`) is a separate app,
`~/Applications/MarketPulse Bar.app`, with preferences under `dev.marketpulse.bar`; remove it
the same way.
