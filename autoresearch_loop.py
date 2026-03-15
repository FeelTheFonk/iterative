"""
autoresearch_loop.py — Autonomous SVG evolution via llama-server API.

Boucle infinie : Read → LLM proposes 1 change → Verify → Keep/Discard → Repeat.
Git as memory. TSV as log. Snapshots in output/.

Usage:  python autoresearch_loop.py
Needs:  llama-server on localhost:8001, git in PATH
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
# CONFIG — adapt these if needed
# ──────────────────────────────────────────────────────────
API_URL = "http://localhost:8001/v1/chat/completions"
MODEL = "HauhauCS/Qwen3.5-35B-A3B"
SVG_FILE = Path("masterpiece.svg")
SCORER = Path("score_svg.py")
LOG_FILE = Path("autoresearch-results.tsv")
OUTPUT_DIR = Path("output")
SUMMARY_EVERY = 10
API_TIMEOUT = 300


# ──────────────────────────────────────────────────────────
# LLM CALL
# ──────────────────────────────────────────────────────────
def call_llm(prompt: str, system: str = "") -> str:
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


# ──────────────────────────────────────────────────────────
# SCORING
# ──────────────────────────────────────────────────────────
def run_scorer() -> float | None:
    try:
        result = subprocess.run(
            [sys.executable, str(SCORER), str(SVG_FILE)],
            capture_output=True, text=True, timeout=30,
            cwd=str(Path.cwd()),
        )
        for line in result.stdout.splitlines():
            if line.startswith("SCORE:"):
                return float(line.split(":", 1)[1].strip())
        if result.stderr:
            print(f"  [SCORER STDERR] {result.stderr.strip()[:200]}")
        return None
    except Exception as e:
        print(f"  [SCORER ERROR] {e}")
        return None


# ──────────────────────────────────────────────────────────
# GIT
# ──────────────────────────────────────────────────────────
def git_commit(message: str):
    subprocess.run(["git", "add", str(SVG_FILE)], capture_output=True)
    subprocess.run(["git", "commit", "-m", message, "--allow-empty"], capture_output=True)


def git_revert():
    subprocess.run(["git", "checkout", "--", str(SVG_FILE)], capture_output=True)


# ──────────────────────────────────────────────────────────
# PARSING LLM OUTPUT
# ──────────────────────────────────────────────────────────
def extract_svg(response: str) -> str | None:
    """Extract complete SVG from LLM response. Handles fenced and bare SVG."""
    # Strategy 1: fenced code block (```svg, ```xml, ```)
    fence_match = re.findall(r"```(?:xml|svg|html)?\s*\n(.*?)\n```", response, re.DOTALL)
    for match in fence_match:
        candidate = match.strip()
        if "<svg" in candidate and "</svg>" in candidate:
            start = candidate.index("<svg")
            end = candidate.rindex("</svg>") + len("</svg>")
            return candidate[start:end]

    # Strategy 2: bare <svg>...</svg> anywhere in the response
    bare_match = re.search(r"(<svg[\s\S]*?</svg>)", response)
    if bare_match:
        return bare_match.group(1)

    return None


def extract_description(response: str) -> str:
    for line in response.splitlines():
        ls = line.strip()
        for prefix in ("CHANGE:", "MODIFICATION:", "CHANGEMENT:"):
            if ls.upper().startswith(prefix):
                return ls.split(":", 1)[1].strip()
    return "unknown change"


# ──────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────
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
    print(f"  Baseline: {baseline} -> Best: {best} (+{best - baseline:.1f})")
    print(f"  Keeps: {keeps} | Discards: {discards} | Crashes: {crashes} | Skips: {skips}")
    if last5:
        print(f"  Last 5: {', '.join(last5)}")
    print(f"{'=' * 55}")
    print()


# ──────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
Tu es un artiste SVG d'elite. Tu crees des oeuvres animees d'une beaute saisissante.
Tu travailles sur un SVG unique (800x600) qui doit devenir un chef-d'oeuvre anime avec une profondeur visuelle immense.

STYLE VISUEL CIBLE : scenes cosmiques, oceans bioluminescents, champs de particules abstraits,
architectures geometriques etherees. L'oeuvre doit sembler VIVANTE.

REGLES ABSOLUES :
- SVG + CSS uniquement. AUCUN <script>. AUCUN JavaScript.
- XML valide en permanence.
- viewBox="0 0 800 600" obligatoire, width="800" height="600".
- Max 500KB.
- Animations via SMIL (animate, animateTransform, animateMotion) et/ou CSS @keyframes dans <style>.

METRIQUE DE SCORING (ce que tu optimises) :
- Animation richness (30pts) : elements SMIL, @keyframes, proprietes animation
- Depth & layering (25pts) : <filter>, gradients, <g> groups, opacity, transforms
- Visual complexity (25pts) : diversite de shapes, palette couleurs, complexite des paths
- Structure quality (20pts) : <defs>, <style>, <clipPath>, <mask>, <pattern>, <symbol>

TECHNIQUE DE PROFONDEUR :
- Background (z-far) : gradients diffus, formes floues (feGaussianBlur), animations lentes (30-60s)
- Midground : formes geometriques, elements organiques, animations moyennes (5-15s)
- Foreground (z-near) : accents lumineux, particules fines, animations rapides (1-5s)
- Parallaxe : couches eloignees = mouvement lent, proches = mouvement rapide

FORMAT DE REPONSE OBLIGATOIRE :
CHANGE: <description en 1 phrase>
```svg
<le SVG COMPLET modifie, pas un extrait>
```"""


