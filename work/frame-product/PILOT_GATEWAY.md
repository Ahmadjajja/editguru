# Frame invite-only pilot gateway

This is a separate, Edge-voice-only gateway for the October 31 unified Frame app. It forwards only the Frame homepage, its two assets, the simple project API, and owned Frame media. It does not expose Studio, the footage editor, imports, Fish connection/quote/render actions, or pre-existing projects.

## Required topology

```text
tester browser --HTTPS--> trusted TLS proxy --loopback--> pilot gateway :18780
                                                  \--loopback--> clean Katana backend :8780
```

Run the backend from this clean `work/frame-product` package. Do not copy saved `studio-jobs`, `jobs`, credentials, tests, backups, or personal data from the original local app. Keep both Python servers bound to loopback. The TLS proxy must preserve the original `Host` header and forward only to the gateway. Do not publish the backend port. The gateway has a seven-day session cookie (`Secure`, `HttpOnly`, `SameSite=Strict`); each invitation is bound to one owner in a private SQLite database. Back up the SQLite database and keep `PILOT_SECRET` stable across restarts so saved request IDs remain recoverable.

The backend still needs its model/FFmpeg dependencies and a working AI planning connection. Edge speech uses its online service; this route spends no Fish credits. Configure the backend as a low-privilege service account with enough disk and a private writable `studio-jobs` directory. The public origin must be HTTPS. The gateway is a narrow pilot boundary, not a production identity or abuse-control system.

## Start

```sh
export PILOT_ORIGIN='https://YOUR-PILOT-HOST'
export PILOT_SECRET='REPLACE-WITH-A-STABLE-RANDOM-SECRET-AT-LEAST-32-CHARS'
export BACKEND_PORT=8780
export PILOT_PORT=18780
python3 server.py serve --db /private/path/frame-pilot.sqlite3
```

In another process, start the clean backend with `PORT=8780 python3 app.py`. Example Caddy route: `YOUR-PILOT-HOST { reverse_proxy 127.0.0.1:18780 }`. Restrict both local server ports with the host firewall. Set the host's public DNS and TLS before sending an invitation.

Create one invitation per tester:

```sh
python3 server.py invite --db /private/path/frame-pilot.sqlite3 --owner tester_one --days 7
```

The command prints an invitation code; send it privately. The tester opens `https://YOUR-PILOT-HOST/pilot/login`, enters the code, and is redirected to Frame. The invite is reusable until expiry; a separate session is created on each login. Do not put the invite in a URL. Revoke a tester's invitation and active sessions with `python3 server.py revoke --db /private/path/frame-pilot.sqlite3 --owner tester_one`. Existing projects remain on disk until separately deleted.

## Verification

`python3 -m unittest -v test_server.py` exercises invitation login, session isolation, route blocks, Edge-only generation, replay ID mapping, origin/size limits, and media byte ranges against a fake backend. It does not certify the live backend, TLS proxy, planning service, speech quality, or a remote tester's browser. After starting the real stack, use one invitation to complete an Edge video, revision, playback, and download. Use a second invitation to confirm that the first project's list, detail URL, and media URL all return 404 or an empty list.

## Intentional limits

- The pilot permits only the explicit Edge preview narrator. Fish generation and imported saved demos are blocked.
- Existing advanced voice, references, overlays, and footage editing routes are outside this public pilot.
- The backend's script limit is 80 words / 1,800 characters and approximately one minute; the gateway caps JSON writes at 12 KB.
- The gateway does not make a judgment about voice acting, visual quality, or publishability.
- Each invitation permits two generated projects. Each project permits two visual revisions and one retry. Repeating an already accepted request ID does not consume another slot. These are lifetime pilot limits for the invitation owner, enforced by the gateway database.
