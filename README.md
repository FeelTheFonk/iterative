# autoresearch-svg

Autonomous iterative evolution of an animated SVG artwork via a local LLM in an infinite loop.

Based on [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — the principle that constraint + mechanical metric + autonomous iteration = compounding gains. Adapted for SVG art generation with a local Qwen 3.5 model via [llama.cpp](https://github.com/ggml-org/llama.cpp) server.

## Architecture

```
                    ┌──────────────┐
                    │  llama-server │ (Qwen 3.5 35B-A3B, port 8001)
                    └──────┬───────┘
                           │ OpenAI-compatible API
                           │ cache_prompt: true
                    ┌──────▼───────┐
                    │   MAIN LOOP  │ autoresearch_loop.py
                    │              │
                    │  1. Read SVG │
                    │  2. Build prompt (compressed context + actionable feedback)
                    │  3. Call LLM (temperature scheduled)
                    │  4. Extract SVG from response
                    │  5. Score    │────► score_svg.py (IMMUTABLE)
                    │  6. Keep/Discard
                    │  7. Git commit (if kept)
                    │  8. Log + snapshot
                    │  9. REPEAT   │
                    └──────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        masterpiece.svg   output/    autoresearch-results.tsv
        (mutable)         (snapshots) (iteration log)
```

### Design decisions and their rationale

**Immutable scorer** — The agent never modifies `score_svg.py`. This is the single most important architectural decision, directly from autoresearch. It prevents reward hacking, which [METR's June 2025 research](https://metr.org/blog/2025-06-05-recent-reward-hacking/) demonstrated is a real and frequent failure mode: frontier models actively modify evaluation code when given the chance. [OpenAI's Goodhart's Law measurements](https://openai.com/index/measuring-goodharts-law/) confirm that proxy optimization diverges from true quality beyond a critical threshold.

**Single mutable artifact** — Only `masterpiece.svg` changes. This keeps the entire artifact in the LLM's context window at all times, following autoresearch's principle of constraining scope to fit agent context. [Karpathy's `program.md`](https://github.com/karpathy/autoresearch/blob/master/program.md) specifies a single mutable `train.py` of ~630 lines for the same reason.

**Git as memory** — Every kept improvement is committed. The branch history is monotonically improving. Failures revert cleanly. The agent never needs to remember what it tried — git log and the TSV log serve as external memory. This follows the [Ralph Wiggum Loop](https://ghuntley.com/specs/) pattern: progress persists in files and git, not in LLM context.

**Context compression** — The prompt contains only: the current SVG, the scorer's per-axis breakdown, the weakest axis with its remaining gap, and a compressed 8-entry history. Verbose scorer output, raw TSV data, and old SVG states are excluded. [JetBrains research (December 2025)](https://blog.jetbrains.com/research/2025/12/efficient-context-management/) found that observation masking — replacing older outputs with summaries — often outperforms full context retention. [Anthropic's context engineering guide](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) recommends the same principle: include only what the agent needs for the current decision.

**Temperature scheduling** — Interpolates from 0.6 (exploration, low scores) to 0.35 (exploitation, high scores), with a boost on consecutive failures. This replaces a fixed temperature, following the [Self-Refine](https://selfrefine.info/) finding (Madaan et al., NeurIPS 2023, [arXiv:2303.17651](https://arxiv.org/abs/2303.17651)) that iterative refinement benefits from controlled diversity. Dynamic temperature is also recommended in the [llama.cpp documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/completion/README.md) for mixed code-and-prose generation.

**Actionable feedback** — The prompt explicitly names the weakest scoring axis and its point gap, rather than just giving a total score. This directly addresses Self-Refine's key finding: vague feedback yields only cosmetic changes, while localized actionable feedback drives meaningful improvement.

**Diversity injection** — Five rotating strategies activate after consecutive failures, preventing mode collapse. [Verbalized Sampling (Zhang et al., 2025)](https://openreview.net/forum?id=9jQkmGunGo) demonstrates that explicit diversity instructions increase LLM output variety by 1.6–2.1×.

**Anti-gaming scoring** — Duplicate element detection with linear penalty, perceptual color clustering (near-identical hex colors count as one), animation duration diversity requirement, and diminishing returns (sqrt scaling) on raw element counts. Inspired by [SVGauge (2025)](https://arxiv.org/html/2509.07127v1) which combines multiple independent metrics for human-aligned SVG evaluation, and [SVGenius](https://arxiv.org/html/2506.03139v1) which defines complexity via command diversity rather than raw counts.

## Requirements

- Windows 11
- [git](https://git-scm.com/) in PATH
- [uv](https://docs.astral.sh/uv/) in PATH
- [llama.cpp](https://github.com/ggml-org/llama.cpp) server running on port 8001

Example llama-server launch (adapt model path and GPU layers):

```
./llama-server ^
  --model models/Qwen3.5-35B-A3B-Q4_K_M.gguf ^
  --alias "HauhauCS/Qwen3.5-35B-A3B" ^
  --port 8001 --jinja --flash-attn on ^
  --ctx-size 262144 --no-context-shift ^
  --cache-type-k q8_0 --cache-type-v q8_0 ^
  --batch-size 4096 --ubatch-size 1024
```

Notes on llama-server parameters:
- `--jinja` is required for Qwen models to activate the embedded chat template ([Qwen docs](https://qwen.readthedocs.io/en/latest/run_locally/llama.cpp.html))
- `--no-context-shift` is recommended for autonomous loops where the application manages context truncation
- Sampling parameters (temp, top_p, etc.) are set per-request by the loop, not at server level, because [llama-server API defaults differ from CLI defaults](https://github.com/ggml-org/llama.cpp/discussions/9660)
- `cache_prompt: true` in API requests enables KV cache reuse for matching prompt prefixes — the system prompt is identical across iterations, so this saves significant compute ([llama.cpp KV cache discussion](https://github.com/ggml-org/llama.cpp/discussions/8860))

## Files

```
autoresearch_loop.py    Main loop: LLM call, scoring, keep/discard, git, logging
score_svg.py            Immutable scorer (0-100), anti-gaming, actionable breakdown
masterpiece.svg         The SVG being evolved (seed: single animated circle)
setup_and_run.ps1       One-shot setup (venv, deps, checks) + launch
pyproject.toml          uv dependency declaration (httpx)
.gitignore              Excludes runtime artifacts
```

Created at runtime:

```
autoresearch-results.tsv    TSV log of every iteration
output/                     SVG snapshot of every kept iteration
.git/                       Monotonically improving commit history
```

## Usage

```powershell
.\setup_and_run.ps1
```

This creates a `.venv`, installs `httpx`, validates the scorer, checks llama-server connectivity, and launches the loop. `Ctrl+C` to stop.

## Scoring (4 axes, max 100)

| Axis       | Max | What it measures                                                              |
|------------|-----|-------------------------------------------------------------------------------|
| Animation  | 30  | SMIL elements, CSS @keyframes, animation properties, duration diversity       |
| Depth      | 25  | `<filter>` + fe primitives, gradients, `<g>` groups, opacity variance, transforms |
| Complexity | 25  | Shape type diversity, perceptually distinct colors, path richness, command diversity |
| Structure  | 20  | `<defs>`, `<style>`, `<clipPath>`, `<mask>`, `<pattern>`, `<symbol>`, `<use>` |

Anti-gaming mechanisms:
- **Duplicate penalty**: elements with identical tag+attributes hashed; >6 copies triggers linear score reduction
- **Perceptual color clustering**: near-identical hex colors (HLS distance < 0.08) count as one
- **Duration diversity**: all-same-duration animations score lower than varied durations
- **Diminishing returns**: sqrt scaling on shape counts prevents brute-force element spam
- **Hard constraints**: valid XML, no `<script>`, max 500KB, viewBox must be `0 0 800 600`

## Loop mechanics

```
REPEAT FOREVER:
  1. Read current masterpiece.svg
  2. Compress history to last 8 entries (symbol + score + description)
  3. Parse scorer breakdown → identify weakest axis + gap
  4. Select strategy (rotates after 3+ consecutive failures)
  5. Compute temperature (0.6→0.35 by score progress, boost on failures)
  6. Build prompt: system (immutable) + user (SVG + breakdown + strategy)
  7. Call LLM via OpenAI-compatible API (cache_prompt: true)
  8. Strip <think> blocks (Qwen), extract SVG and description
  9. Write new SVG, run immutable scorer
  10. If score improved → git commit, snapshot to output/, reset fail counter
      If score unchanged or worse → revert SVG from backup
      If invalid XML or crash → revert
  11. Log to TSV
  12. Every 10 iterations → print summary (baseline, best, keep rate)
```

## Monitoring

```powershell
# Live log (separate terminal)
Get-Content autoresearch-results.tsv -Wait -Tail 20

# Git history of kept improvements
git log --oneline

# Current score breakdown
python score_svg.py masterpiece.svg

# View current SVG: open masterpiece.svg in Firefox/Chrome, F5 to refresh
# Browse snapshots: output/iter_0042_score_67.3.svg
```

Console output format:
```
  [10:03:03] #1 T=0.54 (score:20.3) ... KEEP [G] 75.8 (+55.5) (46s): Added nebula layers
  [10:05:16] #2 T=0.49 (score:75.8) ... DISC 74.2 (-1.6) (86s): Replaced gradient
  [10:07:01] #3 T=0.49 (score:75.8) ... KEEP [G] 82.1 (+6.3) (105s): Added mask + particles
```

- `T=` — current temperature
- `[G]` — git commit succeeded, `[g]` — git error (SVG still kept)
- `(46s)` — LLM inference time

## Configuration

All tunables are constants at the top of `autoresearch_loop.py`:

| Variable       | Default                                     | Purpose                                 |
|----------------|---------------------------------------------|-----------------------------------------|
| `API_URL`      | `http://localhost:8001/v1/chat/completions`  | llama-server endpoint                   |
| `MODEL`        | `HauhauCS/Qwen3.5-35B-A3B`                 | Must match `--alias`                    |
| `API_TIMEOUT`  | `300.0`                                     | Seconds per LLM call                    |
| `BASE_TEMP`    | `0.6`                                       | Starting temperature (exploration)      |
| `MIN_TEMP`     | `0.35`                                      | Floor temperature (exploitation)        |
| `TOP_P`        | `0.95`                                      | Nucleus sampling threshold              |
| `TOP_K`        | `20`                                        | Top-k candidates                        |
| `MIN_P`        | `0.05`                                      | Adaptive minimum probability filter     |
| `SUMMARY_EVERY`| `10`                                        | Iterations between progress summaries   |

Sampling parameters follow [Qwen3 official recommendations](https://qwen.readthedocs.io/en/latest/run_locally/llama.cpp.html) with `min_p=0.05` added per [llama.cpp best practices](https://deepwiki.com/ggml-org/llama.cpp/2.3-configuration-and-parameters) as the most effective adaptive filter for structured generation.

## References

### Core architecture

- **Karpathy's autoresearch** — The original autonomous ML experimentation loop. Single mutable file, immutable evaluation, git as memory, 5-minute time budget.
  [GitHub](https://github.com/karpathy/autoresearch) · [program.md](https://github.com/karpathy/autoresearch/blob/master/program.md) · [DeepWiki analysis](https://deepwiki.com/karpathy/autoresearch)

- **Self-Refine** (Madaan et al., NeurIPS 2023) — Generate → feedback → refine cycle. Key finding: actionable localized feedback outperforms vague "improve this" by ~20% absolute.
  [Project page](https://selfrefine.info/) · [arXiv:2303.17651](https://arxiv.org/abs/2303.17651)

- **IMPROVE** (February 2025) — Component-wise iterative pipeline refinement with convergence guarantees. Updates one component at a time rather than attempting global optimization.
  [arXiv:2502.18530](https://arxiv.org/pdf/2502.18530)

- **Verbalized Sampling** (Zhang et al., 2025) — Explicit diversity instructions increase LLM output variety 1.6–2.1×, mitigating mode collapse in iterative loops.
  [OpenReview](https://openreview.net/forum?id=9jQkmGunGo)

### Context engineering

- **JetBrains: Efficient Context Management** (December 2025) — Observation masking outperforms LLM summarization for agent context. Hybrid approach: 11% cost reduction, 2.6% accuracy gain.
  [Blog post](https://blog.jetbrains.com/research/2025/12/efficient-context-management/)

- **Anthropic: Effective Context Engineering for AI Agents** — Practical guidelines for what to include vs. exclude from agent context.
  [Blog post](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

- **Active Context Compression** (January 2026) — Autonomous memory management achieving 18-57% token savings.
  [arXiv:2601.07190](https://arxiv.org/html/2601.07190v1)

### SVG generation with LLMs

- **Chat2SVG** (CVPR 2025) — LLM decomposes subject into parts, generates basic SVG primitives, then visual rectification loop refines iteratively. 2-3 iterations suffice.
  [arXiv:2411.16602](https://arxiv.org/html/2411.16602v1) · [CVPR paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Wu_Chat2SVG_Vector_Graphics_Generation_with_Large_Language_Models_and_Image_CVPR_2025_paper.pdf)

- **OmniSVG** (NeurIPS 2025) — Parameterizes SVG commands into discrete tokens, decoupling structural logic from low-level geometry.
  [Project page](https://omnisvg.github.io/) · [OpenReview](https://openreview.net/pdf/67dc0bc8d01a1a124aeac60a7bb456507f3dff10.pdf)

- **LLM4SVG / Empowering LLMs for Complex Vector Graphics** (December 2024) — Regression heads for coordinate/color prediction, 250K curated SVG dataset.
  [arXiv:2412.11102](https://arxiv.org/html/2412.11102v1)

- **TextGrad for SVG** (Headstorm, 2025) — LLM-as-judge gradient descent for iterative SVG improvement with local models (Qwen2.5-Coder-32B demonstrated).
  [Case study](https://headstorm.com/case-study/technical-insight/optimizing-local-llm-svg-code-generation-with-textgrad/)

- **SVGauge** (2025) — Human-aligned SVG evaluation combining rasterized visual similarity and semantic alignment.
  [arXiv:2509.07127](https://arxiv.org/html/2509.07127v1)

- **SVGenius** (ACM MM 2025) — Benchmarking LLMs on SVG understanding, editing, and generation. 18 metrics across complexity levels.
  [arXiv:2506.03139](https://arxiv.org/html/2506.03139v1) · [ACM](https://dl.acm.org/doi/10.1145/3746027.3758287)

- **VCode** (2025) — Multimodal coding benchmark using SVG as symbolic visual representation.
  [arXiv:2511.02778](https://arxiv.org/pdf/2511.02778)

### Scoring and reward hacking

- **METR: Recent Frontier Models Are Reward Hacking** (June 2025) — Frontier models (o3, Claude 3.7 Sonnet) actively modify evaluation code when possible. Instructing "don't cheat" had negligible effect.
  [Blog post](https://metr.org/blog/2025-06-05-recent-reward-hacking/)

- **OpenAI: Measuring Goodhart's Law** — Proxy optimization initially improves true objective, then diverges after ~10 nats KL divergence.
  [Blog post](https://openai.com/index/measuring-goodharts-law/)

- **Goodhart's Law in Reinforcement Learning** (2023) — Formal analysis of when proxy metrics diverge from true objectives.
  [arXiv:2310.09144](https://arxiv.org/html/2310.09144v1)

- **ICLR 2026 Workshop on AI with Recursive Self-Improvement** — Survey of LLM agents rewriting their own codebases, from thought experiments to deployed systems.
  [OpenReview](https://openreview.net/pdf?id=OsPQ6zTQXV)

### llama.cpp and Qwen

- **Qwen: Running with llama.cpp** — Official Qwen documentation for llama.cpp, recommended parameters, `--jinja` requirement.
  [Docs](https://qwen.readthedocs.io/en/latest/run_locally/llama.cpp.html)

- **llama.cpp Configuration and Parameters** — Comprehensive parameter reference including min_p, DRY sampling, dynamic temperature.
  [DeepWiki](https://deepwiki.com/ggml-org/llama.cpp/2.3-configuration-and-parameters) · [Completion README](https://github.com/ggml-org/llama.cpp/blob/master/tools/completion/README.md)

- **llama-server API vs CLI defaults** — Server API defaults to temperature=0.8 while CLI defaults to 0.2. Always set explicitly.
  [Discussion #9660](https://github.com/ggml-org/llama.cpp/discussions/9660)

- **KV cache persistence across requests** — `cache_prompt: true` reuses KV cache for matching prefixes.
  [Discussion #8860](https://github.com/ggml-org/llama.cpp/discussions/8860)

### Windows git integration

- **Git for Windows UTF-8 encoding** — Windows defaults to ANSI codepages; git stores UTF-8. Explicit `encoding="utf-8"` required in subprocess calls.
  [Guide](https://www.tutorialpedia.org/blog/git-msysgit-accents-utf-8-the-definitive-answers/)

- **GitPython Windows issues** — Known encoding bugs (#147, #750, #1374). Raw subprocess with explicit parameters is more reliable.
  [Issue #147](https://github.com/gitpython-developers/GitPython/issues/147) · [Issue #750](https://github.com/gitpython-developers/GitPython/issues/750) · [Discussion #1374](https://github.com/gitpython-developers/GitPython/discussions/1374)

- **Git index.lock stale files** — Crash during git operations leaves lock files that block all subsequent commands. Age-based cleanup required.
  [Guide](https://gitscripts.com/index-lock-git)

## License

MIT
