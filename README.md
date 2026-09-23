# Angel Audio Keeper

[Download 0.2.0](https://github.com/AngelsClan/angel-audio-keeper/releases/tag/v0.2.0) · [Report an issue](https://github.com/AngelsClan/angel-audio-keeper/issues)

Angel Audio Keeper is an NVDA add-on that sends very quiet sound to an output device while NVDA runs. On hardware that sleeps between sounds, it may reduce wake delay or clipped speech. It does not change NVDA's voice, repair drivers, change Windows enhancements, or record speech. Fresh installs start disabled.

## Install and start

1. Download the `.nvda-addon` from the release, open it, accept NVDA's installation prompt, and restart NVDA. Upgrading keeps your settings.
2. Open **NVDA menu > Preferences > Settings > Audio Keeper**.
3. Choose the output mode. **Follow NVDA's configured output** is a useful starting point when headphones or NVDA profiles change.
4. Leave **Noise volume** at 5 initially. Check **Enable continuous audio**, then choose **Apply** or **OK**. Use **Refresh status** to check its state.

Press **NVDA+Shift+F12** or choose **Stop audio now** to stop immediately and save the disabled state. Change the shortcut in NVDA's Input Gestures if needed.

## Output modes

| Mode | What stays active |
| --- | --- |
| Follow NVDA's configured output | NVDA's chosen device, including profile changes. |
| Follow Windows default | The current Windows default multimedia output. |
| One selected output | One named device you choose. |
| Several selected outputs | Each device you check. |
| All active outputs | Every active playback device found, up to 16. |

Each selected device has its own quiet stream. If headphones disconnect, a working speaker stream can continue. A missing named device is retried when it returns. All active outputs can use more power and produce sound on devices you are not currently using.

The add-on generates separate noise for every channel the device exposes, including surround channels when available. It cannot turn a stereo device into surround sound. Volume 0 sends silence and may not keep hardware awake. The volume controls only this add-on, not NVDA or Windows master volume.

## Other settings and limits

Optional computer and display keep-awake settings defer idle sleep while Audio Keeper runs. They start off and are withheld on battery unless explicitly allowed. Deliberate shutdown and critical battery protection are unaffected.

**Copy diagnostic summary** and **Open log folder** help with troubleshooting. Logs contain device names and technical status; review them before sharing. They contain no speech or audio recording and are kept locally. Nothing is uploaded.

Effectiveness depends on hardware. The add-on cannot guarantee that an audio enhancement stays disabled. Playback was tested with NVDA 2026.2 on Windows 11 and Realtek stereo. NVDA 2026.1 is the declared minimum; physical HDMI surround and other devices need more user testing. See [test evidence](TEST-REPORT.md) and the add-on's help.

## Other voice projects

Audio Keeper makes no speech. The [Legacy Voice Bridge](https://github.com/AngelsClan/angel-legacy-voice-bridge) connects NVDA to older SAPI 5 voices inside Windows XP. Optional **Lion Voices**, **Snow Leopard Voices**, **Leopard Voices**, and **Tiger Voices** add-ons run their corresponding MacinTalk engines locally on Windows. Audio Keeper can coexist with all of them.

## For contributors

Run `python -m unittest discover -s tests -q`, `python tools/ui_smoke.py`, and `python build.py`. The build places the add-on and SHA-256 checksum in `dist/`. Source is [GPL-2.0-or-later](LICENSE). No proprietary voices are included.
