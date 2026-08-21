"""v0.6.1 Plan 4 Phase 10 — the approved Chatterbox voices in the unified queue.

The maintainer listened to all four Phase 9 evaluation outputs on 2026-08-15 and
approved all four, with the GUI labels written as ``Chatterbox - Female 1`` and
so on — an ordinary ASCII hyphen, not the em dash the drop's §5.7 had proposed.
This phase registers exactly those four rows and makes them usable through the
**one** PDF/TXT queue Phases 6–7 established.

What these tests are about
--------------------------
* **Registration is additive and exact.** The twelve existing rows keep every
  field they had, in the order they had it, and four approved rows are appended.
  The four display labels are asserted as literal strings, and the em-dash
  variants are asserted *absent*.
* **Registered is not the same as available.** The four reference recordings are
  local, maintainer-supplied assets that exist on one machine. A voice whose
  recording is missing, altered, or whose engine is not installed stays in the
  registry and is reported as setup-required — it is never silently swapped for
  another voice, another engine, or anything fetched from the internet.
* **One backend decision, not two booleans.** ``VoiceEntry.backend`` drives a
  three-way Edge / Kokoro / Chatterbox dispatch at the synthesis seam. Everything
  else — the imported queue, the frozen run, output planning, the controller, the
  publisher, retry lineage — is the same single path all three engines share.
* **Placement is Plan 2's, not the engine's.** Directly added files land flat,
  folder-derived files mirror their root, several roots each get a container, and
  a retry lands exactly where its original run planned.

Determinism and safety
----------------------
**No synthesis ever runs.** ``tts.chatterbox_synth`` is replaced by a stub module
at ``sys.modules``, so nothing loads Turbo weights, reads a maintainer recording,
touches the network or writes real audio. Every fixture is generated under
``tmp_path``; the protected uploads folder is never read and never written.
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared.cancellation import ConversionCancelled  # noqa: E402
from shared.job_control import JobState  # noqa: E402
from tts import epub2tts_gui as panel_module  # noqa: E402
from tts import voice_registry as vr  # noqa: E402

# The Phase 6/7 fixtures own "a TtsPanel built safely" and the engine stubs.
from test_tts_importing import (  # noqa: E402,F401
    PANEL_SOURCE,
    _Stubs,
    make_panel,
    output_base,
    panel_tree,
    sources,
    stubs,
    tk_root,
)
from test_tts_jobs import (  # noqa: E402,F401
    accept,
    direct_panel,
    finish,
    folder_panel,
    mixed_panel,
    relative,
    run_attempt,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TTS_DIR = REPO_ROOT / "scripts" / "Universal" / "tts"
SHARED_DIR = REPO_ROOT / "scripts" / "Universal" / "shared"


# --------------------------------------------------------------------------- #
# The approved decision, written as literals rather than read from the module
# --------------------------------------------------------------------------- #

#: Exactly what the maintainer approved, in the approved order.
APPROVED = (
    ("chatterbox-female-1", "Chatterbox - Female 1"),
    ("chatterbox-female-2", "Chatterbox - Female 2"),
    ("chatterbox-male-1", "Chatterbox - Male 1"),
    ("chatterbox-male-2", "Chatterbox - Male 2"),
)

#: The labels §5.7 originally proposed. The maintainer replaced them; none of
#: these may be a registry display label.
SUPERSEDED_LABELS = (
    "Chatterbox — Female 1",
    "Chatterbox — Female 2",
    "Chatterbox — Male 1",
    "Chatterbox — Male 2",
)

FEMALE_1 = "Chatterbox - Female 1"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class ChatterboxStub:
    """Stands in for ``tts.chatterbox_synth`` at ``sys.modules``.

    Records every synthesis request and answers the availability seam from a
    dictionary the test controls, so "this voice's recording is missing" is an
    injected condition rather than a real file the suite would have to move.
    """

    def __init__(self, *, available=None, reason="", failing: str = ""):
        self.calls: list[dict] = []
        self.status_requests: list[str] = []
        #: voice_id -> (ok, reason). Missing key means available.
        self.available: dict[str, tuple[bool, str]] = dict(available or {})
        self.default_reason = reason
        self.failing = failing
        #: When set, the engine behaves like a real one that observed a cancel at
        #: a chunk boundary: it calls this, leaves a partial file behind, and
        #: raises. Used to exercise the run's partial-output cleanup.
        self.cancel_at_chunk = None

    # -- the two seams the panel is allowed to use -------------------------- #

    def voice_availability(self, voice_id: str) -> tuple[bool, str]:
        self.status_requests.append(voice_id)
        return self.available.get(voice_id, (True, "ok"))

    def chatterbox_file_to_mp3(self, source_path, output_mp3_path, voice_id,
                               **kwargs):
        self.calls.append({"source": str(source_path),
                           "output": str(output_mp3_path),
                           "voice_id": voice_id, **kwargs})
        cancel_check = kwargs.get("cancel_check")
        if cancel_check is not None and cancel_check():
            raise ConversionCancelled("Conversion cancelled by user.")
        if self.cancel_at_chunk is not None:
            self.cancel_at_chunk()
            Path(output_mp3_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_mp3_path).write_bytes(b"a partly written file")
            raise ConversionCancelled("Conversion cancelled by user.")
        if self.failing and self.failing in Path(source_path).name:
            raise RuntimeError("the Chatterbox engine refused this book")
        Path(output_mp3_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_mp3_path).write_bytes(b"audio")

    # -- installation ------------------------------------------------------- #

    def install(self, monkeypatch):
        module = types.ModuleType("tts.chatterbox_synth")
        module.chatterbox_file_to_mp3 = self.chatterbox_file_to_mp3
        module.voice_availability = self.voice_availability
        module.ChatterboxUnavailable = RuntimeError
        monkeypatch.setitem(sys.modules, "tts.chatterbox_synth", module)
        return self

    def status(self, voice_id: str) -> tuple[bool, str]:
        """The panel seam, so a test can inject status without the module."""
        return self.voice_availability(voice_id)


@pytest.fixture()
def chatterbox(monkeypatch):
    return ChatterboxStub().install(monkeypatch)


def pick(label: str = FEMALE_1):
    return vr.get_voice(label)


def select(panel, label: str = FEMALE_1) -> None:
    panel.selected_voice_label.set(label)
    panel._on_voice_selected()


def unparse_panel() -> str:
    return ast.unparse(panel_tree())


def panel_code() -> str:
    """The panel's *executable* source, with every docstring removed.

    Prose has to be able to name the things it retired — "the boolean this
    replaced", "the batch mode this removed" — without a structural guard reading
    that as the thing itself coming back. These assertions are about code.
    """
    tree = panel_tree()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(ast.fix_missing_locations(tree))


def module_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# A. The registry — exactly four appended rows
# --------------------------------------------------------------------------- #


def test_the_registry_now_holds_sixteen_voices():
    assert len(vr.VOICES) == 16


def test_the_twelve_existing_rows_keep_their_engine_values_and_order():
    """Imported from the Phase 8 gate, so there is one description of the twelve.

    Phase 13A.3 renamed the display labels by maintainer override; that table is
    the single place the new wording is written down, and every other column is
    still compared value for value.
    """
    from test_chatterbox_boundaries import EXPECTED_VOICES

    assert len(EXPECTED_VOICES) == 12
    for index, expected in enumerate(EXPECTED_VOICES):
        backend, voice_id, display, group, preset = expected
        entry = vr.VOICES[index]
        assert entry.backend == backend
        assert entry.voice_id == voice_id
        assert entry.display_label == display
        assert entry.group_label == group
        assert entry.timing_preset == preset


def test_the_four_approved_rows_are_appended_in_the_approved_order():
    tail = vr.VOICES[12:]
    assert [(e.voice_id, e.display_label) for e in tail] == list(APPROVED)


def test_every_appended_row_declares_the_chatterbox_backend():
    for entry in vr.VOICES[12:]:
        assert entry.backend == "chatterbox"


@pytest.mark.parametrize("voice_id,label", APPROVED)
def test_each_approved_label_is_the_exact_maintainer_string(voice_id, label):
    entry = vr.get_voice(label)
    assert entry is not None, f"{label!r} is not registered"
    assert entry.voice_id == voice_id
    assert entry.display_label == label
    assert " - " in entry.display_label, "an ASCII hyphen surrounded by spaces"
    assert "—" not in entry.display_label, "the em-dash form was superseded"


@pytest.mark.parametrize("superseded", SUPERSEDED_LABELS)
def test_the_superseded_em_dash_labels_are_not_registered(superseded):
    assert vr.get_voice(superseded) is None
    assert superseded not in vr.display_labels()


def test_the_four_share_one_group_label_and_it_names_the_engine_truthfully():
    groups = {entry.group_label for entry in vr.VOICES[12:]}
    assert len(groups) == 1, "one cosmetic group, not four"
    group = groups.pop()
    assert "Chatterbox" in group
    assert group not in {entry.display_label for entry in vr.VOICES}


def test_no_voice_was_tuned_differently_from_another():
    """Phase 9 approved all four under one parameter set; §6 forbids per-voice tuning."""
    reference = vr._chatterbox_preset()
    for entry in vr.VOICES[12:]:
        assert entry.timing_preset == reference


def test_the_chatterbox_rows_carry_the_kokoro_shaped_timing_fields():
    for entry in vr.VOICES[12:]:
        assert set(entry.timing_preset) == set(vr._kokoro_preset())
        assert entry.timing_preset["trim_edge_chunks"] is False
        assert entry.timing_preset["rate"] == "+0%"
        assert entry.timing_preset["kokoro_speed"] == "1.0"


def test_the_default_voice_is_still_steffan():
    assert vr.DEFAULT_VOICE_LABEL == "Edge Male - Steffan (en-US)"
    assert vr.DEFAULT_VOICE_LABEL == vr.VOICES[0].display_label


def test_the_dropdown_offers_the_twelve_then_the_four():
    labels = vr.display_labels()
    assert len(labels) == 16 == len(set(labels))
    assert labels[12:] == [label for _voice_id, label in APPROVED]


def test_the_registry_source_declares_exactly_sixteen_rows():
    """An AST count, so a commented-out or duplicated row cannot creep in."""
    tree = ast.parse(module_source(TTS_DIR / "voice_registry.py"))
    rows = [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "VoiceEntry"]
    assert len(rows) == 16
    backends = [next(k.value.value for k in row.keywords if k.arg == "backend")
                for row in rows]
    assert backends[:12] == ["edge"] * 7 + ["kokoro"] * 5
    assert backends[12:] == ["chatterbox"] * 4


def test_the_registry_imports_no_engine_module():
    """Registration is data. It must not drag torch in at import time."""
    tree = ast.parse(module_source(TTS_DIR / "voice_registry.py"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import)
                for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree)
                 if isinstance(n, ast.ImportFrom)}
    assert not any(name.startswith("tts.") or name in {"torch", "chatterbox"}
                   for name in imported), imported


# --------------------------------------------------------------------------- #
# B. Voice selection, engine label and the controls each backend shows
# --------------------------------------------------------------------------- #


def test_selecting_a_chatterbox_voice_applies_its_timing_preset(
    make_panel, chatterbox
):
    panel = make_panel(chatterbox_status=chatterbox.status)
    select(panel)
    entry = pick()
    assert panel.voice_var.get() == entry.voice_id
    assert panel.sentence_ms_var.get() == entry.timing_preset["sentencepause"]
    assert panel.paragraph_ms_var.get() == entry.timing_preset["paragraphpause"]
    assert panel.title_ms_var.get() == entry.timing_preset["title_ms"]
    assert panel.chapter_ms_var.get() == entry.timing_preset["chapter_ms"]
    assert panel.end_pause_var.get() == entry.timing_preset["end_pause"]
    assert panel.trim_edge_chunks_var.get() is False


def test_the_engine_label_names_chatterbox_and_neither_other_engine(
    make_panel, chatterbox
):
    panel = make_panel(chatterbox_status=chatterbox.status)
    select(panel)
    shown = panel.backend_label_var.get()
    assert panel_module.CHATTERBOX_ENGINE_LABEL in shown
    assert "Kokoro" not in shown
    assert "Edge" not in shown
    assert pick().voice_id in shown


def test_the_engine_wording_never_leaks_into_the_approved_voice_labels():
    """Turbo / CPU / local / cloned / 0.1.7 belong to the status text, not the name."""
    for _voice_id, label in APPROVED:
        lowered = label.lower()
        for forbidden in ("turbo", "cpu", "cloned", "local", "0.1.7"):
            assert forbidden not in lowered, label


def test_the_kokoro_speed_control_is_hidden_for_a_chatterbox_voice(
    make_panel, chatterbox
):
    panel = make_panel(chatterbox_status=chatterbox.status)
    kokoro = next(v for v in vr.VOICES if v.backend == "kokoro")

    select(panel, kokoro.display_label)
    assert panel.kokoro_speed_frm.winfo_manager(), "shown for Kokoro"

    select(panel)
    assert not panel.kokoro_speed_frm.winfo_manager(), "hidden for Chatterbox"

    select(panel, vr.DEFAULT_VOICE_LABEL)
    assert not panel.kokoro_speed_frm.winfo_manager(), "hidden for Edge"


def test_the_kokoro_notice_is_not_shown_for_a_chatterbox_voice(
    make_panel, chatterbox
):
    panel = make_panel(chatterbox_status=chatterbox.status)
    kokoro = next(v for v in vr.VOICES if v.backend == "kokoro")
    select(panel, kokoro.display_label)
    assert panel.kokoro_notice_lbl.winfo_manager()
    select(panel)
    assert not panel.kokoro_notice_lbl.winfo_manager()


def test_selecting_an_available_chatterbox_voice_shows_no_setup_warning(
    make_panel, chatterbox
):
    panel = make_panel(chatterbox_status=chatterbox.status)
    select(panel)
    assert panel._voice_available is True
    assert panel.voice_status_var.get() == ""
    assert not panel.voice_status_lbl.winfo_manager()


def test_building_the_panel_asks_chatterbox_nothing(make_panel, chatterbox):
    """The default voice is Edge; a machine with no engine must build normally."""
    make_panel(chatterbox_status=chatterbox.status)
    assert chatterbox.status_requests == []


def test_edge_and_kokoro_selection_never_consults_the_chatterbox_engine(
    make_panel, chatterbox
):
    panel = make_panel(chatterbox_status=chatterbox.status)
    kokoro = next(v for v in vr.VOICES if v.backend == "kokoro")
    select(panel, kokoro.display_label)
    select(panel, vr.DEFAULT_VOICE_LABEL)
    assert chatterbox.status_requests == []


# --------------------------------------------------------------------------- #
# C. Availability — registered is not the same as available
# --------------------------------------------------------------------------- #


def unavailable(voice_id: str, reason: str) -> ChatterboxStub:
    return ChatterboxStub(available={voice_id: (False, reason)})


def test_an_unavailable_voice_is_shown_as_setup_required(make_panel):
    stub = unavailable("chatterbox-female-1",
                       "Setup required for Chatterbox - Female 1: the reference "
                       "recording 'Female-1.mp3' is not present.")
    panel = make_panel(chatterbox_status=stub.status)
    select(panel)

    assert panel._voice_available is False
    assert "Setup required" in panel.voice_status_var.get()
    assert panel.voice_status_lbl.winfo_manager(), "the reason is on screen"


def test_starting_a_run_with_an_unavailable_voice_is_refused_before_capture(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    from tkinter import messagebox

    stub = unavailable("chatterbox-female-1", "the reference recording is missing")
    stub.install(monkeypatch)
    warned: list = []
    monkeypatch.setattr(messagebox, "showwarning",
                        lambda *a, **k: warned.append(a))
    monkeypatch.setattr(
        panel_module.output_paths, "reserve_run_directory",
        lambda *a, **k: pytest.fail("a refused run reserved a directory"))

    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt",
                                  chatterbox_status=stub.status)
    select(panel)
    assert accept(panel) == {}, "no worker was started"
    assert warned, "the user was told why"
    assert "missing" in " ".join(str(part) for part in warned[0])
    assert stub.calls == [], "nothing synthesised"


def test_a_selection_that_goes_stale_after_selection_is_refused_at_start(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    """Available when picked, gone when Start is pressed: the run must not begin."""
    from tkinter import messagebox

    stub = ChatterboxStub().install(monkeypatch)
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: None)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt",
                                  chatterbox_status=stub.status)
    select(panel)
    assert panel._voice_available is True

    stub.available["chatterbox-female-1"] = (False, "the recording was removed")
    assert accept(panel) == {}, "the stale selection started a run"
    assert stub.calls == []
    assert panel._voice_available is False
    assert "removed" in panel.voice_status_var.get()


def test_a_refused_run_substitutes_no_other_voice_and_downloads_nothing(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    from tkinter import messagebox

    stub = unavailable("chatterbox-female-1", "setup required")
    stub.install(monkeypatch)
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: None)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt",
                                  chatterbox_status=stub.status)
    select(panel)
    accept(panel)

    assert panel.selected_voice_label.get() == FEMALE_1, "no silent swap"
    assert stubs.conversion_jobs == [], "no fallback to Edge"
    assert stubs.kokoro_calls == [], "no fallback to Kokoro"
    assert stub.calls == [], "no fallback to another Chatterbox voice"


def test_one_missing_recording_leaves_the_other_three_usable(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    stub = unavailable("chatterbox-female-1", "Female-1.mp3 is not present")
    stub.install(monkeypatch)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt",
                                  chatterbox_status=stub.status)

    select(panel, FEMALE_1)
    assert panel._voice_available is False
    for _voice_id, label in APPROVED[1:]:
        select(panel, label)
        assert panel._voice_available is True, label

    select(panel, "Chatterbox - Male 2")
    params = run_attempt(panel)
    assert params["voice_id"] == "chatterbox-male-2"
    assert [call["voice_id"] for call in stub.calls] == ["chatterbox-male-2"]


def test_with_all_four_missing_edge_and_kokoro_still_convert(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    stub = ChatterboxStub(
        available={voice_id: (False, "no local recording on this machine")
                   for voice_id, _label in APPROVED})
    stub.install(monkeypatch)
    stubs.install_kokoro(monkeypatch)
    kokoro = next(v for v in vr.VOICES if v.backend == "kokoro")

    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt",
                                  chatterbox_status=stub.status)
    run_attempt(panel)
    assert len(stubs.conversion_jobs) == 1, "Edge is unaffected"

    panel2, _c2 = direct_panel(make_panel, tmp_path, "two.txt",
                               chatterbox_status=stub.status)
    select(panel2, kokoro.display_label)
    run_attempt(panel2)
    assert len(stubs.kokoro_calls) == 1, "Kokoro is unaffected"
    assert stub.calls == []


def test_an_unimportable_engine_is_reported_rather_than_raised(make_panel):
    """The real seam, with no ``tts.chatterbox_synth`` importable at all."""
    panel = make_panel(chatterbox_status=panel_module.chatterbox_status)
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "tts.chatterbox_synth", None)
        select(panel)
    assert panel._voice_available is False
    assert panel.voice_status_var.get(), "a truthful reason is shown"
    assert "Edge and Kokoro" in panel.voice_status_var.get()


def test_the_status_seam_answers_rather_than_propagating_an_engine_error():
    """§7/§8: a broken engine is a status. It may never escape as an exception."""
    module = types.ModuleType("tts.chatterbox_synth")

    def exploding(_voice_id):
        raise ModuleNotFoundError("No module named 'torch'")

    module.voice_availability = exploding
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "tts.chatterbox_synth", module)
        ok, reason = panel_module.chatterbox_status("chatterbox-female-1")
    assert ok is False
    assert "torch" in reason
    assert "Edge and Kokoro" in reason


def test_a_run_is_refused_when_the_engine_itself_cannot_be_checked(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    from tkinter import messagebox

    module = types.ModuleType("tts.chatterbox_synth")
    module.voice_availability = lambda _v: (_ for _ in ()).throw(
        ModuleNotFoundError("No module named 'torch'"))
    monkeypatch.setitem(sys.modules, "tts.chatterbox_synth", module)
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: None)

    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt",
                                  chatterbox_status=panel_module.chatterbox_status)
    select(panel)
    assert accept(panel) == {}, "an unusable engine started a run"
    assert stubs.conversion_jobs == [], "and did not quietly use Edge instead"


def test_the_panel_asks_the_engine_and_reimplements_none_of_its_checks():
    """§23: no hashing, no derivative naming, no manifest reading in the GUI."""
    body = unparse_panel()
    for forbidden in ("sha256", "hashlib", "manifest", "conditionals",
                      "reference_clips_dir", "Chatterbox-Voice-Uploads",
                      "protected_uploads_dir", "derivative_path"):
        assert forbidden not in body, forbidden


def test_the_availability_seam_is_the_only_chatterbox_symbol_the_panel_imports():
    tree = panel_tree()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and "chatterbox" in (node.module or ""):
            names.update(alias.name for alias in node.names)
    assert names == {"voice_availability", "chatterbox_file_to_mp3"}, names


# --------------------------------------------------------------------------- #
# D. The engine's own availability helper
# --------------------------------------------------------------------------- #


@pytest.fixture()
def engine(monkeypatch, tmp_path):
    """The real ``chatterbox_synth`` with its locations pointed at ``tmp_path``."""
    from tts import chatterbox_synth as cbx

    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cbx, "protected_uploads_dir", lambda: uploads)
    monkeypatch.setattr(cbx, "_runtime_root", lambda: tmp_path / "runtime-data")
    monkeypatch.setattr(cbx, "_find_spec", lambda name: object())
    monkeypatch.setattr(cbx, "_AVAILABILITY_MEMO", {}, raising=False)
    return cbx


def _plant(cbx, monkeypatch, voice_id: str,
           payload: bytes = b"pretend-audio") -> Path:
    """Write a disposable source file and expect exactly that content for *voice_id*.

    The expected hash is swapped through ``monkeypatch.setitem`` rather than
    assigned: ``REFERENCE_VOICES`` is module state, and a test that edited it
    permanently would hand the next test a registry describing a file that is not
    the maintainer's. Never touches the real protected folder — ``engine`` has
    already pointed the module at ``tmp_path``.
    """
    import hashlib
    from dataclasses import replace

    voice = cbx.REFERENCE_VOICES[voice_id]
    path = cbx.protected_uploads_dir() / voice.source_name
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setitem(cbx.REFERENCE_VOICES, voice_id,
                        replace(voice, source_sha256=digest))
    return path


def test_a_present_and_matching_recording_reports_available(engine, monkeypatch):
    _plant(engine, monkeypatch, "chatterbox-male-1")
    assert engine.voice_availability("chatterbox-male-1") == (True, "ok")


def test_an_absent_recording_reports_unavailable_with_a_readable_reason(engine):
    ok, reason = engine.voice_availability("chatterbox-female-2")
    assert ok is False
    assert "Female-2.mp3" in reason
    assert "Edge and Kokoro" in reason, "the message reassures about the rest"


def test_a_recording_whose_hash_does_not_match_reports_unavailable(engine):
    voice = engine.REFERENCE_VOICES["chatterbox-male-1"]
    (engine.protected_uploads_dir() / voice.source_name).write_bytes(b"different")
    ok, reason = engine.voice_availability("chatterbox-male-1")
    assert ok is False
    assert "sha256" in reason.lower()


def test_availability_never_loads_a_model_downloads_or_writes_anything(
    engine, monkeypatch, tmp_path
):
    monkeypatch.setattr(engine, "_get_model",
                        lambda device=None: pytest.fail("a model was loaded"))
    monkeypatch.setattr(engine, "build_reference_clip",
                        lambda *a, **k: pytest.fail("a derivative was built"))
    _plant(engine, monkeypatch, "chatterbox-male-1")
    before = sorted(p.name for p in engine.protected_uploads_dir().iterdir())
    assert engine.voice_availability("chatterbox-male-1")[0] is True
    assert not (tmp_path / "runtime-data").exists(), "nothing was created"
    assert sorted(p.name for p in engine.protected_uploads_dir().iterdir()) == before


def test_availability_does_not_rehash_an_unchanged_recording(engine, monkeypatch):
    _plant(engine, monkeypatch, "chatterbox-male-1")
    hashed: list = []
    real = engine.sha256_of
    monkeypatch.setattr(engine, "sha256_of",
                        lambda path: hashed.append(path) or real(path))

    assert engine.voice_availability("chatterbox-male-1")[0] is True
    assert engine.voice_availability("chatterbox-male-1")[0] is True
    assert engine.voice_availability("chatterbox-male-1")[0] is True
    assert len(hashed) == 1, "a dropdown refresh must not re-read 33 MB each time"


def test_a_replaced_recording_misses_the_memo_and_is_checked_again(
    engine, monkeypatch
):
    _plant(engine, monkeypatch, "chatterbox-male-1")
    assert engine.voice_availability("chatterbox-male-1")[0] is True

    voice = engine.REFERENCE_VOICES["chatterbox-male-1"]
    path = engine.protected_uploads_dir() / voice.source_name
    path.write_bytes(b"a completely different recording entirely")
    assert engine.voice_availability("chatterbox-male-1")[0] is False


def test_availability_is_false_when_the_package_is_not_installed(engine, monkeypatch):
    _plant(engine, monkeypatch, "chatterbox-male-1")
    monkeypatch.setattr(engine, "_find_spec", lambda name: None)
    ok, reason = engine.voice_availability("chatterbox-male-1")
    assert ok is False
    assert "not installed" in reason


def test_a_stale_cached_conditional_is_never_treated_as_valid(engine):
    """§30 D: identity is bound to the source hash, so a stale entry cannot be hit."""
    fresh = engine.conditionals_path("chatterbox-male-1", "a" * 64)
    stale = engine.conditionals_path("chatterbox-male-1", "b" * 64)
    assert fresh != stale
    assert engine.identity_digest("a" * 64) != engine.identity_digest("b" * 64)


def test_the_engine_still_reverifies_the_full_hash_on_a_real_use(engine):
    """The memo is a GUI convenience; the conversion path keeps its own check."""
    src = module_source(TTS_DIR / "chatterbox_synth.py")
    resolve = src.split("def resolve_reference", 1)[1].split("\ndef ", 1)[0]
    assert "sha256_of(path)" in resolve
    assert "_AVAILABILITY_MEMO" not in resolve


# --------------------------------------------------------------------------- #
# E. Three-way dispatch, driven by the registry's backend
# --------------------------------------------------------------------------- #


def test_the_frozen_options_carry_the_backend_and_the_voice_id(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt",
                                  chatterbox_status=chatterbox.status)
    select(panel)
    params = run_attempt(panel)
    options = params["snapshot"].tool_options
    assert options["backend"] == "chatterbox"
    assert options["voice_id"] == "chatterbox-female-1"


@pytest.mark.parametrize("label,backend,voice_id", [
    (vr.DEFAULT_VOICE_LABEL, "edge", "en-US-SteffanNeural"),
    ("Kokoro Female (Default) - Heart (en-US)", "kokoro", "af_heart"),
    (FEMALE_1, "chatterbox", "chatterbox-female-1"),
])
def test_every_backend_freezes_its_own_identity(
    make_panel, output_base, tmp_path, stubs, chatterbox, monkeypatch,
    label, backend, voice_id
):
    stubs.install_kokoro(monkeypatch)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt",
                                  chatterbox_status=chatterbox.status)
    select(panel, label)
    params = run_attempt(panel)
    assert params["backend"] == backend
    assert params["voice_id"] == voice_id


def test_the_panel_keeps_no_second_backend_boolean():
    """§9: one backend value, not ``is_kokoro`` plus ``is_chatterbox``."""
    code = panel_code()
    assert "is_chatterbox" not in code
    assert "is_kokoro" not in code


def test_dispatch_never_reads_the_display_label():
    """§11: engine choice comes from the registry's backend, not a label substring."""
    compares = [node for node in ast.walk(panel_tree())
                if isinstance(node, ast.Compare)]
    engine_tests = [ast.unparse(node) for node in compares
                    if "'chatterbox'" in ast.unparse(node)]
    assert engine_tests, "the three-way dispatch has to test the backend somewhere"
    for text in engine_tests:
        assert "backend" in text, text
    for text in (ast.unparse(node) for node in compares):
        for label_source in ("display_label", "selected_voice_label"):
            assert label_source not in text or "hatterbox" not in text, text


