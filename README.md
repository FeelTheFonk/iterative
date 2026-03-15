# autoresearch-svg

Autonomous iterative evolution of an animated SVG artwork via a local LLM in a loop.  
Inspired by [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — constraint + mechanical metric + autonomous iteration = compounding gains.

The LLM modifies a single SVG file one atomic change at a time, scores the result, keeps improvements, reverts regressions, and repeats forever. Git tracks every successful mutation. You open the SVG in a browser and watch it evolve.

## Requirements

- Windows 11
- [git](https://git-scm.com/) in PATH
- [uv](https://docs.astral.sh/uv/) in PATH
- [llama.cpp](https://github.com/ggml-org/llama.cpp) server running on port 8001 with an OpenAI-compatible API

Example llama-server launch (adapt model path):

```
./llama-server --model models/Qwen3.5-35B-A3B.gguf --alias "HauhauCS/Qwen3.5-35B-A3B" --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0.00 --port 8001 --flash-attn on --ctx-size 262144 --jinja
```

## Files

```
autoresearch_loop.py    Main loop — calls LLM, scores, keeps/discards, logs
score_svg.py            Mechanical scorer (0-100), pure Python, no dependencies
masterpiece.svg         The SVG being evolved (seed: single animated circle)
setup_and_run.ps1       One-shot setup (venv, deps, git init) + launch
pyproject.toml          uv/pip dependency declaration (httpx only)
.gitignore              Excludes logs, snapshots, venv, pycache
```

Created at runtime:

```
autoresearch-results.tsv    TSV log of every iteration (score, delta, status, description)
output/                     SVG snapshots of every kept iteration
```

## Usage

```powershell
# 1. Make sure llama-server is running on port 8001
# 2. From the project directory:
.\setup_and_run.ps1
```

The script creates a venv, installs `httpx`, inits git, validates the scorer, checks llama-server, and launches the loop. Press `Ctrl+C` to stop at any time. All improvements are git-committed; the last successful state is always preserved.

## Scoring

The scorer evaluates 4 orthogonal axes summing to a maximum of 100 points:

| Axis        | Max | Measures                                                        |
|-------------|-----|-----------------------------------------------------------------|
| Animation   | 30  | SMIL elements, CSS `@keyframes`, `animation` properties         |
| Depth       | 25  | `<filter>`, gradients, `<g>` groups, opacity variance, transforms |
| Complexity  | 25  | Shape type diversity, color palette size, path command count     |
| Structure   | 20  | `<defs>`, `<style>`, `<clipPath>`, `<mask>`, `<pattern>`, `<symbol>` |

Constraints enforced by the scorer: valid XML, no `<script>`, max 500KB, `viewBox="0 0 800 600"`.

## Loop mechanics

```
REPEAT FOREVER:
  1. Read current SVG + recent log
  2. Send to LLM with system prompt (artistic direction + scoring rules)
  3. LLM returns ONE atomic modification + the full modified SVG
  4. Parse and write the new SVG
  5. Run scorer
  6. If score improved → git commit + snapshot in output/
     If score unchanged or worse → revert to previous SVG
     If invalid XML or crash → revert
  7. Log result to TSV
```

Every 10 iterations, a progress summary is printed. After 8 consecutive failures, the loop resets its fail counter to push for bolder changes.

## Monitoring

In a separate terminal:

```powershell
# Live log tail
Get-Content autoresearch-results.tsv -Wait

# Git history of kept improvements
git log --oneline
```

Open `masterpiece.svg` in Firefox or Chrome and refresh to see the current state. Animations play natively (SMIL + CSS).

Browse `output/` for snapshots of every kept iteration, named `iter_0042_score_67.3.svg`.

## Configuration

All tunables are constants at the top of `autoresearch_loop.py`:

| Variable        | Default                                    | Purpose                        |
|-----------------|--------------------------------------------|--------------------------------|
| `API_URL`       | `http://localhost:8001/v1/chat/completions` | llama-server endpoint          |
| `MODEL`         | `HauhauCS/Qwen3.5-35B-A3B`                | Must match `--alias`           |
| `API_TIMEOUT`   | `300`                                      | Seconds per LLM call           |
| `SUMMARY_EVERY` | `10`                                       | Iterations between summaries   |

## License

MIT
