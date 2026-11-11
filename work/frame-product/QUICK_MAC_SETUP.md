# Run Frame locally on macOS

Use these instructions from the `work/frame-product` directory of your checkout. For an installed connector, use its managed launcher instead; it may have a different address and project store.

## Start in a terminal

Install **Python 3.9 or newer** and **FFmpeg/ffprobe** (`brew install ffmpeg` if needed), then run:

```sh
sh start-local.sh
```

First run creates `.venv` and installs Pillow, requests, and numpy. This setup needs an internet connection. If setup is interrupted, rerun the command: the launcher retries missing dependencies and preserves saved projects. A ready environment starts without reinstalling dependencies.

After the service starts, open **http://127.0.0.1:8876/frame**. The launcher does not open your browser. Keep the terminal running, and stop with Ctrl+C.

For a different free port:

```sh
PORT=8877 sh start-local.sh
```

Then open `http://127.0.0.1:8877/frame`. Do not run multiple services on the same port.

## Optional background process

The macOS-only launcher runs the service through launchd so closing the terminal does not stop it:

```sh
sh restart-local.sh
```

The default port is **8876**; use `PORT=8877 sh restart-local.sh` to choose another free port. The helper checks that the responding server belongs to this checkout before reporting it ready. It waits through delayed startup instead of testing only once. If the startup check times out, dependency setup may still be running: the job is left alone, and the message points to its log. Check that log before running another copy:

```sh
tail -40 "${XDG_STATE_HOME:-$HOME/.local/state}/frame-quick-edit/editor.log"
```

Once startup completes, open the printed `/frame` address (using your chosen port). To stop this specific background service:

```sh
launchctl remove com.dantegarcia.frame-quick-edit.local
```

It is not installed as a login item. Do not run the foreground and background launchers together on port 8876.

## Edit and save

Import an H.264/AAC MP4 up to five minutes and 700 MB. Seek and press **I** for a section start, then **O** for its end. Add the change in the saved section's notes; use **Preview** and **Adjust** to check its range. Export and download the completed MP4. Projects remain in this checkout's `jobs/` directory after stopping the service.

Manual edits, preview, export, and audio-energy pause detection need no model login. A standalone browser page does not automatically connect to a chat. See [README.md](README.md) for connected workflows and troubleshooting.
