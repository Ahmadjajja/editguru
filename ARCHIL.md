# Running FRAME on Archil

This zip is the FRAME repo, minus Mac-only files (.venv), old renders (jobs/) and git history.
The demo lives at `/demo` (recipe `recipes/frame-demo-v1`).

## 1. Put the zip on an Archil disk
Create a disk (console, or `npx disk create frame`), then upload `frame-archil.zip` to it.

## 2. Start a sandbox with the disk mounted
```ts
import { Archil } from "disk";
const client = new Archil({ apiKey: process.env.ARCHIL_API_KEY, region: "aws-us-east-1" });
const sandbox = await client.sandboxes.create({
  baseImage: "python:3.12",
  vcpuCount: 4,
  memSizeMiB: 8192,
  mounts: [{ disk: "<your disk id>", path: "/mnt/frame" }],
});
```

## 3. Unzip and start FRAME
```sh
cd /mnt/frame && unzip -q frame-archil.zip -d . && cd frame-creative-agent
sh work/frame-product/start-archil.sh
```
First start installs FFmpeg and Python packages (needs package-registry access; allowed on Archil's free plan allowlist).

## 4. Expose the port and open the demo
Expose port 8876 (`exposePort(8876)` in the SDK). Archil gives the port a public hostname.
Restart once with that hostname so FRAME accepts browser requests from it:
```sh
FRAME_PUBLIC_HOST=<that hostname> sh work/frame-product/start-archil.sh
```
Open `https://<that hostname>/demo`.

The link has no login. For anything beyond the demo, use an Archil port token (X-Archil-Token header).
