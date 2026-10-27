# Pool de connexions Postgres

Réglé dans `src/jenny/db/session.py`. Sur SQLite (tests, dev) et avec `JENNY_DB_POOLER=transaction` : un seul moteur, sans ce découpage.

## Deux pools par process

| Moteur | Utilisé par | Pourquoi |
|---|---|---|
| `request_engine` | les routes FastAPI (`get_db` / `DbSession`) | une session de route vit toute la requête |
| `engine` | `async_session_factory` : handlers du moteur (RDV, planning, fiche client), RAG, persona, tâches de fond des webhooks, worker arq, `/ready` | sessions courtes, souvent ouvertes *pendant* une requête |

Pourquoi deux : une route peut tenir sa connexion pendant qu'un handler en demande une autre (session imbriquée). Avec un seul pool, une rafale prend toutes les connexions avec des requêtes qui en attendent chacune une de plus : blocage jusqu'au `pool_timeout` (10 s), puis erreur. Avec deux pools, une session imbriquée n'attend jamais une session de route.

Ce qui rend la connexion de route au plus tôt :

- le chat (`_run_engine_chat` dans `api/routes/conversation.py`) fait `commit` avant `engine.process` : la connexion de route est rendue pendant l'appel LLM, puis reprise pour enregistrer le tour ;
- les webhooks (WhatsApp, Instagram, Twitter, Snapchat) prennent leur session avec `Depends(get_db, scope="function")` : elle est commitée et fermée à la fin de la route, avant les tâches de fond. Sans ce scope, FastAPI (0.135 ici) ne ferme une dépendance `yield` qu'après les `BackgroundTasks`, donc après la réponse Jenny, LLM compris. La tâche ouvre ses propres sessions sur `engine` ;
- le flux SSE `/realtime/stream` fait pareil (`scope="function"`).

## Réglages

Variables d'environnement, ou `.env` (même fichier que `Settings`, la vraie variable d'env gagne) :

| Variable | Défaut | Effet |
|---|---|---|
| `JENNY_DB_MAX_CONNECTIONS` | 16 | connexions max **du process**, moitié par pool : 16 donne 4 gardées + 4 en pic par pool. 10 donne 3 + 2, 8 donne 2 + 2, 4 donne 1 + 1. Minimum 2 ; valeur illisible = 16 |
| `JENNY_DB_POOL_SIZE` | part du budget (4) | connexions gardées, **par pool** (min 1) ; remplace la part du budget |
| `JENNY_DB_MAX_OVERFLOW` | part du budget (4) | connexions en plus en pic, **par pool** (min 0) ; remplace la part du budget |
| `JENNY_DB_POOLER=transaction` | — | pgbouncer en mode transaction : `NullPool`, caches de requêtes préparées coupés, un seul moteur |
| `JENNY_SQL_ECHO=1` | — | SQL + paramètres dans les logs (debug local uniquement) |

Fixes : `pool_timeout` 10 s, `pool_recycle` 1800 s, `pool_pre_ping`.

## Budget de connexions

Total en base = instances × workers uvicorn × `JENNY_DB_MAX_CONNECTIONS` + 8 par worker arq.

- Un process API (un worker uvicorn) : au plus 2 × (4 + 4) = **16** connexions, jusqu'à 8 gardées au repos après un pic.
- Worker arq : n'utilise que `engine`, donc au plus 4 + 4 = **8**.
- Limite : `max_connections` de l'instance Cloud SQL moins 3 réservées. `db-g1-small` : 50, soit **47** utiles. Le défaut dépend de la mémoire de l'instance : vérifier avec `SHOW max_connections;`.

| Déploiement | Calcul | Total |
|---|---|---|
| Démo sans Redis : 1 instance, 1 worker (forcé par `docker/entrypoint.prod.sh`), pas de worker arq | 1 × 1 × 16 | **16** |
| Avec Redis : 1 instance, 2 workers (défaut `WEB_CONCURRENCY=2`), 1 worker arq | 1 × 2 × 16 + 8 | **40** |
| Avec Redis et `--max-instances=4` (DEPLOY.md §7) | 4 × 2 × 16 + 8 = 136 : trop | poser `JENNY_DB_MAX_CONNECTIONS=4` : 4 × 2 × 4 + 8 = **40** |

Consigne démo : **1 worker et 1 instance** (`--max-instances=1`, `WEB_CONCURRENCY=1`). C'est obligatoire sans Redis (état du chat et SSE en mémoire du process, voir DEPLOY.md §3), et ça tient large dans le budget.

Plus d'instances : baisser `JENNY_DB_MAX_CONNECTIONS` ou passer par pgbouncer avec `JENNY_DB_POOLER=transaction`.

## Vérification

- `tests/unit/test_p3_resa_pool.py` : budget 16 = 4 + 4 par pool, calculs ci-dessus ; un pool unique de même taille bloque une rafale de 30 webhooks, deux pools non.
- `tests/unit/test_p2_perf_pool_load.py` : 30 chats lancés d'un coup (connexion de route gardée pendant un faux LLM de 0,2 s, deux sessions imbriquées). Deux pools de 4 + 4 : 0 timeout, ~0,9 s. Sur le Postgres local (lecture seule, `SELECT 1`) : `JENNY_TEST_POSTGRES_URL=postgresql+asyncpg://jenny:jenny_secret@localhost:5433/jenny pytest tests/unit/test_p2_perf_pool_load.py -k live` → 0 timeout, ~0,9 s.
- `tests/e2e/test_p4_routes_webhook_session.py` : pendant la tâche de fond WhatsApp, la connexion de la route est déjà rendue (pool des routes à 1 connexion, toujours libre) ; un témoin sans `scope="function"` la voit encore prise.
