"""Small local HTTP adapter for the FRAME iOS prototype."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from frame_core import export, load, render, restore, save, validate


ROOT = Path(os.environ.get("FRAME_DATA_DIR", Path(__file__).parent / "data")).resolve()
MAX_UPLOAD = 500 * 1024 * 1024
UPLOAD_LOCK = threading.RLock()


def upload_status(project: Path) -> dict:
    source = project / "source.mp4"
    part = project / "source.mp4.part"
    metadata = project / "upload.json"
    if part.exists():
        total = json.loads(metadata.read_text())["total"] if metadata.exists() else None
        return {"offset": part.stat().st_size, "total": total, "complete": False}
    if source.exists():
        return {"offset": source.stat().st_size, "total": source.stat().st_size, "complete": True}
    return {"offset": 0, "total": None, "complete": False}


def project_view(project: Path, origin: str) -> dict:
    data = load(project)
    items = []
    for index, item in enumerate(data["checkpoints"], 1):
        items.append({"id": item["id"], "phase": item["phase"], "version": index,
                      "video_url": f"{origin}/api/projects/{project.name}/media/{item['file']}",
                      "created_at": item["created_at"], "rationale": item.get("rationale") or item["name"]})
    return {"id": project.name, "title": data.get("title", "Untitled"), "brief": data.get("brief", ""),
            "status": "ready" if data["checkpoints"] else "awaiting_media" if (project / "source.mp4").exists() is False else "uploaded",
            "current_phase": next((c["phase"] for c in data["checkpoints"] if c["id"] == data["active"]), 0),
            "checkpoints": items, "progress_message": None}


class Handler(BaseHTTPRequestHandler):
    def respond(self, code: int, value: dict) -> None:
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def error(self, code: int, message: str) -> None:
        self.respond(code, {"error": message})

    def body(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if size > 1_000_000:
            raise ValueError("JSON body too large")
        return json.loads(self.rfile.read(size) or b"{}")

    @property
    def origin(self) -> str:
        return f"http://{self.headers.get('Host', '127.0.0.1:8765')}"

    def route(self) -> tuple[list[str], Path | None]:
        path = urlsplit(self.path).path.strip("/").split("/")
        if path[:2] != ["api", "projects"]:
            return path, None
        if len(path) >= 3 and (len(path[2]) != 32 or any(c not in "0123456789abcdef" for c in path[2])):
            return path, None
        project = ROOT / path[2] if len(path) >= 3 else None
        return path, project

    def do_GET(self) -> None:
        path, project = self.route()
        if path == ["api", "projects"]:
            self.respond(200, {"projects": [project_view(p, self.origin) for p in sorted(ROOT.glob("*/project.json")) for p in [p.parent]]})
            return
        if project is None or not (project / "project.json").exists():
            self.error(404, "Project not found"); return
        if len(path) == 3:
            self.respond(200, project_view(project, self.origin)); return
        if path[3:] == ["media", "upload"]:
            self.respond(200, upload_status(project)); return
        if path[3:] == ["export"]:
            try:
                target = project / "export.mp4"
                export(project, target)
                self.respond(200, {"url": f"{self.origin}/api/projects/{project.name}/media/export.mp4"})
            except ValueError as exc:
                self.error(409, str(exc))
            return
        if len(path) == 5 and path[3] == "media":
            allowed = {item["file"] for item in load(project)["checkpoints"]} | {"export.mp4"}
            if path[4] not in allowed:
                self.error(404, "Media not found"); return
            media = project / path[4]
            if not media.is_file():
                self.error(404, "Media not found"); return
            total = media.stat().st_size
            start, end = 0, total - 1
            requested = self.headers.get("Range")
            if requested:
                import re
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested.strip())
                if not match:
                    self.error(416, "Unsupported range"); return
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else end
                if start >= total or end < start:
                    self.error(416, "Range outside media"); return
                end = min(end, total - 1)
            self.send_response(206 if requested else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if requested: self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            self.end_headers()
            with media.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk: break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            return
        self.error(404, "Route not found")

    def do_PUT(self) -> None:
        path, project = self.route()
        if project is None or not (project / "project.json").exists() or path[3:] != ["media", "upload"]:
            self.error(404, "Route not found"); return
        try:
            offset = int(self.headers.get("X-Upload-Offset", "-1"))
            total = int(self.headers.get("X-Upload-Total", "-1"))
            size = int(self.headers.get("Content-Length", "-1"))
            if total <= 0 or total > MAX_UPLOAD or size <= 0 or offset < 0 or offset + size > total:
                self.error(400, "Invalid chunk bounds"); return
            with UPLOAD_LOCK:
                state = upload_status(project)
                if state["complete"]:
                    self.error(409, "Upload already complete"); return
                if state["total"] not in (None, total):
                    self.error(409, "Upload total changed"); return
                if offset != state["offset"]:
                    self.error(409, f"Expected offset {state['offset']}"); return
                chunk = self.rfile.read(size)
                if len(chunk) != size:
                    self.error(400, "Upload interrupted"); return
                part = project / "source.mp4.part"
                with part.open("ab") as stream:
                    stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Persist total only after the bytes are durable.
                metadata_tmp = project / "upload.json.tmp"
                metadata_tmp.write_text(json.dumps({"total": total}))
                os.replace(metadata_tmp, project / "upload.json")
                if part.stat().st_size == total:
                    try: validate(part)
                    except Exception as exc:
                        part.unlink(missing_ok=True)
                        (project / "upload.json").unlink(missing_ok=True)
                        self.error(422, f"Completed upload is invalid media: {exc}"); return
                    os.replace(part, project / "source.mp4")
                    (project / "upload.json").unlink(missing_ok=True)
                    data = load(project); data["checkpoints"] = []; data["active"] = None; save(project, data)
                self.respond(200, upload_status(project))
        except (ValueError, OSError) as exc:
            self.error(400, str(exc))

    def do_POST(self) -> None:
        path, project = self.route()
        try:
            if path == ["api", "projects"]:
                body = self.body()
                project = ROOT / uuid.uuid4().hex
                project.mkdir(parents=True)
                save(project, {"schema": 1, "title": str(body.get("title", "Untitled"))[:100], "brief": str(body.get("brief", ""))[:2000], "source": "source.mp4", "checkpoints": [], "active": None, "created_at": datetime.now(timezone.utc).isoformat()})
                self.respond(201, project_view(project, self.origin)); return
            if project is None or not (project / "project.json").exists():
                self.error(404, "Project not found"); return
            if path[3:] == ["media"]:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > MAX_UPLOAD:
                    self.error(413, "Invalid upload size"); return
                fd, temporary_name = tempfile.mkstemp(dir=project, suffix=".upload")
                try:
                    with os.fdopen(fd, "wb") as stream:
                        remaining = size
                        while remaining:
                            chunk = self.rfile.read(min(1024 * 1024, remaining))
                            if not chunk: raise ValueError("Upload interrupted")
                            stream.write(chunk); remaining -= len(chunk)
                    validate(Path(temporary_name))
                    os.replace(temporary_name, project / "source.mp4")
                    (project / "source.mp4.part").unlink(missing_ok=True)
                    (project / "upload.json").unlink(missing_ok=True)
                    data = load(project); data["checkpoints"] = []; data["active"] = None; save(project, data)
                finally:
                    Path(temporary_name).unlink(missing_ok=True)
                self.respond(200, project_view(project, self.origin)); return
            body = self.body()
            if path[3:] == ["directives"]:
                phase = int(body.get("phase", 0))
                instruction = str(body.get("instruction", ""))[:2000]
                if not instruction: raise ValueError("Instruction required")
                data = load(project)
                data.setdefault("directives", []).append({"phase": phase, "instruction": instruction})
                save(project, data)
                render(project, phase, caption=instruction if phase == 4 else "A NEW STORY", instruction=instruction)
                self.respond(200, project_view(project, self.origin)); return
            if path[3:] == ["revisions"]:
                checkpoint_id = str(body.get("checkpoint_id", ""))
                data = load(project)
                selected = next((c for c in data["checkpoints"] if c["id"] == checkpoint_id), None)
                if selected is None: raise ValueError("Unknown checkpoint")
                instruction = str(body.get("instruction", ""))[:2000]
                if not instruction: raise ValueError("Instruction required")
                render(project, selected["phase"], caption=instruction if selected["phase"] == 4 else "A NEW STORY", parent=selected["parent"], instruction=instruction)
                self.respond(200, project_view(project, self.origin)); return
            if path[3:] == ["restore"]:
                restore(project, str(body.get("checkpoint_id", "")))
                self.respond(200, project_view(project, self.origin)); return
            self.error(404, "Route not found")
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.error(400, str(exc))
        except Exception as exc:
            self.error(500, str(exc))


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"FRAME API serving on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    options = parser.parse_args()
    serve(options.host, options.port)
