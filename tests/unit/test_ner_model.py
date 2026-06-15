"""Tests unitaires pour le modèle NER BiGRU."""

import torch

from ml.models.ner.config import BIO_TAGS, ID_TO_TAG, TAG_TO_ID, NERModelConfig
from ml.models.ner.dataset import NERDataset, generate_sample_data
from ml.models.ner.model import BiGRUNER


class TestNERConfig:
    """Tests pour la configuration NER."""

    def test_bio_tags(self) -> None:
        assert "O" in BIO_TAGS
        assert "B-ORDER_NUMBER" in BIO_TAGS
        assert "I-ORDER_NUMBER" in BIO_TAGS
        assert "B-EMAIL" in BIO_TAGS

    def test_tag_mapping(self) -> None:
        for tag in BIO_TAGS:
            assert tag in TAG_TO_ID
            assert TAG_TO_ID[tag] in ID_TO_TAG


class TestBiGRUModel:
    """Tests pour le modèle BiGRU NER."""

    def test_model_creation(self) -> None:
        config = NERModelConfig(vocab_size=100)
        model = BiGRUNER(config)
        assert model.count_parameters() > 0

    def test_forward_pass(self) -> None:
        config = NERModelConfig(vocab_size=100)
        model = BiGRUNER(config)

        batch_size = 4
        seq_len = 10
        input_ids = torch.randint(0, 100, (batch_size, seq_len))
        mask = torch.ones(batch_size, seq_len, dtype=torch.long)

        logits = model(input_ids, mask)
        assert logits.shape == (batch_size, seq_len, config.num_tags)

    def test_predict_tags(self) -> None:
        config = NERModelConfig(vocab_size=100)
        model = BiGRUNER(config)

        input_ids = torch.randint(0, 100, (1, 8))
        tags = model.predict_tags(input_ids)
        assert tags.shape == (1, 8)


class TestNERDataset:
    """Tests pour le dataset NER."""

    def test_sample_data(self) -> None:
        tokens, tags = generate_sample_data()
        assert len(tokens) == len(tags)
        for t, tg in zip(tokens, tags, strict=False):
            assert len(t) == len(tg)

    def test_dataset_creation(self) -> None:
        tokens, tags = generate_sample_data()
        dataset = NERDataset(tokens, tags)
        assert len(dataset) > 0

    def test_dataset_item(self) -> None:
        tokens, tags = generate_sample_data()
        config = NERModelConfig(max_seq_length=20)
        dataset = NERDataset(tokens, tags, config=config)

        item = dataset[0]
        assert item["input_ids"].shape == (20,)
        assert item["labels"].shape == (20,)
