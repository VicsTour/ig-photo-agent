#!/usr/bin/env python3
"""Make a photo Instagram-ready.

- applies the camera rotation, converts to sRGB
- fixes the aspect ratio if Instagram would reject it (4:5 .. 1.91:1):
    pad-white / pad-black  -> adds borders, keeps the whole photo
    crop                   -> centre crop to the nearest allowed ratio
- shrinks to max 1440 px wide, saves JPEG under 8 MB
- strips ALL metadata (incl. GPS) from the copy that goes public
"""
import io
import sys

from PIL import Image, ImageCms, ImageOps

MIN_R, MAX_R = 4 / 5, 1.91
MAX_W = 1440
MAX_BYTES = 8 * 1024 * 1024


def to_srgb(img):
    icc = img.info.get("icc_profile")
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            img = ImageCms.profileToProfile(img, src, dst, outputMode="RGB")
        except Exception:
            pass
    return img.convert("RGB")


def fix_ratio(img, fit):
    w, h = img.size
    r = w / h
    if MIN_R <= r <= MAX_R or fit == "none":
        return img
    target = MIN_R if r < MIN_R else MAX_R
    if fit == "crop":
        if r < MIN_R:  # too tall: cut top/bottom
            nh = round(w / target)
            top = (h - nh) // 2
            return img.crop((0, top, w, top + nh))
        nw = round(h * target)  # too wide: cut sides
        left = (w - nw) // 2
        return img.crop((left, 0, left + nw, h))
    color = (0, 0, 0) if fit == "pad-black" else (255, 255, 255)
    if r < MIN_R:  # too tall: add side borders
        nw = round(h * target)
        canvas = Image.new("RGB", (nw, h), color)
        canvas.paste(img, ((nw - w) // 2, 0))
    else:          # too wide: add top/bottom borders
        nh = round(w / target)
        canvas = Image.new("RGB", (w, nh), color)
        canvas.paste(img, (0, (nh - h) // 2))
    return canvas


def prepare(src, dst, fit="pad-white"):
    img = Image.open(src)
    img = ImageOps.exif_transpose(img)
    img = to_srgb(img)
    img = fix_ratio(img, fit)
    if img.width > MAX_W:
        img = img.resize((MAX_W, round(img.height * MAX_W / img.width)), Image.LANCZOS)
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    for q in (92, 88, 84, 80, 75):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True, icc_profile=srgb)  # no exif => no GPS
        if buf.tell() <= MAX_BYTES:
            break
    with open(dst, "wb") as f:
        f.write(buf.getvalue())
    return img.size


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: prepare_image.py <src> <dst.jpg> [pad-white|pad-black|crop|none]")
    size = prepare(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "pad-white")
    print(f"saved {sys.argv[2]} {size[0]}x{size[1]}")
