"""Génération d'un VRAI devis PDF (reportlab) — DA Jenny, avec TVA HT/TTC.

Produit un document A4 propre : logo, en-tête salon, n° de devis, client,
tableau des prestations avec ventilation HT / TVA / TTC, totaux, et mentions
légales (validité, TVA). Renvoie les octets du PDF (à joindre à l'email).
"""

from __future__ import annotations

import datetime as dt
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_CORAL = colors.HexColor("#FF7F6A")
_NIGHT = colors.HexColor("#1A1430")
_INK = colors.HexColor("#1A1D26")
_MUTED = colors.HexColor("#6B7280")
_LINE = colors.HexColor("#E9EBEF")
_TINT = colors.HexColor("#FFF1EE")

_LOGO = Path(__file__).resolve().parent / "assets" / "jenny-email.png"


def _eur(cents: int) -> str:
    return f"{cents / 100:,.2f} €".replace(",", " ").replace(".", ",")


def build_quote_pdf(
    *,
    reference: str,
    business_name: str,
    business_email: str | None,
    business_phone: str | None,
    customer_name: str,
    items: list[dict],
    vat_rate: float,
    valid_until: dt.datetime,
    created: dt.datetime | None = None,
) -> bytes:
    """Construit le PDF du devis et renvoie ses octets."""
    created = created or dt.datetime.now(dt.UTC)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Devis {reference}",
        author=business_name,
    )
    styles = getSampleStyleSheet()
    h_small = ParagraphStyle("hs", parent=styles["Normal"], fontSize=9, textColor=_MUTED, leading=13)
    h_name = ParagraphStyle("hn", parent=styles["Normal"], fontSize=15, textColor=_INK, leading=18, spaceAfter=2)
    body = ParagraphStyle("bd", parent=styles["Normal"], fontSize=9.5, textColor=_INK, leading=14)
    flow: list = []

    # ── En-tête : logo + salon (gauche) / DEVIS + réf (droite) ──
    logo_cell = ""
    if _LOGO.exists():
        logo_cell = Image(str(_LOGO), width=20 * mm, height=20 * mm)
    salon_block = [
        Paragraph(f"<b>{business_name}</b>", h_name),
        Paragraph("<br/>".join(filter(None, [business_email, business_phone])), h_small),
    ]
    devis_title = ParagraphStyle(
        "dt", parent=styles["Normal"], fontSize=22, leading=26, textColor=_CORAL, alignment=2
    )
    devis_block = [
        Paragraph("<b>DEVIS</b>", devis_title),
        Spacer(1, 8),
        Paragraph(f"N° <b>{reference}</b>", h_small),
        Paragraph(f"Date : {created.strftime('%d/%m/%Y')}", h_small),
        Paragraph(f"Valable jusqu'au : <b>{valid_until.strftime('%d/%m/%Y')}</b>", h_small),
    ]
    header = Table(
        [[[logo_cell] if logo_cell else [], salon_block, devis_block]],
        colWidths=[24 * mm, 80 * mm, 66 * mm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    flow += [header, Spacer(1, 16)]

    # ── Client ──
    flow += [
        Paragraph('<font color="#6B7280" size="8">DEVIS ÉTABLI POUR</font>', body),
        Paragraph(f"<b>{customer_name}</b>", body),
        Spacer(1, 14),
    ]

    # ── Tableau des prestations (HT / TVA / TTC) ──
    head = ["Prestation", "Durée", "Montant HT", f"TVA {round(vat_rate*100)}%", "Total TTC"]
    rows = [head]
    total_ttc = 0
    for it in items:
        ttc = round(float(it.get("price_eur", 0)) * 100)
        ht = round(ttc / (1 + vat_rate))
        tva = ttc - ht
        total_ttc += ttc
        dur = it.get("duration_minutes")
        rows.append([
            Paragraph(str(it.get("name", "")), body),
            f"{dur} min" if dur else "—",
            _eur(ht),
            _eur(tva),
            _eur(ttc),
        ])
    table = Table(rows, colWidths=[64 * mm, 22 * mm, 28 * mm, 26 * mm, 30 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _NIGHT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("TOPPADDING", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, _LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    flow += [table, Spacer(1, 4)]

    # ── Totaux ──
    total_ht = round(total_ttc / (1 + vat_rate))
    total_tva = total_ttc - total_ht
    totals = Table(
        [
            ["Total HT", _eur(total_ht)],
            [f"TVA {round(vat_rate*100)} %", _eur(total_tva)],
            ["Total TTC", _eur(total_ttc)],
        ],
        colWidths=[40 * mm, 35 * mm],
        hAlign="RIGHT",
    )
    totals.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, 1), _MUTED),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        # Ligne Total TTC mise en valeur
        ("BACKGROUND", (0, 2), (-1, 2), _TINT),
        ("TEXTCOLOR", (0, 2), (-1, 2), _CORAL),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE", (0, 2), (-1, 2), 12),
        ("TOPPADDING", (0, 2), (-1, 2), 8),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 8),
    ]))
    flow += [totals, Spacer(1, 26)]

    # ── Mentions légales / footer ──
    mentions = (
        f"Devis valable jusqu'au {valid_until.strftime('%d/%m/%Y')}. "
        "Montants exprimés en euros. Prestations soumises à la TVA au taux en vigueur. "
        "Pour accepter ce devis, répondez à l'email ou contactez le salon."
    )
    flow += [
        Paragraph(f'<font color="#9AA1AD" size="8">{mentions}</font>', body),
        Spacer(1, 10),
        Paragraph(
            f'<font color="#9AA1AD" size="8">Devis généré par Jenny pour {business_name}</font>',
            body,
        ),
    ]

    doc.build(flow)
    return buf.getvalue()
