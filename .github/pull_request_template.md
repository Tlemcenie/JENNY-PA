## Résumé

<!-- Décrire brièvement le changement -->

## Type de changement

- [ ] Correctif
- [ ] Fonctionnalité
- [ ] Refactor / qualité (lint, tests, doc)
- [ ] Autre :

## Checklist

- [ ] `make lint` / `ruff check` OK
- [ ] `ruff format --check` OK (ou `make format`)
- [ ] `pytest` OK en local
- [ ] Modèle ORM modifié → révision Alembic (sinon la CI casse sur la dérive)
- [ ] Modèle d'embedding / découpage changé → `scripts/reindex_kb.py --rechunk` prévu (DEPLOY.md §6)
- [ ] Documentation mise à jour si nécessaire

## Notes

<!-- Contexte, tickets, risques -->
