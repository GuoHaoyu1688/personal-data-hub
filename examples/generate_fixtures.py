"""Regenerate fictional spreadsheet/PDF acceptance fixtures locally."""

from pathlib import Path

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).parent
workbook = Workbook()
worksheet = workbook.active
worksheet.title = "Projects"
for row in [
    ["Project name", "Role", "Start date", "Status", "Description"],
    ["Cooling study", "Coordinator", "2026-01-05", "active", "Fictional training project"],
    ["Vocabulary plan", "Learner", "2026-02-10", "planned", "Sample practice schedule"],
]:
    worksheet.append(row)
workbook.save(ROOT / "projects.xlsx")
rows = [
    ["Document", "Category", "Expiry date", "Reference"],
    ["Example training card", "Training", "2026-11-01", "FICTIONAL-001"],
    ["Example equipment permit", "Training", "2027-03-15", "FICTIONAL-002"],
]
table = Table(rows, colWidths=[170, 70, 90, 100])
table.setStyle(
    TableStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.7, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
        ]
    )
)
SimpleDocTemplate(str(ROOT / "documents.pdf"), pagesize=A4).build(
    [
        Paragraph("Fictional document register", getSampleStyleSheet()["Title"]),
        Spacer(1, 18),
        table,
    ]
)
