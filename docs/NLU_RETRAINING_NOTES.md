# Notes de réentraînement NLU (modèles intention + NER maison)

> Ces défauts se corrigent **par les DONNÉES** au prochain entraînement, **pas** par
> des overrides moteur (qui masquent le problème et alourdissent le pipeline).
> Cf. la logique déterministe existante = filet de sécurité, pas une solution.

## Modèle d'intention — cas à renforcer

| Message type | Prédit (à tort) | Attendu | Action data |
|---|---|---|---|
| « il me faut une coupe homme jeudi à 14h » | `greeting` (1.0) | `appointment` | + d'exemples de prise de RDV ouverts (sans « réserver ») |
| « je veux annuler mon rdv » | `complaint` (0.03) | `manage_appointment` | exemples d'annulation/déplacement explicites |
| « Vendredi après-midi » (créneau seul) | `complaint` (0.73) | `appointment`/continuation | fragments temporels étiquetés en contexte RDV |
| message anglais (« how much… ») | `order_status` (0.99) | `pricing`/`faq` | exemples EN si multilingue, sinon rejet propre |
| charabia / ponctuation seule (« ... ») | `order_status` | `general`/fallback | exemples de bruit → intention neutre |
| « faites-vous X ? » / « prix du forfait X » | `payment` (0.9+) | `faq`/`pricing` | désambiguïser paiement vs question de service |

## Modèle NER (compréhension) — entités à fiabiliser

- **Dates relatives non résolues** : « jeudi **prochain** », « **prochain** » seul → l'entité `date` sort brute (`"prochain"`) au lieu d'une date normalisée. Ajouter des exemples annotés de dates relatives.
- **Confusion `time` ⇄ `location`** : l'heure est parfois étiquetée `location` (ex. « à 15h »). Renforcer l'annotation heure.
- **Prestations manquées** : `balayage`, `coloration` parfois non extraites comme `service`. Ajouter ces prestations au jeu d'entraînement.

## Pipeline

1. Enrichir `ml/data_generation/` avec ces cas (générés + réels anonymisés).
2. Réentraîner (`ml/models/intent`, `ml/models/ner`).
3. **Garde-fou obligatoire avant de committer les checkpoints** : `pytest tests/e2e/test_user_coiffeur.py` doit rester vert (cf. mémoire « checkpoints T4 = régression »). ⚠️ Ce garde-fou est aujourd'hui partiel car la suite tourne avec `JENNY_ENABLE_ML_MODELS=false` — ajouter un test e2e qui ACTIVE les modèles et vérifie la précision sur des phrases coiffeur.
