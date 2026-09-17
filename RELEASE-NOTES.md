# Angel Audio Keeper 0.1.0

Initial public pre-release from Angels Clan, licensed under GPL-2.0-or-later.

Keeps one selected audio output active with quiet continuous noise independently
of NVDA speech. Intended to help reduce device wake delays and clipped speech on
affected hardware, without changing microphone, speech or Windows master volume.

## Included

- Accessible NVDA settings and About information.
- Default or named audio output selection and adjustable quiet noise volume.
- Independent noise on all channels exposed by that output, including HDMI
  surround when Windows and the receiver are configured for it.
- Optional, separate computer/display keep-awake requests with battery control.
- Bounded local diagnostic logs, copied summaries and recovery on device failure.
- Persistent global settings and emergency stop: NVDA+Shift+F12.
- No microphone capture, network access or automatic uploads.

## Install

Download **AngelAudioKeeper-0.1.0.nvda-addon** below, open it, accept installation
or replacement, and restart NVDA when prompted. Do not uninstall an older test
build first: settings and logs are retained. Fresh installs start disabled.
Open NVDA Preferences > Settings > Audio Keeper; select an output, start at volume
5, enable continuous audio, then Apply. The checksum file is provided below.

This final package retains version 0.1.0 from the privately tested builds and adds
the completed help, About information, license and official project links.
Once published, later changes will use a new version instead of replacing this one.

## Tested scope

40 automated tests and a real-wx settings check passed. A three-minute native
Windows render test completed with zero empty refills or recoveries. Installed
playback was verified on NVDA 2026.2, Windows 11 and Realtek stereo.

Surround signals/layouts are software-tested, not an acoustic test of a physical
HDMI receiver. Hardware idle behavior varies; this is not a guaranteed cure for HP
enhancements or every sound device. NVDA 2026.1 is the declared minimum, not a
separate hardware-qualified version. Initial UI/help language is English.
Please report device-specific results. See README and TEST-REPORT for details.

This GitHub release is not an NVDA Add-on Store listing.
