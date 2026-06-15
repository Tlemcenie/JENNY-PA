# Contribuer à Jenny

## Environnement local

1. **Python** : 3.12 (recommandé ; 3.12+ supporté par `pyproject.toml`).
2. **Installation** (obligatoire pour les imports `jenny`) :

   ```bash
   pip install -e ".[dev]"
   ```

3. **Variables** : copier `.env.example` vers `.env` et adapter.

4. **Checkpoints ML** : les tests e2e attendent `checkpoints/intent/best_model.pt` et `checkpoints/ner/best_model.pt`. S’ils manquent :

   ```bash
   python scripts/train_models.py
   ```

   (ou utiliser les fichiers déjà présents dans le dépôt si versionnés.)

## Qualité de code

| Commande | Rôle |
|----------|------|
| `make lint` | Ruff (lint) |
| `make format` | Ruff format + fix auto |
| `make typecheck` | mypy sur `src/jenny/` |
| `make test` | Pytest |

Hooks optionnels après `pre-commit install` : exécution automatique de Ruff avant chaque commit.

## Workflow Git / GitHub

1. Créer une branche depuis `main` : `feat/...`, `fix/...`, etc.
2. Commits atomiques et messages clairs.
3. **Pull Request** vers `main` : la CI (`.github/workflows/ci.yml`) doit être verte (lint, format, mypy, tests).
4. Revue de code au besoin.

## Structure des commits (convention simple)

- `feat:` nouvelle fonctionnalité  
- `fix:` correction  
- `docs:` / `chore:` / `test:` selon le cas  

Pas de commit de secrets (`.env`, clés API, tokens).
