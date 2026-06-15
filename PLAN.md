# JENNY — Plan de Refonte Frontend

## Stratégie

Remplacer le frontend Flutter (mobile-first, mock API) par un **frontend web Next.js** premium, connecté exclusivement aux vrais endpoints backend.

## Stack frontend choisie

| Outil | Raison |
|-------|--------|
| Next.js 15 (App Router) | SSR, routing moderne, performance |
| TypeScript | Type safety, DX |
| Tailwind CSS | Utility-first, rapide, cohérent |
| Framer Motion | Animations premium |
| Lucide Icons | Icônes modernes, cohérentes |
| Font Inter | Continuité DA |

## Architecture

```
frontend/
├── app/                    # Next.js App Router
│   ├── layout.tsx         # Root layout
│   ├── page.tsx           # Landing / redirect
│   ├── (auth)/            # Auth group
│   │   ├── login/
│   │   └── register/
│   └── (dashboard)/       # Dashboard group (auth required)
│       ├── layout.tsx     # Sidebar + topbar
│       ├── chat/          # Chat avec Jenny (page principale)
│       ├── messages/      # Liste des messages
│       ├── knowledge/     # Gestion base de connaissances
│       └── profile/       # Profil utilisateur
├── components/
│   ├── ui/               # Composants génériques (Button, Input, Card, Badge, etc.)
│   ├── chat/             # Chat-specific components
│   ├── layout/           # Sidebar, Topbar, Shell
│   └── shared/           # Loaders, Empty states, Error states
├── lib/
│   ├── api.ts            # Client API (fetch wrapper)
│   ├── auth.ts           # Auth context & helpers
│   └── utils.ts          # Utilitaires
├── hooks/                # Custom React hooks
└── styles/               # Tailwind config, globals
```

## Pages prévues

### Pages fonctionnelles (backend réel)

| Page | Route | Endpoints utilisés | Statut |
|------|-------|--------------------|--------|
| Login | `/login` | POST /auth/login | ✅ Branchable |
| Register | `/register` | POST /auth/register | ✅ Branchable |
| Chat Jenny | `/chat` | POST /conversation/chat, GET /conversation/status/{id} | ✅ Core feature |
| Messages | `/messages` | GET /messages/ | ✅ Branchable |
| Knowledge Base | `/knowledge` | GET/POST/DELETE /knowledge/* | ✅ CRUD complet |
| Profil | `/profile` | GET /auth/me | ✅ Branchable |

### Pages bloquées (pas de backend)

| Page | Raison du blocage | Action |
|------|-------------------|--------|
| Dashboard stats | Pas d'endpoint /insights | Masquée, documentée |
| Conversations list | Pas d'endpoint /conversations | Masquée, documentée |
| Team | Pas d'endpoint /users | Masquée, documentée |
| Notifications | Pas d'endpoint /notifications | Masquée, documentée |
| Automation | Pas de backend | Masquée, documentée |
| Settings | Pas de backend | Masquée, documentée |

## Design Direction

### Principes
- **Premium & éditorial** — Inspiré des meilleures SaaS (Linear, Vercel, Notion)
- **Warm & human** — La palette coral/mint apporte chaleur vs le froid corporate
- **Density maîtrisée** — Espace blanc généreux, pas de surcharge
- **Motion subtile** — Micro-interactions, transitions douces, pas de cirque

### Palette (conservée)
- Primary: `#FF7F6A` (coral)
- Background: `#FFF9F8` (warm white)
- AI accent: `#E8F3EE` (mint)
- Text: `#2A3245` (dark blue)
- Sidebar: `#2A3245` (dark)

### Composants clés à soigner
1. **Chat interface** — L'expérience centrale, doit être exceptionnelle
2. **Sidebar navigation** — Dark, élégante, collapsible
3. **Loading states** — Skeleton loaders, progress bars, typing indicators
4. **Empty states** — Illustrations ou messages soignés
5. **Error states** — Feedback clair, retry possible
6. **Cards** — Élevation subtile, hover effects
7. **Forms** — Inputs premium, validation inline
8. **Badges** — Canaux, statuts, priorités

## Étapes d'implémentation

### Phase A — Setup (15 min)
- [x] Créer projet Next.js
- [x] Configurer Tailwind avec la palette JENNY
- [x] Setup structure de fichiers

### Phase B — Auth (30 min)
- [ ] Page login premium
- [ ] Page register premium
- [ ] Auth context avec JWT
- [ ] Protection des routes
- [ ] Gestion token (localStorage)

### Phase C — Layout (30 min)
- [ ] Sidebar dark avec navigation
- [ ] Topbar avec profil
- [ ] Layout responsive
- [ ] Transitions de page

### Phase D — Chat Jenny (1h) — PRIORITÉ #1
- [ ] Interface de chat complète
- [ ] Envoi de messages via /conversation/chat
- [ ] Affichage réponses IA
- [ ] Typing indicator
- [ ] Historique de conversation (session)
- [ ] Gestion erreurs réseau
- [ ] Design premium (bulles, avatars, animations)

### Phase E — Messages (30 min)
- [ ] Liste messages avec filtres
- [ ] Détail message
- [ ] Badges canal/statut/priorité
- [ ] Pagination curseur

### Phase F — Knowledge Base (30 min)
- [ ] Liste entrées KB
- [ ] Ajout texte
- [ ] Upload PDF
- [ ] Suppression
- [ ] Stats KB

### Phase G — Profil (15 min)
- [ ] Affichage infos user
- [ ] Déconnexion

### Phase H — Polish (30 min)
- [ ] Responsive mobile
- [ ] Micro-interactions
- [ ] Performance
- [ ] Tests manuels

## Blockers identifiés

| Blocker | Impact | Correction minimale backend |
|---------|--------|---------------------------|
| Pas d'endpoint GET /conversations | Pas de liste de conversations | Ajouter un endpoint qui query la table conversations avec filtres |
| Pas d'endpoint insights/dashboard | Pas de dashboard analytics | Ajouter agrégations sur messages/conversations |
| business_id non lié au register | Après inscription, pas de business_id pour les requêtes | Créer un business par défaut au register |
| Pas d'endpoint /users | Pas de page équipe | Ajouter endpoint list users by business |
| Pas de notifications | Pas de centre de notifications | Ajouter table + endpoint notifications |

## Variables d'environnement frontend

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

C'est la seule variable nécessaire. Tout le reste (JWT, etc.) est géré côté client via les headers.
