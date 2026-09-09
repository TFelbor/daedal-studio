"""Phase 3 writes three files, and the third one is a deliverable (PRD F9).

`Engineer.process` used to write an `.obj` and an `.stl`. The `.stl` is CuraEngine's
input; the `.3mf` added here is the **handoff** copy, because the interim route to a
printer this project cannot dispatch to is "download the file and open it in Bambu
Studio". What makes it worth a third file rather than a rename is the unit: an STL is a
bag of triangles with no unit, so every consumer guesses millimetres, while 3MF records
`unit="millimeter"` in its model XML. A part whose dimensions *are* the deliverable —
anything compiled from a spec — must not have its size re-guessed by the program that
prints it.

So the tests below measure rather than trust: the 3MF is reloaded and compared against
the STL written from the same mesh, and a spec run's 3MF is put through the archetype's
own `measure()` at the same ±0,05 mm bound the STL is held to.
"""
import itertools

import pytest
import trimesh

from pythonsrc.engineer import EXPORT_SUFFIXES, Engineer
from pythonsrc.organizer.archetypes import compile_spec, deck_box, verify_spec_mesh
from pythonsrc.organizer.compiler import export_stl
from pythonsrc.organizer.spec import CardStack, Compartment, Lid, OrganizerSpec, Process


def _sphere(radius_mm: float = 20.0) -> trimesh.Trimesh:
    """A watertight mesh with enough faces that a vertex weld would show."""
    mesh = trimesh.creation.icosphere(subdivisions=2)
    mesh.apply_scale(radius_mm)
    return mesh


def _raw_mesh(tmp_path):
    path = tmp_path / "raw_mesh.obj"
    _sphere().export(str(path))
    return path


# ── every Phase 3 run writes all three ────────────────────────────────────────

def test_process_writes_obj_stl_and_3mf(tmp_path):
    out = Engineer().process(
        input_path=_raw_mesh(tmp_path), output_path=tmp_path / "engineered_mesh.obj",
        target_mm=50.0,
    )
    assert out.exists()
    for suffix in EXPORT_SUFFIXES:
        sibling = out.with_suffix(suffix)
        assert sibling.exists(), f"Phase 3 did not write {sibling.name}"
        assert sibling.stat().st_size > 0


def test_the_report_names_the_files_the_job_actually_has(tmp_path):
    eng = Engineer()
    eng.process(
        input_path=_raw_mesh(tmp_path), output_path=tmp_path / "engineered_mesh.obj",
        target_mm=50.0,
    )
    assert eng.last_report["exports"] == [
        "engineered_mesh.obj", "engineered_mesh.stl", "engineered_mesh.3mf",
    ]
    # No key at all when every format landed: an empty dict and a missing sibling
    # would otherwise read the same.
    assert "export_errors" not in eng.last_report


def test_the_3mf_is_written_for_a_spec_run_too(tmp_path):
    """The assert path is a different branch of `process`, and it is the path that
    matters most here — a compiled mesh is the one whose dimensions are final."""
    spec = _deck()
    result = compile_spec(spec)
    export_stl(result.mesh, tmp_path / "compiled_mesh.stl")
    out = Engineer().process(
        input_path=tmp_path / "compiled_mesh.stl",
        output_path=tmp_path / "engineered_mesh.obj",
        target_mm=None, repair_mode="assert",
    )
    assert out.with_suffix(".3mf").exists()


# ── the 3MF carries the same geometry as the STL ──────────────────────────────

def test_the_3mf_round_trips_with_the_stl_s_vertex_count_and_bounding_box(tmp_path):
    out = Engineer().process(
        input_path=_raw_mesh(tmp_path), output_path=tmp_path / "engineered_mesh.obj",
        target_mm=50.0,
    )
    stl = trimesh.load(str(out.with_suffix(".stl")), force="mesh")
    threemf = trimesh.load(str(out.with_suffix(".3mf")), force="mesh")

    assert len(threemf.vertices) == len(stl.vertices)
    assert len(threemf.faces) == len(stl.faces)
    assert threemf.bounds == pytest.approx(stl.bounds, abs=1e-4)
    assert threemf.is_watertight == stl.is_watertight


def test_the_3mf_declares_millimetres(tmp_path):
    """The reason the format is here at all. An STL cannot say this."""
    out = Engineer().process(
        input_path=_raw_mesh(tmp_path), output_path=tmp_path / "engineered_mesh.obj",
        target_mm=50.0,
    )
    reloaded = trimesh.load(str(out.with_suffix(".3mf")), force="mesh")
    assert reloaded.units == "millimeter"


