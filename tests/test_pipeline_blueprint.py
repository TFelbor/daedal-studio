"""Guards on the fabricated stand-in blueprint.

When Phase 1 is skipped and no blueprint exists, the pipeline writes a flat
rectangle so Phases 3-5 can still be exercised. That image is written to the
*shared* blueprint path and then persists, so a later run finds a file that
exists and — before this guard — could not tell it from a real render. That is how
a flat blue rectangle came to be sent repeatedly to a backend billed per
generation, and how `data/outputs/` filled with identical blue snapshots.

The detection is by pixel content, so it still recognises a placeholder written by
an earlier run, or by a different Pillow version.
"""

from pathlib import Path

from PIL import Image

from pythonsrc.pipeline import (
    _blueprint_is_placeholder,
    _write_placeholder_blueprint,
)


def test_a_freshly_written_placeholder_is_recognised(tmp_path: Path):
    path = tmp_path / "blueprint.png"
    _write_placeholder_blueprint(path)
    assert _blueprint_is_placeholder(path) is True


def test_a_placeholder_left_by_an_earlier_run_is_still_recognised(tmp_path: Path):
    """The whole point: existence on disk is not evidence of a real blueprint."""
    path = tmp_path / "blueprint.png"
    _write_placeholder_blueprint(path)
    reopened = tmp_path / "copied.png"
    reopened.write_bytes(path.read_bytes())
    assert _blueprint_is_placeholder(reopened) is True


def test_a_real_blueprint_is_not_mistaken_for_the_placeholder(tmp_path: Path):
    path = tmp_path / "blueprint.png"
    image = Image.new("RGB", (512, 512), color=(73, 109, 137))
    # One differing pixel is enough to make it not-flat, which is the property
    # being tested — a real render is never a single colour.
    image.putpixel((0, 0), (255, 255, 255))
    image.save(path)
    assert _blueprint_is_placeholder(path) is False


def test_a_flat_image_of_another_size_is_not_the_placeholder(tmp_path: Path):
    path = tmp_path / "blueprint.png"
    Image.new("RGB", (256, 256), color=(73, 109, 137)).save(path)
    assert _blueprint_is_placeholder(path) is False


def test_a_flat_image_of_another_colour_is_not_the_placeholder(tmp_path: Path):
    path = tmp_path / "blueprint.png"
    Image.new("RGB", (512, 512), color=(10, 10, 10)).save(path)
    assert _blueprint_is_placeholder(path) is False


def test_a_missing_or_unreadable_file_is_not_a_placeholder(tmp_path: Path):
    assert _blueprint_is_placeholder(tmp_path / "nope.png") is False
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    assert _blueprint_is_placeholder(broken) is False
