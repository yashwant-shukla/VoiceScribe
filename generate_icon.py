"""Generate a macOS .icns app icon for VoiceScribe.
Run once: python generate_icon.py
Creates icon.icns in the current directory.
"""

import struct
import os
import tempfile
import subprocess
import math


def create_png_icon(size):
    """Create a simple microphone icon as PNG bytes using pure Python."""

    # We'll create a minimal valid PNG with a gradient background and mic shape
    # For simplicity, we'll generate pixel data directly

    width = height = size
    pixels = []

    cx, cy = width / 2, height / 2
    corner_r = size * 0.18  # rounded corner radius
    margin = size * 0.06

    for y in range(height):
        row = []
        for x in range(width):
            # Check if inside rounded rectangle
            rx = x - margin
            ry = y - margin
            rw = width - 2 * margin
            rh = height - 2 * margin

            inside = False
            if margin <= x <= width - margin and margin <= y <= height - margin:
                # Check corners
                if rx < corner_r and ry < corner_r:
                    inside = math.hypot(rx - corner_r, ry - corner_r) <= corner_r
                elif rx > rw - corner_r and ry < corner_r:
                    inside = math.hypot(rx - (rw - corner_r), ry - corner_r) <= corner_r
                elif rx < corner_r and ry > rh - corner_r:
                    inside = math.hypot(rx - corner_r, ry - (rh - corner_r)) <= corner_r
                elif rx > rw - corner_r and ry > rh - corner_r:
                    inside = math.hypot(rx - (rw - corner_r), ry - (rh - corner_r)) <= corner_r
                else:
                    inside = True

            if inside:
                # Gradient from #007AFF to #5856D6
                t = y / height
                r = int(0x00 + (0x58 - 0x00) * t)
                g = int(0x7A + (0x56 - 0x7A) * t)
                b = int(0xFF + (0xD6 - 0xFF) * t)

                # Draw microphone shape — proportions designed to fit within icon
                mic_cx = width / 2
                mic_top = height * 0.20   # top of mic body
                mic_bot = height * 0.50   # bottom of mic body
                mic_w = size * 0.11       # half-width of mic body
                mic_cap_r = mic_w         # radius for rounded top/bottom caps

                # Mic body (rectangular middle)
                in_mic_body = (abs(x - mic_cx) <= mic_w and
                               mic_top <= y <= mic_bot)

                # Mic head (full semicircle on top)
                in_mic_head = (math.hypot(x - mic_cx, y - mic_top) <= mic_cap_r and
                               y <= mic_top)

                # Mic bottom (full semicircle on bottom)
                in_mic_bottom = (math.hypot(x - mic_cx, y - mic_bot) <= mic_cap_r and
                                 y >= mic_bot)

                # Arc (cradle) around mic
                arc_cy = mic_bot + size * 0.02
                arc_r_outer = size * 0.20
                arc_r_inner = size * 0.16
                arc_dist = math.hypot(x - mic_cx, y - arc_cy)
                in_arc = (arc_r_inner < arc_dist < arc_r_outer and
                          y > arc_cy and y < arc_cy + arc_r_outer)

                # Stand (vertical line from arc bottom to base)
                stand_w = size * 0.025
                stand_top = arc_cy + arc_r_inner
                stand_bot = height * 0.76
                in_stand = (abs(x - mic_cx) < stand_w and
                            stand_top < y < stand_bot)

                # Base (horizontal bar)
                base_w = size * 0.13
                base_h = size * 0.03
                base_y = stand_bot
                in_base = (abs(x - mic_cx) < base_w and
                           base_y <= y <= base_y + base_h)

                if in_mic_body or in_mic_head or in_mic_bottom or in_arc or in_stand or in_base:
                    row.append((255, 255, 255, 255))
                else:
                    row.append((r, g, b, 255))
            else:
                row.append((0, 0, 0, 0))

        pixels.append(row)

    return encode_png(width, height, pixels)


def encode_png(width, height, pixels):
    """Encode RGBA pixels as a PNG file (minimal encoder)."""
    import zlib

    def chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack('>I', len(data)) + c + crc

    # PNG signature
    sig = b'\x89PNG\r\n\x1a\n'

    # IHDR
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    ihdr = chunk(b'IHDR', ihdr_data)

    # IDAT
    raw_data = b''
    for row in pixels:
        raw_data += b'\x00'  # filter: none
        for r, g, b, a in row:
            raw_data += struct.pack('BBBB', r, g, b, a)

    compressed = zlib.compress(raw_data, 9)
    idat = chunk(b'IDAT', compressed)

    # IEND
    iend = chunk(b'IEND', b'')

    return sig + ihdr + idat + iend


def create_icns(output_path):
    """Create .icns file from PNG icons."""

    # Generate PNGs at required sizes
    sizes = {
        'ic07': 128,   # 128x128
        'ic08': 256,   # 256x256
        'ic09': 512,   # 512x512
    }

    # Build ICNS file
    icns_data = b''

    for icon_type, size in sizes.items():
        print(f"  Generating {size}x{size} icon...")
        png_data = create_png_icon(size)
        entry = icon_type.encode('ascii') + struct.pack('>I', len(png_data) + 8) + png_data
        icns_data += entry

    # ICNS header
    total_size = len(icns_data) + 8
    icns_file = b'icns' + struct.pack('>I', total_size) + icns_data

    with open(output_path, 'wb') as f:
        f.write(icns_file)

    print(f"  Icon saved to {output_path}")


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output = os.path.join(script_dir, "icon.icns")
    print("Generating VoiceScribe icon...")
    create_icns(output)
    print("Done!")
