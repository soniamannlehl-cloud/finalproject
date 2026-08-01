"""HTML and PDF rendering for InvestmentReport."""

import logging
from pathlib import Path

from contracts import InvestmentReport
from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "jinja2"]),
)


def render_html(report: InvestmentReport) -> str:
    template = _env.get_template("report.html.j2")
    return template.render(report=report, sections=report.ordered_sections())


def render_pdf(report: InvestmentReport) -> bytes:
    """Render PDF via WeasyPrint. Raises ImportError if WeasyPrint unavailable."""
    try:
        from weasyprint import HTML
    except ImportError as e:
        raise ImportError("WeasyPrint is required for PDF export") from e

    html = render_html(report)
    return HTML(string=html).write_pdf()
