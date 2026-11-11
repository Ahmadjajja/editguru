import http.client
import json
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch

import server


P1 = "1" * 32
P2 = "2" * 32
V1 = "a" * 32


class FakeBackend(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/frame/projects":
            data = [{"id": P1, "name": "One"}, {"id": P2, "name": "Two"}]
        elif self.path.startswith("/api/frame/projects/"):
            data = {"id": self.path.split("/")[-1], "versions": []}
        elif self.path.startswith("/frame-media/"):
            raw = b"abcdefghij"
            if self.headers.get("Range") == "bytes=2-4":
                self.send_response(206)
                self.send_header("Content-Range", "bytes 2-4/10")
                raw = raw[2:5]
            else:
                self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            return self.wfile.write(raw)
        elif self.path in ("/", "/frame"):
            raw = b'<a id="connectFish" href="/studio#fishSettings" hidden>Connect</a><option value="fish-mcp">Fish Audio narrator</option><option value="edge">Edge preview voice</option>'
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            return self.wfile.write(raw)
        else:
            data = {"ok": True}
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.calls.append((self.path, body))
        raw = json.dumps({"id": P1, "versions": []}).encode()
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_):
        pass


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "pilot.db")
        with server.db_connect(self.db) as db:
            db.execute("INSERT INTO invites VALUES(?,?,?)", (server.digest("invite-one"), "one", time.time() + 3600))
            db.execute("INSERT INTO invites VALUES(?,?,?)", (server.digest("invite-two"), "two", time.time() + 3600))
            db.execute("INSERT INTO projects VALUES(?,?)", (P2, "two"))
        self.backend = ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend)
        self.backend.calls = []
        self.pilot = ThreadingHTTPServer(("127.0.0.1", 0), server.PilotHandler)
        self.pilot.db_path = self.db
        self.pilot.public_origin = "https://pilot.example"
        self.pilot.public_host = "pilot.example"
        self.pilot.backend_port = self.backend.server_port
        self.pilot.secret = b"test-secret-long-enough-for-hmac-123456"
        self.threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (self.backend, self.pilot)]
        for thread in self.threads:
            thread.start()

    def tearDown(self):
        self.pilot.shutdown()
        self.backend.shutdown()
        self.pilot.server_close()
        self.backend.server_close()
        self.temp.cleanup()

    def request(self, method, path, data=None, cookie=None, origin="https://pilot.example", ctype="application/json", headers=None):
        con = http.client.HTTPConnection("127.0.0.1", self.pilot.server_port)
        hdr = {"Host": "pilot.example", **(headers or {})}
        if data is not None:
            hdr["Content-Type"] = ctype
            hdr["Origin"] = origin
        if cookie:
            hdr["Cookie"] = cookie
        con.request(method, path, body=data, headers=hdr)
        result = con.getresponse()
        status, head, body = result.status, dict(result.getheaders()), result.read()
        con.close()
        return status, head, body

    def login(self, invite):
        status, head, _ = self.request("POST", "/pilot/login", urlencode({"invite": invite}), ctype="application/x-www-form-urlencoded")
        self.assertEqual(status, 303)
        self.assertIn("Secure", head["Set-Cookie"])
        return head["Set-Cookie"].split(";", 1)[0]

    def test_authentication_allowlist_and_isolation(self):
        self.assertEqual(self.request("GET", "/api/frame/projects")[0], 401)
        one = self.login("invite-one")
        two = self.login("invite-two")
        self.assertEqual(self.request("GET", "/api/frame/projects/" + P2, cookie=one)[0], 404)
        self.assertEqual(self.request("GET", "/frame-media/" + P2 + "/" + V1 + "/export.mp4", cookie=one)[0], 404)
        status, _, body = self.request("GET", "/api/frame/projects", cookie=one)
        self.assertEqual((status, json.loads(body)), (200, []))
        status, _, body = self.request("GET", "/api/frame/projects", cookie=two)
        self.assertEqual([p["id"] for p in json.loads(body)], [P2])
        for path in ("/studio", "/editor", "/api/frame/import", "/api/studio/fish-mcp/status", "/media/" + P2 + "/input.mp4"):
            self.assertEqual(self.request("GET", path, cookie=one)[0], 404)
        self.assertEqual(self.request("POST", "/api/frame/import", b"{}", cookie=one)[0], 404)

    def test_edge_generation_and_project_binding(self):
        one = self.login("invite-one")
        rid = secrets.token_hex(16)
        body = json.dumps({"script": "Hello there.", "idea": "Test", "provider": "edge", "request_id": rid}).encode()
        self.assertEqual(self.request("POST", "/api/frame/generate", body, cookie=one)[0], 202)
        self.assertEqual(self.request("GET", "/api/frame/projects/" + P1, cookie=one)[0], 200)
        self.assertEqual(self.request("GET", "/api/frame/projects/" + P1, cookie=self.login("invite-two"))[0], 404)
        self.assertEqual(self.backend.calls[0][1]["provider"], "edge")
        self.assertNotEqual(self.backend.calls[0][1]["request_id"], rid)
        self.assertEqual(self.request("POST", "/api/frame/generate", body, cookie=one)[0], 202)
        self.assertEqual(self.backend.calls[-1][1]["request_id"], self.backend.calls[0][1]["request_id"])
        fish = json.dumps({"script": "Hello", "provider": "fish-mcp", "request_id": secrets.token_hex(16)}).encode()
        self.assertEqual(self.request("POST", "/api/frame/generate", fish, cookie=one)[0], 403)
        self.assertEqual(self.request("POST", "/api/frame/projects/" + P1 + "/render", b"{}", cookie=one)[0], 404)

    def test_origin_limits_and_media_range(self):
        one = self.login("invite-one")
        status, head, login_page = self.request("GET", "/pilot/login")
        self.assertEqual((status, head["Referrer-Policy"]), (200, "same-origin"))
        self.assertIn(b'name="invite"', login_page)
        self.assertIn(b'href="/pilot.css"', login_page)
        self.assertEqual(self.request("GET", "/pilot.css")[0], 200)
        self.assertEqual(self.request("GET", "/?project=" + P1, cookie=one)[0], 200)
        self.assertEqual(self.request("GET", "/?project=invalid", cookie=one)[0], 400)
        self.assertEqual(self.request("POST", "/api/frame/generate", b"{}", cookie=one, origin="https://evil.example")[0], 403)
        self.assertEqual(self.request("POST", "/api/frame/generate", b"x" * 12001, cookie=one)[0], 400)
        html = self.request("GET", "/", cookie=one)[2]
        self.assertNotIn(b"fish-mcp", html)
        self.assertIn(b'id="connectFish"', html)
        status, _, config = self.request("GET", "/api/frame/config", cookie=one)
        self.assertEqual((status, json.loads(config)["default_provider"]), (200, "edge"))
        with server.db_connect(self.db) as db:
            db.execute("INSERT INTO projects VALUES(?,?)", (P1, "one"))
        status, head, body = self.request("GET", "/frame-media/" + P1 + "/" + V1 + "/export.mp4", cookie=one, headers={"Range": "bytes=2-4"})
        self.assertEqual((status, body, head.get("Content-Range")), (206, b"cde", "bytes 2-4/10"))

    def test_invitation_work_limits_preserve_idempotent_replays(self):
        one = self.login("invite-one")
        request_ids = [secrets.token_hex(16) for _ in range(3)]
        for rid in request_ids[:2]:
            body = json.dumps({"script": "Hello there.", "idea": "Test", "provider": "edge", "request_id": rid}).encode()
            self.assertEqual(self.request("POST", "/api/frame/generate", body, cookie=one)[0], 202)
        last = json.dumps({"script": "Hello there.", "idea": "Test", "provider": "edge", "request_id": request_ids[2]}).encode()
        self.assertEqual(self.request("POST", "/api/frame/generate", last, cookie=one)[0], 429)
        replay = json.dumps({"script": "Hello there.", "idea": "Test", "provider": "edge", "request_id": request_ids[0]}).encode()
        self.assertEqual(self.request("POST", "/api/frame/generate", replay, cookie=one)[0], 202)
        revisions = [secrets.token_hex(16) for _ in range(3)]
        for rid in revisions[:2]:
            body = json.dumps({"base_version_id": V1, "feedback": "Make the title larger.", "request_id": rid}).encode()
            self.assertEqual(self.request("POST", "/api/frame/projects/" + P1 + "/revise", body, cookie=one)[0], 202)
        blocked = json.dumps({"base_version_id": V1, "feedback": "Make the title larger.", "request_id": revisions[2]}).encode()
        self.assertEqual(self.request("POST", "/api/frame/projects/" + P1 + "/revise", blocked, cookie=one)[0], 429)
        replay_revision = json.dumps({"base_version_id": V1, "feedback": "Make the title larger.", "request_id": revisions[0]}).encode()
        self.assertEqual(self.request("POST", "/api/frame/projects/" + P1 + "/revise", replay_revision, cookie=one)[0], 202)
        self.assertEqual(self.request("POST", "/api/frame/projects/" + P1 + "/retry", b"{}", cookie=one)[0], 202)
        self.assertEqual(self.request("POST", "/api/frame/projects/" + P1 + "/retry", b"{}", cookie=one)[0], 429)

    def test_revoke_disables_invitation_and_active_session(self):
        one = self.login("invite-one")
        result = subprocess.run([sys.executable, server.__file__, "revoke", "--db", self.db, "--owner", "one"],
                                capture_output=True, text=True, check=True)
        self.assertIn("invites=1 sessions=1", result.stdout)
        self.assertEqual(self.request("GET", "/api/frame/projects", cookie=one)[0], 401)
        status, _, _ = self.request("POST", "/pilot/login", urlencode({"invite": "invite-one"}), ctype="application/x-www-form-urlencoded")
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
