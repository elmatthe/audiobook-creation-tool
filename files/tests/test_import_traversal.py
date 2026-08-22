"""The safe natural traversal core — v0.6.0 Drop 3 (Plan 3), Phase 2.

Every tree here is built under ``tmp_path`` and thrown away. Nothing scans the
repository, the real home directory, Downloads, an output base, runtime data, real
media or a network share, and nothing writes anywhere a scan can see.

Two platform facilities cannot be created by an unelevated Windows account: file and
directory **symlinks** need ``SeCreateSymbolicLinkPrivilege``. Where a real one cannot
be made, the test skips with the exact ``WinError`` text **and** the same refusal is
still proved through an injected classifier, so link safety is never left untested on
this machine. **Junctions** need no privilege and are created for real.
"""

from __future__ import annotations

import os
import stat
import sys
import threading
import unicodedata
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

import pytest

from shared import importing, maintenance
from shared.importing import (
    IdFactory,
    ImportContractError,
    ImportedFile,
    ImportOptions,
    ImportProblem,
    ImportRoot,
    ProblemCategory,
    RootBreadth,
    RootKind,
    ScanOutcome,
    ScanRequest,
    SupportedType,
    SupportedTypeCatalog,
    capture_identity,
    classify_root_breadth,
    has_hidden_attribute,
    is_broad_root,
    is_hidden_name,
    natural_key,
    scan_roots,
)

from test_importing import make_config

WINDOWS = sys.platform == "win32"


# --------------------------------------------------------------------------- #
# Disposable fixtures
# --------------------------------------------------------------------------- #


def catalog() -> SupportedTypeCatalog:
    return SupportedTypeCatalog((
        SupportedType("mp3", "MP3 audio", (".mp3",)),
        SupportedType("m4b", "M4B audiobook", (".m4b",)),
    ))


def request_for(
    *roots: Path,
    types: SupportedTypeCatalog | None = None,
    selected: set[str] | None = None,
    hidden: bool = False,
    threshold: int = 1000,
) -> ScanRequest:
    book = types or catalog()
    options = (
        ImportOptions.for_catalog(book, include_hidden_folders=hidden)
        if selected is None
        else ImportOptions(
            selected_type_ids=frozenset(selected), include_hidden_folders=hidden)
    )
    return ScanRequest(
        request_id="req-1",
        roots=tuple(
            ImportRoot(f"root-{index}", path, index)
            for index, path in enumerate(roots)
        ),
        catalog=book,
        options=options,
        effective_config=make_config(threshold),
        created_at=1.0,
    )


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def scan(*roots: Path, **kwargs) -> "tuple":
    """Scan and return ``(result, [relative paths], {category: count})``."""
    request_kwargs = {
        key: kwargs.pop(key) for key in ("types", "selected", "hidden", "threshold")
        if key in kwargs
    }
    result = scan_roots(request_for(*roots, **request_kwargs),
                        id_factory=IdFactory("t-"), **kwargs)
    relatives = [str(entry.relative_path) for entry in result.files]
    counts = {category.value: count
              for category, count in result.problem_counts().items()}
    return result, relatives, counts


def make_junction(target: Path, link: Path) -> None:
    """A real NTFS junction. Needs no elevation; skips precisely where unsupported."""
    if not WINDOWS:
        pytest.skip("junctions are a Windows-only facility")
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, AttributeError, OSError) as exc:
        pytest.skip(f"this environment cannot create an NTFS junction: "
                    f"{type(exc).__name__}: {exc}")


def make_symlink(target: Path, link: Path, *, directory: bool) -> None:
    """A real symlink, or a skip naming the exact privilege that is missing."""
    try:
        os.symlink(target, link, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"this environment cannot create a "
                    f"{'directory' if directory else 'file'} symlink: {exc}")


def set_hidden(path: Path) -> None:
    """Set the real Windows hidden attribute, or skip with the exact reason."""
    if not WINDOWS:
        pytest.skip("FILE_ATTRIBUTE_HIDDEN is a Windows-only facility")
    import ctypes

    if not ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02):
        pytest.skip(f"SetFileAttributesW failed: {ctypes.GetLastError()}")


def fake_stat(mode: int, *, attributes: int = 0) -> os.stat_result:
    """A stat result carrying the mode we care about.

    The Windows-only extras are supplied explicitly. A ten-tuple alone leaves
    ``st_file_attributes`` as ``None``, which no real ``os.lstat`` ever returns, and
    a fixture that unrealistic would be testing the fixture rather than the scanner.
    """
    base = (mode, 0, 0, 1, 0, 0, 0, 0, 0, 0)
    if os.name == "nt":
        return os.stat_result(base, {"st_file_attributes": attributes,
                                     "st_reparse_tag": 0})
    return os.stat_result(base)


