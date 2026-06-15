#!/usr/bin/env python3
"""Génération massive de données d'intent via Groq LLM.

Génère 5000+ exemples diversifiés pour l'entraînement
du classifieur d'intention multi-label.

Usage :
    PYTHONPATH=src:. python ml/data_generation/generate_intent_data.py

Prend en compte le feedback du prof :
- Ajouter des exemples "small_talk" variés
- Ajouter des variantes de paiement ("paiement carte", etc.)
- Beaucoup plus de diversité pour éviter l'overfitting
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

from groq import Groq
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

console = Console()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or os.environ.get("JENNY_GROQ_API_KEY", "")

# Les intentions supportées par Jenny
INTENT_LABELS = [
    "greeting",
    "order_status",
    "pricing",
    "appointment",
    "complaint",
    "faq",
    "closing",
    "escalation",
    "payment",
    "quote",
    "planning",
    "general",
    "small_talk",  # Ajouté suite au feedback du prof
    "payment_question",  # Ajouté suite au feedback du prof
]

# Description de chaque intention pour le prompt LLM
INTENT_DESCRIPTIONS = {
    "greeting": "Salutations, bonjour, salut, hey, coucou — le client dit bonjour de manière formelle ou informelle",
    "order_status": "Le client demande des informations sur sa commande, livraison, colis, suivi, tracking",
    "pricing": "Le client demande des prix, tarifs, coûts, combien ça coûte, promotions",
    "appointment": "Le client veut prendre rendez-vous, réserver un créneau, fixer un RDV",
    "complaint": "Le client se plaint, n'est pas satisfait, signale un problème, un défaut",
    "faq": "Le client pose une question générale : horaires, adresse, fonctionnement, conditions",
    "closing": "Le client dit au revoir, merci, bonne journée, fin de conversation",
    "escalation": "Le client veut parler à un humain, un responsable, être transféré",
    "payment": "Le client parle de paiement, facture, régler, carte bancaire, virement, payer",
    "quote": "Le client demande un devis, une estimation, un chiffrage",
    "planning": "Le client demande les disponibilités, créneaux, horaires libres, planning",
    "general": "Message vague, réponse courte (ok, oui, non, d'accord), pas d'intention claire",
    "small_talk": "Conversation informelle : ça va ?, comment allez-vous, quoi de neuf, bavardage",
    "payment_question": "Question sur les moyens de paiement acceptés : carte bancaire, CB, espèces, chèque, Apple Pay, paiement en plusieurs fois",
}

# Exemples seed pour chaque intention (aide le LLM à comprendre le style)
SEED_EXAMPLES = {
    "greeting": [
        "Bonjour !",
        "Salut, c'est Marie",
        "Hello, je cherche des infos",
        "Bonsoir, j'ai une question",
        "Coucou !",
        "Hey salut !",
    ],
    "small_talk": [
        "Ça va ?",
        "Comment allez-vous ?",
        "Quoi de neuf ?",
        "Salut ça va bien ?",
        "La forme ?",
        "Ça roule ?",
        "Tout va bien ?",
        "T'es là ?",
        "Belle journée hein ?",
    ],
    "order_status": [
        "Où en est ma commande CMD-12345 ?",
        "Mon colis est en retard",
        "Quand vais-je recevoir ma livraison ?",
        "Numéro de suivi svp",
    ],
    "pricing": [
        "Combien coûte une coupe femme ?",
        "C'est quoi le tarif pour un lissage ?",
        "Vos prix sont TTC ?",
        "Quels sont vos tarifs ?",
    ],
    "appointment": [
        "Je voudrais prendre rendez-vous",
        "Vous avez un créneau mardi ?",
        "Réserver un rdv svp",
        "Je veux fixer un rendez-vous pour samedi",
    ],
    "complaint": [
        "Le produit est défectueux",
        "Je ne suis pas satisfait du résultat",
        "Ma couleur a viré, c'est inadmissible",
        "Service client nul",
    ],
    "faq": [
        "Quels sont vos horaires ?",
        "Vous êtes ouvert le dimanche ?",
        "Où êtes-vous situé ?",
        "Il y a un parking ?",
    ],
    "closing": [
        "Merci beaucoup, au revoir !",
        "Bonne journée",
        "C'est tout, merci",
        "Parfait, à bientôt",
    ],
    "escalation": [
        "Je veux parler à un humain",
        "Passez-moi un responsable",
        "Transférez-moi à quelqu'un",
        "Un humain svp",
    ],
    "payment": [
        "Comment payer ?",
        "Vous acceptez la carte bancaire ?",
        "Je veux régler ma facture",
        "Paiement par carte possible ?",
        "Est-ce que je peux payer en 3 fois ?",
    ],
    "quote": [
        "Je voudrais un devis",
        "Envoyez-moi un devis détaillé",
        "Devis pour une coiffure mariage",
        "Combien pour un devis personnalisé ?",
    ],
    "planning": [
        "Quelles sont vos disponibilités ?",
        "Vos créneaux libres cette semaine ?",
        "C'est quoi vos dispos samedi ?",
        "Montrez-moi le planning",
    ],
    "general": [
        "Ok",
        "D'accord",
        "Oui",
        "Non",
        "Hmm",
        "Je sais pas",
        "Ah bon",
    ],
    "payment_question": [
        "Vous acceptez la carte bancaire ?",
        "Est-ce que vous prenez la CB ?",
        "Paiement par carte possible ?",
        "Vous prenez les espèces ?",
        "Acceptez-vous le paiement sans contact ?",
        "On peut payer en chèque ?",
        "Apple Pay ça marche chez vous ?",
        "Vous faites le paiement en 3 fois ?",
        "Quels moyens de paiement ?",
        "Est-ce que vous acceptez la carte ?",
    ],
}

# Combinaisons multi-label courantes
MULTI_LABEL_COMBOS = [
    (["appointment", "quote"], "RDV + devis"),
    (["appointment", "pricing"], "RDV + prix"),
    (["appointment", "planning"], "RDV + dispos"),
    (["quote", "pricing"], "devis + prix"),
    (["complaint", "escalation"], "réclamation + transfert humain"),
    (["order_status", "complaint"], "suivi commande + réclamation"),
    (["payment", "order_status"], "paiement + suivi"),
    (["greeting", "appointment"], "salutation + rdv"),
    (["greeting", "quote"], "salutation + devis"),
    (["greeting", "pricing"], "salutation + prix"),
    (["greeting", "faq"], "salutation + question"),
    (["closing", "appointment"], "au revoir + confirmation rdv"),
    (["payment", "quote"], "paiement + devis"),
    (["planning", "appointment"], "dispos + rdv"),
    (["payment_question", "appointment"], "paiement question + rdv"),
    (["payment_question", "pricing"], "paiement question + prix"),
    (["greeting", "small_talk"], "salutation + bavardage"),
]


def generate_batch_with_llm(
    client: Groq,
    intent: str,
    batch_size: int = 50,
    context: str = "salon de coiffure",
) -> list[str]:
    """Génère un batch de messages pour une intention donnée via Groq."""

    seeds = SEED_EXAMPLES.get(intent, ["Bonjour"])
    seeds_str = "\n".join(f"- {s}" for s in seeds)
    desc = INTENT_DESCRIPTIONS.get(intent, "message divers")

    prompt = f"""Tu es un générateur de données d'entraînement pour un chatbot de {context}.

