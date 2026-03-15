"""
autoresearch_loop.py — Autonomous SVG evolution via llama-server (OpenAI-compatible API).

Boucle infinie : Read → LLM proposes 1 change → Verify → Keep/Discard → Repeat.
Git as memory. TSV as log. Snapshots in output/.

Usage:
    python autoresearch_loop.py

Requires:
    - llama-server running on localhost:8001 with OpenAI-compatible API
    - git initialized in this directory
"""

import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# ──────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────
API_URL = "http://localhost:8001/v1/chat/completions"
MODEL = "HauhauCS/Qwen3.5-35B-A3B"  # must match --alias
SVG_FILE = Path("masterpiece.svg")
SCORER = Path("scripts/score_svg.py")
LOG_FILE = Path("autoresearch-results.tsv")
OUTPUT_DIR = Path("output")
MAX_RETRIES_ON_CRASH = 3
SUMMARY_EVERY = 10
API_TIMEOUT = 300  # seconds — large ctx can be slow


def call_llm(prompt: str, system: str = "") -> str:
    """Call llama-server OpenAI-compatible endpoint."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 16384,
        "temperature": 0.7,
        "top_p": 0.9,
        "stream": False,
    }

    try:
        r = httpx.post(API_URL, json=payload, timeout=API_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [LLM ERROR] {e}")
        return ""


def run_scorer() -> float | None:
    """Run score_svg.py, return score or None on failure."""
    try:
        result = subprocess.run(
            [sys.executable, str(SCORER), str(SVG_FILE)],
            capture_output=True, text=True, timeout=30
        )
        for line in result.stdout.splitlines():
            if line.startswith("SCORE:"):
                val = line.split(":", 1)[1].strip()
                return float(val)
        # Print stderr for debug
        if result.stderr:
            print(f"  [SCORER STDERR] {result.stderr.strip()}")
        return None
    except Exception as e:
        print(f"  [SCORER ERROR] {e}")
        return None


def git_commit(message: str):
    subprocess.run(["git", "add", str(SVG_FILE)], capture_output=True)
    subprocess.run(["git", "commit", "-m", message, "--allow-empty"], capture_output=True)


def git_revert():
    subprocess.run(["git", "checkout", "--", str(SVG_FILE)], capture_output=True)


def extract_svg(response: str) -> str | None:
    """Extract complete SVG from LLM response. Handles markdown fences."""
    # Try to find SVG block between ```xml or ```svg or ``` fences
    fence_patterns = [
        r"```(?:xml|svg|html)?\s*\n(.*?)\n```",
        r"<svg[\s\S]*?</svg>",
    ]
    for pattern in fence_patterns:
        matches = re.findall(pattern, response, re.DOTALL)
        for match in matches:
            candidate = match.strip()
            if "<svg" in candidate and "</svg>" in candidate:
                # Extract just the SVG part
                start = candidate.index("<svg")
                end = candidate.rindex("</svg>") + len("</svg>")
                return candidate[start:end]

    return None


def extract_description(response: str) -> str:
    """Extract change description from LLM response."""
    for line in response.splitlines():
        line_stripped = line.strip()
        if line_stripped.upper().startswith("CHANGE:"):
            return line_stripped.split(":", 1)[1].strip()
        if line_stripped.upper().startswith("MODIFICATION:"):
            return line_stripped.split(":", 1)[1].strip()
    return "unknown change"


def log_entry(iteration: int, metric: float, delta: float, status: str, desc: str):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{iteration}\t{metric}\t{delta:+.1f}\t{status}\t{desc}\n")


def print_summary(iteration: int, baseline: float, best: float):
    if not LOG_FILE.exists():
        return
    lines = LOG_FILE.read_text(encoding="utf-8").strip().splitlines()[1:]  # skip header
    keeps = sum(1 for l in lines if "\tkeep\t" in l)
    discards = sum(1 for l in lines if "\tdiscard\t" in l)
    crashes = sum(1 for l in lines if "\tcrash\t" in l)
    skips = sum(1 for l in lines if "\tskip\t" in l)
    last5 = [l.split("\t")[3] for l in lines[-5:]] if len(lines) >= 5 else []

    print()
    print(f"{'=' * 55}")
    print(f"  PROGRESS — iteration {iteration}")
    print(f"  Baseline: {baseline} → Best: {best} (+{best - baseline:.1f})")
    print(f"  Keeps: {keeps} | Discards: {discards} | Crashes: {crashes} | Skips: {skips}")
    if last5:
        print(f"  Last 5: {', '.join(last5)}")
    print(f"{'=' * 55}")
    print()


SYSTEM_PROMPT = """\
Tu es un artiste SVG d'élite. Tu crées des oeuvres animées d'une beauté saisissante.
Tu travailles sur un SVG unique (800x600) qui doit devenir un chef-d'oeuvre animé avec une profondeur visuelle immense.

