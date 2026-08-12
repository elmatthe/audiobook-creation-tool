"""The centralized image-capability contract — v0.6.1 Plan 4, Phase 1.

Decision 54A wants HEIC/HEIF to be a pinned, **probed**, tested capability
instead of the bare module-level ``try: import pillow_heif … except: pass`` the
Cover panel carried. Decision 3A adds that decode and encode are separate
capabilities and that a missing encoder must produce a truthful failure rather
than a silently substituted JPEG.

Every capability state below is constructed through the probe's injected seams,
so the suite proves available, unavailable, decode-only, encode-only, failing
registration and failing probes **on any machine** — including this one, where
``pillow-heif`` is not installed. Two tests read the host's real answer; they
assert that it is *coherent and truthful*, never that it is a particular value.

**What these tests do not prove.** Nothing here decodes or encodes a real HEIC
file. They prove the probe's logic and the panel's wiring. Real HEIC behaviour is
Phase 12 on Windows and Phase 13 on Apple Silicon, and neither substitutes for
the other.
"""

from __future__ import annotations

import pytest

from shared import image_capabilities as caps


# --------------------------------------------------------------------------- #
# Fake machines. Each is one probe seam set, named for what it represents.
# --------------------------------------------------------------------------- #


class _Plugin:
    """Stand-in for the ``pillow_heif`` module, counting its registrations."""

    def __init__(self, *, fail: Exception | None = None):
        self.registrations = 0
        self._fail = fail

    def register_heif_opener(self):
        self.registrations += 1
        if self._fail is not None:
            raise self._fail


def _machine(*, plugin=None, decode=True, encode=True,
             decode_raises=None, encode_raises=None, import_error=None):
    """Build the four seams describing one hypothetical machine."""
    plugin = _Plugin() if plugin is None else plugin

    def importer():
        if import_error is not None:
            raise import_error
        return plugin

    def decode_check():
        if decode_raises is not None:
            raise decode_raises
        return decode

    def encode_check():
        if encode_raises is not None:
            raise encode_raises
        if not encode:
            raise OSError("encoder not available")

    return {
        "importer": importer,
        "register": lambda module: module.register_heif_opener(),
        "decode_check": decode_check,
        "encode_check": encode_check,
    }


@pytest.fixture(autouse=True)
def _clean_capability_cache():
    """No test may inherit or leak a cached probe result."""
    caps.reset_cache()
    yield
    caps.reset_cache()


# --------------------------------------------------------------------------- #
# The probe reports truthfully — and reports decode and encode separately.
# --------------------------------------------------------------------------- #


def test_a_working_install_reports_both_capabilities_and_no_complaint():
    capability = caps.probe_heif(**_machine())
    assert (capability.decode, capability.encode) == (True, True)
    assert capability.available and capability.fully_supported
    assert capability.detail == ""
    assert capability.suffixes == (".heic", ".heif")


def test_a_missing_plugin_is_unavailable_and_says_so_without_raising():
    capability = caps.probe_heif(
        **_machine(import_error=ImportError("No module named 'pillow_heif'"))
    )
    assert (capability.decode, capability.encode) == (False, False)
    assert not capability.available
    assert "not installed" in capability.detail
    assert "pillow-heif" in capability.detail


def test_a_decode_only_build_is_reported_as_decode_only():
    """The configuration Decision 3A exists for: readable, not writable."""
    capability = caps.probe_heif(**_machine(decode=True, encode=False))
    assert capability.decode is True
    assert capability.encode is False
    assert capability.available is True
    assert capability.fully_supported is False
    assert "cannot write HEIF" in capability.detail
    # The complaint is about writing only — decoding drew no complaint.
    assert "reader" not in capability.detail


def test_an_encode_only_build_is_reported_as_encode_only():
    """The mirror image. Proves the two flags are genuinely independent."""
    capability = caps.probe_heif(**_machine(decode=False, encode=True))
    assert capability.decode is False
    assert capability.encode is True
    assert capability.available is True
    assert capability.fully_supported is False
    assert "no HEIF reader" in capability.detail
    assert "cannot write" not in capability.detail


