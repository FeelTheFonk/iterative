"""
autoresearch_loop.py — Autonomous SVG evolution via llama-server.

Architecture (from Karpathy's autoresearch + Self-Refine):
  1. Immutable scorer (score_svg.py) — agent cannot modify
  2. Single mutable artifact (masterpiece.svg)
  3. Git as memory — branch history is monotonically improving
  4. Context compression — only current SVG + score breakdown + compressed history
  5. Temperature scheduling — exploration early, exploitation late
  6. Diversity injection — rotates strategy after consecutive failures

Windows-compatible: UTF-8 git, lock file management, CREATE_NO_WINDOW.
"""

import math
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
API_URL = "http://localhost:8001/v1/chat/completions"
MODEL = "HauhauCS/Qwen3.5-35B-A3B"
SVG_FILE = Path("masterpiece.svg")
SCORER = Path("score_svg.py")
LOG_FILE = Path("autoresearch-results.tsv")
OUTPUT_DIR = Path("output")
SUMMARY_EVERY = 10
API_TIMEOUT = 300.0

# Sampling: Qwen3 recommended base, with dynamic temperature
BASE_TEMP = 0.6
MIN_TEMP = 0.35
TOP_P = 0.95
TOP_K = 20
MIN_P = 0.05
REPEAT_PENALTY = 1.0

IS_WINDOWS = os.name == "nt"
CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0


# ──────────────────────────────────────────────
# GIT (Windows-safe)
# ──────────────────────────────────────────────
def git(*args):
    """Run git command with proper Windows encoding and flags."""
    try:
        return subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            cwd=str(Path.cwd()),
            creationflags=CREATION_FLAGS,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            timeout=30,
        )
    except Exception as e:
        print(f"  [GIT ERROR] {' '.join(args)}: {e}")
        return None


def git_init():
    """Initialize git repo if needed, with Windows-safe config."""
    if not Path(".git").exists():
        git("init")
        git("config", "core.autocrlf", "false")
        git("config", "core.quotepath", "false")
        git("add", "-A")
        git("commit", "-m", "autoresearch: seed")
        print("  Git repo initialized.")
    else:
        print("  Git repo found.")


def git_commit(message):
    """Commit current SVG. Handles stale lock files on Windows."""
    lock = Path(".git/index.lock")
    if lock.exists():
        try:
            age = time.time() - lock.stat().st_mtime
            if age > 30:
                lock.unlink()
                print("  [GIT] Removed stale index.lock")
        except OSError:
            pass
    git("add", str(SVG_FILE))
    result = git("commit", "-m", message)
    if result and result.returncode == 0:
        return True
    return False


def git_revert():
    git("checkout", "--", str(SVG_FILE))


