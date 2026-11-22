#!/usr/bin/env python3
"""Queue an APPROVED post. Run only after the owner said yes in chat.

python scripts/approve.py --photo inbox/DSC0123.jpg --caption-file /tmp/caption.txt \
    --publish-at "2026-11-24T19:30:00+07:00" [--fit pad-white|pad-black|crop|none] [--alt-text "..."]

Creates queue/<slug>/photo.jpg + post.json and removes the photo from inbox/.
Then commit and push to main; the GitHub Action publishes when publish_at passes.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from photo_info import read  # noqa: E402
from prepare_image import prepare  # noqa: E402

MAX_HASHTAGS = 5      # Instagram's per-post cap
MAX_CAPTION = 2200


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", required=True)
    ap.add_argument("--caption-file", required=True)
    ap.add_argument("--publish-at", required=True, help="ISO time with offset, e.g. 2026-11-24T19:30:00+07:00")
    ap.add_argument("--fit", default="pad-white", choices=["pad-white", "pad-black", "crop", "none"])
    ap.add_argument("--alt-text", default="")
    a = ap.parse_args()

    caption = open(a.caption_file, encoding="utf-8").read().strip()
    tags = re.findall(r"(?<!\w)#\w+", caption)
    if len(tags) > MAX_HASHTAGS:
        sys.exit(f"caption has {len(tags)} hashtags; Instagram allows {MAX_HASHTAGS}")
    if len(caption) > MAX_CAPTION:
        sys.exit(f"caption is {len(caption)} chars; max {MAX_CAPTION}")

    when = dt.datetime.fromisoformat(a.publish_at)
    if when.tzinfo is None:
        sys.exit("--publish-at needs a timezone offset, e.g. +07:00")

    info = read(a.photo)
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", os.path.splitext(os.path.basename(a.photo))[0]).strip("-")
    slug = f"{when.strftime('%Y-%m-%d-%H%M')}-{stem}"[:80]
    folder = os.path.join("queue", slug)
    os.makedirs(folder, exist_ok=True)
    size = prepare(a.photo, os.path.join(folder, "photo.jpg"), a.fit)

    post = {
        "slug": slug,
        "source_file": os.path.basename(a.photo),
        "caption": caption,
        "alt_text": a.alt_text,
        "publish_at": when.isoformat(),
        "fit": a.fit,
        "final_size": f"{size[0]}x{size[1]}",
        "exif": {k: info[k] for k in ("camera", "lens", "focal_length", "aperture", "shutter", "iso", "taken_at", "gear_line")},
        "approved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "queued",
        "attempts": 0,
    }
    with open(os.path.join(folder, "post.json"), "w", encoding="utf-8") as f:
        json.dump(post, f, indent=2, ensure_ascii=False)

    # take the original out of the inbox so it is never proposed again
    if subprocess.run(["git", "rm", "-q", "--cached", a.photo], capture_output=True).returncode != 0:
        pass
    os.remove(a.photo)
    print(json.dumps({"queued": folder, "publish_at": post["publish_at"], "size": post["final_size"]}))


if __name__ == "__main__":
    main()
