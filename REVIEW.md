# JENNY — Audit & Review Complet

## Résumé du projet

JENNY est une **plateforme IA de gestion de messages clients multi-canaux**. Elle agrège les messages provenant de WhatsApp, Instagram, Twitter/X, Email, Snapchat et formulaires web, puis utilise des agents IA (LangGraph + LLM) pour classifier, router et répondre automatiquement aux demandes clients.

---

## Stack technique

| Couche | Technologies |
|--------|-------------|
| Backend API | FastAPI 0.115+, Python 3.12, Pydantic 2.10+ |
| Base de données | PostgreSQL 16 + pgvector, SQLAlchemy 2.0 (async), Alembic |
| Cache & Queue | Redis 7, ARQ (job queue async) |
| IA / Agents | LangGraph, LangChain, Groq (Llama 3.3 70B), OpenAI (optionnel) |
| ML | PyTorch, MLflow, modèles intent/NER custom |
| Auth | JWT (HS256), API Keys, Google OAuth 2.0 |
| Paiements | Stripe, PayPal (webhooks) |
| Frontend actuel | Flutter (Dart), Riverpod, Dio, Material 3 |
| Infra | Docker Compose, GitHub Actions CI |

---

## Cartographie Backend

### Endpoints réellement disponibles

| Méthode | Route | Fonctionnel | Notes |
|---------|-------|-------------|-------|
| GET | `/health` | ✅ | Liveness probe |
| GET | `/ready` | ✅ | Readiness (DB, Redis, ML) |
| POST | `/api/v1/auth/register` | ✅ | Inscription email/password |
| POST | `/api/v1/auth/login` | ✅ | Connexion, retourne JWT |
| GET | `/api/v1/auth/me` | ✅ | Profil utilisateur courant |
| GET | `/api/v1/auth/google/login` | ⚠️ | Nécessite OAuth config |
| GET | `/api/v1/auth/google/callback` | ⚠️ | Nécessite OAuth config |
| GET | `/api/v1/messages/` | ✅ | Liste messages (business_id requis, curseur, filtres) |
| GET | `/api/v1/messages/{id}` | ✅ | Détail d'un message |
| POST | `/api/v1/conversation/chat` | ✅ | Moteur conversationnel IA (core feature) |
| GET | `/api/v1/conversation/status/{id}` | ✅ | Statut d'une conversation |
| POST | `/api/v1/ingest/form` | ✅ | Ingestion formulaire |
| POST | `/api/v1/ingest/email` | ✅ | Ingestion email |
| POST | `/api/v1/ingest/email/inbound` | ✅ | Webhook email entrant |
| POST | `/api/v1/webhooks/whatsapp` | ✅ | Webhook WhatsApp |
| POST | `/api/v1/webhooks/instagram` | ✅ | Webhook Instagram |
| POST | `/api/v1/webhooks/twitter` | ✅ | Webhook Twitter |
| POST | `/api/v1/webhooks/snapchat` | ✅ | Webhook Snapchat |
| POST | `/api/v1/knowledge/text` | ✅ | Ajouter texte à la KB |
| POST | `/api/v1/knowledge/pdf` | ✅ | Upload PDF vers KB |
| GET | `/api/v1/knowledge/entries/{bid}` | ✅ | Lister entrées KB |
| DELETE | `/api/v1/knowledge/entries/{bid}/{eid}` | ✅ | Supprimer entrée KB |
| GET | `/api/v1/knowledge/stats/{bid}` | ✅ | Stats KB |
| POST | `/api/v1/payments/stripe` | ✅ | Webhook Stripe |
| POST | `/api/v1/payments/paypal` | ✅ | Webhook PayPal |

### Endpoints MANQUANTS (attendus par le Flutter mais inexistants)

| Endpoint attendu | Usage prévu | Statut |
|-----------------|-------------|--------|
| GET `/api/v1/conversations` | Liste des conversations | ❌ N'existe pas |
| GET `/api/v1/conversations/{id}/messages` | Messages d'une conversation | ❌ N'existe pas |
| POST `/api/v1/conversations/{id}/messages` | Envoyer un message dans une conv | ❌ N'existe pas |
| GET `/api/v1/conversations/{id}/ai-suggest` | Suggestion IA | ❌ N'existe pas |
| POST `/api/v1/ai/suggest` | Suggestion IA générique | ❌ N'existe pas |
| GET `/api/v1/insights` | Données dashboard/analytics | ❌ N'existe pas |
| GET `/api/v1/notifications` | Notifications | ❌ N'existe pas |
| GET `/api/v1/users` | Liste équipe | ❌ N'existe pas |

---

## Cartographie Frontend (Flutter actuel)

### Pages existantes

