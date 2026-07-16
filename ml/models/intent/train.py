"""entraînement du classifieur d'intention."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import torch
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
from torch import nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader, random_split

from jenny.core.logging import get_logger, setup_logging
from ml.models.intent.config import ID_TO_LABEL, INTENT_LABELS, IntentModelConfig
from ml.models.intent.dataset import IntentDataset, generate_sample_data
from ml.models.intent.model import IntentClassifier

logger = get_logger(__name__)
console = Console()


def train_intent_model(
    config: IntentModelConfig | None = None,
    data_path: str | None = None,
    output_dir: str = "checkpoints/intent",
) -> IntentClassifier:
    """entraîne le modèle d'intention."""
    setup_logging()
    config = config or IntentModelConfig()
    torch.manual_seed(config.seed)

    console.print(
        Panel.fit(
            "[bold magenta]🧠 JENNY — Entraînement Intent Classifier[/bold magenta]\n"
            f"[dim]Device: {config.device} • Multi-label: {config.multi_label} • Epochs: {config.epochs}[/dim]",
            border_style="magenta",
        )
    )

    # 1. charger les données
    if data_path and Path(data_path).exists():
        dataset = IntentDataset.from_jsonl(data_path, config=config)
        console.print(
            f"  📂 Données chargées : [green]{data_path}[/green] ({len(dataset):,} exemples)"
        )
    else:
        texts, labels = generate_sample_data()
        dataset = IntentDataset(texts, labels, config=config)
        console.print(f"  📂 Données sample : [yellow]{len(dataset):,} exemples[/yellow]")

    # 2. split train/val/test
    total = len(dataset)
    train_size = int(0.70 * total)
    val_size = int(0.15 * total)
    test_size = total - train_size - val_size

    train_dataset, val_dataset, test_dataset = random_split(
        dataset,
        [train_size, val_size, test_size],
        generator=torch.Generator().manual_seed(config.seed),
    )

    train_loader = DataLoader(train_dataset, batch_size=config.batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=config.batch_size, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=config.batch_size, shuffle=False)

    split_table = Table(title="📊 Dataset Split")
    split_table.add_column("Split", style="cyan")
    split_table.add_column("Exemples", style="green", justify="right")
    split_table.add_column("Ratio", style="dim", justify="right")
    split_table.add_row("Train", f"{train_size:,}", "70%")
    split_table.add_row("Validation", f"{val_size:,}", "15%")
    split_table.add_row("Test", f"{test_size:,}", "15%")
    split_table.add_row("[bold]Total[/bold]", f"[bold]{total:,}[/bold]", "100%")
    console.print(split_table)

    # 3. modèle
    config.vocab_size = len(dataset.vocab)
    model = IntentClassifier(config)
    model = model.to(config.device)

    model_table = Table(title="🏗️ Architecture")
    model_table.add_column("Param", style="cyan")
    model_table.add_column("Valeur", style="green")
    model_table.add_row("Paramètres", f"{model.count_parameters():,}")
    model_table.add_row("Vocab", f"{config.vocab_size:,}")
    model_table.add_row("Device", config.device)
    model_table.add_row("Classes", f"{config.num_classes} ({', '.join(INTENT_LABELS[:5])}...)")
    model_table.add_row("Multi-label", "✅" if config.multi_label else "❌")
    console.print(model_table)

    # 4. optimiseur, loss, scheduler
    optimizer = AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )

    scheduler = ReduceLROnPlateau(
        optimizer,
        mode="max",
        factor=0.5,
        patience=5,
    )

    if config.multi_label:
        criterion = nn.BCEWithLogitsLoss()
        console.print("  📉 Loss : [cyan]BCEWithLogitsLoss[/cyan] (multi-label)")
    else:
        criterion = nn.CrossEntropyLoss()
        console.print("  📉 Loss : [cyan]CrossEntropyLoss[/cyan] (single-label)")

    # 5. boucle d'entraînement
    best_metric = 0.0
    patience_counter = 0
    max_patience = 10
    history: list[dict] = []

    console.print(
        f"\n[bold]🚀 Entraînement ({config.epochs} epochs, patience={max_patience})[/bold]\n"
    )

    epoch_progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=50),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    )

    with epoch_progress:
        task_epoch = epoch_progress.add_task("[magenta]Epochs", total=config.epochs)

        for epoch in range(config.epochs):
            epoch_start = time.time()
            model.train()
            total_loss = 0.0
            correct = 0
            total = 0

            for batch in train_loader:
                input_ids = batch["input_ids"].to(config.device)
                attention_mask = batch["attention_mask"].to(config.device)

                optimizer.zero_grad()
                logits = model(input_ids, attention_mask)

                if config.multi_label:
                    labels_multi = batch["labels_multi"].to(config.device)
                    loss = criterion(logits, labels_multi)
                    preds = torch.sigmoid(logits)
                    top1 = preds.argmax(dim=-1)
                    for i in range(len(top1)):
                        if labels_multi[i][top1[i]] == 1.0:
                            correct += 1
                    total += len(top1)
                else:
                    labels = batch["labels"].to(config.device)
                    loss = criterion(logits, labels)
                    preds = logits.argmax(dim=-1)
                    correct += (preds == labels).sum().item()
                    total += labels.size(0)

                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()
                total_loss += loss.item()

            train_acc = correct / max(total, 1)
            avg_loss = total_loss / max(len(train_loader), 1)

            # éval validation
            if config.multi_label:
                val_metric = _evaluate_multi_label(model, val_loader, config)
            else:
                val_metric = _evaluate(model, val_loader, config.device)

            scheduler.step(val_metric)
            current_lr = optimizer.param_groups[0]["lr"]

            epoch_time = time.time() - epoch_start

            history.append(
                {
                    "epoch": epoch + 1,
                    "loss": avg_loss,
                    "train_acc": train_acc,
                    "val_f1": val_metric,
                    "lr": current_lr,
                    "time": epoch_time,
                }
            )

            # maj progress bar
            epoch_progress.update(
                task_epoch,
                description=(
                    f"[magenta]Epoch {epoch + 1:3d}/{config.epochs} │ "
                    f"Loss: {avg_loss:.4f} │ "
                    f"Train: {train_acc:.1%} │ "
                    f"Val F1: {val_metric:.1%} │ "
                    f"LR: {current_lr:.1e}"
                ),
            )
            epoch_progress.advance(task_epoch)

            # sauve le meilleur modèle
            if val_metric > best_metric:
                best_metric = val_metric
                patience_counter = 0
                _save_checkpoint(model, dataset.vocab, config, output_dir)
                console.print(
                    f"  [green]✨ Nouveau best: Val F1={val_metric:.2%} (epoch {epoch + 1})[/green]"
                )
            else:
                patience_counter += 1

            # early stopping
            if patience_counter >= max_patience:
                console.print(
                    f"\n  [yellow]⏹ Early stopping à l'epoch {epoch + 1} (patience={max_patience})[/yellow]"
                )
                break

    # 6. éval finale sur test
    console.print("\n[bold cyan]📋 Évaluation sur le Test Set[/bold cyan]")

    # recharge le meilleur modèle
    best_path = Path(output_dir) / "best_model.pt"
    if best_path.exists():
        checkpoint = torch.load(best_path, map_location=config.device, weights_only=False)
        model.load_state_dict(checkpoint["model_state_dict"])
        console.print("  📦 Meilleur modèle rechargé")

    if config.multi_label:
        test_f1, test_details = _evaluate_multi_label_detailed(model, test_loader, config)
    else:
        test_f1 = _evaluate(model, test_loader, config.device)
        test_details = {}

    results_table = Table(title="🎯 Résultats Finaux")
    results_table.add_column("Métrique", style="cyan")
    results_table.add_column("Valeur", style="green", justify="right")
    results_table.add_row("Best Val F1", f"{best_metric:.2%}")
    results_table.add_row("[bold]Test F1[/bold]", f"[bold]{test_f1:.2%}[/bold]")
    if test_details:
        results_table.add_row("Test Precision", f"{test_details.get('precision', 0):.2%}")
        results_table.add_row("Test Recall", f"{test_details.get('recall', 0):.2%}")
    results_table.add_row("Epochs effectués", str(len(history)))
    results_table.add_row("Checkpoint", str(best_path))
    console.print(results_table)

    # métriques par classe
    if test_details.get("per_class"):
        class_table = Table(title="📊 F1 par intention")
        class_table.add_column("Intent", style="cyan")
        class_table.add_column("F1", style="green", justify="right")
        class_table.add_column("Support", style="dim", justify="right")
        for intent_name, metrics in sorted(
            test_details["per_class"].items(),
            key=lambda x: x[1]["f1"],
            reverse=True,
        ):
            f1 = metrics["f1"]
            support = metrics["support"]
            color = "green" if f1 > 0.7 else ("yellow" if f1 > 0.4 else "red")
            class_table.add_row(intent_name, f"[{color}]{f1:.2%}[/{color}]", str(support))
        console.print(class_table)

    console.print(
        Panel.fit(
            f"[bold green]✅ Entraînement terminé — Test F1: {test_f1:.2%}[/bold green]",
            border_style="green",
        )
    )

    return model


