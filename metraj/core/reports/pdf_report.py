"""PDF report builder using ReportLab.

Generates a one-pager keşif özeti showing kategori-level totals and the top
pozlar by tutar.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..pozlar import PozTotals
from ..quantities import RoomQuantities

logger = logging.getLogger(__name__)


class PdfReportBuilder:
    """Compose the kategori summary PDF."""

    def build(
        self,
        path: str | Path,
        project_name: str,
        quantities: Sequence[RoomQuantities],
        totals: PozTotals,
        author: str = "Metraj Otomasyon",
    ) -> Path:
        styles = getSampleStyleSheet()
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(str(out), pagesize=A4,
                                leftMargin=2 * cm, rightMargin=2 * cm,
                                topMargin=2 * cm, bottomMargin=2 * cm)
        story = []
        story.append(Paragraph(f"<b>METRAJ OZET RAPORU</b>", styles["Title"]))
        story.append(Paragraph(project_name or "(proje adi)", styles["Heading2"]))
        story.append(Paragraph(
            f"Olusturma: {datetime.now():%Y-%m-%d %H:%M} | {author}",
            styles["Normal"],
        ))
        story.append(Spacer(1, 0.5 * cm))

        # Mahal ozeti
        total_area = sum(q.room.area for q in quantities)
        total_walls = sum(q.net_wall_m2 for q in quantities)
        total_doors = sum(q.door_count for q in quantities)
        total_windows = sum(q.window_count for q in quantities)
        story.append(Paragraph("<b>Mahal Ozet</b>", styles["Heading3"]))
        mahal_table = Table([
            ["Mahal Sayisi", "Toplam Alan (m2)", "Toplam Net Duvar (m2)", "Kapi Adet", "Pencere Adet"],
            [len(quantities), f"{total_area:.2f}", f"{total_walls:.2f}",
             total_doors, total_windows],
        ], colWidths=[3.5 * cm] * 5)
        mahal_table.setStyle(self._table_style())
        story.append(mahal_table)
        story.append(Spacer(1, 0.5 * cm))

        # Kategori totals
        story.append(Paragraph("<b>Kategori Toplamlari</b>", styles["Heading3"]))
        kategori_rows = [["Kategori", "Tutar (TL)"]]
        for kategori, tutar in sorted(totals.by_kategori.items(),
                                      key=lambda kv: kv[1], reverse=True):
            kategori_rows.append([kategori, f"{tutar:,.2f}"])
        kategori_rows.append(["GENEL TOPLAM", f"{totals.grand_total:,.2f}"])
        kategori_table = Table(kategori_rows, colWidths=[8 * cm, 5 * cm])
        kategori_table.setStyle(self._table_style(highlight_last=True))
        story.append(kategori_table)
        story.append(Spacer(1, 0.5 * cm))

        # Top 10 poz by tutar
        story.append(Paragraph("<b>Tutara Gore En Buyuk 10 Poz</b>", styles["Heading3"]))
        top_rows = [["Poz", "Kategori", "Tanim", "Birim", "Miktar", "Tutar (TL)"]]
        for entry in sorted(totals.rows, key=lambda r: r.tutar, reverse=True)[:10]:
            top_rows.append([
                entry.poz_no,
                entry.kategori,
                entry.tanim[:40],
                entry.birim,
                f"{entry.miktar:.2f}",
                f"{entry.tutar:,.2f}",
            ])
        top_table = Table(top_rows, colWidths=[2.6 * cm, 2.2 * cm, 6 * cm, 1.4 * cm, 2 * cm, 2.8 * cm])
        top_table.setStyle(self._table_style())
        story.append(top_table)

        doc.build(story)
        logger.info("PDF report generated at %s", out)
        return out

    @staticmethod
    def _table_style(highlight_last: bool = False) -> TableStyle:
        ts = TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#305496")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F2F2F2")]),
        ])
        if highlight_last:
            ts.add("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#FFE699"))
            ts.add("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")
        return ts