def test_the_worker_dispatches_on_the_frozen_backend(make_panel):
    """The seam is a three-way decision inside the run body, not three pipelines."""
    body = unparse_panel()
    assert "params['backend']" in body
    assert "convert_with_chatterbox" in body
    assert "convert_with_kokoro" in body
    assert "convert_with_edge_engine" in body


def test_no_second_queue_controller_publisher_or_planner_was_added():
    body = unparse_panel()
    tree = panel_tree()
    classes = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    assert classes == {"TimingSample", "PlannedOutput", "RunPublisher", "TtsPanel",
                       "_RunContext", "QueueWriter"}, classes
    assert body.count("capture_run(") == 1
    assert "plan_multi_root" in body and body.count("def plan_destinations") == 1


def test_changing_the_voice_after_start_cannot_reach_a_running_run(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt",
                                  chatterbox_status=chatterbox.status)
    select(panel)
    captured = accept(panel)
    select(panel, vr.DEFAULT_VOICE_LABEL)
    params = finish(panel, captured)

    assert params["backend"] == "chatterbox"
    assert [call["voice_id"] for call in chatterbox.calls] == ["chatterbox-female-1"]
    assert stubs.conversion_jobs == []


# --------------------------------------------------------------------------- #
# F. Directly added PDF and TXT
# --------------------------------------------------------------------------- #