| # | Page | Fichier | Connecté au vrai backend ? |
|---|------|---------|---------------------------|
| 0 | Dashboard | dashboard_page.dart | ❌ Mock API uniquement |
| 1 | Inbox | inbox_page.dart | ❌ Mock API uniquement |
| 2 | Insights | insights_page.dart | ❌ Mock API uniquement |
| 3 | Search | search_page.dart | ❌ Mock API uniquement |
| 4 | Team | team_page.dart | ❌ Mock API uniquement |
| 5 | Knowledge | knowledge_page.dart | ❌ Pas d'endpoint front |
| 6 | Automation | automation_page.dart | ❌ Pas de backend |
| 7 | Notifications | notifications_page.dart | ❌ Mock API uniquement |
| 8 | Settings | settings_page.dart | ❌ Pas de backend |

### Composants

- AppShell (sidebar + topbar)
- ChatView (messages, bulles, input)
- ConversationList (filtres, recherche)
- AiSuggestionPanel (suggestions IA)
- KpiCard, ChannelBadge, StatusBadge, PriorityDot
- JennyButton, JennyTextField
- GlassContainer, ShimmerLoading, AnimatedGradientBackground

### ADN visuel à conserver

| Token | Valeur | Usage |
|-------|--------|-------|
| Primary (Coral) | `#FF7F6A` | Couleur principale, CTAs |
| Primary Light | `#FCBFB7` | Hover, backgrounds légers |
| Structure (Slate) | `#7284A8` | Couleur secondaire |
| Background | `#FFF9F8` | Fond chaud |
| AI Highlight | `#E8F3EE` | Zone IA, mint |
| Text Primary | `#2A3245` | Textes principaux |
| Text Secondary | `#8E99A4` | Textes secondaires |
| Sidebar | `#2A3245` | Navigation dark |
| Success | `#2ECC71` | Validations |
| Error | `#E74C3C` | Erreurs |
| Warning | `#F39C12` | Alertes |
| WhatsApp | `#25D366` | Badge canal |
| Instagram | `#E4405F` | Badge canal |
| Email | `#4A90D9` | Badge canal |
| Twitter | `#1DA1F2` | Badge canal |
| Font | Inter | Typographie globale |

---

## Features réellement branchables au backend

| Feature | Endpoint backend | Prêt ? |
|---------|-----------------|--------|
| Inscription | POST /auth/register | ✅ |
| Connexion | POST /auth/login | ✅ |
| Profil utilisateur | GET /auth/me | ✅ |
| Chat avec Jenny (IA) | POST /conversation/chat | ✅ Core feature |
| Statut conversation | GET /conversation/status/{id} | ✅ |
| Liste messages | GET /messages/ | ✅ (business_id requis) |
| Détail message | GET /messages/{id} | ✅ |
| Gestion KB - texte | POST /knowledge/text | ✅ |
| Gestion KB - PDF | POST /knowledge/pdf | ✅ |
| Liste KB | GET /knowledge/entries/{bid} | ✅ |
| Supprimer KB | DELETE /knowledge/entries/{bid}/{eid} | ✅ |
| Stats KB | GET /knowledge/stats/{bid} | ✅ |

---

## Incohérences et dettes techniques

1. **Frontend pointe sur mock API** — `api_client.dart` utilise `/api/v1/mock` par défaut
2. **Mock MVP intégré au backend** — `mock_mvp.py` contient des données fake en mémoire, mélangé avec les vrais endpoints
3. **Pas de liste de conversations** — Le backend a un moteur de conversation mais pas d'endpoint pour lister les conversations d'un business
4. **Pas d'endpoint dashboard/insights** — Le Flutter a une page dashboard mais aucun endpoint réel
5. **Auth optionnelle** — `JENNY_REQUIRE_AUTH=false` par défaut, tout est public
6. **JWT secret non sécurisé** — `"change-me-in-production"` en dur
7. **business_id en dur nécessaire** — Pas de mécanisme automatique pour associer un user à un business après login
8. **Pas de relation user↔business dans l'auth flow** — Le JWT contient `business_ids` mais le register ne crée pas de business
9. **Google OAuth non configuré** — Nécessite client ID/secret

---

## Quick wins

1. Le chat IA (`/conversation/chat`) est le coeur du produit et fonctionne — à mettre en avant
2. La knowledge base a un CRUD complet — intégrable immédiatement
3. L'auth register/login/me fonctionne — base solide
4. Les messages sont listables avec filtres — exploitable

---

## Ce qu'il faut garder

- Tout le backend API (FastAPI, modèles, services, engine)
- La palette de couleurs et l'ADN visuel (coral, mint, dark sidebar)
- La font Inter
- L'architecture backend (propre, async, bien structurée)

## Ce qu'il faut jeter/refaire

- **Le frontend Flutter entier** — Remplacer par un frontend web moderne (Next.js)
- **La dépendance au mock API** — Brancher sur les vrais endpoints
- **Les pages sans backend** (Automation, Settings, Team, Notifications) — Masquer ou documenter comme blockers
- **Le mock_mvp.py** — Ne pas l'utiliser dans le nouveau front