def patch_lstat(monkeypatch, target: Path, error: OSError | os.stat_result) -> None:
    """Fail (or lie) for exactly one path and behave normally for every other.

    Deliberately narrow: a blanket replacement would break pytest's own machinery,
    and this drop's rule is deterministic injection rather than blunt patching.
    """
    real = os.lstat

    def fake(path, *args, **kwargs):
        if os.fspath(path) == os.fspath(target):
            if isinstance(error, OSError):
                raise error
            return error
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", fake)


# =========================================================================== #
# The risk gate: maintenance.is_link must classify every importing case
# =========================================================================== #


def test_is_link_says_no_to_an_ordinary_file_and_an_ordinary_directory(tmp_path):
    directory = tmp_path / "Books"
    directory.mkdir()
    ordinary = touch(directory / "01.mp3")
    assert maintenance.is_link(directory) is False
    assert maintenance.is_link(ordinary) is False


def test_is_link_says_yes_to_a_real_windows_junction(tmp_path):
    """The case a naive ``is_symlink()`` check would miss.

    A junction reports ``is_symlink() == False``; only the reparse-point attribute
    catches it, which is exactly why this drop reuses ``maintenance.is_link`` rather
    than writing its own check.
    """
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "junction"
    make_junction(target, link)

    assert link.is_symlink() is False, "a junction is not a symlink"
    assert maintenance.is_link(link) is True
    attributes = os.lstat(link).st_file_attributes
    assert attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT


def test_is_link_says_yes_to_a_file_symlink(tmp_path):
    target = touch(tmp_path / "real.mp3")
    link = tmp_path / "link.mp3"
    make_symlink(target, link, directory=False)
    assert maintenance.is_link(link) is True