STYLE VISUEL CIBLÉ : scènes cosmiques, océans bioluminescents, champs de particules abstraits,
architectures géométriques éthérées — tout ce qui évoque la profondeur, le mouvement organique,
et une beauté contemplative. L'oeuvre doit sembler VIVANTE.

RÈGLES ABSOLUES :
- SVG + CSS uniquement. AUCUN <script>. AUCUN JavaScript.
- XML valide en permanence.
- viewBox="0 0 800 600" obligatoire.
- Max 500KB.
- Animations via SMIL (animate, animateTransform, animateMotion) et/ou CSS @keyframes dans <style>.

MÉTRIQUE DE SCORING (ce que tu optimises) :
- Animation richness (30pts) : éléments SMIL, @keyframes, propriétés animation
- Depth & layering (25pts) : <filter>, gradients, <g> groups, opacity, transforms
- Visual complexity (25pts) : diversité de shapes, palette couleurs, complexité des paths
- Structure quality (20pts) : <defs>, <style>, <clipPath>, <mask>, <pattern>, <symbol>

TECHNIQUE DE PROFONDEUR :
- Couches background (z-far) : gradients diffus, formes floues (feGaussianBlur), animations lentes (30-60s)
- Couches midground : formes géométriques, éléments organiques, animations moyennes (5-15s)
- Couches foreground (z-near) : accents lumineux, particules fines, animations rapides (1-5s)
- Parallaxe : les couches éloignées bougent lentement, les proches rapidement

FORMAT DE RÉPONSE OBLIGATOIRE :
CHANGE: <description en 1 phrase de la modification>
```svg
<le SVG COMPLET modifié — pas un extrait, le fichier entier>
```"""


def build_user_prompt(current_svg: str, best_score: float, recent_log: str) -> str:
    return f"""Score actuel : {best_score}/100

Log des dernières itérations :
{recent_log}

SVG actuel :
```svg
{current_svg}
```