def test_decode_and_encode_are_never_collapsed_into_one_flag():
    """All four combinations are representable and distinct."""
    observed = {
        (
            caps.probe_heif(**_machine(decode=d, encode=e)).decode,
            caps.probe_heif(**_machine(decode=d, encode=e)).encode,
        )
        for d in (True, False)
        for e in (True, False)
    }
    assert observed == {(True, True), (True, False), (False, True), (False, False)}


# --------------------------------------------------------------------------- #
# Failure never escapes, and never becomes a false claim of support.
# --------------------------------------------------------------------------- #


def test_a_registration_that_raises_degrades_instead_of_propagating():
    plugin = _Plugin(fail=RuntimeError("libheif.dll could not be loaded"))
    capability = caps.probe_heif(**_machine(plugin=plugin))
    assert plugin.registrations == 1
    assert (capability.decode, capability.encode) == (False, False)
    assert "could not register with Pillow" in capability.detail
    assert "libheif.dll" in capability.detail


def test_a_decoder_probe_that_raises_is_reported_not_swallowed():
    capability = caps.probe_heif(
        **_machine(decode_raises=RuntimeError("Pillow registry unreadable"))
    )
    assert capability.decode is False
    assert "decoder probe failed" in capability.detail
    # An exception during the decode probe must not be read as encode failure.
    assert capability.encode is True


def test_an_encoder_probe_that_raises_does_not_claim_encode_support():
    capability = caps.probe_heif(
        **_machine(encode_raises=OSError("encoder plugin for format HEIF not found"))
    )
    assert capability.encode is False
    assert capability.decode is True
    assert "encoder plugin" in capability.detail


def test_a_broken_install_never_advertises_support_anyway():
    """The failure mode the old bare ``except: pass`` had: silent optimism."""
    for machine in (
        _machine(import_error=ImportError("boom")),
        _machine(plugin=_Plugin(fail=OSError("bad wheel"))),
        _machine(decode=False, encode=False),
    ):
        capability = caps.probe_heif(**machine)
        assert not capability.fully_supported
        assert capability.detail, "a failure must always carry a truthful reason"


def test_the_probe_never_raises_for_any_seam_failure():
    """Whatever the optional stack does, the caller gets an answer."""
    for failure in (ImportError("x"), OSError("x"), RuntimeError("x"), ValueError("x")):
        assert caps.probe_heif(**_machine(import_error=failure)).decode is False
        assert caps.probe_heif(**_machine(decode_raises=failure)).decode is False
        assert caps.probe_heif(**_machine(encode_raises=failure)).encode is False


# --------------------------------------------------------------------------- #
# Registration happens exactly once, and is idempotent.
# --------------------------------------------------------------------------- #


def test_registration_happens_once_no_matter_how_often_capability_is_asked():
    calls = {"n": 0}
    plugin = _Plugin()

    def counting_probe():
        calls["n"] += 1
        return caps.probe_heif(**_machine(plugin=plugin))

    first = caps.heif_capability(probe=counting_probe)
    for _ in range(5):
        assert caps.heif_capability(probe=counting_probe) is first
    assert calls["n"] == 1
    assert plugin.registrations == 1


def test_refresh_reprobes_and_a_reset_forgets_the_answer():
    calls = {"n": 0}

    def counting_probe():
        calls["n"] += 1
        return caps.probe_heif(**_machine())

    caps.heif_capability(probe=counting_probe)
    caps.heif_capability(probe=counting_probe, refresh=True)
    assert calls["n"] == 2
    caps.reset_cache()
    caps.heif_capability(probe=counting_probe)
    assert calls["n"] == 3


