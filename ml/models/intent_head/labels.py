"""Les 14 intentions de Jenny."""

INTENT_LABELS: list[str] = [
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
    "small_talk",
    "payment_question",
]

LABEL_TO_ID: dict[str, int] = {label: i for i, label in enumerate(INTENT_LABELS)}
