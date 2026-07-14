"""Dataset intention multi-label."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import torch
from torch.utils.data import Dataset

from ml.models.intent.config import LABEL_TO_ID, IntentModelConfig

if TYPE_CHECKING:
    from pathlib import Path


class IntentDataset(Dataset):
    """Dataset du classifieur multi-label."""

    def __init__(
        self,
        texts: list[str],
        labels: list[str] | list[list[str]],
        vocab: dict[str, int] | None = None,
        config: IntentModelConfig | None = None,
    ) -> None:
        self.config = config or IntentModelConfig()
        self.texts = texts
        # chaque label devient une liste
        self.labels = [lbl if isinstance(lbl, list) else [lbl] for lbl in labels]
        self.vocab = vocab or self._build_vocab(texts)

    def _build_vocab(self, texts: list[str]) -> dict[str, int]:
        """construit le vocab."""
        vocab: dict[str, int] = {"<PAD>": 0, "<UNK>": 1}
        for text in texts:
            for word in self._tokenize(text):
                if word not in vocab and len(vocab) < self.config.vocab_size:
                    vocab[word] = len(vocab)
        return vocab

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """tokenize par mots."""
        return text.lower().strip().split()

    def encode_text(self, text: str) -> list[int]:
        """texte en IDs."""
        tokens = self._tokenize(text)
        ids = [self.vocab.get(t, 1) for t in tokens]
        if len(ids) > self.config.max_seq_length:
            ids = ids[: self.config.max_seq_length]
        return ids

    def _encode_labels(self, label_list: list[str]) -> torch.Tensor:
        """intentions en multi-hot."""
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

        # multi-hot des labels
        labels_tensor = self._encode_labels(label_list)

        # garde le single-label
        primary_label_id = LABEL_TO_ID.get(label_list[0], LABEL_TO_ID["general"])

        # padding
        padding_length = self.config.max_seq_length - len(input_ids)
        attention_mask = [1] * len(input_ids) + [0] * padding_length
        input_ids = input_ids + [0] * padding_length

        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
            "labels": torch.tensor(primary_label_id, dtype=torch.long),  # compat single-label
            "labels_multi": labels_tensor,  # multi-label
        }

    @classmethod
    def from_jsonl(
        cls,
        path: str | Path,
        config: IntentModelConfig | None = None,
        vocab: dict[str, int] | None = None,
    ) -> IntentDataset:
        """charge un JSONL."""
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
        """sauve le vocab."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.vocab, f, ensure_ascii=False)

    @staticmethod
    def load_vocab(path: str | Path) -> dict[str, int]:
        """charge le vocab."""
        with open(path, encoding="utf-8") as f:
            return json.load(f)


def generate_sample_data() -> tuple[list[str], list[list[str]]]:
    """données d'entraînement multi-label."""
    samples: list[tuple[str, list[str]]] = [
        # ═══════════════════════════════════════════
        #  single-label
        # ═══════════════════════════════════════════
        # salutations
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
        # suivi commande
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
        # prix
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
        # rdv
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
        # réclamations
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
        # faq
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
        # clôture
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
        # transfert humain
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
        # paiement
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
        # devis
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
        # planning
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
        # général
        ("Ok", ["general"]),
        ("D'accord", ["general"]),
        ("Je comprends", ["general"]),
        ("Autre chose", ["general"]),
        ("Oui", ["general"]),
        ("Non", ["general"]),
        ("Hmm", ["general"]),
        ("Euh je sais pas", ["general"]),
        # ═══════════════════════════════════════════
        #  multi-label
        # ═══════════════════════════════════════════
        # rdv + devis
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
        # rdv + prix
        ("Je voudrais prendre rdv, c'est combien une coupe ?", ["appointment", "pricing"]),
        ("Dispo pour un rdv ? Et quels sont vos prix ?", ["appointment", "pricing"]),
        ("Combien ça coûte et quand je peux venir ?", ["appointment", "pricing"]),
        ("Tarifs pour une coloration et réserver un créneau", ["appointment", "pricing"]),
        ("Je veux un RDV et connaître vos tarifs", ["appointment", "pricing"]),
        # rdv + dispos
        ("Quelles sont vos dispos ? Je veux réserver", ["appointment", "planning"]),
        ("Montrez-moi le planning et réservez-moi un créneau", ["appointment", "planning"]),
        ("Vos disponibilités ? Je souhaite prendre rdv", ["appointment", "planning"]),
        ("C'est quoi vos horaires et je peux réserver quand ?", ["appointment", "planning"]),
        # devis + prix
        ("Combien ça coûte ? Et envoyez-moi un devis", ["quote", "pricing"]),
        ("Quels sont vos tarifs et pouvez-vous me faire un devis ?", ["quote", "pricing"]),
        ("Tarifs pour un lissage et devis svp", ["quote", "pricing"]),
        ("Je veux connaître les prix et avoir un devis personnalisé", ["quote", "pricing"]),
        # réclamation + transfert
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
        # suivi + réclamation
        ("Ma commande est en retard et je ne suis pas content", ["order_status", "complaint"]),
        ("Où est mon colis ? C'est inadmissible ce retard", ["order_status", "complaint"]),
        ("CMD-123 jamais arrivée, je veux me plaindre", ["order_status", "complaint"]),
        # paiement + suivi
        ("Je veux payer et savoir où en est ma commande", ["payment", "order_status"]),
        ("Comment régler ma facture et suivre mon colis ?", ["payment", "order_status"]),
        # salutation + rdv
        ("Bonjour, je voudrais prendre rendez-vous", ["greeting", "appointment"]),
        ("Salut ! Possible de réserver un créneau ?", ["greeting", "appointment"]),
        ("Coucou, je veux un rdv pour un balayage", ["greeting", "appointment"]),
        # salutation + devis
        ("Bonjour, j'aurais besoin d'un devis", ["greeting", "quote"]),
        ("Salut, pouvez-vous me faire un devis pour un mariage ?", ["greeting", "quote"]),
        # salutation + prix
        ("Bonjour, quels sont vos tarifs ?", ["greeting", "pricing"]),
        ("Salut, combien coûte une coupe homme ?", ["greeting", "pricing"]),
        # clôture
        ("OK merci c'est tout", ["closing"]),
        ("Parfait on fait comme ça, merci !", ["closing"]),
    ]

    texts = [s[0] for s in samples]
    labels = [s[1] for s in samples]
    return texts, labels
