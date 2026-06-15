"""Modèle LSTM pour la détection d'intention — Multi-Label.

Architecture :
- Embedding → Bi-LSTM → Attention → FC → Sigmoid (multi-label)

Le Bi-LSTM capture le contexte bidirectionnel du message.
L'attention pondère les timesteps les plus informatifs.
La couche FC + Sigmoid produit des scores INDÉPENDANTS par intention,
permettant de détecter PLUSIEURS intentions dans un seul message.

Ex: "Je veux un RDV urgent et un devis" → [appointment ✅, quote ✅]
"""

import torch
import torch.nn as nn
import torch.nn.functional as nn_functional

from ml.models.intent.config import IntentModelConfig


class Attention(nn.Module):
    """Mécanisme d'attention simple sur les sorties LSTM."""

    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.attention = nn.Linear(hidden_dim, 1)

    def forward(self, lstm_output: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
        """Calcule l'attention sur les sorties LSTM.

        Args:
            lstm_output: (batch, seq_len, hidden_dim)
            mask: (batch, seq_len) — 1 pour les tokens réels, 0 pour le padding

        Returns:
            Vecteur contexte pondéré (batch, hidden_dim)
        """
        scores = self.attention(lstm_output).squeeze(-1)  # (batch, seq_len)

        if mask is not None:
            scores = scores.masked_fill(mask == 0, float("-inf"))

        weights = nn_functional.softmax(scores, dim=1)  # (batch, seq_len)
        context = torch.bmm(weights.unsqueeze(1), lstm_output).squeeze(1)  # (batch, hidden_dim)

        return context


class IntentClassifier(nn.Module):
    """Classifieur d'intention Multi-Label basé sur Bi-LSTM + Attention.

    Pipeline :
    1. Embedding des tokens
    2. Bi-LSTM pour capturer le contexte séquentiel
    3. Attention pour pondérer les timesteps importants
    4. FC + Dropout pour la classification
    5. Sigmoid (multi-label) : chaque intention a un score indépendant [0, 1]

    Multi-label vs Multi-class :
    - Multi-class (ancien) : softmax → une seule intention (somme des probas = 1)
    - Multi-label (nouveau) : sigmoid → N intentions possibles simultanément
    """

    def __init__(self, config: IntentModelConfig) -> None:
        super().__init__()
        self.config = config

        self.embedding = nn.Embedding(
            config.vocab_size,
            config.embedding_dim,
            padding_idx=0,
        )

        self.lstm = nn.LSTM(
            input_size=config.embedding_dim,
            hidden_size=config.hidden_dim,
            num_layers=config.num_layers,
            batch_first=True,
            bidirectional=config.bidirectional,
            dropout=config.dropout if config.num_layers > 1 else 0.0,
        )

        lstm_output_dim = config.hidden_dim * (2 if config.bidirectional else 1)

        self.attention = Attention(lstm_output_dim)
        self.dropout = nn.Dropout(config.dropout)
        self.fc = nn.Linear(lstm_output_dim, config.num_classes)

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """Forward pass — retourne des logits bruts.

        Args:
            input_ids: (batch, seq_len)
            attention_mask: (batch, seq_len)

        Returns:
            logits: (batch, num_classes)
        """
        embedded = self.embedding(input_ids)
        embedded = self.dropout(embedded)

        lstm_out, _ = self.lstm(embedded)

        context = self.attention(lstm_out, attention_mask)
        context = self.dropout(context)

        logits = self.fc(context)
        return logits

    def predict_proba(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """Retourne les probabilités par classe.

        Utilise sigmoid (multi-label) : chaque classe a un score
        indépendant entre 0 et 1. Plusieurs classes peuvent être
        activées simultanément.
        """
        logits = self.forward(input_ids, attention_mask)
        return torch.sigmoid(logits)

    def predict_proba_softmax(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """Rétro-compatibilité : probabilités softmax (single-label)."""
        logits = self.forward(input_ids, attention_mask)
        return nn_functional.softmax(logits, dim=-1)

    def count_parameters(self) -> int:
        """Nombre de paramètres entraînables."""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
