"""Faz 5: FeedbackStore + multi-project global hint testleri."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from metraj.core.learning.feedback_store import (
    FeedbackStore,
    GlobalHint,
    ManualClassification,
    extract_global_hints,
    global_hints_to_signal_hints_yaml,
    load_stores_from_dir,
)


def test_empty_store_load_returns_empty(tmp_path):
    """Dosya yoksa bos store doner."""
    s = FeedbackStore.load(tmp_path / "nonexistent.json")
    assert s.layer_kind_overrides == {}
    assert s.comparison_alias_overrides == {}
    assert s.excluded_layers == []
    assert s.manual_classifications == []
    assert s.source_path == tmp_path / "nonexistent.json"


def test_save_then_load_round_trip(tmp_path):
    """JSON round-trip: save -> load -> ayni veri."""
    s = FeedbackStore(project_name="Proje Demo")
    s.set_layer_kind("K-30x60", "column")
    s.set_layer_kind("P-A", "shear_wall")
    s.set_alias("BLOK_A", "0,00 BLOK_A")
    s.exclude_layer("IZ_KOLON_PRY")
    s.add_manual_classification(ManualClassification(
        layer="KOLON NA", centroid=(120.5, 5.0),
        kind="shear_wall", reason="aspect=19",
    ))
    s.notes.append("Faz 1 conflict listesinden cikarildi.")
    out = tmp_path / "feedback.json"
    s.save(out)

    loaded = FeedbackStore.load(out)
    assert loaded.project_name == "Proje Demo"
    assert loaded.layer_kind_overrides == {"K-30x60": "column", "P-A": "shear_wall"}
    assert loaded.comparison_alias_overrides == {"BLOK_A": "0,00 BLOK_A"}
    assert loaded.excluded_layers == ["IZ_KOLON_PRY"]
    assert len(loaded.manual_classifications) == 1
    mc = loaded.manual_classifications[0]
    assert mc.layer == "KOLON NA"
    assert mc.centroid == (120.5, 5.0)
    assert mc.kind == "shear_wall"
    assert loaded.notes == ["Faz 1 conflict listesinden cikarildi."]
    assert loaded.source_path == out


def test_schema_version_in_saved_json(tmp_path):
    out = tmp_path / "fb.json"
    s = FeedbackStore(project_name="X")
    s.save(out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1


def test_apply_to_config_dicts_merges_in_place(tmp_path):
    """FeedbackStore overrideleri config dict'lerine merge eder; cakismada feedback kazanir."""
    s = FeedbackStore(
        project_name="P",
        layer_kind_overrides={"K1": "column", "P-A": "shear_wall"},
        comparison_alias_overrides={"X": "Y"},
        excluded_layers=["IZ_KOLON_PRY"],
    )
    layer_kind: dict = {"K1": "beam"}  # cakisma: feedback "column" kazanir
    aliases: dict = {"old": "new"}
    excluded: list = []
    s.apply_to_config_dicts(layer_kind, aliases, excluded)
    assert layer_kind["K1"] == "column"  # feedback kazandi
    assert layer_kind["P-A"] == "shear_wall"
    assert aliases["X"] == "Y"
    assert "IZ_KOLON_PRY" in excluded


# ---------------------------------------------------------------------------
# Multi-project global hints
# ---------------------------------------------------------------------------

def _make_store(project: str, **overrides) -> FeedbackStore:
    return FeedbackStore(
        project_name=project,
        layer_kind_overrides=overrides.get("layer_kinds", {}),
        comparison_alias_overrides=overrides.get("aliases", {}),
    )


def test_global_hints_require_min_two_projects():
    """Tek-projedeki override global olmaz (overfit riski)."""
    stores = [
        _make_store("P1", layer_kinds={"K-A": "column"}),
        _make_store("P2", layer_kinds={"K-B": "column"}),  # farkli layer
    ]
    hints = extract_global_hints(stores, min_project_count=2)
    assert hints == []


def test_global_hints_extract_consistent_layer_kind():
    stores = [
        _make_store("P1", layer_kinds={"K-30x60": "column"}),
        _make_store("P2", layer_kinds={"K-30x60": "column"}),
        _make_store("P3", layer_kinds={"K-30x60": "column", "P-A": "shear_wall"}),
    ]
    hints = extract_global_hints(stores, min_project_count=2)
    # K-30x60 -> column: 3 projede; P-A -> shear_wall: 1 (atlanir)
    assert len(hints) == 1
    h = hints[0]
    assert h.kind == "layer_kind"
    assert h.source == "K-30x60"
    assert h.target == "column"
    assert h.project_count == 3
    assert sorted(h.projects) == ["P1", "P2", "P3"]


def test_global_hints_extract_consistent_alias():
    stores = [
        _make_store("P1", aliases={"BLOK_A": "0,00 BLOK_A"}),
        _make_store("P2", aliases={"BLOK_A": "0,00 BLOK_A"}),
    ]
    hints = extract_global_hints(stores)
    assert len(hints) == 1
    assert hints[0].kind == "comparison_alias"
    assert hints[0].source == "BLOK_A"


def test_global_hints_to_signal_hints_yaml_format():
    hints = [
        GlobalHint(kind="layer_kind", source="K-30x60", target="column",
                   project_count=3, projects=["P1", "P2", "P3"]),
        GlobalHint(kind="layer_kind", source="K-30x90", target="column",
                   project_count=2, projects=["P1", "P2"]),
        GlobalHint(kind="layer_kind", source="P-A", target="shear_wall",
                   project_count=2, projects=["P1", "P2"]),
        GlobalHint(kind="comparison_alias", source="X", target="Y",
                   project_count=2, projects=["P1", "P2"]),
    ]
    out = global_hints_to_signal_hints_yaml(hints)
    assert "name_aliases" in out
    assert sorted(out["name_aliases"]["column"]) == ["K-30x60", "K-30x90"]
    assert out["name_aliases"]["shear_wall"] == ["P-A"]
    assert out["comparison_label_aliases"] == {"X": "Y"}


def test_load_stores_from_dir(tmp_path):
    s1 = FeedbackStore(project_name="P1",
                        layer_kind_overrides={"K-A": "column"})
    s2 = FeedbackStore(project_name="P2",
                        layer_kind_overrides={"K-A": "column"})
    s1.save(tmp_path / "p1.json")
    s2.save(tmp_path / "p2.json")
    loaded = load_stores_from_dir(tmp_path)
    assert len(loaded) == 2
    assert {s.project_name for s in loaded} == {"P1", "P2"}


def test_load_stores_empty_directory(tmp_path):
    assert load_stores_from_dir(tmp_path) == []
    assert load_stores_from_dir(tmp_path / "nonexistent") == []


# ---------------------------------------------------------------------------
# Pipeline integration smoke (StructuralConfig.feedback_store_path)
# ---------------------------------------------------------------------------

def test_structural_config_feedback_path_resolves_relative(tmp_path):
    """YAML yanindaki goreli feedback path absolute'a cevrilir."""
    from metraj.core.structural.config import StructuralConfig

    fb_path = tmp_path / "fb.json"
    FeedbackStore(project_name="X").save(fb_path)

    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "project_name: X\n"
        "feedback_store_path: ./fb.json\n",
        encoding="utf-8",
    )
    cfg = StructuralConfig.from_file(yaml_path)
    assert Path(cfg.feedback_store_path).resolve() == fb_path.resolve()
