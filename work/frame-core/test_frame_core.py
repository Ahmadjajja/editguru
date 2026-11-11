import tempfile
import unittest
from pathlib import Path

from frame_core import create, export, load, probe, render, restore, run


class MediaCoreTest(unittest.TestCase):
    def test_keep_the_opening_preserves_detected_lead_in(self):
        fixture = Path(__file__).parent.parent / "frame-qa" / "portrait_speech.mp4"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            create(fixture, project)
            default = render(project, 1)
            keep = render(project, 1, instruction="Keep the opening")
            self.assertGreater(keep["duration"], default["duration"] + 0.1)

    def test_real_five_phase_render_revision_restore_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=4", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source))
            project = root / "project"
            create(source, project, "Cinematic opening")
            items = [render(project, phase, caption="A FRAME STORY") for phase in range(1, 6)]
            retained = render(project, 1, instruction="Keep the opening")
            self.assertGreater(retained["duration"], 3.95)
            self.assertEqual([item["phase"] for item in items], [1, 2, 3, 4, 5])
            self.assertEqual(len({item["file"] for item in items}), 5)
            self.assertTrue(all((project / item["file"]).stat().st_size > 1000 for item in items))
            self.assertTrue(all(float(probe(project / item["file"])["format"]["duration"]) > 3 for item in items))
            revision = render(project, 4, caption="NEW DIRECTION", parent=items[2]["id"])
            self.assertNotEqual((project / revision["file"]).read_bytes(), (project / items[3]["file"]).read_bytes())
            warm = render(project, 2, parent=items[0]["id"], instruction="warm and vibrant")
            muted = render(project, 2, parent=items[0]["id"], instruction="cool and muted")
            def frame_digest(item):
                import hashlib
                import subprocess
                video = project / item["file"]
                result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True)
                return hashlib.sha256(result.stdout).hexdigest()
            self.assertNotEqual(frame_digest(warm), frame_digest(muted))
            restore(project, items[4]["id"])
            self.assertEqual(load(project)["active"], items[4]["id"])
            final = root / "export.mp4"
            export(project, final)
            self.assertEqual(final.read_bytes(), (project / items[4]["file"]).read_bytes())


if __name__ == "__main__":
    unittest.main()
