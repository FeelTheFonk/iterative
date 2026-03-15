"""
score_svg.py — Immutable mechanical scorer for animated SVG (0-100).

THIS FILE IS READ-ONLY. The LLM must never modify it.
Scoring axes:
  Animation   (0-30): SMIL elements, CSS @keyframes, duration diversity
  Depth       (0-25): filters, gradients, groups, opacity, transforms
  Complexity  (0-25): shape diversity, perceptual color range, path richness
  Structure   (0-20): defs, style, clipPath, mask, pattern, symbol

Anti-gaming:
  - Duplicate element detection (penalizes copy-paste spam)
  - Animation duration diversity requirement
  - Perceptual color distance (clusters near-identical colors)
  - ViewBox compliance check

Usage: python score_svg.py masterpiece.svg
Output last line: SCORE: <number>
Lines before SCORE: per-axis breakdown (machine-parseable for feedback loop).
"""

import colorsys
import math
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from hashlib import md5


def local_tag(el):
    t = el.tag
    return t.split("}")[-1] if "}" in t else t


def hex_to_hsl(h):
    """Convert #rgb or #rrggbb to (hue, saturation, lightness) in [0,1]."""
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) < 6:
        return None
    try:
        r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    except ValueError:
        return None
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    return (hue, sat, light)


def perceptual_color_distance(c1, c2):
    """Rough perceptual distance in HLS space. Returns 0-1."""
    h1, s1, l1 = c1
    h2, s2, l2 = c2
    dh = min(abs(h1 - h2), 1 - abs(h1 - h2)) * 2  # hue wraps
    ds = abs(s1 - s2)
    dl = abs(l1 - l2)
    return math.sqrt(dh ** 2 + ds ** 2 + dl ** 2) / math.sqrt(4 + 1 + 1)


def count_perceptually_distinct_colors(hex_colors, threshold=0.08):
    """Cluster colors that are perceptually near-identical. Return distinct count."""
    hsls = []
    for h in hex_colors:
        hsl = hex_to_hsl(h)
        if hsl:
            hsls.append(hsl)
    if not hsls:
        return 0
    clusters = [hsls[0]]
    for hsl in hsls[1:]:
        if all(perceptual_color_distance(hsl, c) > threshold for c in clusters):
            clusters.append(hsl)
    return len(clusters)


def element_signature(el):
    """Hash of an element's tag + attributes + direct text for duplicate detection."""
    tag = local_tag(el)
    attrs = sorted((k, v) for k, v in el.attrib.items() if k != "id")
    text = (el.text or "").strip()
    return md5(f"{tag}|{attrs}|{text}".encode()).hexdigest()


def extract_durations(raw):
    """Extract all animation duration values in seconds."""
    durs = []
    for m in re.findall(r'dur\s*[:=]\s*"?([^";]+)', raw):
        m = m.strip().rstrip('"')
        try:
            if m.endswith("ms"):
                durs.append(float(m[:-2]) / 1000)
            elif m.endswith("s"):
                durs.append(float(m[:-1]))
            else:
                durs.append(float(m))
        except ValueError:
            pass
    # CSS animation-duration
    for m in re.findall(r"animation(?:-duration)?\s*:[^;]*?([\d.]+)s", raw):
        try:
            durs.append(float(m))
        except ValueError:
            pass
    return durs