def test_the_cached_answer_is_shared_across_threads_and_registers_once():
    """Two workers asking at once must not both register the plugin."""
    import threading

    plugin = _Plugin()
    start = threading.Barrier(4)
    results: list[caps.FormatCapability] = []
    lock = threading.Lock()

    def ask():
        start.wait(timeout=5)
        value = caps.heif_capability(probe=lambda: caps.probe_heif(**_machine(plugin=plugin)))
        with lock:
            results.append(value)

    threads = [threading.Thread(target=ask) for _ in range(3)]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert len(results) == 3
    assert all(value is results[0] for value in results)
    assert plugin.registrations == 1


# --------------------------------------------------------------------------- #
# The supported-extension sets follow the probe.
# --------------------------------------------------------------------------- #


def _pin(monkeypatch, *, decode: bool, encode: bool) -> None:
    """Pin the module's cached answer to a hypothetical machine."""
    caps.reset_cache()
    caps.heif_capability(probe=lambda: caps.probe_heif(**_machine(decode=decode, encode=encode)))


def test_jpg_jpeg_and_png_are_always_offered_in_both_directions(monkeypatch):
    for decode, encode in ((True, True), (True, False), (False, True), (False, False)):
        _pin(monkeypatch, decode=decode, encode=encode)
        for suffix in (".jpg", ".jpeg", ".png"):
            assert caps.can_decode(suffix), (suffix, decode, encode)
            assert caps.can_encode(suffix), (suffix, decode, encode)


def test_the_offered_extensions_follow_the_probe(monkeypatch):
    _pin(monkeypatch, decode=True, encode=True)
    assert caps.decodable_suffixes() == (".jpg", ".jpeg", ".png", ".heic", ".heif")
    assert caps.encodable_suffixes() == (".jpg", ".jpeg", ".png", ".heic", ".heif")

    _pin(monkeypatch, decode=False, encode=False)
    assert caps.decodable_suffixes() == (".jpg", ".jpeg", ".png")
    assert caps.encodable_suffixes() == (".jpg", ".jpeg", ".png")


def test_a_decode_only_machine_offers_heic_for_reading_but_not_for_writing(monkeypatch):
    _pin(monkeypatch, decode=True, encode=False)
    assert caps.can_decode(".heic") and caps.can_decode(".heif")
    assert not caps.can_encode(".heic") and not caps.can_encode(".heif")


def test_suffix_matching_is_case_insensitive(monkeypatch):
    _pin(monkeypatch, decode=True, encode=True)
    assert caps.can_decode(".HEIC") and caps.can_encode(".HEIF")
    assert caps.can_encode(".JPG")


# --------------------------------------------------------------------------- #
# Decision 3A: refuse, never substitute.
# --------------------------------------------------------------------------- #


def test_require_encoder_passes_silently_when_the_format_can_be_written(monkeypatch):
    _pin(monkeypatch, decode=True, encode=True)
    for suffix in (".jpg", ".jpeg", ".png", ".heic", ".heif"):
        assert caps.require_encoder(suffix) is None


def test_require_encoder_refuses_heif_when_encoding_is_unavailable(monkeypatch):
    _pin(monkeypatch, decode=True, encode=False)
    with pytest.raises(caps.UnsupportedImageFormat) as excinfo:
        caps.require_encoder(".heic")
    error = excinfo.value
    assert ".heic" in error.message
    assert "cannot write" in error.message
    # The message must promise the opposite of a silent substitution.
    assert "Nothing was converted to another format" in error.message
    assert error.detail, "the log needs the technical reason"
    assert "jpg" not in error.message.lower() and "jpeg" not in error.message.lower()


def test_require_encoder_never_names_jpeg_as_a_fallback(monkeypatch):
    """No path through this module may suggest quietly writing a JPEG instead."""
    _pin(monkeypatch, decode=False, encode=False)
    for suffix in (".heic", ".heif"):
        with pytest.raises(caps.UnsupportedImageFormat) as excinfo:
            caps.require_encoder(suffix)
        assert "jpg" not in excinfo.value.message.lower()