Fais UNE SEULE modification atomique pour améliorer le score.
Choisis la modification qui aura le plus d'impact sur la dimension la plus faible.
Donne le SVG COMPLET modifié (pas un extrait)."""


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Init log
    if not LOG_FILE.exists():
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("iteration\tmetric\tdelta\tstatus\tdescription\n")

    # Git init check
    if not Path(".git").exists():
        subprocess.run(["git", "init"], capture_output=True)
        subprocess.run(["git", "add", "-A"], capture_output=True)
        subprocess.run(["git", "commit", "-m", "autoresearch: seed"], capture_output=True)

    # Baseline
    baseline = run_scorer()
    if baseline is None:
        print("FATAL: Cannot score seed SVG.")
        sys.exit(1)

    print(f"\n{'=' * 55}")
    print(f"  AUTORESEARCH — SVG Masterpiece Evolution")
    print(f"  Baseline: {baseline}/100")
    print(f"  Model: {MODEL}")
    print(f"  API: {API_URL}")
    print(f"  Press Ctrl+C to stop")
    print(f"{'=' * 55}\n")

    log_entry(0, baseline, 0.0, "baseline", "initial seed")
    best = baseline
    iteration = 0
    consecutive_fails = 0

    try:
        while True:
            iteration += 1
            ts = datetime.now().strftime("%H:%M:%S")

            # Read current state
            current_svg = SVG_FILE.read_text(encoding="utf-8")

            # Recent log for context (last 15 entries)
            log_lines = LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
            recent_log = "\n".join(log_lines[-15:]) if len(log_lines) > 1 else "Aucune itération précédente."

            # Call LLM
            print(f"  [{ts}] #{iteration} — calling LLM (score: {best})...", end=" ", flush=True)
            t0 = time.time()
            response = call_llm(
                build_user_prompt(current_svg, best, recent_log),
                system=SYSTEM_PROMPT
            )
            elapsed = time.time() - t0

            if not response:
                print(f"empty response ({elapsed:.0f}s)")
                log_entry(iteration, 0, 0, "skip", "empty LLM response")
                consecutive_fails += 1
                if consecutive_fails > 5:
                    print("  Too many consecutive fails, waiting 30s...")
                    time.sleep(30)
                continue

            # Extract SVG
            new_svg = extract_svg(response)
            description = extract_description(response)

            if new_svg is None:
                print(f"no SVG extracted ({elapsed:.0f}s)")
                log_entry(iteration, 0, 0, "skip", f"no valid SVG in response: {description[:80]}")
                consecutive_fails += 1
                continue

            # Backup + write new SVG
            backup = current_svg
            SVG_FILE.write_text(new_svg, encoding="utf-8")

            # Score
            new_score = run_scorer()

            if new_score is None or new_score == 0:
                # Crash — restore
                SVG_FILE.write_text(backup, encoding="utf-8")
                print(f"CRASH ({elapsed:.0f}s): {description[:60]}")
                log_entry(iteration, 0, 0, "crash", description[:120])
                consecutive_fails += 1
                continue

            delta = new_score - best

            if delta > 0:
                # KEEP
                best = new_score
                git_commit(f"autoresearch #{iteration}: {description[:72]} (score: {new_score})")
                # Snapshot
                snapshot = OUTPUT_DIR / f"iter_{iteration:04d}_score_{new_score:.1f}.svg"
                shutil.copy2(SVG_FILE, snapshot)
                print(f"KEEP  {new_score} (+{delta:.1f}) ({elapsed:.0f}s): {description[:60]}")
                log_entry(iteration, new_score, delta, "keep", description[:120])
                consecutive_fails = 0
            elif delta == 0:
                # Tie — discard (no improvement)
                SVG_FILE.write_text(backup, encoding="utf-8")
                print(f"TIE   {new_score} (±0) ({elapsed:.0f}s): {description[:60]}")
                log_entry(iteration, new_score, delta, "discard", f"tie: {description[:110]}")
                consecutive_fails += 1
            else:
                # Worse — revert
                SVG_FILE.write_text(backup, encoding="utf-8")
                print(f"DISC  {new_score} ({delta:.1f}) ({elapsed:.0f}s): {description[:60]}")
                log_entry(iteration, new_score, delta, "discard", description[:120])
                consecutive_fails += 1

            # Summary
            if iteration % SUMMARY_EVERY == 0:
                print_summary(iteration, baseline, best)

            # Stuck detection — inject creativity boost
            if consecutive_fails >= 8:
                print("  [STUCK] 8+ consecutive fails — injecting creativity boost next iteration")
                consecutive_fails = 0  # reset to avoid spam

    except KeyboardInterrupt:
        print(f"\n\nStopped at iteration {iteration}.")
        print_summary(iteration, baseline, best)
        print(f"Final SVG: {SVG_FILE}")
        print(f"Snapshots: {OUTPUT_DIR}/")
        print(f"Log: {LOG_FILE}")


if __name__ == "__main__":
    main()