Génère exactement {batch_size} messages UNIQUES et VARIÉS de clients qui correspondent à l'intention "{intent}".

Description de l'intention : {desc}

Exemples de référence :
{seeds_str}

RÈGLES STRICTES :
1. Chaque message doit être UNIQUE (pas de doublons)
2. Varier le style : formel, informel, SMS, avec emojis, avec fautes, abrégé
3. Varier la longueur : très court (2-3 mots) à long (phrase complète)
4. Contexte : salon de coiffure / beauté / service client
5. Messages en FRANÇAIS uniquement
6. Un message par ligne, sans numérotation ni tiret
7. Certains messages doivent avoir des fautes d'orthographe (réaliste)
8. Certains en style SMS (rdv, svp, slt, bjr, mrc)

Génère UNIQUEMENT les messages, un par ligne, RIEN d'autre :"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=4000,
        )
        text = response.choices[0].message.content.strip()
        lines = [
            line.strip().lstrip("- ").lstrip("• ").strip('"').strip("'")
            for line in text.split("\n")
            if line.strip() and len(line.strip()) > 1
        ]
        # Nettoyer les lignes numérotées
        cleaned = []
        for line in lines:
            # Enlever numérotation "1. ", "1) ", etc.
            import re

            line = re.sub(r"^\d+[\.\)]\s*", "", line)
            if line and len(line) > 1:
                cleaned.append(line)
        return cleaned[:batch_size]
    except Exception as e:
        console.print(f"[red]Erreur API : {e}[/red]")
        return seeds[:batch_size]