def test_require_encoder_rejects_a_format_the_writer_does_not_know(monkeypatch):
    _pin(monkeypatch, decode=True, encode=True)
    with pytest.raises(caps.UnsupportedImageFormat):
        caps.require_encoder(".webp")


# --------------------------------------------------------------------------- #
# The host's real answer, whatever it is, must be coherent.
# --------------------------------------------------------------------------- #


def test_the_real_probe_on_this_machine_returns_a_coherent_truthful_answer():
    """No mocks. Asserts consistency, never a particular capability.

    This is the one test that touches the host's actual optional stack, and it
    deliberately passes on a machine with HEIC support and on one without.
    """
    capability = caps.heif_capability(refresh=True)
    assert isinstance(capability, caps.FormatCapability)
    assert capability.name == "heif"
    assert capability.suffixes == (".heic", ".heif")
    assert isinstance(capability.decode, bool)
    assert isinstance(capability.encode, bool)
    if capability.fully_supported:
        assert capability.detail == ""
    else:
        assert capability.detail, "anything less than full support must explain itself"


def test_the_real_extension_sets_always_contain_the_baseline_formats():
    caps.reset_cache()
    for offered in (caps.decodable_suffixes(), caps.encodable_suffixes()):
        assert offered[:3] == (".jpg", ".jpeg", ".png")
        assert set(offered) <= {".jpg", ".jpeg", ".png", ".heic", ".heif"}


# --------------------------------------------------------------------------- #
# Degraded startup: an absent codec stops nothing from importing.
# --------------------------------------------------------------------------- #


def test_the_capability_module_imports_no_optional_dependency_at_module_level():
    """Import-time work is what made the old probe unsafe. Prove it is gone."""
    import ast
    from pathlib import Path

    source = Path(caps.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level = {
        alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    }
    top_level.discard("")
    import sys

    for name in top_level:
        assert name in sys.stdlib_module_names, f"{name} must not be a module-level import"


def test_importing_the_cover_panel_works_without_heic_support(monkeypatch):
    """The panel's module must import even when the optional plugin explodes."""
    import builtins
    import importlib

    real_import = builtins.__import__

    def refuse_pillow_heif(name, *args, **kwargs):
        if name == "pillow_heif":
            raise ImportError("simulated: no pillow_heif on this machine")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_pillow_heif)
    caps.reset_cache()
    module = importlib.import_module("mp3_tools.cover_resizer")
    importlib.reload(module)
    assert module.REPLACEABLE_SUFFIXES == frozenset(
        {".jpg", ".jpeg", ".png", ".heic", ".heif"}
    )


# --------------------------------------------------------------------------- #
# The Cover panel consumes the probe rather than owning one.
# --------------------------------------------------------------------------- #


def test_the_cover_panel_no_longer_owns_a_bare_optional_import():
    """The centralization itself, checked structurally by AST."""
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent.parent
    panel = repo_root / "scripts" / "Universal" / "mp3_tools" / "cover_resizer.py"
    source = panel.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "pillow_heif" not in imported, "the optional import belongs to the shared probe"
    assert "register_heif_opener" not in source
    # And it does name the shared seam.
    shared_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "shared"
        for alias in node.names
    }
    assert "image_capabilities" in shared_imports


def test_the_replaceable_suffix_contract_is_unchanged():
    """§4.2 depends on this set and Phase 1 must not touch it."""
    from mp3_tools import cover_resizer

    assert cover_resizer.REPLACEABLE_SUFFIXES == frozenset(
        {".jpg", ".jpeg", ".png", ".heic", ".heif"}
    )


def test_written_suffix_behaviour_is_unchanged():
    """Static format knowledge, not runtime capability. Same answers as before."""
    from mp3_tools import cover_resizer

    for suffix in (".jpg", ".jpeg", ".png", ".heic", ".heif"):
        assert cover_resizer.written_suffix(suffix) == suffix
        assert cover_resizer.written_suffix(suffix.upper()) == suffix
    for suffix in (".webp", ".gif", ".bmp", "", ".tiff"):
        assert cover_resizer.written_suffix(suffix) == ".jpg"


