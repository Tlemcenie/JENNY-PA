# Configuration des Connecteurs — Guide Complet

Ce guide explique comment obtenir les clés API de chaque plateforme et configurer Jenny pour les utiliser.

## Table des matières
1. [WhatsApp Business API](#whatsapp)
2. [Instagram Messaging API](#instagram)
3. [Twilio (SMS)](#twilio)
4. [Email (SMTP/IMAP)](#email)
5. [Stripe (Paiements)](#stripe)
6. [PayPal (Paiements)](#paypal)
7. [Twitter/X (DMs)](#twitter)
8. [Snapchat](#snapchat)
9. [Google Calendar](#google-calendar)
10. [Test Local des Connecteurs](#test-local)

---

## WhatsApp {#whatsapp}

### Pré-requis
- Compte Meta Business Manager (gratuit)
- Page Facebook (si vous n'en avez pas)
- Numéro de téléphone pour recevoir les SMS de vérification

### Étapes

#### 1. Créer une application Meta
```
https://developers.facebook.com/
→ Mes apps (en haut à gauche)
→ Créer une application
→ Sélectionner "Entreprise"
→ Donner un nom (ex: "Jenny WhatsApp")
→ Remplir les détails
```

#### 2. Ajouter WhatsApp Business API
```
Ma nouvelle app → Tableau de bord
→ (Ajouter des produits)
→ Chercher "WhatsApp"
→ Cliquer "Configurer"
→ Accepter les conditions
```

#### 3. Obtenir les tokens
```
Ma nouvelle appli → WhatsApp → Configuration
→ Section "Token d'accès"
   - Sélectionner votre compte Business Manager
   - Cliquer "Générer un token"
   - **COPIER LE TOKEN** (À AJOUTER DANS .env)

→ Section "Numéro de téléphone"
   - Cliquer "Ajouter un numéro de téléphone"
   - Sélectionner ou ajouter un numéro
   - **COPIER LE PHONE_NUMBER_ID** (À AJOUTER DANS .env)

→ Section "Webhooks"
   - Cliquer "Configurer les webhooks"
   - Callback URL: https://your-domain.com/webhooks/whatsapp
   - Verify Token: jenny-whatsapp-verify (ou autre)
   - Événements: messages (déjà pré-sélectionné)
```

#### 4. Configuration locale (.env)
```bash
# Copier les valeurs obtenues
JENNY_WHATSAPP_PHONE_NUMBER_ID=<numéro obtenu en étape 3>
JENNY_WHATSAPP_ACCESS_TOKEN=<token obtenu en étape 3>
JENNY_WHATSAPP_VERIFY_TOKEN=jenny-whatsapp-verify
JENNY_FACEBOOK_APP_SECRET=<voir ci-dessous>
```

#### 5. Obtenir Facebook App Secret (pour signature webhooks)
```
Ma nouvelle app → Paramètres → Informations de base
→ Copier "App Secret" (cliquer sur l'œil pour révéler)
→ JENNY_FACEBOOK_APP_SECRET=...
```

#### 6. Test rapide
```bash
make api
# Dans un autre terminal :
curl -X POST http://localhost:8000/webhooks/whatsapp \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [{
      "changes": [{
        "value": {
          "messages": [{
            "from": "33612345678",
            "id": "msg_123",
            "type": "text",
            "text": {"body": "Bonjour!"},
            "timestamp": "1234567890"
          }],
          "contacts": [{"wa_id": "33612345678", "profile": {"name": "Alice"}}]
        }
      }]
    }]
  }'
```

---

## Instagram Messaging API {#instagram}

### Pré-requis
- Compte Meta Business Manager
- Page Instagram Business (connectée à une page Facebook)

### Étapes

#### 1. Créer/Configurer l'application Meta (même app que WhatsApp)

Si vous avez déjà créé une app pour WhatsApp, réutilisez-la.

#### 2. Ajouter Instagram à l'application
```
Ma nouvelle app → Tableau de bord
→ Ajouter des produits
→ Chercher "Instagram"
→ Cliquer "Configurer"
```

#### 3. Obtenir les tokens
```
Ma nouvelle app → Instagram → Configuration
→ Sélectionner votre Page Instagram Business
→ Cliquer "Générer un token"
→ **COPIER LE TOKEN** et **PAGE_ID**
```

#### 4. Configuration locale (.env)
```bash
JENNY_INSTAGRAM_PAGE_ID=<page_id obtenu>
JENNY_INSTAGRAM_ACCESS_TOKEN=<token obtenu>
JENNY_INSTAGRAM_VERIFY_TOKEN=jenny-instagram-verify
JENNY_FACEBOOK_APP_SECRET=<même que WhatsApp>
```

#### 5. Webhook setup (même que WhatsApp)
```
Ma nouvelle app → Webhooks
→ Callback URL: https://your-domain.com/webhooks/instagram
→ Verify Token: jenny-instagram-verify
→ Événements: messages
```

---

## Twilio (SMS) {#twilio}

### Pré-requis
- Compte Twilio (essai gratuit : https://www.twilio.com/try-twilio)
- Carte bancaire pour passer en production (optionnel en essai)

### Étapes

#### 1. Créer un compte Twilio
```
https://www.twilio.com/try-twilio
→ Remplir le formulaire
→ Valider l'email
```

#### 2. Obtenir les clés
```
Twilio Console (https://console.twilio.com)
→ Onglet "Account" (en haut)
→ Section "API Keys & Tokens"
   - COPIER "Account SID"
   - Cliquer "Show API Key" → COPIER "Auth Token"

→ Onglet "Phone Numbers"
→ Acheter un numéro (essai gratuit ≈ 1$ USD)
   - Chercher un pays/région
   - Sélectionner un numéro
   - COPIER le numéro
```

#### 3. Configuration locale (.env)
```bash
JENNY_TWILIO_ACCOUNT_SID=<Account SID>
JENNY_TWILIO_AUTH_TOKEN=<Auth Token>
JENNY_TWILIO_PHONE_NUMBER=<numéro acheté, ex: +1234567890>
```

#### 4. Webhook setup (incoming SMS)
```
Twilio Console → Phone Numbers → Gestion
→ Sélectionner votre numéro
→ Messaging
   - Incoming messages → Webhook URL:
     https://your-domain.com/webhooks/twilio
   - Sauvegarder
```

---

## Email (SMTP/IMAP) {#email}

### Option 1 : Gmail (avec App Password)

#### 1. Activer l'authentification à deux facteurs
```
Google Account → Sécurité
→ Authentification à deux facteurs (activer si pas déjà fait)
```

#### 2. Générer une App Password
```
Google Account → Sécurité
→ App passwords
→ Sélectionner "Mail" et "Windows" (ou autre)
→ Générer
→ **COPIER LE MOT DE PASSE GÉNÉRÉ**
```

#### 3. Configuration locale (.env)
```bash
# Envoi (SMTP)
JENNY_SMTP_HOST=smtp.gmail.com
JENNY_SMTP_PORT=587
JENNY_SMTP_USERNAME=your-email@gmail.com
JENNY_SMTP_PASSWORD=<app_password obtenu>
JENNY_SMTP_FROM_EMAIL=your-email@gmail.com
JENNY_SMTP_FROM_NAME=Jenny
JENNY_SMTP_USE_TLS=true

# Réception (IMAP)
JENNY_IMAP_HOST=imap.gmail.com
JENNY_IMAP_USER=your-email@gmail.com
JENNY_IMAP_PASSWORD=<app_password obtenu>
JENNY_IMAP_MAILBOX=INBOX
JENNY_IMAP_POLL_SECONDS=120
JENNY_IMAP_USE_SSL=true
```

### Option 2 : Mailhog (local — développement uniquement)

Mailhog capture tous les emails locaux sans vraies clés.

```bash
# Dans docker-compose.yml (déjà configuré)
# Accéder à l'UI : http://localhost:8025

# Dans .env
JENNY_SMTP_HOST=mailhog
JENNY_SMTP_PORT=1025
JENNY_SMTP_USE_TLS=false
JENNY_SMTP_USERNAME=dummy
JENNY_SMTP_PASSWORD=dummy
JENNY_SMTP_FROM_EMAIL=jenny@localhost
```

---

## Stripe (Paiements) {#stripe}

### Étapes

#### 1. Créer un compte Stripe
```
https://dashboard.stripe.com/register
→ Remplir les informations
→ Valider l'email
```

#### 2. Obtenir les clés
```
Stripe Dashboard → Développeurs → Clés API
→ Mode Test (plus simple d'abord)
→ **COPIER "Clé secrète test"** (commence par sk_test_)
→ **COPIER "Clé publiable test"** (commence par pk_test_)
```

#### 3. Configuration locale (.env)
```bash
JENNY_STRIPE_SECRET_KEY=sk_test_...
JENNY_STRIPE_WEBHOOK_SECRET=whsec_... (voir ci-dessous)
```

#### 4. Webhook Secret (pour les événements Stripe)
```
Stripe Dashboard → Développeurs → Événements
→ Ajouter un endpoint
   - URL: https://your-domain.com/webhooks/stripe
   - Événements à écouter: payment_intent.succeeded, charge.failed, etc.
   - Cliquer "Ajouter un endpoint"
→ Affiche "Clé secrète de signature" (commence par whsec_)
→ **COPIER CETTE CLÉ**
```

---

## PayPal (Paiements) {#paypal}

### Étapes

#### 1. Créer un compte PayPal Business
```
https://www.paypal.com/en/business
→ Créer un compte ou se connecter
```

#### 2. Obtenir les clés
```
PayPal Business Dashboard → Paramètres → Intégration
→ Afficher la signature API (hérité) ou Certificat
→ Ou utiliser OAuth2 :
   - Accueil → Développeurs → API Signature
   - Afficher "Client ID" et "Secret"
```

#### 3. Configuration locale (.env)
```bash
JENNY_PAYPAL_CLIENT_ID=<Client ID>
JENNY_PAYPAL_CLIENT_SECRET=<Secret>
JENNY_PAYPAL_WEBHOOK_ID=<Webhook ID, si créé>
# Mode sandbox (tests) ou production
JENNY_PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com  # Essai
# ou production: https://api-m.paypal.com
```

---

## Twitter/X (DMs) {#twitter}

### Pré-requis
- Compte Twitter développeur (https://developer.twitter.com)
- Accès API v2 (peut nécessiter une demande)

### Étapes

#### 1. Demander l'accès développeur
```
https://developer.twitter.com/en/portal/dashboard
→ Demander un accès
→ (Peut prendre quelques jours)
```

#### 2. Créer une application
```
Twitter Developer Portal → Projets & Apps
→ Créer une nouvelle app
→ Donner un nom, accepter les conditions
```

#### 3. Obtenir les clés
```
App Console → Keys and tokens
→ API Key (copier)
→ API Secret Key (copier)
→ Access Token (générer, copier)
→ Access Token Secret (générer, copier)
→ Bearer Token (copier)
```

#### 4. Configuration locale (.env)
```bash
JENNY_TWITTER_API_KEY=<API Key>
JENNY_TWITTER_API_SECRET=<API Secret>
JENNY_TWITTER_ACCESS_TOKEN=<Access Token>
JENNY_TWITTER_ACCESS_TOKEN_SECRET=<Access Token Secret>
JENNY_TWITTER_BEARER_TOKEN=<Bearer Token>
JENNY_TWITTER_WEBHOOK_ENV=production
```

---

## Snapchat {#snapchat}

### Étapes

#### 1. Créer un compte Snapchat for Business
```
https://ads.snapchat.com/
→ S'enregistrer
```

#### 2. Obtenir les clés
```
Snapchat Ads Manager → Settings → API
→ Générer les credentials
→ Copier Client ID, Client Secret
```

#### 3. Configuration locale (.env)
```bash
JENNY_SNAPCHAT_CLIENT_ID=<Client ID>
JENNY_SNAPCHAT_CLIENT_SECRET=<Client Secret>
JENNY_SNAPCHAT_ACCESS_TOKEN=<Access Token, si généré>
```

---

## Google Calendar {#google-calendar}

### Pré-requis
- Compte Google Cloud Platform (gratuit)
- Un calendrier Google (celui de votre entreprise ou personnel)

### Étapes

#### 1. Créer un projet GCP
```
https://console.cloud.google.com/
→ Créer un nouveau projet
→ Donner un nom (ex: "Jenny Calendar")
```

#### 2. Activer l'API Google Calendar
```
Google Cloud Console → API & Services → API bibliothèque
→ Chercher "Google Calendar API"
→ Cliquer sur le résultat
→ Cliquer "Activer"
```

#### 3. Créer un compte de service
```
Google Cloud Console → API & Services → Identifiants
→ Créer des identifiants
→ Sélectionner "Compte de service"
   - Donner un nom (ex: "jenny-calendar")
   - Accepter et continuer
   - Ajouter un rôle (Editor pour commencer)
   - Créer
```

#### 4. Générer la clé JSON
```
Google Cloud Console → API & Services → Identifiants
→ Sélectionner le compte de service créé
→ Onglet "Clés"
→ Ajouter une clé → Type JSON
→ Télécharger le fichier JSON
→ **SAUVEGARDER CE FICHIER** (ex: dans `credentials/google-service.json`)
```

#### 5. Configuration locale (.env)
```bash
JENNY_GOOGLE_CALENDAR_ID=primary
# ou un ID de calendrier spécifique (obtenu depuis Google Calendar settings)
JENNY_GOOGLE_SERVICE_ACCOUNT_JSON=/chemin/vers/google-service.json
```

---

## LLM Providers {#llm}

### Groq (défaut)
```bash
JENNY_LLM_PROVIDER=groq
JENNY_GROQ_API_KEY=<clé obtenue sur https://console.groq.com>
JENNY_LLM_MODEL=llama-3.3-70b-versatile
```

### OpenAI
```bash
JENNY_LLM_PROVIDER=openai
JENNY_OPENAI_API_KEY=sk-...
JENNY_LLM_MODEL=gpt-4o-mini
```

### Mistral
```bash
JENNY_LLM_PROVIDER=mistral
JENNY_MISTRAL_API_KEY=...
JENNY_LLM_MODEL=mistral-small-latest
```

### Ollama (local)
```bash
JENNY_LLM_PROVIDER=llama
JENNY_LLAMA_BASE_URL=http://localhost:11434
JENNY_LLM_MODEL=llama3.2
```

---

## Test Local des Connecteurs {#test-local}

### Script de test automatisé
```bash
# Lancer le script
python scripts/test_connectors.py

# Options
python scripts/test_connectors.py --channel whatsapp
python scripts/test_connectors.py --channel instagram
python scripts/test_connectors.py --env-check  # Vérifier les clés chargées
```

### Test manuel WhatsApp
```bash
# Terminal 1 : Lancer l'API
make api

# Terminal 2 : Simuler un message WhatsApp
curl -X POST http://localhost:8000/webhooks/whatsapp \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [{
      "changes": [{
        "value": {
          "messages": [{
            "from": "33612345678",
            "id": "msg_123",
            "type": "text",
            "text": {"body": "Bonjour, ça marche?"},
            "timestamp": "1234567890"
          }],
          "contacts": [{"wa_id": "33612345678", "profile": {"name": "Test"}}]
        }
      }]
    }]
  }'

# Terminal 3 : Vérifier les logs
tail -f logs/jenny.log | grep whatsapp
```

### Test avec ngrok (production-like)
```bash
# 1. Installer ngrok
brew install ngrok

# 2. Exposer localhost:8000
ngrok http 8000
# Affiche : Forwarding https://abc123.ngrok.io -> http://localhost:8000

# 3. Mettre à jour les webhooks sur les plateformes
# Ex: WhatsApp → https://abc123.ngrok.io/webhooks/whatsapp

# 4. Envoyer un vrai message (depuis WhatsApp/Instagram/etc)
# → Recevra sur votre localhost
# → Jenny répondra automatiquement
```

---

## Checklist de Setup Complète

```
[ ] WhatsApp : PHONE_NUMBER_ID, ACCESS_TOKEN configurés
[ ] Instagram : PAGE_ID, ACCESS_TOKEN configurés
[ ] Twilio : ACCOUNT_SID, AUTH_TOKEN, PHONE_NUMBER configurés
[ ] Email SMTP : HOST, PORT, USERNAME, PASSWORD configurés
[ ] Email IMAP : HOST, USER, PASSWORD configurés (si inbound)
[ ] Stripe : SECRET_KEY, WEBHOOK_SECRET configurés
[ ] PayPal : CLIENT_ID, CLIENT_SECRET configurés
[ ] Twitter : API_KEY, API_SECRET, ACCESS_TOKEN, BEARER_TOKEN configurés
[ ] Google Calendar : SERVICE_ACCOUNT_JSON chemin valide
[ ] LLM Provider : GROQ_API_KEY (ou autre) configuré

Vérification:
[ ] make api → démarrage OK
[ ] Logs sans erreurs de clés manquantes
[ ] Test webhook local fonctionne
[ ] (Optionnel) ngrok expose correctement le serveur
```

---

## Troubleshooting

### "Invalid webhook signature"
→ Vérifier que `JENNY_FACEBOOK_APP_SECRET` est correct
→ Ou désactiver temporairement: `JENNY_SKIP_META_SIGNATURE=true` (dev only !)

### "API key missing"
→ Vérifier que la clé est dans `.env`
→ Vérifier que `.env` est chargé : `python -c "from jenny.core.config import get_settings; print(get_settings().groq_api_key[:10])"`

### "Connection refused" sur webhooks
→ S'assurer que l'API est lancée : `make api`
→ S'assurer que le port 8000 est disponible

### Emails ne sont pas envoyés
→ Vérifier les logs : `tail -f logs/jenny.log | grep smtp`
→ Utiliser Mailhog localement (via Docker) pour éviter les clés Gmail

---

## Ressources
- Meta Developer Docs: https://developers.facebook.com/docs/
- Twilio Docs: https://www.twilio.com/docs/
- Stripe Docs: https://stripe.com/docs
- PayPal Docs: https://developer.paypal.com/docs/
- Twitter Dev Docs: https://developer.twitter.com/en/docs
- Google Cloud Docs: https://cloud.google.com/docs