# ──────────────────────────────────────────────
# LLM
# ──────────────────────────────────────────────
def call_llm(messages, temperature):
    """Call llama-server with explicit sampling params and cache_prompt."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 16384,
        "temperature": temperature,
        "top_p": TOP_P,
        "top_k": TOP_K,
        "min_p": MIN_P,
        "repeat_penalty": REPEAT_PENALTY,
        "cache_prompt": True,
        "stream": False,
    }
    try:
        r = httpx.post(
            API_URL, json=payload,
            timeout=httpx.Timeout(API_TIMEOUT, connect=10.0),
        )
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        # Strip Qwen thinking blocks if present
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        return content
    except Exception as e:
        print(f"  [LLM ERROR] {e}")
        return ""


# ──────────────────────────────────────────────
# SCORING
# ──────────────────────────────────────────────
def run_scorer():
    """Run score_svg.py. Returns (score, breakdown_text) or (None, error)."""
    try:
        result = subprocess.run(
            [sys.executable, str(SCORER), str(SVG_FILE)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=30, cwd=str(Path.cwd()),
            creationflags=CREATION_FLAGS,
        )
        stdout = result.stdout
        score = None
        for line in stdout.splitlines():
            if line.startswith("SCORE:"):
                score = float(line.split(":", 1)[1].strip())

        # Extract breakdown lines (everything before SCORE:)
        breakdown_lines = [
            l for l in stdout.splitlines()
            if l.startswith(("ANIMATION:", "DEPTH:", "COMPLEXITY:", "STRUCTURE:", "DUPLICATE_PENALTY:", "SIZE:"))
        ]
        breakdown = "\n".join(breakdown_lines)

        if score is not None:
            return score, breakdown

        err = result.stderr.strip()[:200] if result.stderr else "no SCORE line"
        return None, err
    except Exception as e:
        return None, str(e)


def weakest_axis(breakdown):
    """Parse breakdown to find the axis with most room for improvement."""
    axes = {}
    for line in breakdown.splitlines():
        for name, maxval in [("ANIMATION", 30), ("DEPTH", 25), ("COMPLEXITY", 25), ("STRUCTURE", 20)]:
            if line.startswith(name + ":"):
                try:
                    val = float(line.split(":")[1].split("/")[0].strip())
                    axes[name] = (val, maxval, maxval - val)
                except (ValueError, IndexError):
                    pass
    if not axes:
        return "ANIMATION", 30.0
    # Return axis with largest gap
    worst = max(axes.items(), key=lambda x: x[1][2])
    return worst[0], worst[1][2]


# ──────────────────────────────────────────────
# SVG EXTRACTION
# ──────────────────────────────────────────────
def extract_svg(response):
    """Extract complete SVG from LLM response. Multiple strategies."""
    # Strategy 1: fenced block (```svg, ```xml, ```)
    for m in re.findall(r"```(?:xml|svg|html)?\s*\n(.*?)\n```", response, re.DOTALL):
        c = m.strip()
        if "<svg" in c and "</svg>" in c:
            return c[c.index("<svg"):c.rindex("</svg>") + 6]
    # Strategy 2: bare <svg>...</svg>
    m = re.search(r"(<svg\b[\s\S]*?</svg>)", response)
    if m:
        return m.group(1)
    return None


def extract_description(response):
    for line in response.splitlines()[:10]:  # Only check first 10 lines
        ls = line.strip()
        for prefix in ("CHANGE:", "MODIFICATION:", "CHANGEMENT:"):
            if ls.upper().startswith(prefix):
                return ls.split(":", 1)[1].strip()
    return "unknown change"


# ──────────────────────────────────────────────
# TEMPERATURE SCHEDULING
# ──────────────────────────────────────────────
def compute_temperature(best_score, consecutive_fails):
    """Higher temp when exploring (low score or stuck), lower when exploiting (high score)."""
    # Base: interpolate between BASE_TEMP and MIN_TEMP based on score progress
    progress = min(1.0, best_score / 90.0)  # 90 = practical ceiling
    temp = BASE_TEMP - (BASE_TEMP - MIN_TEMP) * progress
    # Boost on consecutive failures (exploration kick)
    if consecutive_fails >= 5:
        temp = min(0.9, temp + 0.2)
    elif consecutive_fails >= 3:
        temp = min(0.8, temp + 0.1)
    return round(temp, 2)


# ──────────────────────────────────────────────
# CONTEXT COMPRESSION
# ──────────────────────────────────────────────
DIVERSITY_STRATEGIES = [
    "Focus sur la dimension la plus faible identifiée ci-dessus. Un seul changement ciblé.",
    "Essaie une technique SVG que tu n'as pas encore utilisée (animateMotion, pattern, mask, clipPath, symbol, use).",
    "Ajoute de la profondeur : un nouveau calque (background OU midground OU foreground) avec un rythme d'animation différent.",
    "Combine deux éléments existants avec une nouvelle interaction : un filtre qui s'applique à un groupe, un clipPath qui révèle un gradient, etc.",
    "Changement radical : restructure les couches existantes ou remplace un élément faible par un plus riche.",
]

SYSTEM_PROMPT = """\
Tu es un artiste SVG d'elite. Tu fais evoluer un SVG anime (800x600) vers un chef-d'oeuvre visuel avec une profondeur immense.

STYLE : scenes cosmiques, oceans bioluminescents, champs de particules, architectures geometriques etherees. L'oeuvre doit sembler VIVANTE.