def _evaluate(
    model: IntentClassifier,
    loader: DataLoader,
    device: str,
) -> float:
    """éval single-label."""
    model.eval()
    correct = 0
    total = 0

    with torch.no_grad():
        for batch in loader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)

            logits = model(input_ids, attention_mask)
            preds = logits.argmax(dim=-1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)

    return correct / max(total, 1)


def _evaluate_multi_label(
    model: IntentClassifier,
    loader: DataLoader,
    config: IntentModelConfig,
) -> float:
    """éval multi-label, f1 micro."""
    model.eval()
    true_positives = 0
    false_positives = 0
    false_negatives = 0

    threshold = config.multi_label_threshold

    with torch.no_grad():
        for batch in loader:
            input_ids = batch["input_ids"].to(config.device)
            attention_mask = batch["attention_mask"].to(config.device)
            labels_multi = batch["labels_multi"].to(config.device)

            logits = model(input_ids, attention_mask)
            preds = (torch.sigmoid(logits) >= threshold).float()

            true_positives += ((preds == 1) & (labels_multi == 1)).sum().item()
            false_positives += ((preds == 1) & (labels_multi == 0)).sum().item()
            false_negatives += ((preds == 0) & (labels_multi == 1)).sum().item()

    precision = true_positives / max(true_positives + false_positives, 1)
    recall = true_positives / max(true_positives + false_negatives, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-8)

    return f1


