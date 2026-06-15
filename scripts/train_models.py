"""Script d'entraînement des deux modèles Jenny from scratch.

Entraîne :
1. Le classifieur d'intention (Bi-LSTM + Attention)
2. L'extracteur d'entités NER (BiGRU + BIO tagging)

Les modèles sont sauvegardés dans checkpoints/intent/ et checkpoints/ner/.

Usage:
    python scripts/train_models.py
"""

import sys
from pathlib import Path

# Ajouter les chemins
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jenny.core.logging import setup_logging

setup_logging()


def train_intent() -> None:
    """Entraîne le classifieur d'intention."""
    print("\n" + "=" * 60)
    print("  ENTRAÎNEMENT — Détection d'intention (Bi-LSTM)")
    print("=" * 60 + "\n")

    from ml.models.intent.config import IntentModelConfig
    from ml.models.intent.train import train_intent_model

    config = IntentModelConfig(epochs=50, learning_rate=5e-3)
    model = train_intent_model(
        config=config,
        output_dir="checkpoints/intent",
    )
    print(f"\n✅ Modèle Intent sauvegardé — {model.count_parameters():,} paramètres")


def train_ner() -> None:
    """Entraîne l'extracteur d'entités NER."""
    print("\n" + "=" * 60)
    print("  ENTRAÎNEMENT — Extraction d'entités (BiGRU NER)")
    print("=" * 60 + "\n")

    from ml.models.ner.config import NERModelConfig
    from ml.models.ner.train import train_ner_model

    config = NERModelConfig(epochs=50, learning_rate=5e-3)
    model = train_ner_model(
        config=config,
        output_dir="checkpoints/ner",
    )
    print(f"\n✅ Modèle NER sauvegardé — {model.count_parameters():,} paramètres")


def verify_models() -> None:
    """Vérifie que les modèles entraînés fonctionnent."""
    print("\n" + "=" * 60)
    print("  VÉRIFICATION — Test des modèles entraînés")
    print("=" * 60 + "\n")

    # Test Intent
    from ml.models.intent.predict import IntentPredictor

    intent_predictor = IntentPredictor.from_checkpoint("checkpoints/intent/best_model.pt")

    test_messages = [
        "Bonjour !",
        "Où en est ma commande CMD-123 ?",
        "Combien ça coûte ?",
        "Je voudrais prendre rendez-vous",
        "J'ai un problème avec mon produit",
        "Je veux parler à un humain",
        "Merci, au revoir",
    ]

    print("─── Détection d'intention ───")
    for msg in test_messages:
        result = intent_predictor.predict(msg)
        print(f"  '{msg}'")
        print(f"    → {result['intent']} ({result['confidence']:.0%})")
        print()

    # Test NER
    from ml.models.ner.predict import NERPredictor

    ner_predictor = NERPredictor.from_checkpoint("checkpoints/ner/best_model.pt")

    test_ner = [
        "Ma commande CMD-12345 est en retard",
        "Mon email est test@example.com",
        "Livraison prévue le 15/03/2026",
        "Je suis Marie Dupont",
    ]

    print("─── Extraction d'entités ───")
    for msg in test_ner:
        entities = ner_predictor.predict(msg)
        tags = ner_predictor.predict_with_tags(msg)
        print(f"  '{msg}'")
        print(f"    Entités: {entities}")
        print(f"    Tags: {[(t, tag) for t, tag in tags if tag != 'O']}")
        print()


if __name__ == "__main__":
    train_intent()
    train_ner()
    verify_models()
    print("\n🎉 Tous les modèles sont entraînés et vérifiés !")