def test_the_import_dialog_offers_exactly_what_the_probe_allows(monkeypatch):
    from mp3_tools import cover_resizer

    _pin(monkeypatch, decode=True, encode=True)
    assert cover_resizer._image_filetypes() == [
        ("Images", "*.jpg *.jpeg *.png *.heic *.heif"),
        ("All files", "*.*"),
    ]

    _pin(monkeypatch, decode=False, encode=False)
    assert cover_resizer._image_filetypes() == [
        ("Images", "*.jpg *.jpeg *.png"),
        ("All files", "*.*"),
    ]


def test_a_decode_only_machine_still_offers_heic_for_import(monkeypatch):
    from mp3_tools import cover_resizer

    _pin(monkeypatch, decode=True, encode=False)
    assert "*.heic" in cover_resizer._image_filetypes()[0][1]


# --------------------------------------------------------------------------- #
# The resizer refuses rather than substitutes.
# --------------------------------------------------------------------------- #


Image = pytest.importorskip("PIL.Image")


@pytest.fixture()
def tall_cover(tmp_path):
    path = tmp_path / "cover.jpg"
    Image.new("RGB", (200, 400), color=(200, 30, 30)).save(path, format="JPEG")
    return path


def test_a_heic_destination_fails_truthfully_when_encoding_is_unavailable(
    monkeypatch, tall_cover, tmp_path
):
    """Decision 3A, at the one place a substitution could happen."""
    from mp3_tools import cover_resizer

    _pin(monkeypatch, decode=True, encode=False)
    destination = tmp_path / "out.heic"
    with pytest.raises(caps.UnsupportedImageFormat):
        cover_resizer.resize_for_audiobook(tall_cover, destination, size=64, letterbox=True)
    assert not destination.exists()
    # The decisive assertion: no JPEG appeared under any name.
    assert not (tmp_path / "out.jpg").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cover.jpg"]


def test_no_silent_jpeg_substitution_for_either_heif_suffix(
    monkeypatch, tall_cover, tmp_path
):
    from mp3_tools import cover_resizer

    _pin(monkeypatch, decode=True, encode=False)
    for suffix in (".heic", ".heif"):
        destination = tmp_path / f"art{suffix}"
        with pytest.raises(caps.UnsupportedImageFormat):
            cover_resizer.resize_for_audiobook(
                tall_cover, destination, size=64, letterbox=True
            )
        assert not destination.with_suffix(".jpg").exists()


def test_an_unknown_extension_still_falls_back_to_jpg(monkeypatch, tall_cover, tmp_path):
    """Pre-existing, deliberate behaviour for formats the writer never claimed.

    Distinct from the HEIF case: ``.webp`` was never advertised as preserved, so
    falling back is not a broken promise. HEIC was, which is why it refuses.
    """
    from mp3_tools import cover_resizer

    _pin(monkeypatch, decode=False, encode=False)
    cover_resizer.resize_for_audiobook(
        tall_cover, tmp_path / "cover.webp", size=64, letterbox=True
    )
    assert (tmp_path / "cover.jpg").exists()


def test_jpg_and_png_output_is_unaffected_by_the_heif_capability(
    monkeypatch, tall_cover, tmp_path
):
    """No behaviour change for the formats Pillow always provides."""
    from mp3_tools import cover_resizer

    for decode, encode in ((True, True), (False, False)):
        _pin(monkeypatch, decode=decode, encode=encode)
        for name in ("out.jpg", "out.png"):
            written = cover_resizer.resize_for_audiobook(
                tall_cover, tmp_path / name, size=64, letterbox=True
            )
            with Image.open(written) as image:
                assert image.size == (64, 64)