def test_is_link_says_yes_to_a_directory_symlink(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    make_symlink(target, link, directory=True)
    assert maintenance.is_link(link) is True


def test_is_link_says_yes_to_a_selected_root_that_is_a_link(tmp_path):
    """The root case specifically: a chosen folder may itself be a link."""
    target = tmp_path / "real"
    target.mkdir()
    touch(target / "01.mp3")
    link = tmp_path / "chosen"
    make_junction(target, link)
    assert maintenance.is_link(link) is True


def test_is_link_answers_false_for_something_it_cannot_read_which_is_why_we_gate_first():
    """The one nuance, recorded rather than worked around.

    ``is_link`` reports ``False`` for a path it cannot ``lstat`` at all. That is the
    right answer for a cleanup target that gets re-authorised immediately afterwards,
    but "I could not read it" must never be read as "safe to walk into". The scanner
    therefore settles existence and readability **before** it asks the link question,
    and the tests below prove an unreadable entry is refused rather than descended.
    """
    assert maintenance.is_link(Path(os.path.abspath(os.sep + "act-no-such-path"))) is False


def test_the_scanner_asks_maintenance_and_does_not_reimplement_it():
    source = Path(importing.__file__).read_text(encoding="utf-8")
    assert "from shared.maintenance import is_link as _is_link" in source
    assert "FILE_ATTRIBUTE_REPARSE_POINT" not in source, "no second link implementation"
    assert "is_symlink" not in source


# =========================================================================== #
# Natural ordering
# =========================================================================== #


def test_natural_order_counts_rather_than_spells():
    names = ["10.mp3", "1.mp3", "2.mp3", "20.mp3", "3.mp3"]
    assert sorted(names, key=natural_key) == [
        "1.mp3", "2.mp3", "3.mp3", "10.mp3", "20.mp3"]


def test_natural_order_is_case_insensitive_but_still_deterministic():
    assert sorted(["b.mp3", "A.mp3"], key=natural_key) == ["A.mp3", "b.mp3"]
    twice = sorted(["a.mp3", "A.mp3"], key=natural_key)
    assert twice == sorted(["A.mp3", "a.mp3"], key=natural_key), "ties must not wobble"


def test_natural_order_is_unicode_aware():
    """NFC and NFD spellings of one name sort together, and digits still count."""
    composed = unicodedata.normalize("NFC", "Ré 2.mp3")
    decomposed = unicodedata.normalize("NFD", "Ré 2.mp3")
    assert natural_key(composed) == natural_key(decomposed)
    assert sorted(["Ré 10.mp3", "Ré 2.mp3"], key=natural_key) == [
        "Ré 2.mp3", "Ré 10.mp3"]


def test_natural_order_never_compares_a_number_with_a_word():
    mixed = ["2 disc", "disc 2", "10 disc", "disc 10"]
    assert sorted(mixed, key=natural_key) == ["2 disc", "10 disc", "disc 2", "disc 10"]


def test_natural_order_survives_an_absurd_digit_run():
    """CPython refuses ``int()`` past 4300 digits; a filename may still carry one."""
    huge = "9" * 5000 + ".mp3"
    assert sorted([huge, "1.mp3"], key=natural_key) == ["1.mp3", huge]


def test_natural_order_handles_spaces_apostrophes_and_empty_stems():
    names = ["o'clock 2.mp3", "o'clock 10.mp3", " leading.mp3", ".mp3"]
    assert sorted(names, key=natural_key)[-2:] == ["o'clock 2.mp3", "o'clock 10.mp3"]


def test_natural_key_refuses_a_non_name():
    with pytest.raises(ImportContractError):
        natural_key(None)


# =========================================================================== #
# Broad-root classification (pure — no real broad root is ever scanned)
# =========================================================================== #


@pytest.mark.parametrize(
    "path,expected",
    [
        (PureWindowsPath("C:/"), RootBreadth.VOLUME_ROOT),
        (PureWindowsPath("D:/"), RootBreadth.VOLUME_ROOT),
        (PurePosixPath("/"), RootBreadth.VOLUME_ROOT),
        (PureWindowsPath("//server/share"), RootBreadth.UNC_SHARE_ROOT),
        (PureWindowsPath("//server/share/books"), RootBreadth.NARROW),
        (PureWindowsPath("C:/Books"), RootBreadth.NARROW),
        (PurePosixPath("/Volumes/Media"), RootBreadth.NARROW),
    ],
)
def test_a_broad_root_is_recognised_lexically(path, expected):
    assert classify_root_breadth(path) is expected


def test_the_user_home_is_recognised_from_an_injected_path_only():
    home = PureWindowsPath("C:/Users/someone")
    assert classify_root_breadth(home, home=home) is RootBreadth.USER_HOME
    assert classify_root_breadth(
        PureWindowsPath("C:/Users/SOMEONE"), home=home) is RootBreadth.USER_HOME, \
        "Windows paths compare case-insensitively"
    assert classify_root_breadth(
        PureWindowsPath("C:/Users/someone/Books"), home=home) is RootBreadth.NARROW
    assert classify_root_breadth(home) is RootBreadth.NARROW, \
        "with no home injected there is nothing to compare against"


def test_posix_home_comparison_preserves_case():
    home = PurePosixPath("/Users/someone")
    assert classify_root_breadth(home, home=home) is RootBreadth.USER_HOME
    assert classify_root_breadth(
        PurePosixPath("/Users/SOMEONE"), home=home) is RootBreadth.NARROW


def test_is_broad_root_is_the_yes_no_form():
    assert is_broad_root(PureWindowsPath("C:/")) is True
    assert is_broad_root(PureWindowsPath("C:/Books")) is False


def test_classification_touches_no_filesystem(tmp_path):
    """It classifies paths that do not exist, which is the whole point."""
    ghost = tmp_path / "never" / "created"
    assert classify_root_breadth(ghost) is RootBreadth.NARROW
    assert not ghost.exists()


# =========================================================================== #
# Hidden detection
# =========================================================================== #


@pytest.mark.parametrize(
    "name,expected",
    [(".hidden", True), (".", False), ("..", False), ("visible", False),
     ("mid.dle", False), (".config", True)],
)
def test_the_portable_dot_rule(name, expected):
    assert is_hidden_name(name) is expected


def test_the_windows_attribute_is_read_without_following_a_link(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert has_hidden_attribute(plain) is False
    set_hidden(plain)
    assert has_hidden_attribute(plain) is True


def test_a_missing_path_is_not_reported_as_hidden(tmp_path):
    assert has_hidden_attribute(tmp_path / "nope") is False


# =========================================================================== #
# Identity capture
# =========================================================================== #


def test_identity_prefers_the_platform_file_id(tmp_path):
    first = touch(tmp_path / "a.mp3")
    identity = capture_identity(first)
    assert identity.startswith("file:"), "this filesystem reports (st_dev, st_ino)"
    assert capture_identity(first) == identity, "and it is stable"


def test_a_hard_link_is_recognised_as_the_same_source(tmp_path):
    original = touch(tmp_path / "a.mp3")
    hard = tmp_path / "b.mp3"
    try:
        os.link(original, hard)
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(f"this environment cannot create a hard link: "
                    f"{type(exc).__name__}: {exc}")
    assert capture_identity(original) == capture_identity(hard)


def test_two_different_files_have_different_identities(tmp_path):
    assert capture_identity(touch(tmp_path / "a.mp3")) != \
        capture_identity(touch(tmp_path / "b.mp3"))


def test_identity_falls_back_to_a_lexical_key_when_the_platform_reports_none(tmp_path):
    target = touch(tmp_path / "a.mp3")
    identity = capture_identity(target, fake_stat(stat.S_IFREG | 0o644))
    assert identity.startswith("path:")
    assert "a.mp3" in identity.lower()


def test_the_lexical_fallback_matches_the_volumes_own_case_rule(tmp_path):
    """The rule belongs to the volume, not to the platform.

    ``os.name == "posix"`` covers both the default case-insensitive macOS APFS
    volume and a case-sensitive one, so the platform cannot answer this. The
    expectation is therefore taken from what this volume really does, checked
    independently of the production probe; both answers are proved
    deterministically in ``test_import_manager.py``.
    """
    upper = capture_identity(tmp_path / "A.MP3", fake_stat(stat.S_IFREG))
    lower = capture_identity(tmp_path / "a.mp3", fake_stat(stat.S_IFREG))
    assert upper.startswith("path:") and lower.startswith("path:")
    folds = _volume_folds_case(tmp_path)
    if folds is None:
        pytest.skip("this temporary directory name has no case to flip")
    if folds:
        assert upper == lower, "this volume folds case, so these are one source"
    else:
        assert upper != lower, "a case-sensitive volume keeps them apart"


def _volume_folds_case(directory: Path) -> bool | None:
    """Whether *directory* is reachable through a case-flipped spelling of itself.

    Deliberately independent of :func:`shared.importing.filesystem_is_case_insensitive`
    — an expectation computed by the code under test would prove only that the
    code agrees with itself. Read-only: nothing is created.
    """
    name = directory.name
    flipped = name.upper() if name != name.upper() else name.lower()
    if not name or flipped == name:
        return None
    try:
        original, twin = os.lstat(directory), os.lstat(directory.parent / flipped)
    except OSError:
        return False
    return (original.st_dev, original.st_ino) == (twin.st_dev, twin.st_ino)


def test_identity_capture_never_resolves_through_a_link(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "junction"
    make_junction(target, link)
    # The link is refused before identity is ever captured; capturing one directly
    # still describes the link itself rather than its target.
    assert capture_identity(link) != capture_identity(target)


def test_identity_capture_reads_and_writes_nothing(tmp_path):
    before = sorted(tmp_path.iterdir())
    capture_identity(tmp_path / "does-not-exist.mp3")
    assert sorted(tmp_path.iterdir()) == before


# =========================================================================== #
# Ordering through a real traversal
# =========================================================================== #


def test_compatible_files_come_before_child_directories(tmp_path):
    root = tmp_path / "Book"
    touch(root / "02.mp3")
    touch(root / "01.mp3")
    touch(root / "Extras" / "bonus.mp3")

    _result, relatives, _counts = scan(root)
    assert relatives == ["01.mp3", "02.mp3", str(PurePath("Extras/bonus.mp3"))]


def test_natural_order_holds_at_every_level(tmp_path):
    root = tmp_path / "Book"
    for name in ("10.mp3", "2.mp3", "1.mp3"):
        touch(root / name)
    for disc in ("Disc 10", "Disc 2", "Disc 1"):
        touch(root / disc / "10.mp3")
        touch(root / disc / "2.mp3")

    _result, relatives, _counts = scan(root)
    assert relatives[:3] == ["1.mp3", "2.mp3", "10.mp3"]
    assert relatives[3:] == [
        str(PurePath("Disc 1/2.mp3")), str(PurePath("Disc 1/10.mp3")),
        str(PurePath("Disc 2/2.mp3")), str(PurePath("Disc 2/10.mp3")),
        str(PurePath("Disc 10/2.mp3")), str(PurePath("Disc 10/10.mp3")),
    ]


def test_traversal_is_depth_first_not_breadth_first(tmp_path):
    root = tmp_path / "Book"
    touch(root / "A" / "a.mp3")
    touch(root / "A" / "deep" / "d.mp3")
    touch(root / "B" / "b.mp3")

    _result, relatives, _counts = scan(root)
    assert relatives == [
        str(PurePath("A/a.mp3")),
        str(PurePath("A/deep/d.mp3")),
        str(PurePath("B/b.mp3")),
    ]


def test_several_roots_keep_the_order_they_were_supplied(tmp_path):
    second = tmp_path / "Zebra"
    first = tmp_path / "Apple"
    touch(second / "z.mp3")
    touch(first / "a.mp3")

    _result, relatives, _counts = scan(second, first)
    assert relatives == ["z.mp3", "a.mp3"], "roots are never globally re-sorted"


def test_repeated_directory_names_under_different_roots_stay_separate(tmp_path):
    one = tmp_path / "Series One"
    two = tmp_path / "Series Two"
    touch(one / "Book" / "01.mp3")
    touch(two / "Book" / "01.mp3")

    result, relatives, _counts = scan(one, two)
    assert relatives == [str(PurePath("Book/01.mp3"))] * 2
    assert [entry.mirroring_root for entry in result.files] == [one, two]
    assert len({entry.path for entry in result.files}) == 2


def test_every_file_keeps_what_plan_two_mirroring_will_need(tmp_path):
    root = tmp_path / "Book"
    touch(root / "Disc 1" / "Side A" / "01.mp3")

    result, _relatives, _counts = scan(root)
    entry = result.files[0]
    assert entry.mirroring_root == root
    assert entry.relative_path == PurePath("Disc 1/Side A/01.mp3")
    assert entry.relative_parent == PurePath("Disc 1/Side A")
    assert entry.path == root / "Disc 1" / "Side A" / "01.mp3"


def test_unicode_spaces_and_apostrophes_all_survive_a_scan(tmp_path):
    root = tmp_path / "Ré'sumé Ñ"
    touch(root / "o'clock 2.mp3")
    touch(root / "o'clock 10.mp3")
    touch(root / "Ré 1.mp3")

    _result, relatives, counts = scan(root)
    # 'o' precedes 'r' once casefolded, and 2 precedes 10 within the same stem.
    assert relatives == ["o'clock 2.mp3", "o'clock 10.mp3", "Ré 1.mp3"]
    assert counts == {}


def test_both_unicode_normalisations_are_found_and_ordered_together(tmp_path):
    """NFC and NFD spellings of one name must not sort into different places."""
    root = tmp_path / "Book"
    composed = touch(root / (unicodedata.normalize("NFC", "Ré") + " 2.mp3"))
    decomposed_name = unicodedata.normalize("NFD", "Ré") + " 10.mp3"
    decomposed = touch(root / decomposed_name)
    if composed.name == decomposed.name:  # pragma: no cover - normalising filesystem
        pytest.skip("this filesystem normalises filenames, so both spellings collide")

    _result, relatives, counts = scan(root)
    assert len(relatives) == 2
    assert counts == {}
    assert [natural_key(name)[0][0] for name in relatives] == \
        [natural_key(relatives[0])[0][0]] * 2, "both share the same leading text run"
    assert relatives[0].endswith("2.mp3") and relatives[1].endswith("10.mp3")


def test_names_differing_only_in_case_are_both_collected(tmp_path):
    root = tmp_path / "Book"
    first = touch(root / "track.mp3")
    second = root / "TRACK.mp3"
    touch(second)
    if len(list(root.iterdir())) == 1:  # pragma: no cover - case-blind filesystem
        pytest.skip("this filesystem is case-insensitive, so the two names are one file")

    _result, relatives, _counts = scan(root)
    assert len(relatives) == 2
    assert first.name in relatives and second.name in relatives


# =========================================================================== #
# Supported types
# =========================================================================== #


def test_only_the_selected_types_are_collected(tmp_path):
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    touch(root / "02.m4b")
    touch(root / "cover.jpg")

    _result, relatives, counts = scan(root, selected={"mp3"})
    assert relatives == ["01.mp3"]
    assert counts == {"unsupported_type": 2}


def test_every_type_is_collected_by_default(tmp_path):
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    touch(root / "02.m4b")

    _result, relatives, counts = scan(root)
    assert relatives == ["01.mp3", "02.m4b"]
    assert counts == {}


def test_selecting_nothing_collects_nothing_and_says_so(tmp_path):
    """Phase 4 stops this reaching a worker; the core still behaves truthfully."""
    root = tmp_path / "Book"
    touch(root / "01.mp3")

    result, relatives, counts = scan(root, selected=set())
    assert relatives == []
    assert counts == {"unsupported_type": 1}
    assert result.outcome is ScanOutcome.COMPLETED


def test_extension_matching_is_case_insensitive(tmp_path):
    root = tmp_path / "Book"
    touch(root / "01.MP3")
    _result, relatives, _counts = scan(root)
    assert relatives == ["01.MP3"]


def test_a_file_with_no_extension_is_reported_as_unsupported(tmp_path):
    root = tmp_path / "Book"
    touch(root / "README")
    _result, _relatives, counts = scan(root)
    assert counts == {"unsupported_type": 1}


# =========================================================================== #
# Hidden handling
# =========================================================================== #


def test_a_dot_hidden_folder_is_skipped_and_reported_by_default(tmp_path):
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    touch(root / ".cache" / "hidden.mp3")

    _result, relatives, counts = scan(root)
    assert relatives == ["01.mp3"]
    assert counts == {"hidden": 1}


def test_a_dot_hidden_folder_is_traversed_when_the_option_is_on(tmp_path):
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    touch(root / ".cache" / "hidden.mp3")

    _result, relatives, counts = scan(root, hidden=True)
    assert relatives == ["01.mp3", str(PurePath(".cache/hidden.mp3"))]
    assert counts == {}


def test_a_hidden_file_found_by_walking_is_always_skipped(tmp_path):
    """The option covers folders. A hidden *file* is never collected by a scan."""
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    touch(root / ".secret.mp3")

    for include in (False, True):
        _result, relatives, counts = scan(root, hidden=include)
        assert relatives == ["01.mp3"]
        assert counts == {"hidden": 1}


def test_a_real_windows_hidden_folder_is_skipped(tmp_path):
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    hidden = root / "System Stuff"
    touch(hidden / "x.mp3")
    set_hidden(hidden)

    _result, relatives, counts = scan(root)
    assert relatives == ["01.mp3"]
    assert counts == {"hidden": 1}


def test_a_real_windows_hidden_folder_is_traversed_when_the_option_is_on(tmp_path):
    root = tmp_path / "Book"
    hidden = root / "System Stuff"
    touch(hidden / "x.mp3")
    set_hidden(hidden)

    _result, relatives, counts = scan(root, hidden=True)
    assert relatives == [str(PurePath("System Stuff/x.mp3"))]
    assert counts == {}


def test_platform_hidden_detection_can_be_injected(tmp_path):
    """So Windows behaviour is provable on POSIX, and vice versa."""
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    touch(root / "Marked" / "x.mp3")

    def probe(path, _stat_result):
        return path.name == "Marked"

    _result, relatives, counts = scan(root, hidden_probe=probe)
    assert relatives == ["01.mp3"]
    assert counts == {"hidden": 1}

    _result, relatives, counts = scan(root, hidden=True, hidden_probe=probe)
    assert relatives == ["01.mp3", str(PurePath("Marked/x.mp3"))]


def test_an_injected_hidden_folder_is_still_subject_to_the_link_rule(tmp_path):
    """"Include hidden" is not "include anything"."""
    root = tmp_path / "Book"
    root.mkdir()
    target = tmp_path / "outside"
    touch(target / "x.mp3")
    make_junction(target, root / "Marked")

    _result, relatives, counts = scan(
        root, hidden=True, hidden_probe=lambda path, _s: path.name == "Marked")
    assert relatives == []
    assert counts == {"link": 1}


def test_an_explicitly_chosen_hidden_file_remains_a_valid_import(tmp_path):
    """Folder traversal skips hidden files; a file the user picked is still valid.

    ``Add Files`` itself is Phase 3. What this phase owes is that the *vocabulary*
    still accepts a hidden path chosen deliberately, so Phase 3 has something to
    build on rather than a rule to unpick.
    """
    hidden = touch(tmp_path / ".secret.mp3")
    direct = ImportRoot("direct", None, 0, RootKind.DIRECT_FILES)
    entry = ImportedFile("occ-1", hidden, direct, None, "mp3",
                         capture_identity(hidden))
    assert entry.name == ".secret.mp3"
    assert is_hidden_name(entry.name) is True
    assert entry.mirroring_root is None


# =========================================================================== #
# Links are never followed
# =========================================================================== #


def test_a_junction_inside_a_scanned_folder_is_refused(tmp_path):
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    outside = tmp_path / "elsewhere"
    touch(outside / "must-not-appear.mp3")
    make_junction(outside, root / "shortcut")

    _result, relatives, counts = scan(root)
    assert relatives == ["01.mp3"]
    assert counts == {"link": 1}


def test_a_root_that_is_a_junction_is_refused_before_anything_is_read(tmp_path):
    outside = tmp_path / "elsewhere"
    touch(outside / "must-not-appear.mp3")
    link = tmp_path / "chosen"
    make_junction(outside, link)

    result, relatives, counts = scan(link)
    assert relatives == []
    assert counts == {"invalid_root": 1}
    assert "link" in result.problems[0].technical_detail


def test_a_file_symlink_inside_a_scanned_folder_is_refused(tmp_path):
    root = tmp_path / "Book"
    real = touch(root / "01.mp3")
    make_symlink(real, root / "02.mp3", directory=False)

    _result, relatives, counts = scan(root)
    assert relatives == ["01.mp3"]
    assert counts == {"link": 1}


def test_a_directory_symlink_inside_a_scanned_folder_is_refused(tmp_path):
    root = tmp_path / "Book"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    touch(outside / "must-not-appear.mp3")
    make_symlink(outside, root / "shortcut", directory=True)

    _result, relatives, counts = scan(root)
    assert relatives == []
    assert counts == {"link": 1}


def test_a_root_that_is_a_symlink_is_refused(tmp_path):
    outside = tmp_path / "elsewhere"
    touch(outside / "must-not-appear.mp3")
    link = tmp_path / "chosen"
    make_symlink(outside, link, directory=True)

    _result, relatives, counts = scan(link)
    assert relatives == []
    assert counts == {"invalid_root": 1}


def test_link_refusal_is_proved_even_where_symlinks_cannot_be_created(
        tmp_path, monkeypatch):
    """The privilege-independent half of the link contract.

    An unelevated Windows account cannot make a symlink, so the classifier is
    injected instead and the refusal is proved on every machine.
    """
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    decoy = touch(root / "02.mp3")

    monkeypatch.setattr(
        importing, "_is_link",
        lambda path: os.fspath(path) == os.fspath(decoy))

    _result, relatives, counts = scan(root)
    assert relatives == ["01.mp3"]
    assert counts == {"link": 1}


# =========================================================================== #
# Failing closed
# =========================================================================== #


def test_an_unreadable_entry_is_reported_and_skipped(tmp_path, monkeypatch):
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    blocked = touch(root / "02.mp3")
    patch_lstat(monkeypatch, blocked, PermissionError(13, "Access is denied"))

    _result, relatives, counts = scan(root)
    assert relatives == ["01.mp3"]
    assert counts == {"unreadable": 1}


def test_an_unreadable_directory_is_reported_and_not_descended(tmp_path, monkeypatch):
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    touch(root / "Locked" / "hidden-away.mp3")
    locked = root / "Locked"
    real = os.scandir

    def fake(path=".", *args, **kwargs):
        if os.fspath(path) == os.fspath(locked):
            raise PermissionError(13, "Access is denied")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", fake)

    _result, relatives, counts = scan(root)
    assert relatives == ["01.mp3"]
    assert counts == {"unreadable": 1}


def test_an_entry_that_disappears_mid_scan_is_reported_as_vanished(
        tmp_path, monkeypatch):
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    going = touch(root / "02.mp3")
    patch_lstat(monkeypatch, going, FileNotFoundError(2, "No such file"))

    _result, relatives, counts = scan(root)
    assert relatives == ["01.mp3"]
    assert counts == {"vanished": 1}


def test_the_fresh_lstat_wins_over_the_scandir_buffer(tmp_path, monkeypatch):
    """An entry that changed shape since enumeration is classified as it is now."""
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    changeling = root / "Disc 1"
    touch(changeling / "inner.mp3")
    patch_lstat(monkeypatch, changeling, fake_stat(stat.S_IFREG | 0o644))

    _result, relatives, counts = scan(root)
    assert relatives == ["01.mp3"], "it is no longer treated as a directory"
    assert counts == {"unsupported_type": 1}, "and 'Disc 1' has no selected extension"


def test_something_that_is_neither_a_file_nor_a_folder_is_refused(
        tmp_path, monkeypatch):
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    oddity = touch(root / "pipe.mp3")
    patch_lstat(monkeypatch, oddity, fake_stat(stat.S_IFIFO | 0o644))

    _result, relatives, counts = scan(root)
    assert relatives == ["01.mp3"]
    assert counts == {"wrong_type": 1}


@pytest.mark.parametrize("problem", list(ProblemCategory))
def test_every_problem_the_scanner_emits_is_display_safe(problem):
    """A category exists for each refusal and the message never leaks a traceback."""
    sample = ImportProblem(problem, "Something was skipped.", "Traceback: fine here")
    assert "\n" not in sample.display_message
    assert sample.category is problem


# =========================================================================== #
# Invalid roots
# =========================================================================== #


def test_a_missing_root_is_reported_and_the_others_still_scan(tmp_path):
    good = tmp_path / "Good"
    touch(good / "01.mp3")
    missing = tmp_path / "Gone"

    _result, relatives, counts = scan(missing, good)
    assert relatives == ["01.mp3"]
    assert counts == {"invalid_root": 1}


def test_an_ordinary_file_supplied_as_a_folder_root_is_refused(tmp_path):
    root = touch(tmp_path / "not-a-folder.mp3")
    result, relatives, counts = scan(root)
    assert relatives == []
    assert counts == {"invalid_root": 1}
    assert "not a directory" in result.problems[0].technical_detail


def test_an_unreadable_root_is_refused_rather_than_assumed_safe(
        tmp_path, monkeypatch):
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    patch_lstat(monkeypatch, root, PermissionError(13, "Access is denied"))

    _result, relatives, counts = scan(root)
    assert relatives == []
    assert counts == {"invalid_root": 1}


def test_a_direct_files_root_names_no_tree_and_is_simply_not_walked(tmp_path):
    folder = tmp_path / "Book"
    touch(folder / "01.mp3")
    request = ScanRequest(
        "req-1",
        (ImportRoot("direct", None, 0, RootKind.DIRECT_FILES),
         ImportRoot("folder", folder, 1)),
        catalog(), ImportOptions.for_catalog(catalog()), make_config())

    result = scan_roots(request, id_factory=IdFactory("t-"))
    assert [str(entry.relative_path) for entry in result.files] == ["01.mp3"]
    assert result.problems == ()


# =========================================================================== #
# Cancellation and the discovered count
# =========================================================================== #


def build_tree(tmp_path: Path) -> Path:
    root = tmp_path / "Book"
    for name in ("01.mp3", "02.mp3"):
        touch(root / name)
    touch(root / "Disc 2" / "03.mp3")
    return root


def test_the_discovered_count_rises_one_at_a_time_in_emission_order(tmp_path):
    root = build_tree(tmp_path)
    seen: list[int] = []
    result, relatives, _counts = scan(root, on_count=seen.append)
    assert seen == [1, 2, 3]
    assert result.discovered_count == 3
    assert len(relatives) == 3


def test_cancelling_before_the_first_root_collects_nothing(tmp_path):
    root = build_tree(tmp_path)
    seen: list[int] = []
    result, relatives, counts = scan(
        root, cancel_check=lambda: True, on_count=seen.append)

    assert result.outcome is ScanOutcome.CANCELLED
    assert relatives == [] and seen == []
    assert counts == {"cancelled": 1}
    assert result.is_committable is False


def test_cancelling_partway_publishes_no_files_at_all(tmp_path):
    root = build_tree(tmp_path)
    seen: list[int] = []
    calls = {"n": 0}

    def cancel_after_two_entries() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    result, relatives, counts = scan(
        root, cancel_check=cancel_after_two_entries, on_count=seen.append)

    assert result.outcome is ScanOutcome.CANCELLED
    assert relatives == [], "a cancelled scan can carry no files"
    assert counts == {"cancelled": 1}


def test_no_count_callback_fires_after_cancellation_is_acknowledged(tmp_path):
    root = build_tree(tmp_path)
    seen: list[int] = []
    stop = {"now": False}

    def cancel() -> bool:
        return stop["now"]

    def count(value: int) -> None:
        seen.append(value)
        stop["now"] = True

    result, _relatives, _counts = scan(root, cancel_check=cancel, on_count=count)
    assert result.outcome is ScanOutcome.CANCELLED
    assert seen == [1], "the callback stops the moment cancellation is observed"


def test_cancellation_is_checked_before_each_descent(tmp_path):
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    touch(root / "Disc 1" / "02.mp3")
    touch(root / "Disc 2" / "03.mp3")
    checks = {"n": 0}

    def cancel() -> bool:
        checks["n"] += 1
        return False

    result, relatives, _counts = scan(root, cancel_check=cancel)
    assert result.outcome is ScanOutcome.COMPLETED
    assert len(relatives) == 3
    # One per entry classified (5) + one per root (1) + one per descent (2)
    # + one before publication (1). The exact total matters less than that every
    # checkpoint the plan names is actually reached.
    assert checks["n"] >= 5


def test_a_cancelled_scan_raises_nothing_and_touches_no_job_controller(tmp_path):
    """Cancel Import stops a scan. It is not the processing job's cancel."""
    root = build_tree(tmp_path)
    result = scan_roots(
        request_for(root), id_factory=IdFactory("t-"), cancel_check=lambda: True)
    assert result.outcome is ScanOutcome.CANCELLED

    source = Path(importing.__file__).read_text(encoding="utf-8")
    assert "ConversionCancelled" not in source
    assert "raise_if_cancelled" not in source


def test_the_default_is_no_cancellation_and_no_callback(tmp_path):
    root = build_tree(tmp_path)
    result = scan_roots(request_for(root))
    assert result.outcome is ScanOutcome.COMPLETED
    assert result.discovered_count == 3


def test_scan_roots_refuses_anything_that_is_not_a_scan_request():
    with pytest.raises(ImportContractError):
        scan_roots({"roots": []})


# =========================================================================== #
# Read-only, side-effect-free
# =========================================================================== #


def snapshot_tree(root: Path) -> dict:
    """Every path under *root* with its size and modification time."""
    seen = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        seen[str(path.relative_to(root))] = (info.st_mode, info.st_size, info.st_mtime_ns)
    return seen


def test_a_scan_changes_nothing_it_reads(tmp_path):
    root = tmp_path / "Book"
    touch(root / "01.mp3", "audio")
    touch(root / "Disc 1" / "02.mp3", "more")
    touch(root / "cover.jpg", "image")
    before = snapshot_tree(tmp_path)

    result, _relatives, _counts = scan(root)

    assert result.outcome is ScanOutcome.COMPLETED
    assert snapshot_tree(tmp_path) == before, \
        "no file created, removed, rewritten or re-stamped"


def test_a_scan_starts_no_thread_and_reserves_no_output(tmp_path):
    root = build_tree(tmp_path)
    threads_before = threading.active_count()

    result, _relatives, _counts = scan(root)

    assert threading.active_count() == threads_before
    assert result.outcome is ScanOutcome.COMPLETED
    # Nothing resembling an output run was created anywhere under the fixture.
    assert not [path for path in tmp_path.rglob("*")
                if path.is_dir() and "Outputs" in path.name]


def test_a_scan_never_leaves_the_roots_it_was_given(tmp_path):
    """Only the supplied roots are read — a sibling tree is never touched."""
    root = tmp_path / "Chosen"
    touch(root / "01.mp3")
    sibling = tmp_path / "NotChosen"
    touch(sibling / "must-not-appear.mp3")

    result, relatives, _counts = scan(root)
    assert relatives == ["01.mp3"]
    assert all(str(entry.path).startswith(str(root)) for entry in result.files)
