"""Optional PDF evidence export. Install requirements.txt to enable it."""
from .reports import html_report


def pdf_report(report, target):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer
    except ImportError as exc:
        raise RuntimeError("PDF export requires reportlab; install requirements.txt first.") from exc
    doc = SimpleDocTemplate(str(target), pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42)
    styles = getSampleStyleSheet(); story = [Paragraph("VerifyNet evidence report", styles["Title"])]
    story.append(Spacer(1, 12)); story.append(Preformatted(html_report(report).replace("<", "").replace(">", "")[:50000], styles["Code"]))
    doc.build(story); return str(target)
