# Release checklist — 0.1.0

## Prepared locally

- GPL-2.0-or-later approved; full LICENSE included in the source and package.
- README and packaged help explain purpose, installation, each setting, every
  button, shortcuts, diagnostics, privacy, recovery, upgrades and limitations.
- About the add-on provides readable author/version/license and purpose details.
- Installed pre-publication 0.1.0 verified against every source/package file;
  live Realtek stereo logs showed no playback errors, empty refills or recovery.
- Final package keeps 0.1.0 because no version has yet been published publicly.
  Install this final package to receive the expanded About/help content.
- Run `python -B -m unittest discover -s tests -v`, `python -B tools/ui_smoke.py`
  on a compatible Windows/NVDA development machine, then `python -B build.py`.
- Confirm the checksum and inspect the release package. `build.py` compares every
  packaged file to the current source. Audio tests are separate and explicit.

## Public export and publication

1. Publish only this add-on project, never its parent workspace. Include `addon/`,
   `tests/`, `tools/`, `build.py`, README, LICENSE, TEST-REPORT, this checklist and
   `.gitignore` and `.gitattributes`. Exclude private development instructions, machine logs,
   configuration, credentials, unrelated projects and test-results.
2. Confirm the destination GitHub account/repository and add its real HTTPS project
   URL to the manifest and README. Do not invent a repository URL.
3. Publish source and tag v0.1.0, preferably as an initial pre-release. Attach the
   `.nvda-addon` and `.sha256` files from the same verified build. Rebuild if the
   manifest changes. Publish corresponding source alongside the download.
4. Test the published download and checksum. After publication, never replace a
   release silently: use a new version/tag/checksum for subsequent changes.
5. NVDA Add-on Store submission is separate: follow the current official guide,
   verify compatibility/API versions and channel, and supply real source/download
   links and license metadata. GitHub hosting alone does not put it in the store.

## Honest release scope

Automated multichannel signal tests and real stereo playback passed. This is not
a promise of a cure for all HP drivers or all speaker power-saving behavior.
Before claiming broad stable hardware support, collect physical HDMI 5.1/7.1,
Bluetooth/USB, output unplug/replug, sleep/resume and extended-run feedback.
The UI is English-only. No microphone, network or automatic update feature exists.

Official submission guide:
https://github.com/nvaccess/addon-datastore/blob/master/docs/submitters/submissionGuide.md