REGLES ABSOLUES :
- SVG + CSS uniquement. ZERO <script>. ZERO JavaScript.
- XML valide. viewBox="0 0 800 600" width="800" height="600".
- Max 500KB. Pas d'elements dupliques en masse (le scorer penalise le spam).
- Animations SMIL (animate, animateTransform, animateMotion) et/ou CSS @keyframes dans <style>.
- Varier les durations d'animation (le scorer mesure la diversite des durations).

SCORING :
- Animation (30pts) : elements SMIL, @keyframes, proprietes CSS animation, diversite des durations
- Profondeur (25pts) : <filter>+fe*, gradients, <g> groups, opacity variance, transforms
- Complexite (25pts) : types de shapes varies, couleurs PERCEPTUELLEMENT distinctes, richesse des paths
- Structure (20pts) : <defs>, <style>, <clipPath>, <mask>, <pattern>, <symbol>, <use>

PROFONDEUR PAR COUCHES :
- Background (z-far) : gradients larges, feGaussianBlur, animations 30-60s
- Midground : geometrie, formes organiques, animations 5-15s
- Foreground (z-near) : accents lumineux, particules, animations 1-5s

FORMAT DE REPONSE (strict) :
CHANGE: <1 phrase decrivant la modification>
```svg
<SVG COMPLET de <svg> a </svg>, pas un extrait>
```"""


def build_prompt(current_svg, best_score, breakdown, history_summary, strategy_hint):
    """Build user prompt with compressed context and actionable feedback."""
    weak_name, weak_gap = weakest_axis(breakdown)

    return f"""Score actuel : {best_score:.1f}/100
Dimension la plus faible : {weak_name} (marge restante : {weak_gap:.1f} points)

Breakdown du scorer :
{breakdown}

Historique recent :
{history_summary}

Directive : {strategy_hint}

SVG actuel :
```svg
{current_svg}
```

