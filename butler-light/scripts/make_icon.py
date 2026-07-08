#!/usr/bin/env python3
import os
import struct
import subprocess
import zlib


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESOURCES = os.path.join(ROOT, "Resources")
ICONSET = os.path.join(RESOURCES, "AppIcon.iconset")
BASE = os.path.join(RESOURCES, "AppIcon-1024.png")
ICNS = os.path.join(RESOURCES, "AppIcon.icns")


def write_png(path, width, height, pixels):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + pixels[y * width * 4 : (y + 1) * width * 4] for y in range(height))
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as f:
        f.write(data)


def rounded_rect_alpha(x, y, size, radius):
    px = min(x, size - 1 - x)
    py = min(y, size - 1 - y)
    if px >= radius or py >= radius:
        return 255
    dx = radius - px
    dy = radius - py
    dist = (dx * dx + dy * dy) ** 0.5
    if dist <= radius - 2:
        return 255
    if dist >= radius + 2:
        return 0
    return int(max(0, min(255, (radius + 2 - dist) / 4 * 255)))


def main():
    os.makedirs(ICONSET, exist_ok=True)
    size = 1024
    margin = 96
    radius = 180
    pixels = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            idx = (y * size + x) * 4
            if margin <= x < size - margin and margin <= y < size - margin:
                a = rounded_rect_alpha(x - margin, y - margin, size - margin * 2, radius)
                t = (x + y) / (size * 2)
                r = int(255 * (1 - t) + 255 * t)
                g = int(114 * (1 - t) + 176 * t)
                b = int(64 * (1 - t) + 32 * t)
                pixels[idx : idx + 4] = bytes((r, g, b, a))
            else:
                pixels[idx : idx + 4] = b"\x00\x00\x00\x00"

    # Small status light mark.
    cx, cy = 690, 332
    for y in range(cy - 72, cy + 73):
        for x in range(cx - 72, cx + 73):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if d <= 72:
                idx = (y * size + x) * 4
                alpha = 255 if d < 62 else int((72 - d) / 10 * 255)
                pixels[idx : idx + 4] = bytes((255, 238, 180, max(0, min(255, alpha))))

    write_png(BASE, size, size, bytes(pixels))

    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for px, name in sizes:
        subprocess.run(["sips", "-z", str(px), str(px), BASE, "--out", os.path.join(ICONSET, name)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["iconutil", "-c", "icns", ICONSET, "-o", ICNS], check=True)
    print(ICNS)


if __name__ == "__main__":
    main()
