# Angel Audio Keeper 0.1.0 qualification

September 17, 2026. Follow-up work began 14:48:04 UTC.
Qualification completed 15:03:53 UTC, about 16 minutes including packaging checks.

## Changes

- Independent noise for every channel exposed by the selected Windows output,
  enabled by default when playback is enabled. No separate surround checkbox.
- Channel-mask decoding provides readable front/center/LFE/back/side/top names
  where supplied by the endpoint; unknown layouts are honestly numbered.
- The noise pool is bounded to 192,000 total source samples, independent of
  output sample rate and channel count, and includes per-channel DC reduction.
- PCM quantization is clamped so rounding cannot exceed the selected digital peak.
- Volume uses per-stream channel gain, applied before playback begins. Live
  changes do not rebuild noise or reopen the stream. A failed initial gain change
  prevents playback instead of starting at an unintended level.
- Randomized wrap positions reduce short-loop repetition; PCM multichannel
  channel ordering and wrap behavior have explicit regression tests.
- Version is 0.1.0. Existing settings/logs remain outside the installed add-on.

## Tests

- All 39 automated unit/integration tests passed, plus one hidden real-wx
  settings-panel check and a ten-second native silent-render probe.
- Automated tests exercise independent float32 signals for mono, stereo, 5.1,
  7.1 and 32-channel formats, plus float64 surround and PCM16/24/32 layouts.
- Stereo/front-left versus other-channel correlations are checked below 0.1
  using deterministic samples; every tested channel has nonzero signal.
- 7.1 masks explicitly cover center, LFE, rear and side channels. Fades, ring
  wrap, frame alignment, amplitude limits and high-rate memory bounds are tested.
- Existing recovery, global persistence, emergency stop, disabled/secure-mode,
  logging bounds/error handling and live-settings regression tests remain covered.
- Tests verify gain is set before any samples are queued, a gain-setting failure
  never starts playback, and live volume updates never reconstruct the noise pool.
- Hidden real-wx settings controls are checked using the installed NVDA 2026.2 wx
  runtime and doubled NVDA host APIs. No running screen reader is replaced.
- A bounded 180-second zero-volume Windows shared-render check is recorded in
  the local `test-results/windows-engine-qualification.json`.
  Final result: 8,643,840 frames in 5,783 buffers, zero empty refills, zero
  recoveries, clean stop, 1.953 seconds process CPU over 180.016 seconds elapsed.
  Whole test-process working memory ranged from 26,988,544 to 27,152,384 bytes.
  This used the final per-stream volume implementation on the Realtek endpoint.

The available physical output is Realtek stereo, 48 kHz, float32. Surround signal
generation/layout is software-tested; no connected physical HDMI surround receiver
was available for an acoustic test. The add-on uses the endpoint's configured PCM
mix format. It cannot make a stereo-configured HDMI output into physical 5.1/7.1.
LFE playback is subject to downstream receiver filtering and may not sound like
the other speakers.

## Installed-use baseline

The user reports the first build works. Its logs showed ongoing playback, live
volume adjustments, zero empty refills and no recoveries/errors during inspection.
This update's package is prepared for the user to replace that installed build.
No NVDA restart or automatic installation is performed by the build/test process.

## Final publication preparation

September 17, 2026, starting 15:17:07 UTC: every installed manifest, help and source
file matched the supplied pre-publication 0.1.0 package. NVDA 2026.2 loaded it at
11:15 local time. Live logs confirmed preserved settings and independent left/right
playback on Realtek 48 kHz float32, with zero empty refills or recoveries.
The main NVDA log also contained transient focus/COM errors and brief recovered
UI freezes; those stack traces did not identify this add-on. They are not counted
as Audio Keeper failures, nor is the overall NVDA session claimed error-free.

Final changes add an accessible About button, expanded manifest description,
comprehensive public documentation and the approved GPL-2.0-or-later license.
Playback/DSP behavior is unchanged from the installed and qualified build.
All 40 unit/integration tests passed. The hidden real-wx check also passed,
including dispatch of the About button to NVDA's readable-message interface.
No live NVDA restart, installation or publication is performed during this pass.
Final package: 25,852 bytes, SHA-256
`576f975790e8d4a63b55105ed287993a50983922b4903a5d8faced5ba32c0938`.
Installed audio remained healthy through 11:21:51 local, with zero empty refills
and recoveries. Final preparation completed at approximately 15:22 UTC; elapsed
time about five minutes. Public files were checked for private machine paths and
development-tool references; none were found. Only add-on files and LICENSE.txt
are included in the installation package.

## GitHub publication build

The public 0.1.0 package adds the actual AngelsClan project links to the manifest
and help, without changing playback code. All 40 tests and the real-wx check
passed again. This supersedes the earlier unpublished package checksum above.
Public package size: 25,962 bytes. SHA-256:
`76b6551ca3e208495b11ccd846537594ff0aa95bb1d2075ea91434999c5c6dcc`.
Repository attributes preserve file bytes across checkouts for reproducible builds.

## Release integrity

The build syntax-checks source, validates the ZIP, and emits a SHA-256 sidecar.
Packaged files are compared byte-for-byte with current source before handoff.
Old test-package artifacts are removed only after the replacement passes checks.
Historical development records and machine-specific logs are kept outside the
public-facing documentation and are not part of the .nvda-addon package.

## September 23 source update, still version 0.1.0

The source now supports Follow NVDA output, Follow Windows default, one or
several selected outputs, and all active outputs (up to 16). Existing saved
single-output choices migrate without rewriting the settings file. One worker
keeps separate streams and retries for each endpoint. Profile changes update
the NVDA-follow target without changing Audio Keeper's global preferences.

Sixty unit and integration tests passed, including migration, per-device
failure isolation, hotplug, default and NVDA output changes, a bounded stop,
and multi-output gain. The hidden real-wx panel check passed two checked
outputs, Apply and Stop. A silent native Windows run opened all nine active
render endpoints on the test machine, then two selected outputs and one
NVDA-follow output, with no reported stream errors. The exact packaged add-on
loaded disabled with all five modes in a separate NVDA desktop. It was not
installed in the owner's live NVDA. The existing GitHub release asset predates
this source update; no new release or version change was made.
