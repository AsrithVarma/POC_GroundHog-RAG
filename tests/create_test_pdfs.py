"""Generate 5 synthetic PDFs in tests/fixtures/ for pipeline testing."""

import os
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim "
    "veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea "
    "commodo consequat. Duis aute irure dolor in reprehenderit in voluptate "
    "velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint "
    "occaecat cupidatat non proident, sunt in culpa qui officia deserunt "
    "mollit anim id est laborum."
)

TOPICS = [
    {
        "filename": "network_security_policy.pdf",
        "title": "Network Security Policy",
        "headings": ["Firewall Rules", "VPN Configuration", "Intrusion Detection", "Incident Response"],
        "table_header": ["Control", "Status", "Owner"],
        "table_rows": [
            ["Firewall audit", "Complete", "NetOps"],
            ["VPN certificates", "Pending", "SecOps"],
            ["IDS signatures", "Current", "SOC"],
        ],
    },
    {
        "filename": "data_handling_procedures.pdf",
        "title": "Data Handling Procedures",
        "headings": ["Classification", "Encryption Standards", "Retention Policy"],
        "table_header": ["Data Type", "Classification", "Retention"],
        "table_rows": [
            ["PII", "Confidential", "3 years"],
            ["Financial", "Restricted", "7 years"],
            ["Public docs", "Public", "1 year"],
            ["Audit logs", "Internal", "5 years"],
        ],
    },
    {
        "filename": "system_architecture_overview.pdf",
        "title": "System Architecture Overview",
        "headings": ["Frontend Layer", "API Gateway", "Database Tier", "Caching Strategy", "Monitoring"],
        "table_header": ["Component", "Technology", "Port"],
        "table_rows": [
            ["Web UI", "React", "3000"],
            ["API", "FastAPI", "8000"],
            ["Database", "PostgreSQL", "5432"],
            ["Cache", "Redis", "6379"],
        ],
    },
    {
        "filename": "compliance_audit_report.pdf",
        "title": "Compliance Audit Report Q4",
        "headings": ["Scope", "Findings", "Remediation Plan"],
        "table_header": ["Finding", "Severity", "Deadline"],
        "table_rows": [
            ["Weak passwords", "High", "2026-02-01"],
            ["Missing MFA", "Critical", "2026-01-15"],
            ["Stale accounts", "Medium", "2026-03-01"],
        ],
    },
    {
        "filename": "employee_onboarding_guide.pdf",
        "title": "Employee Onboarding Guide",
        "headings": ["Account Setup", "Security Training", "Tool Access", "First Week Checklist"],
        "table_header": ["Task", "Day", "Contact"],
        "table_rows": [
            ["Laptop provisioning", "Day 1", "IT Help Desk"],
            ["Badge activation", "Day 1", "Facilities"],
            ["Security awareness", "Day 2", "SecOps"],
            ["VPN enrollment", "Day 2", "NetOps"],
            ["Code repo access", "Day 3", "DevOps"],
        ],
    },
]


def build_table(header: list[str], rows: list[list[str]]) -> Table:
    """Create a styled reportlab Table."""
    data = [header] + rows
    table = Table(data, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#336699")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def generate_pdf(topic: dict, output_dir: Path) -> Path:
    """Generate a single test PDF from a topic definition."""
    filepath = output_dir / topic["filename"]
    doc = SimpleDocTemplate(str(filepath), pagesize=letter)

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading_style = ParagraphStyle(
        "CustomHeading",
        parent=styles["Heading2"],
        spaceAfter=12,
        spaceBefore=18,
    )
    body_style = styles["BodyText"]

    story = []

    # Title page content
    story.append(Paragraph(topic["title"], title_style))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(LOREM, body_style))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(LOREM, body_style))

    # Heading pages with body text
    for heading in topic["headings"]:
        story.append(Spacer(1, 0.4 * inch))
        story.append(Paragraph(heading, heading_style))
        # Two paragraphs of body text per section
        story.append(Paragraph(LOREM, body_style))
        story.append(Spacer(1, 0.1 * inch))
        story.append(
            Paragraph(
                f"This section covers {heading.lower()} in detail. "
                + LOREM,
                body_style,
            )
        )

    # Table section
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("Summary Table", heading_style))
    story.append(build_table(topic["table_header"], topic["table_rows"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(LOREM, body_style))

    doc.build(story)
    return filepath


def main():
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating {len(TOPICS)} test PDFs in {FIXTURES_DIR}/")

    for topic in TOPICS:
        filepath = generate_pdf(topic, FIXTURES_DIR)
        size_kb = os.path.getsize(filepath) / 1024
        print(f"  Created: {filepath.name} ({size_kb:.1f} KB)")

    print("Done.")


if __name__ == "__main__":
    main()