def test_a_direct_txt_converts_with_chatterbox_and_lands_flat(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    panel, chosen = direct_panel(make_panel, tmp_path, "solo.txt",
                                 chatterbox_status=chatterbox.status)
    select(panel)
    params = run_attempt(panel)

    assert len(chatterbox.calls) == 1
    call = chatterbox.calls[0]
    assert call["source"] == str(chosen[0]), "a TXT is handed over as it stands"
    assert call["voice_id"] == "chatterbox-female-1"
    assert relative(call["output"], params["run_directory"]) == "solo.mp3"
    assert stubs.conversion_jobs == [] and stubs.batch_items == []


def test_a_direct_pdf_goes_through_the_existing_extractor_first(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    panel, chosen = direct_panel(make_panel, tmp_path, "book.pdf",
                                 chatterbox_status=chatterbox.status)
    select(panel)
    params = run_attempt(panel)

    assert [source for source, _target in stubs.extracted] == [str(chosen[0])]
    assert len(chatterbox.calls) == 1
    assert chatterbox.calls[0]["source"] != str(chosen[0]), "a temp .txt is used"
    assert chatterbox.calls[0]["source"].endswith(".txt")
    assert relative(chatterbox.calls[0]["output"],
                    params["run_directory"]) == "book.mp3"


def test_a_direct_chatterbox_output_is_named_like_the_other_local_engine(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    """No Edge speaker-in-filename convention: local engines write ``<stem>.mp3``."""
    panel, _chosen = direct_panel(make_panel, tmp_path, "solo.txt",
                                  chatterbox_status=chatterbox.status)
    select(panel)
    params = run_attempt(panel)
    names = [item["destination"].name for item in params["items"]]
    assert names == ["solo.mp3"]
    assert not any("(" in name for name in names)


def test_two_deliberate_duplicates_stay_two_collision_safe_outputs(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    chosen = sources(tmp_path / "Loose", "twice.txt")
    panel = make_panel(choose_files=lambda: chosen,
                       chatterbox_status=chatterbox.status,
                       confirm_large_result=lambda outcome: True)
    panel.importer.add_files()
    panel.importer.options.set_allow_duplicates(True)
    panel.importer.add_files()
    panel._pump.tick()
    select(panel)
    params = run_attempt(panel)

    outputs = sorted(relative(call["output"], params["run_directory"])
                     for call in chatterbox.calls)
    assert len(outputs) == 2 == len(set(outputs))


@pytest.mark.parametrize("voice_id,label", APPROVED)
def test_all_four_approved_voices_route_identically_by_voice_id(
    make_panel, output_base, tmp_path, stubs, chatterbox, voice_id, label
):
    """§27: parametrized at the registry level, not four expensive engine runs."""
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt",
                                  chatterbox_status=chatterbox.status)
    select(panel, label)
    params = run_attempt(panel)
    assert params["backend"] == "chatterbox"
    assert [call["voice_id"] for call in chatterbox.calls] == [voice_id]
    assert relative(chatterbox.calls[0]["output"],
                    params["run_directory"]) == "one.mp3"


# --------------------------------------------------------------------------- #
# G. Folder-imported PDF and TXT
# --------------------------------------------------------------------------- #


def test_folder_imported_files_mirror_their_root_with_chatterbox(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    panel, _folders = folder_panel(make_panel, tmp_path,
                                   chatterbox_status=chatterbox.status)
    select(panel)
    params = run_attempt(panel)

    outputs = sorted(relative(call["output"], params["run_directory"])
                     for call in chatterbox.calls)
    assert outputs == ["01.mp3", "Book A/02.mp3"]
    assert stubs.batch_items == [], "the Edge batch worker was not used"


def test_a_nested_folder_pdf_is_extracted_then_synthesised_in_place(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    root = tmp_path / "Library"
    sources(root / "Series" / "Book One", "ch1.pdf")
    panel = make_panel(choose_folder=lambda: (root,),
                       chatterbox_status=chatterbox.status)
    panel.importer.add_folder()
    panel._pump.tick()
    select(panel)
    params = run_attempt(panel)

    assert len(stubs.extracted) == 1
    assert relative(chatterbox.calls[0]["output"],
                    params["run_directory"]) == "Series/Book One/ch1.mp3"


def test_the_same_stem_in_two_subfolders_stays_two_outputs(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    root = tmp_path / "Library"
    sources(root / "A", "same.txt")
    sources(root / "B", "same.txt")
    panel = make_panel(choose_folder=lambda: (root,),
                       chatterbox_status=chatterbox.status)
    panel.importer.add_folder()
    panel._pump.tick()
    select(panel)
    params = run_attempt(panel)

    outputs = sorted(relative(call["output"], params["run_directory"])
                     for call in chatterbox.calls)
    assert outputs == ["A/same.mp3", "B/same.mp3"]


def test_the_worker_never_rescans_a_folder(make_panel):
    """The frozen occurrence already carries its provenance."""
    body = ast.unparse(
        next(n for n in panel_tree().body
             if isinstance(n, ast.ClassDef) and n.name == "_RunContext"))
    for forbidden in ("rglob", "iterdir", "walk", "scan_roots", "planning_groups"):
        assert forbidden not in body, forbidden


# --------------------------------------------------------------------------- #
# H. One run holding both provenances
# --------------------------------------------------------------------------- #


def test_a_mixed_chatterbox_run_places_each_half_by_its_provenance(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    panel, _direct, _folders = mixed_panel(make_panel, tmp_path,
                                           chatterbox_status=chatterbox.status)
    select(panel)
    params = run_attempt(panel)

    outputs = sorted(relative(call["output"], params["run_directory"])
                     for call in chatterbox.calls)
    assert outputs == ["01.mp3", "Book A/02.mp3", "notes.mp3", "solo.mp3"]
    assert len(chatterbox.calls) == 4, "one run, one queue"
    assert {call["voice_id"] for call in chatterbox.calls} == {"chatterbox-female-1"}
    assert stubs.conversion_jobs == [] and stubs.batch_items == []


def test_a_mixed_multi_root_chatterbox_run_keeps_each_root_in_its_container(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    panel, _direct, folders = mixed_panel(make_panel, tmp_path, roots=2,
                                          chatterbox_status=chatterbox.status)
    select(panel)
    params = run_attempt(panel)

    outputs = sorted(relative(call["output"], params["run_directory"])
                     for call in chatterbox.calls)
    assert outputs == [
        "Library 1/01.mp3", "Library 1/Book A/02.mp3",
        "Library 2/01.mp3", "Library 2/Book A/02.mp3",
        "notes.mp3", "solo.mp3",
    ]
    assert len(folders) == 2


def test_a_mixed_run_is_one_frozen_snapshot_with_one_backend(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    panel, _direct, _folders = mixed_panel(make_panel, tmp_path,
                                           chatterbox_status=chatterbox.status)
    select(panel)
    params = run_attempt(panel)
    snapshot = params["snapshot"]
    assert len(snapshot.item_ids) == 4
    assert snapshot.tool_options["backend"] == "chatterbox"
    assert panel._result.state is JobState.SUCCEEDED
    assert len(panel._result.completed_ids) == 4


# --------------------------------------------------------------------------- #
# I. Pause, cancel and progress
# --------------------------------------------------------------------------- #


def test_a_chatterbox_run_pauses_and_resumes_through_the_one_controller(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "a.txt", "b.txt",
                                  chatterbox_status=chatterbox.status)
    select(panel)
    captured = accept(panel)
    panel.pause()
    assert panel._controller.state.value == "pause_requested"
    panel.resume()
    assert panel._controller.state.value == "running"
    finish(panel, captured)
    assert len(chatterbox.calls) == 2


def test_cancelling_a_chatterbox_run_yields_cancelled_and_no_false_success(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "a.txt", "b.txt", "c.txt",
                                  chatterbox_status=chatterbox.status)
    select(panel)
    captured = accept(panel)
    panel._controller.request_cancel()
    finish(panel, captured)

    assert chatterbox.calls == [], "a cancelled run synthesises nothing"
    assert panel._controller.state.value == "cancelled"
    assert panel._result.cancelled is True
    assert panel._result.completed_ids == ()


def test_cancellation_reaches_the_engine_through_the_controllers_own_predicate(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "a.txt",
                                  chatterbox_status=chatterbox.status)
    select(panel)
    run_attempt(panel)
    seen = chatterbox.calls[0]["cancel_check"]
    assert seen == panel._controller.cancel_check, "the controller's own predicate"
    assert seen() is False


def test_no_second_cancellation_event_exists_for_chatterbox():
    """Phase 6's cancellation ``Event`` stayed retired; the controller is it.

    The panel does hold two ``Event``s — the busy flag and the publisher's
    retirement flag — and neither is a cancellation domain. What must not exist is
    a third, engine-specific one.
    """
    body = unparse_panel()
    assert body.count("threading.Event()") == 2, "the busy and retirement flags"
    for forbidden in ("cancel_event", "_cancel_flag", "cancel_requested_event"):
        assert forbidden not in body, forbidden
    run_context = ast.unparse(
        next(n for n in panel_tree().body
             if isinstance(n, ast.ClassDef) and n.name == "_RunContext"))
    assert "threading.Event" not in run_context
    assert "controller.cancel_check" in run_context


def test_a_partial_chatterbox_output_is_discarded_when_cancelled(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    stub = ChatterboxStub().install(monkeypatch)
    panel, _chosen = direct_panel(make_panel, tmp_path, "a.txt",
                                  chatterbox_status=stub.status)
    select(panel)
    captured = accept(panel)
    destination = captured["params"]["items"][0]["destination"]
    # The engine gets as far as a chunk boundary, sees the cancel, and leaves a
    # part-written file behind — which is exactly what a real one does.
    stub.cancel_at_chunk = panel._controller.request_cancel
    finish(panel, captured)

    assert stub.calls, "the engine was reached"
    assert not destination.exists(), "the partial artifact was removed"
    assert panel._controller.state.value == "cancelled"
    assert panel._result.cancelled is True


def test_chatterbox_progress_reaches_the_ui_only_through_the_run_publisher(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "a.txt", "b.txt",
                                  chatterbox_status=chatterbox.status)
    select(panel)
    run_attempt(panel)
    assert panel._result.state is JobState.SUCCEEDED
    # The engine's fine-grained callback is deliberately not wired: one run has
    # one progress model and it counts completed source files, exactly as Kokoro.
    assert all(call["progress_callback"] is None for call in chatterbox.calls)


def test_the_publication_authority_and_the_shared_controller_are_untouched():
    """§38: Phase 7's reporting-order remediation is not re-opened here."""
    for name in ("job_control.py", "job_ui.py"):
        assert "chatterbox" not in module_source(SHARED_DIR / name).lower(), name
    body = unparse_panel()
    assert "JobReporter.for_run" in body
    assert body.count("class RunPublisher") == 1
    publisher = next(n for n in panel_tree().body
                     if isinstance(n, ast.ClassDef) and n.name == "RunPublisher")
    assert "chatterbox" not in ast.unparse(publisher).lower()


# --------------------------------------------------------------------------- #
# J. Retry Failed
# --------------------------------------------------------------------------- #


@pytest.fixture()
def failing_chatterbox(monkeypatch):
    return ChatterboxStub(failing="bad").install(monkeypatch)


def test_retry_reuses_the_original_backend_voice_and_destination(
    make_panel, output_base, tmp_path, stubs, failing_chatterbox
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt",
                                  chatterbox_status=failing_chatterbox.status)
    select(panel)
    first = run_attempt(panel)
    original = first["snapshot"]
    planned = dict(panel.destinations())

    assert panel._result.state is JobState.COMPLETED_WITH_FAILURES
    failed_id = panel._result.retryable_ids[0]

    second = run_attempt(panel, panel.retry_failed)
    assert second["snapshot"] is original, "the exact frozen object"
    assert [item["item_id"] for item in second["items"]] == [failed_id]
    assert second["backend"] == "chatterbox"
    assert second["voice_id"] == "chatterbox-female-1"
    assert second["items"][0]["destination"] == planned[failed_id].destination
    assert panel.destinations() == planned, "nothing was replanned"


def test_a_retry_uses_the_original_voice_even_after_the_dropdown_changed(
    make_panel, output_base, tmp_path, stubs, failing_chatterbox, monkeypatch
):
    stubs.install_kokoro(monkeypatch)
    panel, _chosen = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt",
                                  chatterbox_status=failing_chatterbox.status)
    select(panel, "Chatterbox - Male 2")
    run_attempt(panel)

    select(panel, "Kokoro Female (Default) - Heart (en-US)")
    second = run_attempt(panel, panel.retry_failed)

    assert second["backend"] == "chatterbox"
    assert second["voice_id"] == "chatterbox-male-2"
    assert stubs.kokoro_calls == [], "today's dropdown did not decide the retry"
    assert {call["voice_id"] for call in failing_chatterbox.calls} == {
        "chatterbox-male-2"}


def test_a_chatterbox_retry_never_overwrites_an_earlier_success(
    make_panel, output_base, tmp_path, stubs, failing_chatterbox
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt",
                                  chatterbox_status=failing_chatterbox.status)
    select(panel)
    first = run_attempt(panel)
    survivor = next(item["destination"] for item in first["items"]
                    if "good" in item["source"].name)
    survivor.write_bytes(b"the first success")

    run_attempt(panel, panel.retry_failed)
    assert survivor.read_bytes() == b"the first success"


def test_a_mixed_run_retry_keeps_each_half_of_the_queue_in_its_own_place(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    """§29: the failure/retry version of the mixed run."""
    stub = ChatterboxStub(failing="02").install(monkeypatch)
    panel, _direct, _folders = mixed_panel(make_panel, tmp_path,
                                           chatterbox_status=stub.status)
    select(panel)
    first = run_attempt(panel)
    run_root = first["run_directory"]

    assert panel._result.state is JobState.COMPLETED_WITH_FAILURES
    failed_id = panel._result.retryable_ids[0]
    planned = panel.destinations()[failed_id]
    assert relative(planned.destination, run_root) == "Book A/02.mp3"
    assert planned.direct is False

    stub.failing = "never"
    second = run_attempt(panel, panel.retry_failed)
    assert [item["item_id"] for item in second["items"]] == [failed_id]
    assert second["run_directory"] == run_root
    assert relative(second["items"][0]["destination"], run_root) == "Book A/02.mp3"


def test_retiring_the_first_attempt_keeps_its_reports_off_the_live_queue(
    make_panel, output_base, tmp_path, stubs, failing_chatterbox
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt",
                                  chatterbox_status=failing_chatterbox.status)
    select(panel)
    first = run_attempt(panel)
    retired = first["publisher"]
    run_attempt(panel, panel.retry_failed)

    assert retired.closed is True
    assert retired is not panel._publisher
    assert retired.progress(1, 1) is None, "a retired attempt publishes nothing"


# --------------------------------------------------------------------------- #
# K. Edge and Kokoro are unchanged
# --------------------------------------------------------------------------- #


def test_the_seven_edge_rows_survive_by_value():
    from test_chatterbox_boundaries import EXPECTED_VOICES

    edge = [v for v in vr.VOICES if v.backend == "edge"]
    assert len(edge) == 7
    for entry, expected in zip(edge, EXPECTED_VOICES[:7]):
        assert (entry.backend, entry.voice_id, entry.display_label,
                entry.group_label, entry.timing_preset) == expected


def test_the_five_kokoro_rows_survive_by_value():
    from test_chatterbox_boundaries import EXPECTED_VOICES

    kokoro = [v for v in vr.VOICES if v.backend == "kokoro"]
    assert len(kokoro) == 5
    for entry, expected in zip(kokoro, EXPECTED_VOICES[7:12]):
        assert (entry.backend, entry.voice_id, entry.display_label,
                entry.group_label, entry.timing_preset) == expected


def test_an_edge_run_is_untouched_by_the_new_backend(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    panel, _direct, _folders = mixed_panel(make_panel, tmp_path,
                                           chatterbox_status=chatterbox.status)
    params = run_attempt(panel)
    assert len(stubs.conversion_jobs) == 2, "the two directly added files"
    assert len(stubs.batch_items) == 2, "the two folder-derived files"
    assert chatterbox.calls == []
    assert params["speaker"] == "en-US-SteffanNeural"
    assert params["rate"] == "+0%"
    assert params["pause_kw"]["sentencepause"] == 800
    names = sorted(item["destination"].name for item in params["items"]
                   if item["direct"])
    assert names == ["notes (en-US-SteffanNeural).mp3",
                     "solo (en-US-SteffanNeural).mp3"]


def test_a_kokoro_run_is_untouched_by_the_new_backend(
    make_panel, output_base, tmp_path, stubs, chatterbox, monkeypatch
):
    stubs.install_kokoro(monkeypatch)
    kokoro = next(v for v in vr.VOICES if v.backend == "kokoro")
    panel, _direct, _folders = mixed_panel(make_panel, tmp_path,
                                           chatterbox_status=chatterbox.status)
    select(panel, kokoro.display_label)
    params = run_attempt(panel)

    assert len(stubs.kokoro_calls) == 4
    assert {call["voice_id"] for call in stubs.kokoro_calls} == {kokoro.voice_id}
    assert params["kokoro_speed"] == 1.0
    assert chatterbox.calls == []
    assert sorted(relative(call["output"], params["run_directory"])
                  for call in stubs.kokoro_calls) == [
        "01.mp3", "Book A/02.mp3", "notes.mp3", "solo.mp3"]


def test_no_chatterbox_symbol_reached_the_engines_themselves():
    """§21/§22: the engines are consumed, never edited, to add a third backend."""
    for filename in ("kokoro_synth.py", "batch_convert.py", "pdf_extractor.py",
                     "epub2tts_edge/runner.py"):
        assert "chatterbox" not in module_source(TTS_DIR / filename).lower(), filename


def test_the_panel_reimplements_no_engine():
    defined = {n.name for n in ast.walk(panel_tree())
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for symbol in ("chatterbox_file_to_mp3", "synthesize_text_to_mp3",
                   "prepare_reference_clip", "load_conditionals",
                   "kokoro_file_to_mp3", "pdf_to_txt", "split_into_chunks"):
        assert symbol not in defined, symbol


# --------------------------------------------------------------------------- #
# L. EPUB stays retired, and no legacy mode returns
# --------------------------------------------------------------------------- #


def test_the_catalog_still_offers_only_pdf_and_txt():
    catalog = panel_module.build_catalog()
    assert sorted(t.type_id for t in catalog.types) == ["pdf", "txt"]
    extensions = {ext for t in catalog.types for ext in t.extensions}
    assert extensions == {".pdf", ".txt"}
    assert ".epub" not in extensions


def test_an_epub_cannot_enter_a_chatterbox_run(
    make_panel, output_base, tmp_path, stubs, chatterbox
):
    folder = tmp_path / "Loose"
    chosen = sources(folder, "ok.txt")
    smuggled = sources(folder, "book.epub")
    panel = make_panel(choose_files=lambda: chosen + smuggled,
                       chatterbox_status=chatterbox.status)
    panel.importer.add_files()
    select(panel)
    params = run_attempt(panel)

    assert [p.name for p in panel.imported_files()] == ["ok.txt"]
    assert [item["source"].name for item in params["items"]] == ["ok.txt"]
    assert [Path(call["source"]).name for call in chatterbox.calls] == ["ok.txt"]
    assert smuggled[0].exists(), "the file is left alone, just never imported"


def test_no_legacy_mode_returned_with_the_new_backend():
    """Prose may name what Phase 5 retired; code may not bring any of it back."""
    code = panel_code().lower()
    for forbidden in ("mode_var", "radiobutton", "single_mode", "batch_mode",
                      "epub_path", "read_epub"):
        assert forbidden not in code, forbidden
    # ``tts.epub2tts_edge`` is the documented compatibility *module* name and is
    # allowed; an EPUB extension used as a value is not.
    assert "'.epub'" not in code
    assert '"*.epub"' not in code and "*.epub" not in code


def test_the_panel_reads_the_chatterbox_voice_from_the_registry_only():
    """No second table of voice ids inside the GUI."""
    body = unparse_panel()
    for voice_id, _label in APPROVED:
        assert voice_id not in body, voice_id
    for _voice_id, label in APPROVED:
        assert label not in body, label
