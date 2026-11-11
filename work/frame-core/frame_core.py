"""FRAME local media engine: reproducible FFmpeg checkpoints and revisions."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


PHASES = ("story_rhythm", "studio_visuals", "broll_storytelling", "captions_graphics", "sound_polish")


def run(*args: str) -> None:
    subprocess.run(list(args), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def validate(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty media: {path}")
    info = probe(path)
    types = {stream["codec_type"] for stream in info["streams"]}
    if "video" not in types or "audio" not in types or float(info["format"]["duration"]) <= 0:
        raise ValueError("Source requires playable video and audio")
    return info


def load(project: Path) -> dict:
    return json.loads((project / "project.json").read_text())


def save(project: Path, data: dict) -> None:
    temporary = project / "project.json.tmp"
    temporary.write_text(json.dumps(data, indent=2))
    temporary.replace(project / "project.json")


def create(source: Path, project: Path, brief: str = "") -> dict:
    source = source.resolve()
    validate(source)
    if project.exists():
        raise FileExistsError(project)
    project.mkdir(parents=True)
    shutil.copy2(source, project / "source.mp4")
    data = {"schema": 1, "brief": brief, "source": "source.mp4", "checkpoints": [], "active": None, "created_at": datetime.now(timezone.utc).isoformat()}
    save(project, data)
    return data


def _silence_trim(source: Path) -> float:
    """Only remove a long initial quiet section, with a 120 ms speech guard."""
    result = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(source), "-af", "silencedetect=noise=-38dB:d=0.35", "-f", "null", "-"], capture_output=True, text=True)
    ends = re.findall(r"silence_end: ([0-9.]+)", result.stderr)
    starts = re.findall(r"silence_start: ([0-9.]+)", result.stderr)
    if starts and ends and float(starts[0]) < 0.1:
        return max(0.0, float(ends[0]) - 0.12)
    return 0.0


def render(project: Path, phase: int, caption: str = "A NEW STORY", parent: str | None = None, instruction: str = "") -> dict:
    data = load(project)
    if phase < 1 or phase > 5:
        raise ValueError("phase must be 1..5")
    checkpoints = data["checkpoints"]
    if parent is None:
        if phase == 1:
            parent = "source"
        else:
            previous = next((c for c in reversed(checkpoints) if c["phase"] == phase - 1), None)
            if previous is None:
                raise ValueError("Previous phase must be rendered first")
            parent = previous["id"]
    if parent == "source":
        input_file = project / data["source"]
    else:
        prior = next((c for c in checkpoints if c["id"] == parent), None)
        if prior is None:
            raise ValueError("Unknown parent checkpoint")
        input_file = project / prior["file"]
    if phase > 1 and parent == "source":
        raise ValueError("Later phases require a prior rendered checkpoint")

    checkpoint_id = uuid.uuid4().hex[:12]
    output = project / f"v{phase}-{checkpoint_id}.mp4"
    # Each phase is a distinct transcode, and its filter changes pixels or sound.
    common = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(input_file)]
    direction = instruction.lower()
    if phase == 1:
        cut = _silence_trim(input_file)
        if re.search(r"\bkeep (?:the )?opening\b", direction) or "don't trim" in direction or "do not trim" in direction:
            cut = 0.0
        elif "tight" in direction or "faster" in direction:
            cut = min(cut + 0.04, max(0.0, float(probe(input_file)["format"]["duration"]) - 0.5))
        options = ["-vf", f"trim=start={cut},setpts=PTS-STARTPTS", "-af", f"atrim=start={cut},asetpts=PTS-STARTPTS"]
    elif phase == 2:
        brightness = -0.025 if "darker" in direction else 0.06 if "brighter" in direction else 0.025
        saturation = 0.82 if "muted" in direction else 1.3 if "vibrant" in direction else 1.14
        tint = ",hue=h=8" if "warm" in direction else ",hue=h=-8" if "cool" in direction else ""
        options = ["-vf", f"eq=contrast=1.10:brightness={brightness}:saturation={saturation},unsharp=3:3:0.35{tint}"]
    elif phase == 3:
        # A second shot is derived from the creator's own footage: an early close crop
        # is inserted briefly over later footage. No third-party assets are assumed.
        duration = float(probe(input_file)["format"]["duration"])
        if duration < 1.5:
            options = ["-vf", "crop=iw*0.80:ih*0.80:(iw-ow)/2:(ih-oh)/2,scale=iw/0.8:ih/0.8"]
        else:
            reveal = min(1.5, duration / 3)
            x = "0" if "left" in direction else "iw-ow" if "right" in direction else "(iw-ow)/2"
            crop_scale = "0.62" if "closer" in direction else "0.75"
            options = ["-filter_complex", f"[0:v]split=2[base][alt];[alt]crop=iw*{crop_scale}:ih*{crop_scale}:{x}:(ih-oh)/2,scale=iw/{crop_scale}:ih/{crop_scale},setpts=PTS-STARTPTS+{reveal}/TB[crop];[base][crop]overlay=0:0:enable='between(t,{reveal},{min(duration-0.2,reveal+0.9)})'[v]", "-map", "[v]", "-map", "0:a"]
    elif phase == 4:
        frame = next(s for s in probe(input_file)["streams"] if s["codec_type"] == "video")
        width, height = frame["width"], frame["height"]
        overlay_file = project / f"caption-{checkpoint_id}.png"
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        font_size = max(18, width // 13)
        font = None
        for font_path in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            try:
                font = ImageFont.truetype(font_path, font_size)
                break
            except OSError:
                continue
        if font is None:
            font = ImageFont.load_default(size=font_size)
        label = caption.replace("\n", " ")[:50]
        draw.rounded_rectangle((28, height - 91, width - 25, height - 30), radius=10, fill=(0, 0, 0, 195))
        draw.text((43, height - 80), label, font=font, fill="white")
        image.save(overlay_file)
        common += ["-loop", "1", "-i", str(overlay_file)]
        options = ["-filter_complex", "[0:v][1:v]overlay=0:0:shortest=1[v]", "-map", "[v]", "-map", "0:a", "-af", "anull"]
    else:
        target = -20 if "quieter" in direction else -13 if "louder" in direction else -16
        options = ["-af", f"loudnorm=I={target}:TP=-1.5:LRA=11,alimiter=limit=0.90"]
    try:
        run(*(common + options + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-shortest", str(output)]))
        media = validate(output)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    item = {"id": checkpoint_id, "phase": phase, "name": PHASES[phase - 1], "parent": parent, "file": output.name, "caption": caption if phase == 4 else None, "instruction": instruction, "duration": float(media["format"]["duration"]), "bytes": output.stat().st_size, "created_at": datetime.now(timezone.utc).isoformat()}
    checkpoints.append(item)
    data["active"] = checkpoint_id
    save(project, data)
    return item


def restore(project: Path, checkpoint_id: str) -> dict:
    data = load(project)
    if not any(c["id"] == checkpoint_id for c in data["checkpoints"]):
        raise ValueError("Unknown checkpoint")
    data["active"] = checkpoint_id
    save(project, data)
    return data


def export(project: Path, target: Path) -> Path:
    data = load(project)
    active = next((c for c in data["checkpoints"] if c["id"] == data["active"]), None)
    if active is None:
        raise ValueError("No active render")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(project / active["file"], target)
    validate(target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("create"); new.add_argument("source", type=Path); new.add_argument("project", type=Path); new.add_argument("--brief", default="")
    edit = sub.add_parser("render"); edit.add_argument("project", type=Path); edit.add_argument("phase", type=int); edit.add_argument("--caption", default="A NEW STORY"); edit.add_argument("--parent")
    back = sub.add_parser("restore"); back.add_argument("project", type=Path); back.add_argument("checkpoint_id")
    out = sub.add_parser("export"); out.add_argument("project", type=Path); out.add_argument("target", type=Path)
    args = parser.parse_args()
    if args.command == "create": result = create(args.source, args.project, args.brief)
    elif args.command == "render": result = render(args.project, args.phase, args.caption, args.parent)
    elif args.command == "restore": result = restore(args.project, args.checkpoint_id)
    else: result = {"export": str(export(args.project, args.target))}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
