"""The download control and the download endpoint must name the same three formats.

There is no frontend test runner in this repo, so this reads the sources as text —
the same weak-but-cheap guard `tests/test_ip_notice.py` uses. Weak is enough for what
can go wrong here: the failure is not a subtle one, it is a button that 400s or a file
the product produces and offers nowhere. A format the server accepts and the UI never
offers is an artifact written on every job and reachable only by typing a URL, which
is the state this change set exists to end; a format the UI offers and the server does
not know is a dead button.

`Engineer.EXPORT_SUFFIXES` is the third side of the same triangle: the endpoint can
only serve a file Phase 3 wrote.
"""
import re
from pathlib import Path

import pytest

from pythonsrc.engineer import EXPORT_SUFFIXES
from server.app import DEFAULT_DOWNLOAD_FORMAT, DOWNLOAD_FORMATS

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Quote-agnostic on purpose: a formatter switching the TSX from single to double
#: quotes must not read as the control dropping a format.
_OFFERED_FORMAT = re.compile(r"""format:\s*['"]([^'"]+)['"]""")

CONTROL = REPO_ROOT / "web" / "src" / "components" / "DownloadFormats.tsx"
#: The finished-job view. The one page that shows a job after it has stopped moving,
#: and therefore the one that has to offer the files.
FINISHED_JOB_VIEW = REPO_ROOT / "web" / "src" / "pages" / "JobDetail.tsx"


def test_the_endpoint_serves_gcode_and_both_mesh_formats():
    assert set(DOWNLOAD_FORMATS) == {"gcode", "stl", "3mf"}


def test_the_default_format_is_the_gcode_so_existing_callers_are_unchanged():
    """`GET /jobs/{id}/download` with no parameter is what the toolpath viewer, the
    dispatch gate and every bookmark send."""
    assert DEFAULT_DOWNLOAD_FORMAT == "gcode"
    assert DOWNLOAD_FORMATS[DEFAULT_DOWNLOAD_FORMAT][0] == "engineered_mesh.gcode"


@pytest.mark.parametrize("fmt", ["stl", "3mf"])
def test_every_mesh_format_the_endpoint_serves_is_one_phase_3_writes(fmt):
    filename, _ = DOWNLOAD_FORMATS[fmt]
    assert Path(filename).suffix in EXPORT_SUFFIXES, (
        f"?format={fmt} serves {filename}, which Phase 3 does not write — "
        "see Engineer.EXPORT_SUFFIXES."
    )


def test_the_finished_job_view_renders_the_download_control():
    text = FINISHED_JOB_VIEW.read_text()
    assert "DownloadFormats" in text, (
        "The finished-job view no longer renders the download control. The engineered "
        "mesh is then written on every job and reachable only by typing a URL."
    )


@pytest.mark.parametrize("fmt", sorted(DOWNLOAD_FORMATS))
def test_the_control_offers_every_format_the_endpoint_serves(fmt):
    assert fmt in set(_OFFERED_FORMAT.findall(CONTROL.read_text())), (
        f"The download control does not offer ?format={fmt}, which the server serves."
    )


def test_the_control_offers_nothing_the_endpoint_would_refuse():
    """A dead button is worse than a missing one: it reports a 400 as a broken app."""
    offered = set(_OFFERED_FORMAT.findall(CONTROL.read_text()))
    assert offered <= set(DOWNLOAD_FORMATS), (
        f"The control offers {offered - set(DOWNLOAD_FORMATS)}, which the endpoint "
        "answers with a 400."
    )
    assert offered, "no formats were found in the control at all — has it been rewritten?"