def _evaluate_multi_label_detailed(
    model: IntentClassifier,
    loader: DataLoader,
    config: IntentModelConfig,
) -> tuple[float, dict]:
    """éval détaillée par classe."""
    model.eval()
    threshold = config.multi_label_threshold
    num_classes = config.num_classes

    # compteurs par classe
    tp = [0] * num_classes
    fp = [0] * num_classes
    fn = [0] * num_classes

    with torch.no_grad():
        for batch in loader:
            input_ids = batch["input_ids"].to(config.device)
            attention_mask = batch["attention_mask"].to(config.device)
            labels_multi = batch["labels_multi"].to(config.device)

            logits = model(input_ids, attention_mask)
            preds = (torch.sigmoid(logits) >= threshold).float()

            for c in range(num_classes):
                tp[c] += ((preds[:, c] == 1) & (labels_multi[:, c] == 1)).sum().item()
                fp[c] += ((preds[:, c] == 1) & (labels_multi[:, c] == 0)).sum().item()
                fn[c] += ((preds[:, c] == 0) & (labels_multi[:, c] == 1)).sum().item()

    # f1 micro
    total_tp = sum(tp)
    total_fp = sum(fp)
    total_fn = sum(fn)
    precision = total_tp / max(total_tp + total_fp, 1)
    recall = total_tp / max(total_tp + total_fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-8)

    # f1 par classe
    per_class = {}
    for c in range(num_classes):
        p = tp[c] / max(tp[c] + fp[c], 1)
        r = tp[c] / max(tp[c] + fn[c], 1)
        cf1 = 2 * p * r / max(p + r, 1e-8)
        label = ID_TO_LABEL.get(c, f"class_{c}")
        per_class[label] = {"f1": cf1, "precision": p, "recall": r, "support": tp[c] + fn[c]}

    return f1, {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "per_class": per_class,
    }


def _save_checkpoint(
    model: IntentClassifier,
    vocab: dict[str, int],
    config: IntentModelConfig,
    output_dir: str,
) -> None:
    """sauve modèle, vocab, config."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "config": config,
            "vocab": vocab,
        },
        path / "best_model.pt",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Entraîner le classifieur d'intention")
    parser.add_argument("--data", type=str, default=None, help="Chemin JSONL")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--output", type=str, default="checkpoints/intent")
    parser.add_argument("--multi-label", action="store_true", default=True)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    cfg = IntentModelConfig(
        epochs=args.epochs,
        multi_label=args.multi_label,
        batch_size=args.batch_size,
    )
    train_intent_model(config=cfg, data_path=args.data, output_dir=args.output)
