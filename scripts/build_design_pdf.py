#!/usr/bin/env python3
"""Build docs/moboclaw-design-document.pdf (architecture, data model, sequence diagrams).

Requires: pip install reportlab
Inputs (under docs/): architecture-high-level.png, sequence-diagram-1.png, sequence-diagram-2.png
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT_PDF = DOCS / "moboclaw-design-document.pdf"


def _img(path: Path, max_width: float = 16 * cm) -> Image:
    ir = ImageReader(str(path))
    iw, ih = ir.getSize()
    w = max_width
    h = w * (ih / float(iw))
    return Image(str(path), width=w, height=h)


def _styles():
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        name="BodyJustify",
        parent=base["Normal"],
        fontSize=10,
        leading=14,
        alignment=TA_JUSTIFY,
        spaceAfter=6,
    )
    h2 = ParagraphStyle(
        name="H2",
        parent=base["Heading2"],
        fontSize=14,
        spaceBefore=12,
        spaceAfter=8,
    )
    h3 = ParagraphStyle(
        name="H3",
        parent=base["Heading3"],
        fontSize=12,
        spaceBefore=10,
        spaceAfter=6,
    )
    mono = ParagraphStyle(
        name="MonoSmall",
        parent=base["Code"],
        fontSize=7,
        leading=9,
        fontName="Courier",
    )
    return base, body, h2, h3, mono


def _p(text: str, style) -> Paragraph:
    t = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(t, style)


def build() -> None:
    base, body, h2, h3, mono = _styles()
    story: list = []

    story.append(_p("Mobile Agent Infrastructure", base["Title"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(
        _p(
            "Design overview: architecture, relational data model, and sequence diagrams.",
            body,
        )
    )
    story.append(PageBreak())

    story.append(_p("1. Architecture", h2))
    story.append(
        _p(
            "Single FastAPI process. Emulators and snapshot metadata are in memory (mock). "
            "Users, sessions, and health history persist in SQLite. Routers: system, "
            "emulators, users/sessions. Background: warm pool, emulator health simulation, "
            "session health worker.",
            body,
        )
    )
    story.append(Spacer(1, 0.2 * cm))
    arch_png = DOCS / "architecture-high-level.png"
    if not arch_png.exists():
        raise FileNotFoundError(f"Missing {arch_png}")
    story.append(_img(arch_png))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_p("Layer summary:", h3))
    data = [
        ["Layer", "Role"],
        ["Controllers", "HTTP routes and validation"],
        ["EmulatorService + warm pool, health, snapshots", "In-memory orchestration"],
        ["session_service + session_health_worker", "Session CRUD, mock health, tiering"],
        ["SQLite", "Durable users, sessions, health history"],
        ["models + store", "Part 1 in-memory registry"],
    ]
    t = Table(data, colWidths=[5.5 * cm, 11 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(t)
    story.append(PageBreak())

    story.append(_p("2. Data model", h2))
    story.append(
        _p(
            "Tables: users; user_sessions (unique user_id + app_package); "
            "session_health_history (append-only checks). Enums stored as VARCHAR. "
            "Full details: docs/DATA_MODEL.md.",
            body,
        )
    )
    story.append(Spacer(1, 0.2 * cm))
    dm = [
        ["Table", "Role"],
        ["users", "One row per external user id (string PK)."],
        ["user_sessions", "Health, tier, snapshot ref; one row per (user, app)."],
        ["session_health_history", "Append-only log of health checks for a session."],
    ]
    t2 = Table(dm, colWidths=[4 * cm, 12.5 * cm])
    t2.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(t2)
    story.append(Spacer(1, 0.2 * cm))
    story.append(
        _p(
            "Relationships: users (1) — user_sessions (N) — session_health_history (N). "
            "ON DELETE CASCADE from users and sessions.",
            body,
        )
    )
    story.append(_p("SQLite DDL (equivalent to Base.metadata.create_all):", h3))

    ddl = """CREATE TABLE users (
	id VARCHAR(256) NOT NULL,
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE user_sessions (
	id INTEGER NOT NULL,
	user_id VARCHAR(256) NOT NULL,
	app_package VARCHAR(512) NOT NULL,
	snapshot_id VARCHAR(512),
	health VARCHAR(32) NOT NULL,
	last_verified_at DATETIME,
	last_access_at DATETIME,
	login_method VARCHAR(32) NOT NULL,
	tier VARCHAR(32) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_user_app UNIQUE (user_id, app_package),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE session_health_history (
	id INTEGER NOT NULL,
	session_id INTEGER NOT NULL,
	checked_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
	observed VARCHAR(32) NOT NULL,
	detail VARCHAR(1024),
	PRIMARY KEY (id),
	FOREIGN KEY(session_id) REFERENCES user_sessions (id) ON DELETE CASCADE
);

CREATE INDEX ix_session_health_history_session_id ON session_health_history (session_id);"""
    story.append(Preformatted(ddl, mono, maxLineLength=100))
    story.append(PageBreak())

    story.append(_p("3. Sequence diagrams", h2))
    story.append(
        _p(
            "Rendered from pdf-sequences.md using @mermaid-js/mermaid-cli.",
            body,
        )
    )
    s1 = DOCS / "sequence-diagram-1.png"
    s2 = DOCS / "sequence-diagram-2.png"
    for label, path in (
        ("3.1 Emulator provision (POST /emulators)", s1),
        ("3.2 Session verify (POST /users/.../verify)", s2),
    ):
        if not path.exists():
            raise FileNotFoundError(f"Missing {path}")
        story.append(_p(label, h3))
        story.append(_img(path, max_width=15 * cm))
        story.append(Spacer(1, 0.3 * cm))

    story.append(_p("See README.md for setup and API.", body))

    doc = SimpleDocTemplate(
        str(OUT_PDF),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Mobile Agent Infrastructure — Design overview",
    )
    doc.build(story)
    print(f"Wrote {OUT_PDF}")


if __name__ == "__main__":
    build()
