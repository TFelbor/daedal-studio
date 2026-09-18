"""The fit photo: the first route in this application that accepts bytes from a browser.

Everything else the server takes from a client is a short JSON body that pydantic
validates. `POST /jobs/{id}/photo` takes an arbitrary stream of bytes and writes it to a
disk that also holds `~/.ds-mvp/.config_key`'s neighbours, so the four properties the
issue asked for are each pinned here:

* **authenticated** — by wearing no `@public`, which `tests/test_api_auth.py` asserts
  from the router; the 401s below are the same fact seen from this end;
* **size-capped** — twice, because `Content-Length` is a claim and a chunked body makes
  none at all;
* **type-checked** — against a three-entry allowlist that the magic bytes must agree
  with, so a caller cannot label a script `image/jpeg` into the outputs tree;
* **contained** — every join goes through `contained_path`, and `/jobs/%2e%2e/photo`
  reaches the handler as a literal `..`.

The traversal cases are sent **percent-encoded** for the reason
`tests/test_static_path_traversal.py` states: `httpx` normalises a literal `../` away
client-side, and a real client does not.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob
from server import app as app_module
from server.app import (
    FIT_PHOTO_MAX_BYTES,
    app,
    fit_photo_on_disk,
    fit_photo_target,
    sniff_image_type,
)

client = TestClient(app)

#: The smallest byte strings each accepted type is recognised by. Real files, cut
#: short: the server sniffs a prefix rather than decoding, and these are that prefix.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 "


@pytest.fixture(autouse=True)
def data_root(tmp_path, monkeypatch):
    """Point the server's data directory at a throwaway one.

    Every test in this file writes bytes the server chose to accept, and the real
    `data/outputs/` is a developer's working tree. Read at call time by
    `fit_photo_target`, `fit_photo_on_disk` and `resolve_job_artifact`, so patching the
    module attribute is enough.
    """
    root = tmp_path / "data"
    (root / "outputs").mkdir(parents=True)
    monkeypatch.setattr(app_module, "DATA_DIR", root)
    return root


@pytest.fixture
def small_cap(monkeypatch):
    """A 64-byte cap, so the limit can be crossed without moving 10 MiB.

    The figure under test is the *behaviour* at the boundary, not the constant; the
    constant itself is asserted once, in `test_the_cap_is_ten_mebibytes`.
    """
    monkeypatch.setattr(app_module, "FIT_PHOTO_MAX_BYTES", 64)
    return 64


def make_job(outcome: str = "awaiting_verdict", **kwargs) -> str:
    """Insert a job into the live telemetry database and return its id."""
    job_id = str(uuid.uuid4())
    db = TelemetryDB()
    db.init_schema()
    defaults = dict(
        job_id=job_id,
        prompt="a tray for 60 sleeved cards",
        printer_id="printer-1",
        printer_firmware="octoprint",
        slicer="cura",
        profile_name="pythonsrc/profiles/ender3.json",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        outcome=outcome,
    )
    defaults.update(kwargs)
    db.insert_job(PrintJob(**defaults))
    db.close()
    return job_id


def read_job(job_id: str) -> PrintJob:
    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    return job


def upload(job_id: str, body: bytes, content_type: str | None = "image/jpeg", **kwargs):
    """POST a photo the way the SPA does: the image as the body, typed by its header."""
    headers = {"Content-Type": content_type} if content_type else {}
    return client.post(f"/jobs/{job_id}/photo", content=body, headers=headers, **kwargs)


def stored_files(root: Path, job_id: str) -> list[str]:
    directory = root / "outputs" / job_id
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


# ── Authenticated by writing nothing ──────────────────────────────────────────


def test_an_anonymous_upload_is_refused():
    """No `@public`, so the middleware never lets the handler run."""
    anonymous = TestClient(app, headers={})
    job_id = make_job()
    assert anonymous.post(f"/jobs/{job_id}/photo", content=JPEG).status_code == 401


def test_an_anonymous_read_is_refused(data_root):
    """A photo of someone's living room is not public either."""
    anonymous = TestClient(app, headers={})
    job_id = make_job()
    assert upload(job_id, JPEG).status_code == 200
    assert anonymous.get(f"/jobs/{job_id}/photo").status_code == 401


# ── Capped ────────────────────────────────────────────────────────────────────


def test_the_cap_is_ten_mebibytes():
    """A 12 MP phone JPEG is 3–6 MB; 5 MiB would refuse photographs people take."""
    assert FIT_PHOTO_MAX_BYTES == 10 * 1024 * 1024


