"""Export a saved VerifyNet JSON report to PDF.

Usage: python work/export_pdf.py report.json evidence.pdf
"""
import json
import sys
from pathlib import Path

from verifynet.pdf_report import pdf_report


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python work/export_pdf.py report.json output.pdf")
    pdf_report(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")), Path(sys.argv[2]))