def generate_multi_label_batch(
    client: Groq,
    intents: list[str],
    description: str,
    batch_size: int = 30,
) -> list[tuple[str, list[str]]]:
    """Génère des exemples multi-label."""

    intent_descs = " ET ".join(INTENT_DESCRIPTIONS.get(i, i) for i in intents)

    prompt = f"""Tu es un générateur de données d'entraînement pour un chatbot de salon de coiffure.

Génère exactement {batch_size} messages UNIQUES de clients qui combinent PLUSIEURS intentions en un seul message.

Intentions combinées : {", ".join(intents)} ({description})
Description : Le client veut {intent_descs} en même temps, dans le MÊME message.

RÈGLES :
1. Chaque message doit contenir clairement les {len(intents)} intentions
2. Messages variés : formel, informel, SMS, avec emojis
3. FRANÇAIS uniquement
4. Un message par ligne, sans numérotation
5. Certains avec fautes d'orthographe (réaliste)

Génère UNIQUEMENT les messages, un par ligne :"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=3000,
        )
        text = response.choices[0].message.content.strip()
        lines = [
            line.strip().lstrip("- ").lstrip("• ").strip('"').strip("'")
            for line in text.split("\n")
            if line.strip() and len(line.strip()) > 2
        ]
        import re

        cleaned = []
        for line in lines:
            line = re.sub(r"^\d+[\.\)]\s*", "", line)
            if line and len(line) > 2:
                cleaned.append((line, intents))
        return cleaned[:batch_size]
    except Exception as e:
        console.print(f"[red]Erreur API multi-label : {e}[/red]")
        return []


def main():
    console.print(
        Panel.fit(
            "[bold magenta]🧠 JENNY — Génération de données Intent (5000+)[/bold magenta]\n"
            "[dim]Via Groq LLM (llama-3.3-70b-versatile)[/dim]",
            border_style="magenta",
        )
    )

    client = Groq(api_key=GROQ_API_KEY)
    output_path = Path("data/generated/intents.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_examples: list[dict] = []

    # ══════════════════════════════════════════════
    # Phase 1 : Exemples single-label (par intention)
    # ══════════════════════════════════════════════
    batches_per_intent = 8  # 8 batches de 50

    console.print("\n[bold cyan]📊 Phase 1 : Données single-label[/bold cyan]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_intents = progress.add_task("[cyan]Intentions...", total=len(INTENT_LABELS))

        for intent in INTENT_LABELS:
            intent_examples = []

            # Ajouter les seeds d'abord
            for seed in SEED_EXAMPLES.get(intent, []):
                intent_examples.append(seed)

            # Générer par batch via LLM
            task_batch = progress.add_task(f"  [dim]{intent}[/dim]", total=batches_per_intent)

            for _batch_idx in range(batches_per_intent):
                messages = generate_batch_with_llm(client, intent, batch_size=50)
                intent_examples.extend(messages)
                progress.advance(task_batch)
                time.sleep(0.3)  # Rate limit Groq

            # Dédupliquer
            seen = set()
            unique = []
            for msg in intent_examples:
                key = msg.lower().strip()
                if key not in seen:
                    seen.add(key)
                    unique.append(msg)

            for msg in unique:
                all_examples.append(
                    {
                        "text": msg,
                        "intents": [intent],
                    }
                )

            progress.remove_task(task_batch)
            progress.advance(task_intents)
            console.print(f"  ✅ [green]{intent:15s}[/green] → {len(unique):4d} exemples")

    # ══════════════════════════════════════════════
    # Phase 2 : Exemples multi-label
    # ══════════════════════════════════════════════
    console.print("\n[bold cyan]📊 Phase 2 : Données multi-label[/bold cyan]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_multi = progress.add_task("[cyan]Combos multi-label...", total=len(MULTI_LABEL_COMBOS))

        for intents, desc in MULTI_LABEL_COMBOS:
            examples = generate_multi_label_batch(client, intents, desc, batch_size=40)
            for msg, labels in examples:
                all_examples.append(
                    {
                        "text": msg,
                        "intents": labels,
                    }
                )
            progress.advance(task_multi)
            console.print(
                f"  ✅ [yellow]{'+'.join(intents):30s}[/yellow] → {len(examples):3d} exemples"
            )
            time.sleep(0.3)

    # ══════════════════════════════════════════════
    # Phase 3 : Shuffle et sauvegarde
    # ══════════════════════════════════════════════
    random.shuffle(all_examples)

    with open(output_path, "w", encoding="utf-8") as f:
        for example in all_examples:
            f.write(json.dumps(example, ensure_ascii=False) + "\n")

    # Statistiques
    console.print(f"\n[bold green]✅ Dataset sauvegardé : {output_path}[/bold green]")

    table = Table(title="📊 Statistiques du dataset")
    table.add_column("Métrique", style="cyan")
    table.add_column("Valeur", style="green", justify="right")
    table.add_row("Total exemples", f"{len(all_examples):,}")
    table.add_row("Fichier", str(output_path))

    # Compter par intention
    intent_counts: dict[str, int] = {}
    multi_count = 0
    for ex in all_examples:
        intents = ex["intents"]
        if len(intents) > 1:
            multi_count += 1
        for intent in intents:
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

    for intent in sorted(intent_counts, key=intent_counts.get, reverse=True):
        table.add_row(f"  {intent}", f"{intent_counts[intent]:,}")
    table.add_row("Multi-label", f"{multi_count:,}")

    console.print(table)


if __name__ == "__main__":
    main()
