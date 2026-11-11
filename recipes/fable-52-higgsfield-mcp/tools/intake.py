"""Footage intake: hash, probe and contact-sheet a source file, then record it in ../inventory.json.
Never copies or modifies the original (disk is tight; originals stay where they are).
Usage: python3 tools/intake.py <file> --role <role> [--note "..."]"""
import argparse, datetime, hashlib, json, os, subprocess, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INV = os.path.join(HERE, "inventory.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
                          "-of", "json", path], capture_output=True, text=True, check=True)
    d = json.loads(out.stdout); v = next((s for s in d["streams"] if s["codec_type"] == "video"), None); a = [s for s in d["streams"] if s["codec_type"] == "audio"]
    return {"duration_s": round(float(d["format"]["duration"]), 3), "video": v and {"codec": v["codec_name"], "width": v["width"], "height": v["height"], "fps": v["r_frame_rate"]},
            "audio_streams": [{"codec": s["codec_name"], "sample_rate": s.get("sample_rate"), "channels": s.get("channels")} for s in a]}


def sheet(path, info, name):
    if not info["video"]:
        return None
    out = os.path.join(HERE, "analysis", name + "_sheet.jpg"); os.makedirs(os.path.dirname(out), exist_ok=True)
    step = max(info["duration_s"] / 24, 0.1)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vf", "fps=1/%.3f,scale=180:-2,tile=8x3" % step, "-frames:v", "1", out], check=True)
    return os.path.relpath(out, HERE)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("file"); ap.add_argument("--role", required=True); ap.add_argument("--note", default="")
    a = ap.parse_args(); path = os.path.abspath(a.file)
    info = probe(path); digest = sha256(path)
    name = os.path.splitext(os.path.basename(path))[0][:40].replace(" ", "_")
    entry = {"role": a.role, "original_path": path, "bytes": os.path.getsize(path), "sha256": digest, **info,
             "contact_sheet": sheet(path, info, name), "copied": False, "logged_at": datetime.datetime.now().isoformat(timespec="seconds"), "note": a.note,
             "evidence_status": "measured from source file"}
    inv = json.load(open(INV)) if os.path.exists(INV) else {"format": "inventory/1", "items": []}
    inv["items"] = [i for i in inv["items"] if i.get("sha256") != digest] + [entry]
    json.dump(inv, open(INV, "w"), indent=1, ensure_ascii=False)
    print(json.dumps({k: entry[k] for k in ("role", "sha256", "duration_s", "video", "audio_streams", "contact_sheet")}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
