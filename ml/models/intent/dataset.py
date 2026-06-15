"""Dataset PyTorch pour la détection d'intention — Multi-Label.

Supporte deux formats de données :
1. Single-label :  {"text": "Bonjour", "intent": "greeting"}
2. Multi-label  :  {"text": "RDV + devis", "intents": ["appointment", "quote"]}

La tokenization est faite par un vocabulaire simple (word-level).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import torch
from torch.utils.data import Dataset

from ml.models.intent.config import LABEL_TO_ID, IntentModelConfig

if TYPE_CHECKING:
    from pathlib import Path


class IntentDataset(Dataset):
    """Dataset pour l'entraînement du classifieur d'intention multi-label.

    Chaque exemple a un texte et un VECTEUR binaire de labels
    (1 pour chaque intention active, 0 sinon).

    Ex: "RDV urgent et devis" → [0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0]
                                             ^appointment          ^quote
    """

    def __init__(
        self,
        texts: list[str],
        labels: list[str] | list[list[str]],
        vocab: dict[str, int] | None = None,
        config: IntentModelConfig | None = None,
    ) -> None:
        self.config = config or IntentModelConfig()
        self.texts = texts
        # Normaliser : chaque label est une LISTE d'intentions
        self.labels = [lbl if isinstance(lbl, list) else [lbl] for lbl in labels]
        self.vocab = vocab or self._build_vocab(texts)

    def _build_vocab(self, texts: list[str]) -> dict[str, int]:
        """Construit un vocabulaire simple à partir des textes."""
        vocab: dict[str, int] = {"<PAD>": 0, "<UNK>": 1}
        for text in texts:
            for word in self._tokenize(text):
                if word not in vocab and len(vocab) < self.config.vocab_size:
                    vocab[word] = len(vocab)
        return vocab

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenization simple par mots (lowercase + split)."""
        return text.lower().strip().split()

    def encode_text(self, text: str) -> list[int]:
        """Encode un texte en séquence d'IDs."""
        tokens = self._tokenize(text)
        ids = [self.vocab.get(t, 1) for t in tokens]
        if len(ids) > self.config.max_seq_length:
            ids = ids[: self.config.max_seq_length]
        return ids

    def _encode_labels(self, label_list: list[str]) -> torch.Tensor:
        """Encode une liste d'intentions en vecteur multi-hot.

        Ex: ["appointment", "quote"] → [0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0]
        """
        multi_hot = torch.zeros(self.config.num_classes, dtype=torch.float)
        for label in label_list:
            label_id = LABEL_TO_ID.get(label)
            if label_id is not None:
                multi_hot[label_id] = 1.0
        return multi_hot

    def __len__(self) -> int:
        return len(self.texts)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        text = self.texts[idx]
        label_list = self.labels[idx]

        input_ids = self.encode_text(text)

        # Multi-hot encoding pour les labels
        labels_tensor = self._encode_labels(label_list)

        # Aussi garder le single-label (premier label) pour rétro-compat
        primary_label_id = LABEL_TO_ID.get(label_list[0], LABEL_TO_ID["general"])

        # Padding
        padding_length = self.config.max_seq_length - len(input_ids)
        attention_mask = [1] * len(input_ids) + [0] * padding_length
        input_ids = input_ids + [0] * padding_length

        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
            "labels": torch.tensor(primary_label_id, dtype=torch.long),  # single-label compat
            "labels_multi": labels_tensor,  # multi-label (multi-hot)
        }

    @classmethod
    def from_jsonl(
        cls,
        path: str | Path,
        config: IntentModelConfig | None = None,
        vocab: dict[str, int] | None = None,
    ) -> IntentDataset:
        """Charge un dataset depuis un fichier JSONL.

        Supporte les deux formats :
        - {"text": "...", "intent": "greeting"}              (single)
        - {"text": "...", "intents": ["appointment", "quote"]} (multi)
        """
        texts: list[str] = []
        labels: list[list[str]] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                data = json.loads(line.strip())
                texts.append(data["text"])
                if "intents" in data:
                    labels.append(data["intents"])
                else:
                    labels.append([data["intent"]])
        return cls(texts, labels, vocab=vocab, config=config)

    def save_vocab(self, path: str | Path) -> None:
        """Sauvegarde le vocabulaire."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.vocab, f, ensure_ascii=False)

    @staticmethod
    def load_vocab(path: str | Path) -> dict[str, int]:
        """Charge un vocabulaire sauvegardé."""
        with open(path, encoding="utf-8") as f:
            return json.load(f)


def generate_sample_data() -> tuple[list[str], list[list[str]]]:
    """Génère des données d'entraînement enrichies pour le multi-label.

    Inclut des exemples single-label ET multi-label.
    """
    samples: list[tuple[str, list[str]]] = [
        # ═══════════════════════════════════════════
        #  SINGLE-LABEL (une seule intention)
        # ═══════════════════════════════════════════
        # ── Greeting (10) ──
        ("Bonjour", ["greeting"]),
        ("Salut, comment ça va ?", ["greeting"]),
        ("Hello", ["greeting"]),
        ("Bonsoir", ["greeting"]),
        ("Coucou", ["greeting"]),
        ("Hey, c'est Jenny ?", ["greeting"]),
        ("Bonjour, j'ai une question", ["greeting"]),
        ("Salut à vous", ["greeting"]),
        ("Coucou, c'est Marie !", ["greeting"]),
        ("Re bonjour !", ["greeting"]),
        # ── Order status (10) ──
        ("Où en est ma commande ?", ["order_status"]),
        ("Je voudrais suivre mon colis", ["order_status"]),
        ("Ma livraison est en retard", ["order_status"]),
        ("Quand vais-je recevoir mon colis ?", ["order_status"]),
        ("Numéro de suivi commande CMD-12345", ["order_status"]),
        ("Mon colis n'est toujours pas arrivé", ["order_status"]),
        ("Statut de ma commande ORD-789", ["order_status"]),
        ("La livraison devait arriver hier", ["order_status"]),
        ("Suivi de mon colis s'il vous plaît", ["order_status"]),
        ("Mon colis numéro CMD-2026 est où ?", ["order_status"]),
        # ── Pricing (10) ──
        ("Combien ça coûte ?", ["pricing"]),
        ("Quels sont vos tarifs ?", ["pricing"]),
        ("Quel est le prix pour une prestation photo ?", ["pricing"]),
        ("Avez-vous des promotions ?", ["pricing"]),
        ("C'est quoi le prix de base ?", ["pricing"]),
        ("Vos prix incluent la TVA ?", ["pricing"]),
        ("Quel budget faut-il prévoir ?", ["pricing"]),
        ("Le tarif horaire c'est combien ?", ["pricing"]),
        ("Combien pour une coupe femme ?", ["pricing"]),
        ("C'est quel prix le lissage brésilien ?", ["pricing"]),
        # ── Appointment (10) ──
        ("Je voudrais prendre rendez-vous", ["appointment"]),
        ("Vous avez des disponibilités ?", ["appointment"]),
        ("Je cherche un créneau la semaine prochaine", ["appointment"]),
        ("Peut-on se voir mardi ?", ["appointment"]),
        ("Réserver un rdv", ["appointment"]),
        ("Je veux fixer un rendez-vous", ["appointment"]),
        ("Quand peut-on se rencontrer ?", ["appointment"]),
        ("Un créneau jeudi matin ça irait ?", ["appointment"]),
        ("Je veux réserver un créneau pour lundi", ["appointment"]),
        ("Possible de prendre rdv demain ?", ["appointment"]),
        # ── Complaint (10) ──
        ("J'ai un problème avec ma commande", ["complaint"]),
        ("Le produit est défectueux", ["complaint"]),
        ("Je ne suis pas satisfait", ["complaint"]),
        ("Je voudrais me plaindre", ["complaint"]),
        ("Ça ne marche pas du tout", ["complaint"]),
        ("Service client nul", ["complaint"]),
        ("Article cassé à la réception", ["complaint"]),
        ("Très déçu de votre service", ["complaint"]),
        ("Ma couleur a viré, c'est inadmissible", ["complaint"]),
        ("Je ne suis vraiment pas contente du résultat", ["complaint"]),
        # ── FAQ (10) ──
        ("Comment ça fonctionne ?", ["faq"]),
        ("Quels sont vos horaires ?", ["faq"]),
        ("Où êtes-vous situé ?", ["faq"]),
        ("Acceptez-vous les cartes bancaires ?", ["faq"]),
        ("Comment retourner un article ?", ["faq"]),
        ("Quelle est votre politique de retour ?", ["faq"]),
        ("Vous faites des livraisons le samedi ?", ["faq"]),
        ("Quels modes de livraison proposez-vous ?", ["faq"]),
        ("Vous êtes ouvert le dimanche ?", ["faq"]),
        ("Il y a un parking à côté ?", ["faq"]),
        # ── Closing (10) ──
        ("Merci beaucoup", ["closing"]),
        ("Au revoir", ["closing"]),
        ("Bonne journée", ["closing"]),
        ("C'est tout, merci", ["closing"]),
        ("Parfait, merci", ["closing"]),
        ("Super, bonne continuation", ["closing"]),
        ("Merci et à bientôt", ["closing"]),
        ("Bonne soirée à vous", ["closing"]),
        ("Merci pour votre aide, au revoir", ["closing"]),
        ("OK c'est tout merci beaucoup !", ["closing"]),
        # ── Escalation (10) ──
        ("Je veux parler à un humain", ["escalation"]),
        ("Passez-moi un conseiller", ["escalation"]),
        ("Je veux un agent", ["escalation"]),
        ("Transférez-moi à quelqu'un", ["escalation"]),
        ("Je veux parler à une vraie personne", ["escalation"]),
        ("Pouvez-vous me transférer au service client", ["escalation"]),
        ("Je refuse de parler à un robot", ["escalation"]),
        ("Je veux parler à la responsable", ["escalation"]),
        ("Passez-moi la gérante s'il vous plaît", ["escalation"]),
        ("Un humain svp", ["escalation"]),
        # ── Payment (10) ──
        ("Comment payer ?", ["payment"]),
        ("Je voudrais régler ma facture", ["payment"]),
        ("Quels moyens de paiement acceptez-vous ?", ["payment"]),
        ("Paiement par carte bancaire possible ?", ["payment"]),
        ("Je veux payer en plusieurs fois", ["payment"]),
        ("Problème de paiement refusé", ["payment"]),
        ("Comment faire un virement ?", ["payment"]),
        ("Effectuer le paiement de ma commande", ["payment"]),
        ("Je peux payer en 3 fois ?", ["payment"]),
        ("Comment régler ma facture ?", ["payment"]),
        # ── Quote / Devis (10) ──
        ("Je voudrais un devis", ["quote"]),
        ("Pouvez-vous me faire un devis ?", ["quote"]),
        ("Demande de devis pour une prestation", ["quote"]),
        ("Envoyez-moi un devis détaillé", ["quote"]),
        ("J'aimerais recevoir une estimation", ["quote"]),
        ("Établir un devis sur mesure", ["quote"]),
        ("Faire un devis pour un événement", ["quote"]),
        ("Combien pour un devis personnalisé ?", ["quote"]),
        ("Devis pour une coiffure mariage", ["quote"]),
        ("Préparez-moi un devis s'il vous plaît", ["quote"]),
        # ── Planning (10) ──
        ("Quelles sont vos disponibilités ?", ["planning"]),
        ("Je veux voir le planning", ["planning"]),
        ("Vos créneaux libres cette semaine ?", ["planning"]),
        ("Le calendrier des prochaines sessions", ["planning"]),
        ("Quand êtes-vous disponible ?", ["planning"]),
        ("Montrez-moi les horaires disponibles", ["planning"]),
        ("Planning du mois prochain", ["planning"]),
        ("Consulter les créneaux ouverts", ["planning"]),
        ("C'est quoi vos dispos samedi ?", ["planning"]),
        ("Quels jours vous travaillez ?", ["planning"]),
        # ── General (8) ──
        ("Ok", ["general"]),
        ("D'accord", ["general"]),
        ("Je comprends", ["general"]),
        ("Autre chose", ["general"]),
        ("Oui", ["general"]),
        ("Non", ["general"]),
        ("Hmm", ["general"]),
        ("Euh je sais pas", ["general"]),
        # ═══════════════════════════════════════════
        #  MULTI-LABEL (plusieurs intentions)
        # ═══════════════════════════════════════════
        # ── Appointment + Quote (RDV + Devis) ──
        ("Je veux prendre rendez-vous et recevoir un devis", ["appointment", "quote"]),
        (
            "Bonjour j'aimerais le rendez-vous le plus rapide dispo c'est urgent et envoyez-moi un devis",
            ["appointment", "quote"],
        ),
        ("RDV + devis pour une coupe et coloration", ["appointment", "quote"]),
        ("Je voudrais réserver un créneau et avoir une estimation", ["appointment", "quote"]),
        ("Envoyez-moi un devis et réservez-moi un rdv", ["appointment", "quote"]),
        ("Devis et rendez-vous pour un mariage", ["appointment", "quote"]),
        ("Pouvez-vous me faire un devis et me caler un rdv ?", ["appointment", "quote"]),
        (
            "J'aimerais un devis pour un balayage et prendre rdv si possible",
            ["appointment", "quote"],
        ),
        # ── Appointment + Pricing (RDV + Prix) ──
        ("Je voudrais prendre rdv, c'est combien une coupe ?", ["appointment", "pricing"]),
        ("Dispo pour un rdv ? Et quels sont vos prix ?", ["appointment", "pricing"]),
        ("Combien ça coûte et quand je peux venir ?", ["appointment", "pricing"]),
        ("Tarifs pour une coloration et réserver un créneau", ["appointment", "pricing"]),
        ("Je veux un RDV et connaître vos tarifs", ["appointment", "pricing"]),
        # ── Appointment + Planning (RDV + Dispos) ──
        ("Quelles sont vos dispos ? Je veux réserver", ["appointment", "planning"]),
        ("Montrez-moi le planning et réservez-moi un créneau", ["appointment", "planning"]),
        ("Vos disponibilités ? Je souhaite prendre rdv", ["appointment", "planning"]),
        ("C'est quoi vos horaires et je peux réserver quand ?", ["appointment", "planning"]),
        # ── Quote + Pricing (Devis + Prix) ──
        ("Combien ça coûte ? Et envoyez-moi un devis", ["quote", "pricing"]),
        ("Quels sont vos tarifs et pouvez-vous me faire un devis ?", ["quote", "pricing"]),
        ("Tarifs pour un lissage et devis svp", ["quote", "pricing"]),
        ("Je veux connaître les prix et avoir un devis personnalisé", ["quote", "pricing"]),
        # ── Complaint + Escalation (Réclamation + Transfert) ──
        ("Je suis pas content et je veux parler à un responsable", ["complaint", "escalation"]),
        ("C'est nul, passez-moi un humain", ["complaint", "escalation"]),
        (
            "Le résultat est catastrophique, je veux parler à la gérante",
            ["complaint", "escalation"],
        ),
        (
            "Je me plains et je veux un remboursement, passez-moi quelqu'un",
            ["complaint", "escalation"],
        ),
        # ── Order status + Complaint (Suivi + Réclamation) ──
        ("Ma commande est en retard et je ne suis pas content", ["order_status", "complaint"]),
        ("Où est mon colis ? C'est inadmissible ce retard", ["order_status", "complaint"]),
        ("CMD-123 jamais arrivée, je veux me plaindre", ["order_status", "complaint"]),
        # ── Payment + Order status (Paiement + Suivi) ──
        ("Je veux payer et savoir où en est ma commande", ["payment", "order_status"]),
        ("Comment régler ma facture et suivre mon colis ?", ["payment", "order_status"]),
        # ── Greeting + Appointment (Salutation + RDV) ──
        ("Bonjour, je voudrais prendre rendez-vous", ["greeting", "appointment"]),
        ("Salut ! Possible de réserver un créneau ?", ["greeting", "appointment"]),
        ("Coucou, je veux un rdv pour un balayage", ["greeting", "appointment"]),
        # ── Greeting + Quote (Salutation + Devis) ──
        ("Bonjour, j'aurais besoin d'un devis", ["greeting", "quote"]),
        ("Salut, pouvez-vous me faire un devis pour un mariage ?", ["greeting", "quote"]),
        # ── Greeting + Pricing (Salutation + Prix) ──
        ("Bonjour, quels sont vos tarifs ?", ["greeting", "pricing"]),
        ("Salut, combien coûte une coupe homme ?", ["greeting", "pricing"]),
        # ── Closing + General ──
        ("OK merci c'est tout", ["closing"]),
        ("Parfait on fait comme ça, merci !", ["closing"]),
    ]

    texts = [s[0] for s in samples]
    labels = [s[1] for s in samples]
    return texts, labels
