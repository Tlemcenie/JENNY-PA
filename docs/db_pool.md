# Pool de connexions Postgres

Réglé dans `src/jenny/db/session.py`. Sur SQLite (tests, dev) rien de tout ça : un seul moteur, pool par défaut.

## Deux pools par process

| Moteur | Utilisé par | Pourquoi |
|---|---|---|
| `request_engine` | les routes FastAPI (`get_db` / `DbSession`) | une session de route vit toute la requête |
| `engine` | `async_session_factory` : handlers du moteur (RDV, planning, fiche client), RAG, persona, webhooks, tâches, `/ready` | sessions courtes, souvent ouvertes *pendant* une requête |

Le chat (`_run_engine_chat`) garde sa session de route pendant l'appel LLM, et les handlers ouvrent une deuxième session à l'intérieur. Avec un seul pool, dès que le nombre de chats simultanés atteint la taille du pool, toutes les connexions sont prises par des requêtes qui attendent chacune une connexion de plus : blocage jusqu'au `pool_timeout`, puis réservation ratée en silence. Avec deux pools, une session imbriquée n'attend jamais une session de route ; au pire une requête attend qu'une autre se termine.

## Réglages

Variables d'environnement, ou `.env` (même fichier que `Settings`, la vraie variable d'env gagne) :

| Variable | Défaut | Effet |
|---|---|---|
| `JENNY_DB_POOL_SIZE` | 10 | connexions gardées, **par pool** (min 1) |
| `JENNY_DB_MAX_OVERFLOW` | 10 | connexions en plus en pic, **par pool** (min 0) |
| `JENNY_DB_POOLER=transaction` | — | pgbouncer / pooler Cloud SQL : `NullPool`, caches de requêtes préparées coupés, un seul moteur |
| `JENNY_SQL_ECHO=1` | — | SQL + paramètres dans les logs (debug local uniquement) |

Fixes : `pool_timeout` 10 s, `pool_recycle` 1800 s, `pool_pre_ping`.

## Budget de connexions

- API (1 worker uvicorn) : au plus 2 × (10 + 10) = **40** connexions, 20 gardées au repos après un pic.
- Worker arq : n'utilise que `engine` → au plus **20**.
- Cloud SQL `db-g1-small` (prod actuelle) : 50 connexions max, dont 3 réservées → 47 utiles. 1 API + psql passe.
- Si le worker est déployé à côté : mettre `JENNY_DB_MAX_OVERFLOW=0` sur le worker (10 max) ou passer `JENNY_DB_POOL_SIZE=5` partout.
- Plusieurs instances / workers uvicorn : multiplier, ou passer par `JENNY_DB_POOLER=transaction`.

## Vérification

`tests/unit/test_p2_perf_pool_load.py` simule 30 chats lancés d'un coup (session de route gardée pendant un faux appel LLM de 0,2 s, deux sessions imbriquées) :

- un pool partagé de 10 + 10 : timeouts (le blocage décrit plus haut) ;
- deux pools de 10 + 10 : 0 timeout, ~0,5 s pour 30 chats, 60 chats passent aussi ;
- sur le vrai Postgres local (lecture seule, `SELECT 1`) : `JENNY_TEST_POSTGRES_URL=postgresql+asyncpg://jenny:jenny_secret@localhost:5433/jenny pytest tests/unit/test_p2_perf_pool_load.py -k live` → 0 timeout, ~0,5 s.

Correctif de fond, toujours conseillé : libérer la session de route (`commit`) avant `engine.process` dans `api/routes/conversation.py`.