def test_a_declared_length_over_the_cap_is_refused_before_anything_is_written(
    small_cap, data_root,
):
    """413 off the header, so the body is never transferred."""
    job_id = make_job()
    response = upload(job_id, JPEG + b"\x00" * small_cap)
    assert response.status_code == 413
    assert stored_files(data_root, job_id) == []
    assert read_job(job_id).fit_photo_path is None


def test_a_body_of_exactly_the_cap_is_accepted(small_cap, data_root):
    """The boundary is inclusive: `> cap` is refused, `== cap` is a photo."""
    job_id = make_job()
    body = JPEG + b"\x00" * (small_cap - len(JPEG))
    assert len(body) == small_cap
    assert upload(job_id, body).status_code == 200
    assert stored_files(data_root, job_id) == ["fit_photo.jpg"]


def test_a_chunked_body_over_the_cap_is_cut_off_mid_stream(small_cap, data_root):
    """The check that actually bounds the disk.

    A chunked request declares no length at all, and uvicorn caps nothing, so the
    header check above would pass everything. Sending an iterator is what makes `httpx`
    use `Transfer-Encoding: chunked`.
    """
    job_id = make_job()

    def chunks():
        yield JPEG
        for _ in range(8):
            yield b"\x00" * 32

    response = upload(job_id, chunks())
    # The point of the test: no declared length, so only the streamed count can refuse it.
    assert "content-length" not in response.request.headers
    assert response.request.headers["transfer-encoding"] == "chunked"
    assert response.status_code == 413
    assert stored_files(data_root, job_id) == []
    assert read_job(job_id).fit_photo_path is None


# ── Type-checked ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("content_type", ["text/plain", "application/octet-stream", None])
def test_a_type_outside_the_allowlist_is_refused(content_type, data_root):
    """415, naming the three that would have worked."""
    job_id = make_job()
    response = upload(job_id, JPEG, content_type=content_type)
    assert response.status_code == 415
    assert "image/jpeg" in response.json()["detail"]
    assert stored_files(data_root, job_id) == []


def test_bytes_that_are_not_what_the_header_claims_are_refused(data_root):
    """The header is the caller's word; the magic bytes are the file's own."""
    job_id = make_job()
    response = upload(job_id, PNG, content_type="image/jpeg")
    assert response.status_code == 415
    assert stored_files(data_root, job_id) == []


def test_an_empty_body_is_refused(data_root):
    """400 rather than a zero-byte file the detail page would render as broken."""
    job_id = make_job()
    assert upload(job_id, b"").status_code == 400
    assert stored_files(data_root, job_id) == []


@pytest.mark.parametrize(
    "body,content_type,suffix",
    [
        (JPEG, "image/jpeg", ".jpg"),
        (PNG, "image/png", ".png"),
        (WEBP, "image/webp", ".webp"),
    ],
)
def test_each_accepted_type_lands_under_its_own_suffix(body, content_type, suffix, data_root):
    job_id = make_job()
    response = upload(job_id, body, content_type=content_type)
    assert response.status_code == 200
    assert response.json()["content_type"] == content_type
    assert stored_files(data_root, job_id) == [f"fit_photo{suffix}"]
    assert read_job(job_id).fit_photo_path.endswith(f"fit_photo{suffix}")


def test_a_charset_parameter_does_not_defeat_the_allowlist(data_root):
    """`image/jpeg; charset=binary` is a type this route accepts, spelled long."""
    job_id = make_job()
    response = upload(job_id, JPEG, content_type="image/jpeg; charset=binary")
    assert response.status_code == 200


def test_sniff_reads_the_prefix_and_nothing_else():
    assert sniff_image_type(JPEG) == "image/jpeg"
    assert sniff_image_type(PNG) == "image/png"
    assert sniff_image_type(WEBP) == "image/webp"
    assert sniff_image_type(b"#!/bin/sh\nrm -rf /") is None
    assert sniff_image_type(b"") is None
    # RIFF without WEBP is a WAV, which the outputs tree has no business holding.
    assert sniff_image_type(b"RIFF\x24\x00\x00\x00WAVEfmt ") is None


# ── Contained ─────────────────────────────────────────────────────────────────


def test_a_traversing_job_id_never_reaches_a_path_join(data_root):
    """`/jobs/%2e%2e/photo` is a 404 from the row lookup, which happens first."""
    response = client.post("/jobs/%2e%2e/photo", content=JPEG, headers={"Content-Type": "image/jpeg"})
    assert response.status_code == 404
    assert sorted(p.name for p in data_root.iterdir()) == ["outputs"]
    assert list((data_root / "outputs").iterdir()) == []


