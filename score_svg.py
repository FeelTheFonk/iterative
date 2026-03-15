#!/usr/bin/env python3
"""
SVG Masterpiece Scorer — mechanical metric for animated SVG complexity/depth/beauty.

Composite score (0-100) based on:
  - Animation richness: SMIL + CSS keyframes          (0-30)
  - Depth & layering: filters, gradients, opacity      (0-25)
  - Visual complexity: shapes, colors, paths            (0-25)
  - Structure quality: defs, clipPath, mask, pattern    (0-20)

Usage: python score_svg.py masterpiece.svg
Output: SCORE: <number>
"""

import sys
import re
import xml.etree.ElementTree as ET
from collections import Counter


def score_svg(filepath: str) -> int:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        print(f"ERROR: Cannot read file: {e}", file=sys.stderr)
        print("SCORE: 0")
        return 1

    # --- VALIDITY ---
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"ERROR: Invalid XML: {e}", file=sys.stderr)
        print("SCORE: 0")
        return 1

    all_elements = list(root.iter())

    def local_tag(el):
        t = el.tag
        return t.split("}")[-1] if "}" in t else t

    # Reject <script>
    if any(local_tag(el) == "script" for el in all_elements):
        print("ERROR: Contains <script>", file=sys.stderr)
        print("SCORE: 0")
        return 1

    # Size guard
    size_kb = len(raw.encode("utf-8")) / 1024
    if size_kb > 500:
        print(f"ERROR: Too large ({size_kb:.0f}KB > 500KB)", file=sys.stderr)
        print("SCORE: 0")
        return 1

    scores = {}
    tag_list = [local_tag(el) for el in all_elements]
    tag_counts = Counter(tag_list)

    # === 1. ANIMATION (0-30) ===
    smil_tags = {"animate", "animateTransform", "animateMotion", "animateColor", "set"}
    smil_count = sum(tag_counts.get(t, 0) for t in smil_tags)
    css_keyframes = len(re.findall(r"@keyframes\s+\w+", raw))
    css_anim_props = len(re.findall(r"animation\s*:", raw))
    total_anim = smil_count + css_keyframes + css_anim_props
    anim_score = min(30, total_anim * 2.5 if total_anim <= 12 else 30)
    anim_techniques = sum([smil_count > 0, css_keyframes > 0, css_anim_props > 0])
    scores["animation"] = min(30, anim_score + anim_techniques * 2)

    # === 2. DEPTH (0-25) ===
    filter_els = tag_counts.get("filter", 0)
    fe_prims = sum(v for k, v in tag_counts.items() if k.startswith("fe"))
    lin_grads = tag_counts.get("linearGradient", 0)
    rad_grads = tag_counts.get("radialGradient", 0)
    total_grads = lin_grads + rad_grads
    groups = tag_counts.get("g", 0)

    opacities = set()
    for el in all_elements:
        for val in [el.get("opacity"), *re.findall(r"opacity\s*:\s*([\d.]+)", el.get("style", ""))]:
            if val:
                try:
                    opacities.add(round(float(val), 2))
                except ValueError:
                    pass

    transforms = sum(1 for el in all_elements if el.get("transform"))

    d = 0
    d += min(8, filter_els * 2 + fe_prims)
    d += min(7, total_grads * 1.5)
    d += min(5, groups * 0.8)
    d += min(3, len(opacities))
    d += min(2, transforms * 0.3)
    scores["depth"] = min(25, d)

    # === 3. COMPLEXITY (0-25) ===
    shape_tags = {"circle", "ellipse", "rect", "line", "polyline", "polygon", "path", "text", "use", "image"}
    shape_types_used = len(shape_tags & set(tag_counts.keys()))
    total_shapes = sum(tag_counts.get(t, 0) for t in shape_tags)

    colors = set()
    for m in re.findall(r"#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsla?\([^)]+\)", raw):
        colors.add(m.lower().strip())
    svg_named = {
        "red", "blue", "green", "purple", "orange", "yellow", "cyan", "magenta",
        "white", "black", "pink", "gold", "silver", "coral", "crimson", "indigo",
        "violet", "teal", "salmon", "turquoise", "navy", "maroon", "lime",
        "aqua", "fuchsia", "olive", "sienna", "orchid", "plum", "peru", "tomato",
    }
    for nc in re.findall(r'(?:fill|stroke)\s*[:=]\s*"?([a-zA-Z]+)', raw):
        if nc.lower() in svg_named:
            colors.add(nc.lower())

    path_cmds = sum(len(re.findall(r"[MmLlHhVvCcSsQqTtAaZz]", el.get("d", ""))) for el in all_elements)

    c = 0
    c += min(6, shape_types_used * 1.2)
    c += min(7, total_shapes * 0.25)
    c += min(6, len(colors) * 0.5)
    c += min(6, path_cmds * 0.05)
    scores["complexity"] = min(25, c)

    # === 4. STRUCTURE (0-20) ===
    s = 0
    s += 3 if "defs" in tag_counts else 0
    s += 2 if root.get("viewBox") else 0
    elem_count = len(all_elements)
    s += 5 if 10 <= elem_count <= 500 else (2 if 5 <= elem_count < 10 else 3 if elem_count > 500 else 0)
    s += 3 if "style" in tag_counts else 0
    s += 2 if "clipPath" in tag_counts else 0
    s += 2 if "mask" in tag_counts else 0
    s += 1.5 if "pattern" in tag_counts else 0
    s += 1.5 if "symbol" in tag_counts else 0
    scores["structure"] = min(20, s)

    total = round(sum(scores.values()), 1)

    print("--- SVG Masterpiece Score ---")
    print(f"  Animation:  {scores['animation']:.1f}/30  (SMIL:{smil_count} keyframes:{css_keyframes} css-anim:{css_anim_props})")
    print(f"  Depth:      {scores['depth']:.1f}/25  (filters:{filter_els} gradients:{total_grads} groups:{groups} opacities:{len(opacities)})")
    print(f"  Complexity: {scores['complexity']:.1f}/25  (shapes:{total_shapes} types:{shape_types_used} colors:{len(colors)} path-cmds:{path_cmds})")
    print(f"  Structure:  {scores['structure']:.1f}/20  (elements:{elem_count} defs:{'defs' in tag_counts} style:{'style' in tag_counts} clip:{'clipPath' in tag_counts} mask:{'mask' in tag_counts})")
    print(f"  Size:       {size_kb:.1f}KB")
    print(f"SCORE: {total}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python score_svg.py <file.svg>")
        sys.exit(1)
    sys.exit(score_svg(sys.argv[1]))