# ──────────────────────────────────────────────────────────
# USER PROMPT BUILDER
# ──────────────────────────────────────────────────────────
def build_user_prompt(current_svg: str, best_score: float, recent_log: str) -> str:
    return f"""Score actuel : {best_score}/100

Log des dernieres iterations :
{recent_log}

SVG actuel :
```svg
{current_svg}
```

Fais UNE SEULE modification atomique pour ameliorer le score.
Choisis la modification qui aura le plus d'impact sur la dimension la plus faible.
Donne le SVG COMPLET modifie (pas un extrait, le fichier entier de <svg> a </svg>)."""


# ──────────────────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    if not LOG_FILE.exists():
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("iteration\tmetric\tdelta\tstatus\tdescription\n")

    if not Path(".git").exists():
        subprocess.run(["git", "init"], capture_output=True)
        subprocess.run(["git", "add", "-A"], capture_output=True)
        subprocess.run(["git", "commit", "-m", "autoresearch: seed"], capture_output=True)

    # Baseline
    baseline = run_scorer()
    if baseline is None or baseline == 0:
        print("FATAL: Cannot score seed SVG. Check that masterpiece.svg and score_svg.py exist.")
        sys.exit(1)

    print(f"\n{'=' * 55}")
    print(f"  AUTORESEARCH — SVG Masterpiece Evolution")
    print(f"  Baseline: {baseline}/100")
    print(f"  Model: {MODEL}")
    print(f"  API: {API_URL}")
    print(f"  Ctrl+C to stop")
    print(f"{'=' * 55}\n")

    log_entry(0, baseline, 0.0, "baseline", "initial seed")
    best = baseline
    iteration = 0
    consecutive_fails = 0

    try:
        while True:
            iteration += 1
            ts = datetime.now().strftime("%H:%M:%S")

            current_svg = SVG_FILE.read_text(encoding="utf-8")

            log_lines = LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
            recent_log = "\n".join(log_lines[-15:]) if len(log_lines) > 1 else "(aucune)"

            print(f"  [{ts}] #{iteration} calling LLM (score: {best})...", end=" ", flush=True)
            t0 = time.time()
            response = call_llm(
                build_user_prompt(current_svg, best, recent_log),
                system=SYSTEM_PROMPT,
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

            new_svg = extract_svg(response)
            description = extract_description(response)

            if new_svg is None:
                print(f"no SVG extracted ({elapsed:.0f}s)")
                log_entry(iteration, 0, 0, "skip", f"no SVG in response: {description[:80]}")
                consecutive_fails += 1
                continue

            # Backup current, write new
            backup = current_svg
            SVG_FILE.write_text(new_svg, encoding="utf-8")

            new_score = run_scorer()

            if new_score is None or new_score == 0:
                SVG_FILE.write_text(backup, encoding="utf-8")
                print(f"CRASH ({elapsed:.0f}s): {description[:60]}")
                log_entry(iteration, 0, 0, "crash", description[:120])
                consecutive_fails += 1
                continue

            delta = new_score - best

            if delta > 0:
                best = new_score
                git_commit(f"autoresearch #{iteration}: {description[:72]} (score: {new_score})")
                snapshot = OUTPUT_DIR / f"iter_{iteration:04d}_score_{new_score:.1f}.svg"
                shutil.copy2(SVG_FILE, snapshot)
                print(f"KEEP  {new_score} (+{delta:.1f}) ({elapsed:.0f}s): {description[:60]}")
                log_entry(iteration, new_score, delta, "keep", description[:120])
                consecutive_fails = 0
            else:
                SVG_FILE.write_text(backup, encoding="utf-8")
                label = "TIE " if delta == 0 else "DISC"
                print(f"{label}  {new_score} ({delta:+.1f}) ({elapsed:.0f}s): {description[:60]}")
                log_entry(iteration, new_score, delta, "discard", description[:120])
                consecutive_fails += 1

            if iteration % SUMMARY_EVERY == 0:
                print_summary(iteration, baseline, best)

            if consecutive_fails >= 8:
                print("  [STUCK] 8+ consecutive fails — next prompt will push for radical change")
                consecutive_fails = 0

    except KeyboardInterrupt:
        print(f"\n\nStopped at iteration {iteration}.")
        print_summary(iteration, baseline, best)
        print(f"Final SVG: {SVG_FILE.resolve()}")
        print(f"Snapshots: {OUTPUT_DIR.resolve()}")
        print(f"Log:       {LOG_FILE.resolve()}")


if __name__ == "__main__":
    main()
