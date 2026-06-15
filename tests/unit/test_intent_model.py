"""Tests unitaires pour le modèle de détection d'intention."""

import torch

from ml.models.intent.config import ID_TO_LABEL, INTENT_LABELS, LABEL_TO_ID, IntentModelConfig
from ml.models.intent.dataset import IntentDataset, generate_sample_data
from ml.models.intent.model import IntentClassifier


class TestIntentConfig:
    """Tests pour la configuration du modèle d'intention."""

    def test_labels_defined(self) -> None:
        assert len(INTENT_LABELS) >= 5
        assert "greeting" in INTENT_LABELS
        assert "order_status" in INTENT_LABELS

    def test_label_mapping(self) -> None:
        for label in INTENT_LABELS:
            assert label in LABEL_TO_ID
            assert LABEL_TO_ID[label] in ID_TO_LABEL
            assert ID_TO_LABEL[LABEL_TO_ID[label]] == label


class TestIntentModel:
    """Tests pour le modèle LSTM d'intention."""

    def test_model_creation(self) -> None:
        config = IntentModelConfig(vocab_size=100)
        model = IntentClassifier(config)
        assert model.count_parameters() > 0

    def test_forward_pass(self) -> None:
        config = IntentModelConfig(vocab_size=100)
        model = IntentClassifier(config)

        batch_size = 4
        seq_len = 10
        input_ids = torch.randint(0, 100, (batch_size, seq_len))
        mask = torch.ones(batch_size, seq_len, dtype=torch.long)

        logits = model(input_ids, mask)
        assert logits.shape == (batch_size, config.num_classes)

    def test_predict_proba(self) -> None:
        config = IntentModelConfig(vocab_size=100)
        model = IntentClassifier(config)

        input_ids = torch.randint(0, 100, (1, 10))
        probs = model.predict_proba(input_ids)
        assert probs.shape == (1, config.num_classes)
        # Sigmoid : chaque probabilité est indépendante, entre 0 et 1
        assert (probs >= 0).all() and (probs <= 1).all()


class TestIntentDataset:
    """Tests pour le dataset d'intention."""

    def test_sample_data(self) -> None:
        texts, labels = generate_sample_data()
        assert len(texts) == len(labels)
        assert len(texts) > 0

    def test_dataset_creation(self) -> None:
        texts, labels = generate_sample_data()
        dataset = IntentDataset(texts, labels)
        assert len(dataset) == len(texts)

    def test_dataset_item(self) -> None:
        texts, labels = generate_sample_data()
        config = IntentModelConfig(max_seq_length=32)
        dataset = IntentDataset(texts, labels, config=config)

        item = dataset[0]
        assert "input_ids" in item
        assert "attention_mask" in item
        assert "labels" in item
        assert item["input_ids"].shape == (32,)
        assert item["attention_mask"].shape == (32,)

    def test_vocab_building(self) -> None:
        texts, labels = generate_sample_data()
        dataset = IntentDataset(texts, labels)
        assert "<PAD>" in dataset.vocab
        assert "<UNK>" in dataset.vocab
        assert len(dataset.vocab) > 2
