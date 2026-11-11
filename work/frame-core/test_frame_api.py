import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import frame_api
from frame_api import Handler


class APITest(unittest.TestCase):
    def test_invalid_completed_upload_can_retry(self):
        fixture = Path(__file__).parent.parent / "frame-qa" / "portrait_speech.mp4"
        with tempfile.TemporaryDirectory() as temporary:
            frame_api.ROOT = Path(temporary)
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            base = f"http://127.0.0.1:{server.server_port}/api/projects"
            try:
                with urlopen(Request(base, data=b'{}', method="POST", headers={"Content-Type": "application/json"})) as response:
                    project = json.load(response)
                upload = f"{base}/{project['id']}/media/upload"
                bad = b"invalid media"
                with self.assertRaises(HTTPError) as raised:
                    urlopen(Request(upload, data=bad, method="PUT", headers={"X-Upload-Offset": "0", "X-Upload-Total": str(len(bad))}))
                self.assertEqual(raised.exception.code, 422)
                with urlopen(upload) as response: self.assertEqual(json.load(response)["offset"], 0)
                good = fixture.read_bytes()
                with urlopen(Request(upload, data=good, method="PUT", headers={"X-Upload-Offset": "0", "X-Upload-Total": str(len(good))})) as response:
                    self.assertTrue(json.load(response)["complete"])
            finally:
                server.shutdown(); server.server_close(); worker.join(timeout=2)

    def test_resumable_upload_survives_server_restart(self):
        fixture = Path(__file__).parent.parent / "frame-qa" / "portrait_speech.mp4"
        video = fixture.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            frame_api.ROOT = Path(temporary)
            def start():
                service = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                worker = threading.Thread(target=service.serve_forever, daemon=True)
                worker.start()
                return service, worker, f"http://127.0.0.1:{service.server_port}/api/projects"
            server, thread, base = start()
            try:
                req = Request(base, data=b'{"title":"Resume"}', method="POST", headers={"Content-Type": "application/json"})
                with urlopen(req) as response: project = json.load(response)
                project_id = project["id"]
                upload = f"{base}/{project_id}/media/upload"
                split = len(video) // 2
                req = Request(upload, data=video[:split], method="PUT", headers={"X-Upload-Offset": "0", "X-Upload-Total": str(len(video)), "Content-Type": "video/mp4"})
                with urlopen(req) as response: state = json.load(response)
                self.assertEqual(state, {"offset": split, "total": len(video), "complete": False})
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)
            server, thread, base = start()
            try:
                upload = f"{base}/{project_id}/media/upload"
                with urlopen(upload) as response: state = json.load(response)
                self.assertEqual(state["offset"], split)
                req = Request(upload, data=video[split:], method="PUT", headers={"X-Upload-Offset": str(split), "X-Upload-Total": str(len(video)), "Content-Type": "video/mp4"})
                with urlopen(req) as response: state = json.load(response)
                self.assertTrue(state["complete"])
                self.assertEqual((frame_api.ROOT / project_id / "source.mp4").read_bytes(), video)
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_project_upload_render_revision_restore_export(self):
        fixture = Path(__file__).parent.parent / "frame-qa" / "portrait_speech.mp4"
        self.assertTrue(fixture.is_file(), "Independent QA fixture required")
        with tempfile.TemporaryDirectory() as temporary:
            frame_api.ROOT = Path(temporary)
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}/api/projects"

            def send(url, method="GET", payload=None, content_type="application/json"):
                if payload is not None and not isinstance(payload, bytes): payload = json.dumps(payload).encode()
                request = Request(url, data=payload, method=method, headers={"Content-Type": content_type})
                with urlopen(request, timeout=30) as response:
                    return json.load(response)

            try:
                project = send(base, "POST", {"title": "QA", "brief": "Test story"})
                url = f"{base}/{project['id']}"
                self.assertEqual(project["status"], "awaiting_media")
                uploaded = send(url + "/media", "POST", fixture.read_bytes(), "video/mp4")
                self.assertEqual(uploaded["status"], "uploaded")
                for phase in range(1, 6):
                    project = send(url + "/directives", "POST", {"phase": phase, "instruction": "Make the story cinematic" if phase != 4 else "A FRAME STORY"})
                    self.assertEqual(len(project["checkpoints"]), phase)
                first_four = project["checkpoints"][3]
                revision = send(url + "/revisions", "POST", {"checkpoint_id": first_four["id"], "instruction": "A DIFFERENT STORY"})
                self.assertEqual(len(revision["checkpoints"]), 6)
                restored = send(url + "/restore", "POST", {"checkpoint_id": project["checkpoints"][4]["id"]})
                self.assertEqual(restored["current_phase"], 5)
                exported = send(url + "/export")
                with urlopen(exported["url"]) as response: self.assertGreater(len(response.read()), 1000)
                with urlopen(Request(exported["url"], headers={"Range": "bytes=0-1023"})) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(len(response.read()), 1024)
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
