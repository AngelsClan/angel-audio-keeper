# Angel Audio Keeper

[Download 0.1.0](https://github.com/AngelsClan/angel-audio-keeper/releases/tag/v0.1.0)
· [Report an issue](https://github.com/AngelsClan/angel-audio-keeper/issues)

An NVDA add-on from Angels Clan. It maintains an independent, continuous
shared-mode audio stream, even when NVDA is not speaking. The intended use is to
reduce audio-device idle/wake delays and clipped speech on affected hardware.

**Version: 0.1.0. Initially disabled on fresh installation.** Prepared for NVDA 2026.1–2026.2 on
Windows; local qualification includes an installed NVDA 2026.2 session on Windows
11/Realtek stereo, automated tests and real wx controls. This initial release is
not a verified fix for HP audio enhancements or a guarantee for every sound device.
NVDA 2026.1 is the declared minimum, not a separately hardware-tested version.
See `TEST-REPORT.md` for results and remaining hardware tests.

## About the add-on and its purpose

Some speakers, headphones and audio drivers go idle between sounds. Waking them
can clip the beginning of NVDA speech or cause a delay. Audio Keeper supplies a
continuous, very quiet render stream to the selected Windows output independently
of speech. It can help where speech-only keep-awake features do not, but hardware
can still apply its own power-saving rules. Use the lowest effective noise level.

It does not boost your microphone, change speech routing, repair drivers, disable
enhancements, or control other applications. Optional keep-awake requests concern
computer/display idle sleep, not microphone or speech settings. These options are
separate from keeping the audio stream active.

The **About the add-on** button in the Audio Keeper settings opens readable text
with version, author, purpose, privacy, safety and support limitations. The add-on
details also contain a purpose summary; its Help opens the packaged manual.

## Install and first test

1. Save work that needs uninterrupted NVDA speech. Download the `.nvda-addon`
   asset from this project's GitHub Releases when published, not GitHub's source
   ZIP. For a local build use `dist/AngelAudioKeeper-0.1.0.nvda-addon`.
   Open the file in File Explorer and press Enter.
2. Review NVDA's installation prompt and accept if you want this test build.
   Restart NVDA when prompted. A Windows reboot is not needed. We have not
   installed the add-on automatically or restarted your current screen reader.
3. Open **NVDA menu > Preferences > Settings > Audio Keeper**. If the category
   does not appear, check NVDA's Installed Add-ons list for disabled/incompatible
   status and its log for an import error.
4. Select your named speakers, headphones or HDMI output, or select
   **Follow Windows default (multimedia)** to follow Windows' default output.
   The output list is populated asynchronously and updates automatically. Use
   **Refresh output list** to request another scan after plugging in a device.
5. Leave noise volume at **5** to begin. Check **Enable continuous audio**, then
   Apply or OK. The choice also controls automatic activation on later NVDA
   starts. Do not enable the computer/display keep-awake boxes unless wanted.
6. Wait a few seconds and use **Refresh status**. Expect **Playing**, your chosen
   output, format/channel count, and increasing frame/buffer counters.
7. Test normal speech after an idle interval that previously caused clipping or
   stuttering. The noise need not be audible to be useful. Increase gently only
   if necessary. Do not raise the Windows master volume to test this.

**Stop at any time:** press **NVDA+Shift+F12**, or use **Stop audio now** in the
settings category. This takes effect without restarting NVDA. A small amount of
already queued audio can finish. The setting is saved globally; changing NVDA
profiles cannot silently undo your stop. Cancel does not undo an emergency stop.
Gestures can be reassigned under **Preferences > Input gestures > Audio Keeper**;
toggle and report-status commands are also available there, unassigned by default.

If another continuous-audio add-on such as Bluetooth Audio Active is enabled,
consider disabling that other add-on for a clean comparison. Do this through
NVDA's add-on controls, not by deleting its files. Existing add-ons and NVDA's
built-in speech keep-awake setting are not changed by this package.

## Settings

- **Enable continuous audio:** starts the stream now and on future NVDA starts.
  Stops with NVDA; does not run as a service, at shutdown, or in NVDA secure mode.
- **Audio output:** one named render endpoint, or Windows default multimedia
  output. A selected missing endpoint is retried; it does not unexpectedly switch
  to another speaker. Default changes are checked approximately every two seconds.
- **Noise volume:** 0–100 in a deliberately quiet range. At 100 the generated
  peak is limited to 1% of digital full scale (−40 dBFS); 5 is 0.05% peak, about
  −66 dBFS. These are digital sample amplitudes, not a physical loudness guarantee.
  Amplifiers/headphones can still make low-level noise audible. Zero outputs
  silence, which drivers may optimize away; it is mainly useful for diagnostics.
- **Channels:** automatically uses every channel exposed by that output's mix
  format. Stereo stays stereo. Supported surround layouts include their exposed
  channels, including LFE where present. It does not manufacture physical speakers,
  use every separate device, or override Windows/NVDA speech routing.
  Version 0.1.0 generates independent noise per channel by default, not a mono
  signal duplicated into each channel. Status/logs list the exposed speaker names.
  HDMI works the same way: select the HDMI output or let Windows default follow it.
  For 5.1/7.1 the receiver and Windows speaker configuration must expose that
  layout; an HDMI endpoint configured as stereo still has only two channels.
  Center, side, rear and LFE channels receive samples when present. An LFE output
  may be filtered by the receiver and need not produce clearly audible static.
- **Keep computer awake / Keep display awake:** independent opt-in Windows power
  requests while playback is active. No power-plan changes, no simulated input,
  and no attempt to prevent a deliberate sleep/shutdown or critical-battery action.
  By default these requests are withheld on battery. The audio stream itself can
  also affect idle sleep on some drivers even with these boxes unchecked.
- **Allow keep-awake requests on battery power:** off by default. When off, the
  computer/display requests above are withheld on battery; audio itself continues.
  When on, the selected requests also apply on battery and can reduce battery life.
- **Detailed diagnostic logging:** adds a ten-second activity summary instead of
  the normal sixty-second summary and additional buffer diagnostics. Errors and
  transitions are logged at both levels. It does not record audio.

Volume uses Windows' per-stream channel gain for this add-on only, not the device,
NVDA speech, or session master volume. It is set before playback starts. Live
volume changes do not regenerate the noise pool or interrupt buffer refilling.
The bounded noise pool uses randomized wrap positions to avoid an identical short
loop on high-rate multichannel devices.

Apply/OK saves and activates changes. Volume, diagnostic and power-option changes
do not reopen the stream. Selecting another output necessarily closes the old
output and opens the new one. Disabled mode performs no audio-device polling
unless you open/refresh its settings. Failed playback retries at 1, 2, 4, 8, 16,
then 30-second intervals; an unavailable output cannot be made to produce sound.
Settings-file writes are synchronous; a redirected or stalled network configuration
folder can delay the settings UI. This test build is qualified with a local NVDA
configuration folder. Emergency Stop requests audio stop before attempting a save.

### Buttons, saving and defaults

- **Refresh output list:** scans currently available outputs in the background.
- **Refresh status:** updates the read-only status and counters without repeated
  speech announcements. Counters are cumulative for the current worker session.
- **Copy diagnostic summary:** copies status and diagnostic paths, not audio.
- **Open log folder:** opens the local diagnostic folder in File Explorer.
- **About the add-on:** opens its accessible information page; changes no settings.
- **Stop audio now:** disables playback and saves that choice immediately. Cancel
  will not undo it. The emergency keyboard shortcut does the same thing.
- **Apply / OK:** save and apply the displayed settings. **Cancel** discards
  unsaved edits, but not settings already applied or the emergency stop.

Fresh-install defaults: disabled; follow Windows multimedia default; volume 5;
all exposed channels; computer/display/battery keep-awake and detailed logging off.
The channel behavior is automatic, not another setting to configure. Language is
English in this initial release. Installation does not require administrator rights
when using an existing ordinary-user NVDA configuration.

## Logs and privacy

Use **Copy diagnostic summary** or **Open log folder** in the settings category.
The status is explicitly refreshed; it does not repeatedly interrupt your speech.
The add-on creates these files under the active NVDA configuration directory:

- `angelAudioKeeper.json`: global add-on settings, atomically replaced on save.
  Not per application profile. Does not save or alter unrelated NVDA settings.
- `angelAudioKeeperLogs/audio-keeper.log`, `.1`, `.2`, `.3`: current and rotated
  logs, at most four files of approximately 512 KiB each (about 2 MiB total).

For a usual installed NVDA, the log directory is
`%APPDATA%\nvda\angelAudioKeeperLogs`.
Portable NVDA uses its own configuration directory instead.

Logs include local timestamps, versions, selected/actual output names and device
IDs, format, channel mask, buffer counts, errors/retries, and power-request
transitions. Diagnostic summaries include the log folder path. These may identify
your Windows user/device, so review them before sharing publicly. There are **no
microphone recordings, speech text, audio recordings, credentials, networking or
automatic uploads**. Device IDs are endpoint identifiers, not hardware tracking.

Increasing buffer/frame counters show ongoing submission to Windows, not proof
that a physical speaker remains powered. Empty-buffer refill counters are a
diagnostic clue, not a guaranteed audible-glitch count. Very slow or stuck driver
calls cannot be forcibly cancelled safely from Python; shutdown waits at most
one second for this worker and logs a failure if it cannot finish in time.

## What we need you to test

1. Confirm the category is accessible and that enable/stop and output choices work.
2. Confirm normal NVDA/TeamTalk audio remains usable while playback is enabled.
3. Leave speech idle for the interval that caused trouble, then read a short line.
   Compare clipping/stuttering to disabled mode. No need to listen for the noise.
4. Report whether enhancements actually change. If they do, provide the time and
   diagnostic log: this build does not change or guarantee preservation of those
   driver settings.
5. When convenient, test ordinary sleep/resume and output changes. Do not do these
   in the middle of a call. Real HP idle behavior still requires your observation.

## Remove or recover

First use the stop shortcut. To disable/remove the add-on, use NVDA's Installed
Add-ons interface and restart NVDA when prompted. If necessary start NVDA with
add-ons disabled (`--disable-addons`) to recover access. Removing the add-on does
not delete its settings or logs automatically; these are small and can be removed
later after troubleshooting. Existing screen-reader and Windows audio settings
are not modified, so there is no driver/power-plan rollback to perform.

## Troubleshooting

- **No audible static:** low volumes are intentionally quiet. Check enabled state,
  selected output and increasing counters. A muted endpoint or silent value 0
  cannot prove hardware stays awake. Do not raise volume sharply to test it.
- **Only left/right on HDMI:** configure surround in Windows and on the receiver.
  Status lists what Windows actually exposes. The add-on cannot create missing
  speakers or force stereo HDMI to 5.1/7.1. Receiver filtering may suppress LFE hiss.
- **Waiting to recover:** connect the selected output or choose an available one.
  A missing named output does not fall back to a potentially unexpected speaker.
- **Computer stays awake unexpectedly:** inspect both keep-awake options. Even
  with those disabled, some drivers treat an active audio stream as activity.
  Stop Audio Keeper to compare; it cannot override critical-battery shutdown.
- **Speech still clips or enhancements return:** this may be a driver/device
  limitation. Stop and compare, note the time, and share a redacted summary/log.
  Do not assume increasing noise indefinitely will fix it.
- **Settings fail to save:** inspect the log-folder permissions and disk space.
  Emergency Stop still signals the worker, but if saving fails audio could restart
  on the next NVDA launch. Corrupt settings start disabled, without overwriting the
  original file automatically.

For a bug report include Windows/NVDA/add-on versions, endpoint type and channel
layout, what you expected, what happened, and approximate time. Review diagnostics
for personal paths/device identifiers. Avoid uploading your entire NVDA log or
configuration, which may contain unrelated sensitive information.

## Development and reproducibility

Source lives in `addon/globalPlugins/angelAudioKeeper`. Python standard library
and NVDA's wx/settings/script APIs only. No pip installation, external service,
native custom DLL or private NVDA audio DLL ABI is required. NVDA's frozen Python
omits `logging.handlers`, so a small bounded handler is included instead.

```
python -B -m unittest discover -s tests -v
python -B tools/probe.py
python -B tools/ui_smoke.py
python -B build.py
```

`probe.py` only queries endpoints unless `--silent-test SECONDS` is explicitly
provided. `tools/qualify.py` performs a 180-second zero-volume render test, toggles
logging live, checks resources and writes a result under `test-results`. It does
not install an add-on or claim to test audible noise effectiveness. Do not run
audio tests on someone else's machine without permission.

`build.py` syntax-checks code, packages only `addon/`, validates the ZIP, and emits
a SHA-256 file. Repeated builds of the same sources are byte-for-byte reproducible.
The checksum detects a changed download; it is not publisher code signing.

Source and releases: https://github.com/AngelsClan/angel-audio-keeper

## License

Copyright 2026 Angels Clan. Angel Audio Keeper is free software: you may
redistribute and/or modify it under the GNU General Public License as published
by the Free Software Foundation, either version 2, or (at your option) any later
version. It is distributed without any warranty; without even the implied
warranty of merchantability or fitness for a particular purpose. See [LICENSE](LICENSE)
for the full terms. The installation package contains the same text as LICENSE.txt.
NVDA and Windows remain separate products with their own licensing.

## Publishing this release

See [RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md). The first publication
is a GitHub pre-release of 0.1.0 so more users can test their sound devices.
GitHub publication does not automatically submit an add-on to the NVDA Add-on Store.
No upload, account access or update checker is built into this add-on.

## Upgrade from the first test build

Open the new 0.1.0 package, accept replacement of the installed Angel Audio Keeper
add-on, and restart NVDA when prompted. Settings and logs are stored outside the
add-on and are retained, including your enabled state and chosen volume. Do not
uninstall first. The old test package is removed from `dist/` once its replacement
passes validation. The installation on your machine is not changed by building.

## 0.1.0 changes

- Independent channel noise by default, including all exposed surround channels.
- Clear channel names in diagnostics and logs; supports HDMI's configured PCM layout.
- Noise pool bounded by total sample count, even for high-rate multichannel outputs.
- Integer sample quantization clamped so rounding cannot exceed the selected peak.
- Live volume adjustment uses per-stream gain, with no noise-pool rebuilding.
- Randomized wrap positions avoid repeating an identical short noise loop.
- Numeric version 0.1.0; no settings migration or reset required.

## Technical references

- [NVDA developer guide](https://download.nvaccess.org/documentation/developerGuide.html)
- [Microsoft shared-mode rendering](https://learn.microsoft.com/en-us/windows/win32/coreaudio/rendering-a-stream)
- [IAudioClient initialization](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclient-initialize)
- [Device mix formats](https://learn.microsoft.com/en-us/windows/win32/coreaudio/device-formats)
- [Windows execution-state requests](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate)
