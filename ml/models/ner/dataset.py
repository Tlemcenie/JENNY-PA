"""Dataset PyTorch pour le NER (Named Entity Recognition).

Gère le chargement et le batching des données annotées
au format BIO pour l'entraînement du BiGRU.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import torch
from torch.utils.data import Dataset

from ml.models.ner.config import TAG_TO_ID, NERModelConfig

if TYPE_CHECKING:
    from pathlib import Path


class NERDataset(Dataset):
    """Dataset pour l'entraînement du modèle NER.

    Format de données attendu (JSONL) :
    {"tokens": ["Commande", "CMD-123"], "tags": ["O", "B-ORDER_NUMBER"]}
    {"tokens": ["Le", "15/03/2026"], "tags": ["O", "B-DATE"]}

    Chaque ligne contient une liste de tokens et les tags BIO associés.
    """

    def __init__(
        self,
        token_sequences: list[list[str]],
        tag_sequences: list[list[str]],
        vocab: dict[str, int] | None = None,
        config: NERModelConfig | None = None,
    ) -> None:
        self.config = config or NERModelConfig()
        self.token_sequences = token_sequences
        self.tag_sequences = tag_sequences
        self.vocab = vocab or self._build_vocab(token_sequences)

    def _build_vocab(self, sequences: list[list[str]]) -> dict[str, int]:
        """Construit le vocabulaire."""
        vocab: dict[str, int] = {"<PAD>": 0, "<UNK>": 1}
        for tokens in sequences:
            for token in tokens:
                word = token.lower()
                if word not in vocab and len(vocab) < self.config.vocab_size:
                    vocab[word] = len(vocab)
        return vocab

    def __len__(self) -> int:
        return len(self.token_sequences)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        tokens = self.token_sequences[idx]
        tags = self.tag_sequences[idx]

        # Encoder les tokens
        input_ids = [self.vocab.get(t.lower(), 1) for t in tokens]
        tag_ids = [TAG_TO_ID.get(t, 0) for t in tags]

        # Tronquer
        max_len = self.config.max_seq_length
        input_ids = input_ids[:max_len]
        tag_ids = tag_ids[:max_len]

        # Padding
        padding = max_len - len(input_ids)
        attention_mask = [1] * len(input_ids) + [0] * padding
        input_ids = input_ids + [0] * padding
        tag_ids = tag_ids + [-100] * padding  # -100 = ignore in CrossEntropyLoss

        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
            "labels": torch.tensor(tag_ids, dtype=torch.long),
        }

    @classmethod
    def from_jsonl(
        cls,
        path: str | Path,
        config: NERModelConfig | None = None,
        vocab: dict[str, int] | None = None,
    ) -> NERDataset:
        """Charge un dataset depuis un fichier JSONL."""
        token_sequences: list[list[str]] = []
        tag_sequences: list[list[str]] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                data = json.loads(line.strip())
                token_sequences.append(data["tokens"])
                tag_sequences.append(data["tags"])
        return cls(token_sequences, tag_sequences, vocab=vocab, config=config)

    def save_vocab(self, path: str | Path) -> None:
        """Sauvegarde le vocabulaire."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.vocab, f, ensure_ascii=False)

    @staticmethod
    def load_vocab(path: str | Path) -> dict[str, int]:
        """Charge un vocabulaire."""
        with open(path, encoding="utf-8") as f:
            return json.load(f)


