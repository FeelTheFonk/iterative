# SVG Masterpiece Autoresearch

Boucle autonome d'évolution d'un SVG animé via Qwen 3.5 (llama-server).

## Prérequis

- Windows 11
- `git` dans le PATH
- `uv` installé (`pip install uv` ou via standalone installer)
- llama-server tournant sur port 8001 :
```
./llama-server --model <ton_modèle>.gguf --alias "HauhauCS/Qwen3.5-35B-A3B" --port 8001 ...
```

## Lancement

```powershell
# PowerShell
.\setup_and_run.ps1

# ou CMD
setup_and_run.bat
```

Ctrl+C pour arrêter. Toutes les améliorations sont commitées dans git.

## Structure

```
masterpiece.svg             ← Fichier modifié par le LLM
autoresearch_loop.py        ← Boucle principale
scripts/score_svg.py        ← Scorer mécanique (0-100)
output/                     ← Snapshots des itérations gardées
autoresearch-results.tsv    ← Log de toutes les itérations
```

## Score (4 axes, max 100)

| Axe         | Max | Éléments                                      |
|-------------|-----|------------------------------------------------|
| Animation   | 30  | SMIL, @keyframes, CSS animation                |
| Profondeur  | 25  | filters, gradients, groups, opacity, transforms |
| Complexité  | 25  | shapes, couleurs, path commands                 |
| Structure   | 20  | defs, style, clipPath, mask, pattern, symbol    |

## Suivi en temps réel

- **Log** : `Get-Content autoresearch-results.tsv -Wait` (PowerShell)
- **SVG** : ouvrir `masterpiece.svg` dans Firefox, F5 pour refresh
- **Snapshots** : `output/iter_NNNN_score_XX.X.svg`
- **Git** : `git log --oneline` pour l'historique des améliorations