Fais UNE SEULE modification atomique. Donne le SVG COMPLET (de <svg> a </svg>)."""


def compress_history(log_path, max_entries=8):
    """Compress log to last N entries as one-liners. Context-efficient."""
    if not log_path.exists():
        return "(aucun historique)"
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()[1:]  # skip header
    if not lines:
        return "(aucun historique)"
    recent = lines[-max_entries:]
    summary = []
    for line in recent:
        parts = line.split("\t")
        if len(parts) >= 5:
            it, metric, delta, status, desc = parts[0], parts[1], parts[2], parts[3], parts[4]
            symbol = {"keep": "+", "discard": "-", "crash": "X", "skip": "?", "baseline": "="}
            s = symbol.get(status, "?")
            summary.append(f"  [{s}] #{it} {metric} ({delta}) {desc[:60]}")
    return "\n".join(summary) if summary else "(aucun historique)"


# ──────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────
def init_log():
    if not LOG_FILE.exists():
        LOG_FILE.write_text("iteration\tmetric\tdelta\tstatus\tdescription\n", encoding="utf-8")


def log_entry(iteration, metric, delta, status, desc):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{iteration}\t{metric}\t{delta:+.1f}\t{status}\t{desc}\n")


def print_summary(iteration, baseline, best):
    if not LOG_FILE.exists():
        return
    lines = LOG_FILE.read_text(encoding="utf-8").strip().splitlines()[1:]
    keeps = sum(1 for l in lines if "\tkeep\t" in l)
    discards = sum(1 for l in lines if "\tdiscard\t" in l)
    crashes = sum(1 for l in lines if "\tcrash\t" in l)
    skips = sum(1 for l in lines if "\tskip\t" in l)

    print()
    print(f"{'=' * 60}")
    print(f"  PROGRESS — iteration {iteration}")
    print(f"  Baseline: {baseline} -> Best: {best} (+{best - baseline:.1f})")
    print(f"  Keeps: {keeps} | Discards: {discards} | Crashes: {crashes} | Skips: {skips}")
    if keeps + discards > 0:
        print(f"  Keep rate: {keeps / (keeps + discards) * 100:.0f}%")
    print(f"{'=' * 60}")
    print()


# ──────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    init_log()
    git_init()

    # Baseline
    baseline_score, baseline_breakdown = run_scorer()
    if baseline_score is None or baseline_score == 0:
        print(f"FATAL: Cannot score seed SVG: {baseline_breakdown}")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"  AUTORESEARCH — SVG Masterpiece Evolution")
    print(f"  Baseline:  {baseline_score}/100")
    print(f"  Model:     {MODEL}")
    print(f"  API:       {API_URL}")
    print(f"  Ctrl+C to stop")
    print(f"{'=' * 60}")
    print(f"\n{baseline_breakdown}\n")

    log_entry(0, baseline_score, 0.0, "baseline", "initial seed")
    best = baseline_score
    best_breakdown = baseline_breakdown
    iteration = 0
    consecutive_fails = 0
    strategy_idx = 0

    try:
        while True:
            iteration += 1
            ts = datetime.now().strftime("%H:%M:%S")

            current_svg = SVG_FILE.read_text(encoding="utf-8")
            history_summary = compress_history(LOG_FILE)

            # Temperature scheduling
            temp = compute_temperature(best, consecutive_fails)

            # Strategy rotation on consecutive failures
            if consecutive_fails >= 3:
                strategy_idx = (strategy_idx + 1) % len(DIVERSITY_STRATEGIES)
            strategy = DIVERSITY_STRATEGIES[strategy_idx % len(DIVERSITY_STRATEGIES)]

            prompt = build_prompt(current_svg, best, best_breakdown, history_summary, strategy)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]

            print(f"  [{ts}] #{iteration} T={temp} (score:{best}) ...", end=" ", flush=True)
            t0 = time.time()
            response = call_llm(messages, temp)
            elapsed = time.time() - t0

            if not response:
                print(f"empty ({elapsed:.0f}s)")
                log_entry(iteration, 0, 0, "skip", "empty LLM response")
                consecutive_fails += 1
                if consecutive_fails > 6:
                    time.sleep(15)
                continue

            new_svg = extract_svg(response)
            description = extract_description(response)

            if new_svg is None:
                print(f"no SVG ({elapsed:.0f}s)")
                log_entry(iteration, 0, 0, "skip", f"extraction failed: {description[:80]}")
                consecutive_fails += 1
                continue

            # Write new SVG, score it
            backup = current_svg
            SVG_FILE.write_text(new_svg, encoding="utf-8")

            new_score, new_breakdown = run_scorer()

            if new_score is None or new_score == 0:
                SVG_FILE.write_text(backup, encoding="utf-8")
                print(f"CRASH ({elapsed:.0f}s): {description[:55]}")
                log_entry(iteration, 0, 0, "crash", description[:120])
                consecutive_fails += 1
                continue

            delta = new_score - best

            if delta > 0:
                # KEEP — commit, snapshot, advance
                best = new_score
                best_breakdown = new_breakdown
                msg = f"#{iteration} +{delta:.1f} -> {new_score:.1f}: {description[:60]}"
                committed = git_commit(msg)
                snapshot = OUTPUT_DIR / f"iter_{iteration:04d}_score_{new_score:.1f}.svg"
                shutil.copy2(SVG_FILE, snapshot)
                c_mark = "G" if committed else "g"
                print(f"KEEP [{c_mark}] {new_score:.1f} (+{delta:.1f}) ({elapsed:.0f}s): {description[:50]}")
                log_entry(iteration, new_score, delta, "keep", description[:120])
                consecutive_fails = 0
                strategy_idx = 0
            else:
                SVG_FILE.write_text(backup, encoding="utf-8")
                label = "TIE " if delta == 0 else "DISC"
                print(f"{label} {new_score:.1f} ({delta:+.1f}) ({elapsed:.0f}s): {description[:50]}")
                log_entry(iteration, new_score, delta, "discard", description[:120])
                consecutive_fails += 1

            if iteration % SUMMARY_EVERY == 0:
                print_summary(iteration, baseline_score, best)

    except KeyboardInterrupt:
        print(f"\n\nStopped at iteration {iteration}.")
        print_summary(iteration, baseline_score, best)
        print(f"SVG:       {SVG_FILE.resolve()}")
        print(f"Snapshots: {OUTPUT_DIR.resolve()}")
        print(f"Log:       {LOG_FILE.resolve()}")
        print(f"Git:       git log --oneline")


if __name__ == "__main__":
    main()