def generate_sample_data() -> tuple[list[list[str]], list[list[str]]]:
    """Données d'entraînement pour le NER.

    60+ exemples annotés en BIO avec variété d'entités.
    En production, ces données viendront de data/labeled/.
    """
    samples: list[tuple[list[str], list[str]]] = [
        # ── ORDER_NUMBER ──
        (
            ["Ma", "commande", "CMD-12345", "est", "en", "retard"],
            ["O", "O", "B-ORDER_NUMBER", "O", "O", "O"],
        ),
        (
            ["Suivi", "de", "la", "commande", "ORD-2026-789"],
            ["O", "O", "O", "O", "B-ORDER_NUMBER"],
        ),
        (
            ["Commande", "numéro", "CMD-99001", "pas", "reçue"],
            ["O", "O", "B-ORDER_NUMBER", "O", "O"],
        ),
        (
            ["Où", "en", "est", "CMD-55555", "?"],
            ["O", "O", "O", "B-ORDER_NUMBER", "O"],
        ),
        (
            ["Problème", "avec", "la", "commande", "ORD-123-ABC"],
            ["O", "O", "O", "O", "B-ORDER_NUMBER"],
        ),
        (
            ["Référence", "CMD-00042", "statut", "?"],
            ["O", "B-ORDER_NUMBER", "O", "O"],
        ),
        # ── DATE ──
        (
            ["Livraison", "prévue", "le", "15/03/2026"],
            ["O", "O", "O", "B-DATE"],
        ),
        (
            ["Rendez-vous", "le", "22/04/2026", "à", "14h"],
            ["O", "O", "B-DATE", "O", "O"],
        ),
        (
            ["Disponible", "le", "01/05/2026"],
            ["O", "O", "B-DATE"],
        ),
        (
            ["Commande", "passée", "le", "10/03/2026", "toujours", "rien"],
            ["O", "O", "O", "B-DATE", "O", "O"],
        ),
        (
            ["Avant", "le", "30/06/2026", "si", "possible"],
            ["O", "O", "B-DATE", "O", "O"],
        ),
        (
            ["Créneau", "du", "18/03/2026", "ok", "pour", "moi"],
            ["O", "O", "B-DATE", "O", "O", "O"],
        ),
        # ── PHONE ──
        (
            ["Appelez-moi", "au", "06", "12", "34", "56", "78"],
            ["O", "O", "B-PHONE", "I-PHONE", "I-PHONE", "I-PHONE", "I-PHONE"],
        ),
        (
            ["Mon", "numéro", "est", "07", "98", "76", "54", "32"],
            ["O", "O", "O", "B-PHONE", "I-PHONE", "I-PHONE", "I-PHONE", "I-PHONE"],
        ),
        (
            ["Rappel", "au", "01", "44", "55", "66", "77"],
            ["O", "O", "B-PHONE", "I-PHONE", "I-PHONE", "I-PHONE", "I-PHONE"],
        ),
        (
            ["Contactez", "06", "11", "22", "33", "44", "svp"],
            ["O", "B-PHONE", "I-PHONE", "I-PHONE", "I-PHONE", "I-PHONE", "O"],
        ),
        # ── EMAIL ──
        (
            ["Mon", "email", "est", "marie@example.com"],
            ["O", "O", "O", "B-EMAIL"],
        ),
        (
            ["Envoyer", "à", "jean.dupont@gmail.com", "merci"],
            ["O", "O", "B-EMAIL", "O"],
        ),
        (
            ["Confirmation", "sur", "contact@monshop.fr"],
            ["O", "O", "B-EMAIL"],
        ),
        (
            ["Mail", ":", "alice.martin@yahoo.fr"],
            ["O", "O", "B-EMAIL"],
        ),
        (
            ["Réponse", "à", "info@boutique.com", "svp"],
            ["O", "O", "B-EMAIL", "O"],
        ),
        # ── PRODUCT ──
        (
            ["Je", "cherche", "le", "produit", "iPhone", "15"],
            ["O", "O", "O", "O", "B-PRODUCT", "I-PRODUCT"],
        ),
        (
            ["Problème", "avec", "mon", "Samsung", "Galaxy", "S24"],
            ["O", "O", "O", "B-PRODUCT", "I-PRODUCT", "I-PRODUCT"],
        ),
        (
            ["Prix", "du", "MacBook", "Pro", "?"],
            ["O", "O", "B-PRODUCT", "I-PRODUCT", "O"],
        ),
        (
            ["Disponibilité", "de", "la", "Nike", "Air", "Max"],
            ["O", "O", "O", "B-PRODUCT", "I-PRODUCT", "I-PRODUCT"],
        ),
        (
            ["Retour", "du", "Dyson", "V15"],
            ["O", "O", "B-PRODUCT", "I-PRODUCT"],
        ),
        (
            ["Commande", "de", "PlayStation", "5", "en", "stock", "?"],
            ["O", "O", "B-PRODUCT", "I-PRODUCT", "O", "O", "O"],
        ),
        # ── AMOUNT ──
        (
            ["Montant", "de", "150.50", "€"],
            ["O", "O", "B-AMOUNT", "I-AMOUNT"],
        ),
        (
            ["Facture", "de", "89.99", "euros"],
            ["O", "O", "B-AMOUNT", "I-AMOUNT"],
        ),
        (
            ["Budget", "maximum", "500", "€"],
            ["O", "O", "B-AMOUNT", "I-AMOUNT"],
        ),
        (
            ["Devis", "pour", "1200", "€", "TTC"],
            ["O", "O", "B-AMOUNT", "I-AMOUNT", "O"],
        ),
        (
            ["Paiement", "de", "45.00", "€", "effectué"],
            ["O", "O", "B-AMOUNT", "I-AMOUNT", "O"],
        ),
        # ── NAME ──
        (
            ["Je", "suis", "Marie", "Dupont"],
            ["O", "O", "B-NAME", "I-NAME"],
        ),
        (
            ["Client", ":", "Jean", "Martin"],
            ["O", "O", "B-NAME", "I-NAME"],
        ),
        (
            ["Bonjour", "je", "suis", "Pierre", "Lemoine"],
            ["O", "O", "O", "B-NAME", "I-NAME"],
        ),
        (
            ["Commande", "au", "nom", "de", "Sophie", "Bernard"],
            ["O", "O", "O", "O", "B-NAME", "I-NAME"],
        ),
        (
            ["Contact", ":", "Laurent", "Petit"],
            ["O", "O", "B-NAME", "I-NAME"],
        ),
        (
            ["Mme", "Isabelle", "Moreau", "a", "appelé"],
            ["O", "B-NAME", "I-NAME", "O", "O"],
        ),
        # ── LOCATION ──
        (
            ["Livraison", "à", "Paris", "75001"],
            ["O", "O", "B-LOCATION", "I-LOCATION"],
        ),
        (
            ["Adresse", ":", "Lyon", "69003"],
            ["O", "O", "B-LOCATION", "I-LOCATION"],
        ),
        (
            ["Envoi", "sur", "Marseille"],
            ["O", "O", "B-LOCATION"],
        ),
        (
            ["Boutique", "de", "Bordeaux"],
            ["O", "O", "B-LOCATION"],
        ),
        (
            ["Retrait", "à", "Toulouse", "31000"],
            ["O", "O", "B-LOCATION", "I-LOCATION"],
        ),
        (
            ["Livrer", "à", "Nice", "06000"],
            ["O", "O", "B-LOCATION", "I-LOCATION"],
        ),
        # ── ENTITÉS MULTIPLES ──
        (
            ["Commande", "ORD-2026-789", "du", "10/03/2026", "pour", "Jean", "Martin"],
            ["O", "B-ORDER_NUMBER", "O", "B-DATE", "O", "B-NAME", "I-NAME"],
        ),
        (
            ["Livraison", "CMD-555", "à", "Paris", "le", "20/04/2026"],
            ["O", "B-ORDER_NUMBER", "O", "B-LOCATION", "O", "B-DATE"],
        ),
        (
            ["Contact", "Marie", "Dupont", "au", "06", "12", "34", "56", "78"],
            ["O", "B-NAME", "I-NAME", "O", "B-PHONE", "I-PHONE", "I-PHONE", "I-PHONE", "I-PHONE"],
        ),
        (
            ["Devis", "iPhone", "15", "pour", "Sophie", "Bernard", "à", "Lyon"],
            ["O", "B-PRODUCT", "I-PRODUCT", "O", "B-NAME", "I-NAME", "O", "B-LOCATION"],
        ),
        (
            ["Facture", "250", "€", "pour", "CMD-777", "envoyée", "à", "pierre@mail.com"],
            ["O", "B-AMOUNT", "I-AMOUNT", "O", "B-ORDER_NUMBER", "O", "O", "B-EMAIL"],
        ),
        (
            ["RDV", "le", "15/05/2026", "avec", "Paul", "Durand", "à", "Nantes"],
            ["O", "O", "B-DATE", "O", "B-NAME", "I-NAME", "O", "B-LOCATION"],
        ),
        (
            ["Retour", "Samsung", "Galaxy", "S24", "commande", "CMD-9999"],
            ["O", "B-PRODUCT", "I-PRODUCT", "I-PRODUCT", "O", "B-ORDER_NUMBER"],
        ),
        # ── PHRASES SANS ENTITÉ (important pour le "O") ──
        (
            ["Bonjour", "je", "voudrais", "un", "devis"],
            ["O", "O", "O", "O", "O"],
        ),
        (
            ["Merci", "beaucoup", "bonne", "journée"],
            ["O", "O", "O", "O"],
        ),
        (
            ["Comment", "ça", "fonctionne", "?"],
            ["O", "O", "O", "O"],
        ),
        (
            ["Je", "voudrais", "prendre", "rendez-vous"],
            ["O", "O", "O", "O"],
        ),
        (
            ["Au", "revoir", "merci"],
            ["O", "O", "O"],
        ),
        (
            ["Quels", "sont", "vos", "horaires", "?"],
            ["O", "O", "O", "O", "O"],
        ),
        (
            ["Avez-vous", "des", "promotions", "en", "ce", "moment", "?"],
            ["O", "O", "O", "O", "O", "O", "O"],
        ),
        (
            ["Je", "ne", "suis", "pas", "satisfait", "du", "service"],
            ["O", "O", "O", "O", "O", "O", "O"],
        ),
        (
            ["Je", "veux", "parler", "à", "un", "humain"],
            ["O", "O", "O", "O", "O", "O"],
        ),
        (
            ["Acceptez-vous", "les", "cartes", "bancaires", "?"],
            ["O", "O", "O", "O", "O"],
        ),
    ]

    tokens = [s[0] for s in samples]
    tags = [s[1] for s in samples]
    return tokens, tags
