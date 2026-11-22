#!/usr/bin/env python3
"""Read camera settings + Lightroom title/caption from an exported photo.

Usage:  python scripts/photo_info.py inbox/IMG_1234.jpg
Prints JSON: camera, lens, focal length, aperture, shutter, ISO, date,
Lightroom title/caption, size, aspect ratio and whether Instagram accepts it.
"""
import json
import re
import sys
from fractions import Fraction

from PIL import Image

IG_MIN_RATIO = 4 / 5      # tallest portrait Instagram accepts (0.8)
IG_MAX_RATIO = 1.91       # widest landscape Instagram accepts


def _num(v):
    try:
        return float(v)
    except Exception:
        try:
            return float(Fraction(str(v)))
        except Exception:
            return None


def _shutter(v):
    s = _num(v)
    if not s:
        return None
    if s >= 1:
        return f"{s:g}s"
    return f"1/{round(1 / s)}s"


def _xmp_field(xmp, name):
    """Pull dc:title / dc:description text out of a Lightroom XMP packet."""
    m = re.search(rf"<dc:{name}>.*?<rdf:li[^>]*>(.*?)</rdf:li>", xmp, re.S)
    return m.group(1).strip() if m else None


def _xmp_attr(xmp, name):
    m = re.search(rf'{name}="([^"]+)"', xmp) or re.search(rf"<{name}>(.*?)</{name}>", xmp, re.S)
    return m.group(1).strip() if m else None


def read(path):
    img = Image.open(path)
    w, h = img.size
    exif = img.getexif()
    sub = exif.get_ifd(0x8769)  # Exif sub-IFD (exposure data lives here)
    gps = exif.get_ifd(0x8825)

    raw = open(path, "rb").read()
    xmp = ""
    m = re.search(rb"<x:xmpmeta.*?</x:xmpmeta>", raw, re.S)
    if m:
        xmp = m.group(0).decode("utf-8", "ignore")

    orientation = exif.get(274, 1)
    if orientation in (5, 6, 7, 8):  # rotated 90°, so displayed size is swapped
        w, h = h, w
    ratio = w / h

    focal = _num(sub.get(37386))
    focal35 = sub.get(41989)
    fnum = _num(sub.get(33437))
    bias = _num(sub.get(37380))
    lens = sub.get(42036) or _xmp_attr(xmp, "aux:Lens")

    info = {
        "file": path,
        "camera": " ".join(x for x in [str(exif.get(271, "")).strip(), str(exif.get(272, "")).strip()] if x) or None,
        "lens": str(lens).strip() if lens else None,
        "focal_length": f"{focal:g}mm" if focal else None,
        "focal_length_35mm": f"{focal35}mm" if focal35 else None,
        "aperture": f"f/{fnum:g}" if fnum else None,
        "shutter": _shutter(sub.get(33434)),
        "iso": sub.get(34855),
        "exposure_comp": f"{bias:+g} EV" if bias else None,
        "taken_at": sub.get(36867) or exif.get(306),
        "lightroom_title": _xmp_field(xmp, "title"),
        "lightroom_caption": _xmp_field(xmp, "description"),
        "has_gps_location": bool(gps),
        "width": w,
        "height": h,
        "aspect_ratio": round(ratio, 3),
    }
    if ratio < IG_MIN_RATIO:
        info["instagram_fit"] = "too_tall: needs pad (borders) or crop to 4:5"
    elif ratio > IG_MAX_RATIO:
        info["instagram_fit"] = "too_wide: needs pad (borders) or crop to 1.91:1"
    else:
        info["instagram_fit"] = "ok"

    parts = [info["camera"], info["lens"], info["focal_length"], info["aperture"],
             info["shutter"], f"ISO {info['iso']}" if info["iso"] else None]
    info["gear_line"] = " · ".join(p for p in parts if p)
    return info


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: photo_info.py <photo> [<photo> ...]")
    out = [read(p) for p in sys.argv[1:]]
    print(json.dumps(out[0] if len(out) == 1 else out, indent=2, default=str))