def test_the_3mf_is_single_colour_and_carries_no_material(tmp_path):
    """Nothing upstream of Phase 3 carries a material — `_strip_appearance` discards
    appearance for every sculptor backend — so a colour written here would be one this
    pipeline invented."""
    out = Engineer().process(
        input_path=_raw_mesh(tmp_path), output_path=tmp_path / "engineered_mesh.obj",
        target_mm=50.0,
    )
    reloaded = trimesh.load(str(out.with_suffix(".3mf")), force="mesh")
    visual = getattr(reloaded, "visual", None)
    assert visual is None or visual.kind is None, (
        f"the 3MF carries per-vertex or per-face appearance: {visual}"
    )


# ── a format that cannot be written is recorded, not raised ───────────────────

def test_a_failed_sibling_export_does_not_take_the_phase_with_it(tmp_path, monkeypatch):
    """`lxml` is a declared dependency now, so this is the broken-install case.

    It is recorded rather than raised for the same reason a scorer crash is: the STL is
    on disk and sliceable, and refusing to print a part because a handoff copy could not
    be written trades a working print for a missing convenience. What must not happen is
    silence — the reason lands in `last_report`.
    """
    real_export = trimesh.Trimesh.export

    def refuse_3mf(self, file_obj=None, *args, **kwargs):
        if str(file_obj).endswith(".3mf"):
            raise ImportError("No module named 'lxml'")
        return real_export(self, file_obj, *args, **kwargs)

    monkeypatch.setattr(trimesh.Trimesh, "export", refuse_3mf)

    eng = Engineer()
    out = eng.process(
        input_path=_raw_mesh(tmp_path), output_path=tmp_path / "engineered_mesh.obj",
        target_mm=50.0,
    )
    assert out.with_suffix(".stl").exists()
    assert not out.with_suffix(".3mf").exists()
    assert eng.last_report["exports"] == ["engineered_mesh.obj", "engineered_mesh.stl"]
    assert "lxml" in eng.last_report["export_errors"][".3mf"]


def test_a_failed_primary_export_is_raised(tmp_path, monkeypatch):
    """Everything downstream is keyed off the path the caller named."""
    def refuse(self, file_obj=None, *args, **kwargs):
        raise ValueError("no exporter")

    monkeypatch.setattr(trimesh.Trimesh, "export", refuse)
    with pytest.raises(ValueError):
        Engineer().process(
            input_path=_raw_mesh(tmp_path), output_path=tmp_path / "engineered_mesh.obj",
            target_mm=50.0,
        )


# ── a spec run's 3MF measures the same as its STL ─────────────────────────────

def _deck(count=100, sleeving="double", wall=2.8, clearance=0.2, lid_height=15.0, floor=2.0):
    return OrganizerSpec(
        archetype="deck_box",
        compartments=(Compartment(CardStack(count=count, sleeving=sleeving)),),
        lid=Lid(height_mm=lid_height, clearance_mm=clearance),
        process=Process(wall_mm=wall, floor_mm=floor),
    )


SPEC_CORNERS = list(itertools.product(
    (15, 100, 160), ("none", "double"), ((2.6, 0.1, 8.0), (4.0, 0.35, 30.0)),
))


@pytest.mark.parametrize("count,sleeving,process", SPEC_CORNERS)
def test_a_spec_runs_3mf_measures_the_same_as_its_stl(tmp_path, count, sleeving, process):
    """PRD N1's ±0,05 mm claim, asserted on the 3MF rather than inherited from the STL.

    Both files are read back off disk and put through the archetype's own `measure()`,
    so the numbers are planes in the exported geometry — not the compiler's arithmetic,
    and not the STL's result reused.
    """
    wall, clearance, lid_height = process
    spec = _deck(count, sleeving, wall, clearance, lid_height)
    result = compile_spec(spec)
    export_stl(result.mesh, tmp_path / "compiled_mesh.stl")

    out = Engineer().process(
        input_path=tmp_path / "compiled_mesh.stl",
        output_path=tmp_path / "engineered_mesh.obj",
        target_mm=None, repair_mode="assert",
    )

    stl_report = verify_spec_mesh(
        spec, result.features, trimesh.load(str(out.with_suffix(".stl")), force="mesh"),
    )
    threemf_report = verify_spec_mesh(
        spec, result.features, trimesh.load(str(out.with_suffix(".3mf")), force="mesh"),
    )

    assert threemf_report.within_tolerance, threemf_report.problems()
    assert set(threemf_report.features) == set(deck_box.MEASURED_FEATURES)
    for feature, (designed, measured, _) in threemf_report.features.items():
        stl_measured = stl_report.features[feature][1]
        assert measured == pytest.approx(stl_measured, abs=0.05), (
            f"{feature}: 3MF {measured} vs STL {stl_measured} (designed {designed})"
        )