@pytest.mark.parametrize("job_id", ["..", "../..", "/etc", "a\x00b"])
def test_the_target_join_refuses_anything_that_leaves_the_outputs_tree(job_id):
    """The three ways a join escapes: a dot segment, an absolute part, an unresolvable one."""
    assert fit_photo_target(job_id, ".jpg") is None


def test_the_target_is_the_jobs_own_directory(data_root):
    job_id = make_job()
    target = fit_photo_target(job_id, ".jpg")
    assert target == (data_root / "outputs" / job_id / "fit_photo.jpg").resolve()


def test_a_row_pointing_outside_the_outputs_tree_is_not_served(data_root, tmp_path):
    """A value in a database is data too, and data never authorizes a read."""
    outside = tmp_path / "secret.jpg"
    outside.write_bytes(JPEG)
    job_id = make_job(fit_photo_path="../secret.jpg")
    assert fit_photo_on_disk(read_job(job_id)) is None
    assert client.get(f"/jobs/{job_id}/photo").status_code == 404


def test_the_stored_path_is_repo_relative(data_root):
    """`data/outputs/{id}/fit_photo.jpg` — the same spelling natively and in the image."""
    job_id = make_job()
    body = upload(job_id, JPEG).json()
    assert body["fit_photo_path"] == f"data/outputs/{job_id}/fit_photo.jpg"


# ── The record ────────────────────────────────────────────────────────────────


def test_an_unknown_job_is_a_404(data_root):
    assert upload(str(uuid.uuid4()), JPEG).status_code == 404


def test_the_row_records_the_photo_and_the_response_reports_it(data_root):
    job_id = make_job()
    body = upload(job_id, JPEG).json()
    assert body["job_id"] == job_id
    assert body["bytes"] == len(JPEG)
    assert read_job(job_id).fit_photo_path == body["fit_photo_path"]


def test_a_photo_is_evidence_and_not_a_verdict(data_root):
    """Someone can photograph a part that did not fit and then say nothing.

    If this wrote `outcome`, the job would leave the pending queue unanswered — and
    `update_job_outcome_verdict`'s machine-never-overwrites-human rule would then be
    the thing refusing the verdict they gave a minute later.
    """
    job_id = make_job()
    assert upload(job_id, JPEG).status_code == 200
    job = read_job(job_id)
    assert job.outcome == "awaiting_verdict"
    assert job.outcome_source is None
    assert job.outcome_reported_at is None


def test_a_re_upload_replaces_the_photo_and_leaves_no_orphan(data_root):
    """One part, one picture — including when the type changes."""
    job_id = make_job()
    assert upload(job_id, JPEG).status_code == 200
    assert upload(job_id, PNG, content_type="image/png").status_code == 200
    assert stored_files(data_root, job_id) == ["fit_photo.png"]
    assert read_job(job_id).fit_photo_path.endswith("fit_photo.png")


def test_the_job_endpoint_reports_that_a_photo_exists(data_root):
    job_id = make_job()
    assert client.get(f"/jobs/{job_id}").json()["has_fit_photo"] is False
    upload(job_id, JPEG)
    assert client.get(f"/jobs/{job_id}").json()["has_fit_photo"] is True


def test_provenance_carries_the_path(data_root):
    job_id = make_job()
    upload(job_id, JPEG)
    outcome = client.get(f"/jobs/{job_id}/provenance").json()["outcome"]
    assert outcome["fit_photo_path"] == f"data/outputs/{job_id}/fit_photo.jpg"


# ── Serving it back ───────────────────────────────────────────────────────────


def test_a_job_with_no_photo_answers_404(data_root):
    job_id = make_job()
    assert client.get(f"/jobs/{job_id}/photo").status_code == 404


def test_an_unknown_job_answers_404_on_read(data_root):
    assert client.get(f"/jobs/{uuid.uuid4()}/photo").status_code == 404


@pytest.mark.parametrize(
    "body,content_type",
    [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")],
)
def test_the_photo_comes_back_with_the_type_it_went_in_as(body, content_type, data_root):
    job_id = make_job()
    upload(job_id, body, content_type=content_type)
    response = client.get(f"/jobs/{job_id}/photo")
    assert response.status_code == 200
    assert response.content == body
    assert response.headers["content-type"] == content_type
    # Inline: the detail page shows it, it is not a download.
    assert response.headers["content-disposition"].startswith("inline")


def test_a_deleted_file_answers_404_rather_than_500(data_root):
    """The row outlives the bind mount it points into."""
    job_id = make_job()
    upload(job_id, JPEG)
    (data_root / "outputs" / job_id / "fit_photo.jpg").unlink()
    assert client.get(f"/jobs/{job_id}/photo").status_code == 404
