#!/usr/bin/env python3
"""Generate a single-layer first-layer test print for the Sovol SV06 Plus.

Prints five solid 40x40 mm patches - four inset from the corners plus one
centred - so that Z-offset can be tuned live with SET_GCODE_OFFSET while the
print runs, and so cross-bed uniformity can be confirmed at the same time.

Flow defaults to 1.0 rather than the slicer's 0.92 on purpose: if the patches
look correct here but real prints show gaps, the flow ratio is the culprit and
not the Z-offset.

Usage:
    python3 gen_first_layer_test.py [-o OUTPUT] [--flow 1.0] [--bed 60]
                                    [--hotend 215] [--width 0.45]
"""

import argparse
import math

FILAMENT_DIAMETER = 1.75
PATCH = 40.0          # patch edge length, mm
INSET = 50.0          # corner patch origin offset from bed edge, mm
BED_SIZE = 300.0


def extrusion_per_mm(width, height, flow):
    """Cross-section of a rounded-rectangle bead, converted to filament mm."""
    bead = (width - height) * height + math.pi * (height / 2.0) ** 2
    filament = math.pi * (FILAMENT_DIAMETER / 2.0) ** 2
    return (bead / filament) * flow


def patch(x0, y0, size, width, height, e_per_mm, speed):
    """Serpentine raster fill. Lines run along X, stepping in Y.

    Enters at hop height, descends, prints, retracts, then hops back up, so
    travel between patches never drags the nozzle over printed material.
    """
    out = [f"; --- patch at {x0:.1f},{y0:.1f} ---"]
    lines = int(size / width) + 1
    step = size / (lines - 1)

    out.append(f"G0 X{x0:.3f} Y{y0:.3f} F9000   ; travel at hop height")
    out.append(f"G0 Z{height:.3f} F600          ; down to print height")
    out.append("G1 E0.4 F1800          ; prime after travel")

    for i in range(lines):
        y = y0 + i * step
        # Alternate direction so we never travel dry back to the start.
        xa, xb = (x0, x0 + size) if i % 2 == 0 else (x0 + size, x0)
        out.append(f"G1 X{xb:.3f} Y{y:.3f} E{size * e_per_mm:.5f} F{speed}")
        if i < lines - 1:
            out.append(f"G1 Y{y + step:.3f} E{step * e_per_mm:.5f} F{speed}")

    out.append("G1 E-0.5 F2400         ; retract before travel")
    out.append(f"G0 Z{height + 1.0:.3f} F600    ; hop clear of printed material")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-o", "--output", default="first_layer_test.gcode")
    p.add_argument("--flow", type=float, default=1.0)
    p.add_argument("--bed", type=int, default=60)
    p.add_argument("--hotend", type=int, default=215)
    p.add_argument("--height", type=float, default=0.28)
    p.add_argument("--width", type=float, default=0.45)
    p.add_argument("--speed", type=int, default=2400)  # mm/min == 40 mm/s
    args = p.parse_args()

    e_per_mm = extrusion_per_mm(args.width, args.height, args.flow)

    far = BED_SIZE - INSET - PATCH
    mid = (BED_SIZE - PATCH) / 2.0
    origins = [
        (INSET, INSET), (far, INSET),
        (mid, mid),
        (INSET, far), (far, far),
    ]

    xs = [o[0] for o in origins] + [o[0] + PATCH for o in origins]
    ys = [o[1] for o in origins] + [o[1] + PATCH for o in origins]

    g = [
        "; First layer test - 5 solid patches, single layer",
        f"; layer height {args.height}  line width {args.width}  flow {args.flow}",
        f"; extrusion {e_per_mm:.5f} mm filament per mm of travel",
        ";",
        "; Tune live while this runs:",
        ";   gaps between lines      -> SET_GCODE_OFFSET Z_ADJUST=-0.02 MOVE=1",
        ";   glossy / ridged / wavy  -> SET_GCODE_OFFSET Z_ADJUST=+0.02 MOVE=1",
        "; Then: new z_offset = current z_offset - (net Z_ADJUST applied)",
        ";",
        f"PRINT_START BED={args.bed} HOTEND={args.hotend} NOZZLE=0.4 PA=0.05 "
        f"AREA_START={min(xs):.1f},{min(ys):.1f} AREA_END={max(xs):.1f},{max(ys):.1f}",
        "M107                   ; fan off, matching real first-layer conditions",
        "G90                    ; absolute XY",
        "M83                    ; relative E",
        f"G1 Z{args.height + 1.0:.3f} F600   ; start at hop height",
    ]

    for x0, y0 in origins:
        g += patch(x0, y0, PATCH, args.width, args.height, e_per_mm, args.speed)

    g += ["PRINT_END", ""]

    with open(args.output, "w") as fh:
        fh.write("\n".join(g))

    total = len(origins) * (int(PATCH / args.width) + 1) * PATCH
    print(f"wrote {args.output}")
    print(f"  patches   : {len(origins)} x {PATCH:.0f}x{PATCH:.0f} mm")
    print(f"  extrusion : {e_per_mm:.5f} mm/mm (flow {args.flow})")
    print(f"  filament  : ~{total * e_per_mm:.0f} mm")
    print(f"  est. time : ~{total / (args.speed / 60.0) / 60.0:.0f} min of extrusion")


if __name__ == "__main__":
    main()