def score_svg(filepath):
    # --- READ & VALIDATE ---
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("SCORE: 0")
        return 1

    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"ERROR: Invalid XML: {e}", file=sys.stderr)
        print("SCORE: 0")
        return 1

    all_elements = list(root.iter())
    tags = [local_tag(el) for el in all_elements]
    tag_counts = Counter(tags)

    if "script" in tag_counts:
        print("ERROR: <script> forbidden", file=sys.stderr)
        print("SCORE: 0")
        return 1

    size_kb = len(raw.encode("utf-8")) / 1024
    if size_kb > 500:
        print(f"ERROR: {size_kb:.0f}KB > 500KB", file=sys.stderr)
        print("SCORE: 0")
        return 1

    vb = root.get("viewBox", "")
    if vb != "0 0 800 600":
        print(f"ERROR: viewBox must be '0 0 800 600', got '{vb}'", file=sys.stderr)
        print("SCORE: 0")
        return 1

    elem_count = len(all_elements)

    # --- DUPLICATE DETECTION (anti-gaming) ---
    sigs = [element_signature(el) for el in all_elements]
    sig_counts = Counter(sigs)
    max_dup = max(sig_counts.values()) if sig_counts else 1
    # Penalty: if any element is duplicated >6 times, scale down total score
    dup_penalty = 1.0
    if max_dup > 6:
        dup_penalty = 6.0 / max_dup  # linear penalty

    scores = {}
    details = {}

    # === 1. ANIMATION (0-30) ===
    smil_tags = {"animate", "animateTransform", "animateMotion", "animateColor", "set"}
    smil_count = sum(tag_counts.get(t, 0) for t in smil_tags)
    css_keyframes = len(re.findall(r"@keyframes\s+\w+", raw))
    css_anim_props = len(re.findall(r"animation\s*:", raw))
    total_anim = smil_count + css_keyframes + css_anim_props

    # Diminishing returns: sqrt scaling after 8
    if total_anim <= 8:
        anim_base = total_anim * 2.5
    else:
        anim_base = 20 + math.sqrt(total_anim - 8) * 3.3

    # Technique diversity bonus
    tech_count = sum([smil_count > 0, css_keyframes > 0, css_anim_props > 0])
    anim_base += tech_count * 2

    # Duration diversity bonus (anti-gaming: penalize all-same-duration)
    durations = extract_durations(raw)
    unique_durs = len(set(round(d, 1) for d in durations)) if durations else 0
    if len(durations) >= 3:
        dur_diversity = min(1.0, unique_durs / max(3, len(durations) * 0.4))
    else:
        dur_diversity = 1.0 if unique_durs >= len(durations) else 0.5
    # Scale: 0-3 bonus for diverse durations
    anim_base += dur_diversity * 3

    scores["animation"] = min(30, anim_base)
    details["animation"] = f"SMIL:{smil_count} keyframes:{css_keyframes} css-anim:{css_anim_props} dur-variety:{unique_durs}/{len(durations)}"

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

    d = 0.0
    d += min(8, filter_els * 2 + min(fe_prims, 12))  # cap fe primitives contribution
    d += min(7, total_grads * 1.5)
    d += min(5, groups * 0.7)
    d += min(3, len(opacities) * 0.8)
    d += min(2, transforms * 0.25)
    scores["depth"] = min(25, d)
    details["depth"] = f"filters:{filter_els} fe:{fe_prims} grads:{total_grads} groups:{groups} opacities:{len(opacities)} transforms:{transforms}"

    # === 3. COMPLEXITY (0-25) ===
    shape_tags = {"circle", "ellipse", "rect", "line", "polyline", "polygon", "path", "text", "use", "image"}
    shape_types_used = len(shape_tags & set(tag_counts.keys()))
    total_shapes = sum(tag_counts.get(t, 0) for t in shape_tags)

    # Perceptual color diversity (anti-gaming: near-identical colors count as 1)
    raw_colors = set()
    for m in re.findall(r"#[0-9a-fA-F]{3,8}", raw):
        raw_colors.add(m.lower())
    # Named SVG colors
    svg_named = {
        "red", "blue", "green", "purple", "orange", "yellow", "cyan", "magenta",
        "white", "black", "pink", "gold", "silver", "coral", "crimson", "indigo",
        "violet", "teal", "salmon", "turquoise", "navy", "maroon", "lime",
        "aqua", "fuchsia", "olive", "sienna", "orchid", "plum", "peru", "tomato",
    }
    for nc in re.findall(r'(?:fill|stroke)\s*[:=]\s*"?([a-zA-Z]+)', raw):
        if nc.lower() in svg_named:
            raw_colors.add(nc.lower())

    distinct_colors = count_perceptually_distinct_colors(
        [c for c in raw_colors if c.startswith("#")]
    ) + len([c for c in raw_colors if not c.startswith("#")])

    # Path command richness
    path_cmds = 0
    cmd_types = set()
    for el in all_elements:
        d_attr = el.get("d", "")
        if d_attr:
            cmds = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]", d_attr)
            path_cmds += len(cmds)
            cmd_types.update(c.upper() for c in cmds)

    c = 0.0
    c += min(6, shape_types_used * 1.2)
    c += min(7, math.sqrt(total_shapes) * 1.5)  # sqrt: diminishing returns on shape count
    c += min(6, distinct_colors * 0.5)
    c += min(4, path_cmds * 0.04)
    c += min(2, len(cmd_types) * 0.4)  # path command diversity bonus
    scores["complexity"] = min(25, c)
    details["complexity"] = f"shapes:{total_shapes} types:{shape_types_used} colors:{distinct_colors}(raw:{len(raw_colors)}) paths:{path_cmds} cmd-types:{len(cmd_types)}"

    # === 4. STRUCTURE (0-20) ===
    s = 0.0
    s += 3 if "defs" in tag_counts else 0
    s += 2 if "style" in tag_counts else 0
    s += 2 if "clipPath" in tag_counts else 0
    s += 2 if "mask" in tag_counts else 0
    s += 1.5 if "pattern" in tag_counts else 0
    s += 1.5 if "symbol" in tag_counts else 0
    s += 1.5 if "use" in tag_counts else 0  # reuse via <use>

    # Element count sweet spot: 20-300 is ideal
    if 20 <= elem_count <= 300:
        s += 5
    elif 10 <= elem_count < 20:
        s += 3
    elif 300 < elem_count <= 500:
        s += 3
    elif elem_count > 500:
        s += 1  # bloated

    # viewBox already validated above
    s += 1.5
    scores["structure"] = min(20, s)
    details["structure"] = f"elems:{elem_count} defs:{'defs' in tag_counts} style:{'style' in tag_counts} clip:{'clipPath' in tag_counts} mask:{'mask' in tag_counts} pattern:{'pattern' in tag_counts} symbol:{'symbol' in tag_counts} use:{'use' in tag_counts}"

    # === COMPOSITE ===
    raw_total = sum(scores.values())
    total = round(raw_total * dup_penalty, 1)

    # --- Output: machine-parseable breakdown ---
    print(f"ANIMATION: {scores['animation']:.1f}/30  ({details['animation']})")
    print(f"DEPTH:     {scores['depth']:.1f}/25  ({details['depth']})")
    print(f"COMPLEXITY:{scores['complexity']:.1f}/25  ({details['complexity']})")
    print(f"STRUCTURE: {scores['structure']:.1f}/20  ({details['structure']})")
    if dup_penalty < 1.0:
        print(f"DUPLICATE_PENALTY: x{dup_penalty:.2f} (max {max_dup} identical elements)")
    print(f"SIZE: {size_kb:.1f}KB")
    print(f"SCORE: {total}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python score_svg.py <file.svg>")
        sys.exit(1)
    sys.exit(score_svg(sys.argv[1]))
