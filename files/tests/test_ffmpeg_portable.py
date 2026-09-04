"""PRE-PLAN-6 Phase 3 — safe acquisition of the pinned portable FFmpeg build.

**What was wrong.** The fallback fetched BtbN's ``master-latest`` archive — a URL
floating on two axes, whose bytes change on every upstream commit — with
``urlretrieve`` straight into the live ``files/bin``, verified nothing, then
wrote ``ffmpeg.exe`` and ``ffprobe.exe`` there as two independent writes and
called it success if ``ffmpeg.exe`` merely existed. An interruption could leave
one half of one build beside one half of another; a stale ``ffmpeg.exe`` could
make a download that extracted nothing look successful; and an attempt to
replace a working pair could destroy it.

**Two pins, two claims.** The source pin — version, asset, URL, SHA-256 — says
only *these bytes are the reviewed Gyan 9.0.1 full build*. It says nothing about
whether the executables run. That is the runtime pin, owned by ``ffmpeg_health``
and established by actually executing both halves. Neither substitutes for the
other, and ``ensure_ready`` still re-proves the active pair later. These tests
hold that line, because collapsing two durable artifacts into one claim is the
mistake this drop has already had to correct twice.

Nothing here downloads the real 251 MB asset. Fixture archives are a few
hundred bytes, the fetcher is stubbed, and every path is redirected into
``tmp_path`` before the first write.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared import ffmpeg_health, ffmpeg_portable  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BUILD = ffmpeg_portable.PORTABLE_FFMPEG_BUILD_DIR


class _Log:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, text: str) -> None:
        self.lines.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


# --------------------------------------------------------------------------- #
#  Isolation: every root that Phase 3 can write is redirected into tmp_path.
# --------------------------------------------------------------------------- #
@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    files = tmp_path / "files"
    resources = files / "runtime-data"
    bin_dir = files / "bin"
    resources.mkdir(parents=True)
    bin_dir.mkdir(parents=True)

    monkeypatch.setattr(ffmpeg_portable, "RESOURCES_DIR", resources)
    monkeypatch.setattr(ffmpeg_portable, "BIN_DIR", bin_dir)
    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", resources)
    monkeypatch.setattr(ffmpeg_health, "BIN_DIR", bin_dir)
    # PATH-based discovery must not wander into the real machine.
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    return SimpleNamespace(tmp=tmp_path, files=files,
                           resources=resources, bin_dir=bin_dir)


def _exe(name: str) -> str:
    return name + ffmpeg_health.EXE


def _archive_bytes(*, members: dict | None = None, build: str = BUILD,
                   with_ffmpeg=True, with_ffprobe=True) -> bytes:
    """A tiny stand-in for the Gyan archive, in the real layout."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(f"{build}/README.txt", "fixture")
        if with_ffmpeg:
            zf.writestr(f"{build}/bin/{_exe('ffmpeg')}", "ffmpeg-bytes")
        if with_ffprobe:
            zf.writestr(f"{build}/bin/{_exe('ffprobe')}", "ffprobe-bytes")
        for name, data in (members or {}).items():
            zf.writestr(name, data)
    return buffer.getvalue()


def _pin(monkeypatch, payload: bytes) -> str:
    """Point the source pin at fixture bytes and return their digest."""
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(ffmpeg_portable, "PORTABLE_FFMPEG_SHA256", digest)
    monkeypatch.setattr(ffmpeg_portable, "PORTABLE_FFMPEG_SIZE", len(payload))
    return digest


class _Response:
    """Minimal urlopen stand-in: a context manager with ``read(n)``."""

    def __init__(self, payload: bytes, *, fail_after: int | None = None):
        self._stream = io.BytesIO(payload)
        self._fail_after = fail_after
        self._served = 0

    def read(self, size):
        if self._fail_after is not None and self._served >= self._fail_after:
            raise OSError("connection reset")
        block = self._stream.read(size)
        self._served += len(block)
        return block

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(payload: bytes, **kwargs):
    def open_url(url):
        return _Response(payload, **kwargs)
    return open_url


def _runner(ok=True):
    """A prove_pair runner: (ok, detail) per executable, never a real spawn."""
    def run(executable):
        return (True, "ffmpeg version 9.0.1") if ok else (False, "blocked")
    return run


def _install_pair(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / _exe("ffmpeg")).write_text("a", encoding="utf-8")
    (directory / _exe("ffprobe")).write_text("b", encoding="utf-8")


# --------------------------------------------------------------------------- #
# A. The source pin
# --------------------------------------------------------------------------- #
def test_the_pinned_source_is_the_reviewed_gyan_build():
    assert ffmpeg_portable.PORTABLE_FFMPEG_VERSION == "9.0.1"
    assert ffmpeg_portable.PORTABLE_FFMPEG_ASSET == "ffmpeg-9.0.1-full_build.zip"
    assert ffmpeg_portable.PORTABLE_FFMPEG_URL == (
        "https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/"
        "ffmpeg-9.0.1-full_build.zip")
    assert ffmpeg_portable.PORTABLE_FFMPEG_SHA256 == (
        "2e8e28af97c2ae338ccef92e36da9b2a4cd21d0cad9dde093545606cb07f5b00")
    assert ffmpeg_portable.PORTABLE_FFMPEG_SIZE == 251427729


def test_the_build_directory_matches_the_winget_manifest_layout():
    """winget-pkgs lists ffmpeg-9.0.1-full_build\\bin\\ffmpeg.exe."""
    assert ffmpeg_portable.PORTABLE_FFMPEG_BUILD_DIR == "ffmpeg-9.0.1-full_build"


def test_no_actionable_floating_source_survives_in_production():
    """The old URL floated on both 'latest' and 'master-latest'.

    What must be gone is an *actionable* URL, not the word. Describing the
    superseded implementation in a docstring is how the next reader learns why
    this module exists, so the assertion is about fetchable addresses.
    """
    from shared import bootstrap

    for module in (ffmpeg_portable, ffmpeg_health, bootstrap):
        text = Path(module.__file__).read_text(encoding="utf-8")
        assert "github.com/BtbN" not in text
        assert "/releases/latest/" not in text
        assert "ffmpeg-master-latest" not in text


def test_the_only_download_url_in_production_is_the_pinned_one():
    from shared import bootstrap

    for module in (ffmpeg_portable, ffmpeg_health, bootstrap):
        text = Path(module.__file__).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "releases/download" in line:
                assert "GyanD/codexffmpeg/releases/download/9.0.1/" in line, line


def test_there_is_one_authoritative_constant_set():
    """The URL is built from the pin, not restated as a second literal."""
    text = Path(ffmpeg_portable.__file__).read_text(encoding="utf-8")
    assert text.count(ffmpeg_portable.PORTABLE_FFMPEG_SHA256) == 1


# --------------------------------------------------------------------------- #
# B. Download and hash
# --------------------------------------------------------------------------- #
def test_a_matching_download_is_verified_and_kept(sandbox, monkeypatch):
    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    log = _Log()

    archive = ffmpeg_portable.download_archive(log, opener=_opener(payload))

    assert archive == ffmpeg_portable.archive_path()
    assert archive.read_bytes() == payload
    assert not ffmpeg_portable.partial_path().exists()
    assert "verified against the pinned SHA-256" in log.text


def test_a_download_never_lands_in_the_final_destination(sandbox, monkeypatch):
    payload = _archive_bytes()
    _pin(monkeypatch, payload)

    ffmpeg_portable.download_archive(_Log(), opener=_opener(payload))

    assert ffmpeg_portable.archive_path().is_relative_to(
        ffmpeg_portable.staging_root())
    assert not ffmpeg_portable.final_dir().exists()


def test_a_wrong_hash_fails_before_anything_is_extracted(sandbox, monkeypatch):
    """The upstream-replacement case. It must fail closed."""
    payload = _archive_bytes()
    monkeypatch.setattr(ffmpeg_portable, "PORTABLE_FFMPEG_SHA256", "00" * 32)
    log = _Log()

    archive = ffmpeg_portable.download_archive(log, opener=_opener(payload))

    assert archive is None
    assert not ffmpeg_portable.archive_path().exists()
    assert not ffmpeg_portable.partial_path().exists()
    assert not ffmpeg_portable.extract_root().exists()
    assert not ffmpeg_portable.final_dir().exists()


def test_a_hash_mismatch_reports_expected_and_actual(sandbox, monkeypatch):
    payload = _archive_bytes()
    monkeypatch.setattr(ffmpeg_portable, "PORTABLE_FFMPEG_SHA256", "00" * 32)
    log = _Log()

    ffmpeg_portable.download_archive(log, opener=_opener(payload))

    assert "00" * 32 in log.text
    assert hashlib.sha256(payload).hexdigest() in log.text


def test_an_interrupted_download_leaves_nothing_reusable(sandbox, monkeypatch):
    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    log = _Log()

    archive = ffmpeg_portable.download_archive(
        log, opener=_opener(payload, fail_after=10))

    assert archive is None
    assert not ffmpeg_portable.partial_path().exists()
    assert not ffmpeg_portable.archive_path().exists()


def test_a_partial_download_is_never_named_like_a_verified_archive(sandbox):
    assert ffmpeg_portable.partial_path() != ffmpeg_portable.archive_path()
    assert str(ffmpeg_portable.partial_path()).endswith(".part")


def test_a_verified_archive_is_reused_instead_of_downloaded_again(
        sandbox, monkeypatch):
    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)

    def refuse(url):
        pytest.fail("re-downloaded an archive that was already verified")

    archive = ffmpeg_portable.download_archive(_Log(), opener=refuse)

    assert archive == ffmpeg_portable.archive_path()


def test_a_staged_archive_with_the_wrong_bytes_is_not_reused(sandbox, monkeypatch):
    """A filename is not evidence. Only the bytes decide."""
    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(b"something else entirely")

    assert ffmpeg_portable.verified_archive_available() is False

    archive = ffmpeg_portable.download_archive(_Log(), opener=_opener(payload))
    assert archive is not None
    assert archive.read_bytes() == payload


# --------------------------------------------------------------------------- #
# C. Safe extraction
# --------------------------------------------------------------------------- #
def _reject_reason(sandbox, monkeypatch, members):
    payload = _archive_bytes(members=members)
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)
    log = _Log()
    build = ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), log)
    return build, log


@pytest.mark.parametrize("member, label", [
    ("/etc/passwd", "absolute POSIX path"),
    ("C:/Windows/System32/evil.dll", "drive-absolute path"),
    ("//server/share/evil.dll", "UNC path"),
    ("../../escaped.txt", "parent traversal"),
    ("..\\..\\escaped.txt", "backslash traversal"),
    (f"{BUILD}/bin/../../../escaped.txt", "traversal below a good prefix"),
])
def test_an_unsafe_member_is_refused(sandbox, monkeypatch, member, label):
    build, log = _reject_reason(sandbox, monkeypatch, {member: "x"})

    assert build is None, label
    assert "refusing the archive" in log.text
    assert not ffmpeg_portable.extract_root().exists()


def test_a_symlink_member_is_refused(sandbox, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(f"{BUILD}/bin/{_exe('ffmpeg')}", "x")
        info = zipfile.ZipInfo(f"{BUILD}/bin/{_exe('ffprobe')}")
        info.external_attr = (0xA1FF << 16)      # S_IFLNK | 0777
        zf.writestr(info, "/etc/passwd")
    payload = buffer.getvalue()
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)

    log = _Log()
    build = ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), log)

    assert build is None
    assert "symlink" in log.text


def test_an_archive_claiming_an_absurd_expansion_is_refused(sandbox, monkeypatch):
    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)
    monkeypatch.setattr(ffmpeg_portable, "MAX_UNCOMPRESSED_BYTES", 4)

    log = _Log()
    build = ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), log)

    assert build is None
    assert "expands to more than" in log.text


def test_an_absurd_single_member_is_refused(sandbox, monkeypatch):
    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)
    monkeypatch.setattr(ffmpeg_portable, "MAX_MEMBER_BYTES", 2)

    build = ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), _Log())

    assert build is None


def test_a_corrupt_archive_is_refused(sandbox, monkeypatch):
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(b"not a zip at all")

    log = _Log()
    build = ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), log)

    assert build is None
    assert "ERROR extracting" in log.text


def test_the_member_set_is_vetted_before_any_payload_is_written(sandbox, monkeypatch):
    """An invalid entry at the end must not leave a mostly-extracted tree."""
    payload = _archive_bytes(members={"zz-last/../../escape.txt": "x"})
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)

    ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), _Log())

    assert not ffmpeg_portable.extract_root().exists()


def test_a_good_archive_extracts_to_the_expected_build_directory(sandbox, monkeypatch):
    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)

    build = ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), _Log())

    assert build == ffmpeg_portable.extract_root() / BUILD
    assert (build / "bin" / _exe("ffmpeg")).is_file()


def test_an_archive_without_the_pinned_build_directory_is_refused(
        sandbox, monkeypatch):
    """Deterministic layout, not a hunt for any pair inside the archive."""
    payload = _archive_bytes(build="some-other-build")
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)

    log = _Log()
    build = ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), log)

    assert build is None
    assert BUILD in log.text


def test_a_stale_extraction_cannot_be_merged_into_a_retry(sandbox, monkeypatch):
    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)
    stale = ffmpeg_portable.extract_root() / BUILD / "bin"
    stale.mkdir(parents=True)
    (stale / "leftover.exe").write_text("from a previous attempt", encoding="utf-8")

    build = ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), _Log())

    assert build is not None
    assert not (build / "bin" / "leftover.exe").exists()


# --------------------------------------------------------------------------- #
# D. The sibling pair
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("missing", ["ffmpeg", "ffprobe"])
def test_a_build_missing_either_half_has_no_pair(sandbox, monkeypatch, missing):
    payload = _archive_bytes(with_ffmpeg=(missing != "ffmpeg"),
                             with_ffprobe=(missing != "ffprobe"))
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)
    build = ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), _Log())

    assert ffmpeg_portable.staged_pair(build) is None


def test_the_pair_rule_is_ffmpeg_healths_and_not_a_second_one(sandbox, monkeypatch):
    """Halves cannot come from two directories, because pair_in decides."""
    calls: list = []
    real = ffmpeg_health.pair_in
    monkeypatch.setattr(ffmpeg_health, "pair_in",
                        lambda d: (calls.append(Path(d)), real(d))[1])
    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)
    build = ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), _Log())

    pair = ffmpeg_portable.staged_pair(build)

    assert calls == [build / "bin"]
    assert pair is not None
    assert pair.ffmpeg.as_path.parent == pair.ffprobe.as_path.parent


# --------------------------------------------------------------------------- #
# E. Staging proof, promotion, final proof and pin
# --------------------------------------------------------------------------- #
def _acquire(monkeypatch, payload, *, runner_ok=True, opener=None):
    _pin(monkeypatch, payload)
    return ffmpeg_portable.acquire(_Log(),
                                   opener=opener or _opener(payload),
                                   runner=_runner(runner_ok))


def test_a_full_acquisition_promotes_proves_and_pins(sandbox, monkeypatch):
    pinned = _acquire(monkeypatch, _archive_bytes())

    assert pinned is not None
    assert ffmpeg_portable.final_bin_dir().is_dir()
    assert pinned.directory == ffmpeg_portable.final_bin_dir()
    active = ffmpeg_health.pinned_pair()
    assert active is not None
    assert active.directory == ffmpeg_portable.final_bin_dir()


def test_the_active_pin_records_both_binaries(sandbox, monkeypatch):
    pinned = _acquire(monkeypatch, _archive_bytes())

    assert pinned.ffmpeg.sha256 and pinned.ffprobe.sha256
    assert pinned.ffmpeg.sha256 != pinned.ffprobe.sha256
    assert pinned.version_text
    assert Path(pinned.ffmpeg.path).is_absolute()
    assert Path(pinned.ffprobe.path).is_absolute()


def test_a_staging_pair_that_cannot_run_is_never_promoted(sandbox, monkeypatch):
    """Where an application-control refusal must land: before anything moves."""
    pinned = _acquire(monkeypatch, _archive_bytes(), runner_ok=False)

    assert pinned is None
    assert not ffmpeg_portable.final_dir().exists()
    assert ffmpeg_health.pinned_pair() is None


def test_both_staged_halves_must_execute(sandbox, monkeypatch):
    seen: list = []

    def one_sided(executable):
        seen.append(Path(executable).name)
        return (True, "ok") if "ffmpeg" in Path(executable).name else (False, "blocked")

    _pin(monkeypatch, _archive_bytes())
    payload = _archive_bytes()
    pinned = ffmpeg_portable.acquire(_Log(), opener=_opener(payload),
                                     runner=one_sided)

    assert pinned is None
    assert any("ffprobe" in name for name in seen)
    assert not ffmpeg_portable.final_dir().exists()


def test_promotion_is_a_single_directory_move(sandbox, monkeypatch):
    """Not two independent executable writes into a live directory."""
    moves: list = []
    real_replace = os.replace

    def spy(src, dst):
        moves.append((Path(src), Path(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(ffmpeg_portable.os, "replace", spy)
    _acquire(monkeypatch, _archive_bytes())

    promotions = [m for m in moves if m[1] == ffmpeg_portable.final_dir()]
    assert len(promotions) == 1
    assert promotions[0][0] == ffmpeg_portable.extract_root() / BUILD


def test_promotion_never_writes_the_executables_individually(sandbox, monkeypatch):
    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)
    build = ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), _Log())

    def refuse(self, data):
        pytest.fail("wrote an executable directly into the destination")

    monkeypatch.setattr(Path, "write_bytes", refuse)
    ffmpeg_portable.promote(build, _Log())


def test_the_generic_bin_directory_is_never_replaced(sandbox, monkeypatch):
    keepsake = sandbox.bin_dir / "something-else.txt"
    keepsake.write_text("not ours to delete", encoding="utf-8")

    _acquire(monkeypatch, _archive_bytes())

    assert keepsake.read_text(encoding="utf-8") == "not ours to delete"
    assert ffmpeg_portable.final_dir() == sandbox.bin_dir / "ffmpeg" / "9.0.1"


# --------------------------------------------------------------------------- #
# F. Last-known-good preservation
# --------------------------------------------------------------------------- #
@pytest.fixture
def pinned_a(sandbox):
    """An existing, proved, active pair A."""
    directory = sandbox.tmp / "existing-ffmpeg"
    _install_pair(directory)
    pair = ffmpeg_health.pair_in(directory)
    adopted = ffmpeg_health.adopt_pair(pair, _Log(), runner=_runner(True))
    assert adopted.pinned
    return SimpleNamespace(directory=directory, pair=adopted.pair)


def _assert_a_still_active(pinned_a):
    active = ffmpeg_health.pinned_pair()
    assert active is not None, "the working pair was lost"
    assert active.directory == pinned_a.directory
    assert (pinned_a.directory / _exe("ffmpeg")).exists()
    assert (pinned_a.directory / _exe("ffprobe")).exists()


def test_a_download_failure_leaves_the_working_pair_active(
        sandbox, monkeypatch, pinned_a):
    payload = _archive_bytes()
    _pin(monkeypatch, payload)

    result = ffmpeg_portable.acquire(_Log(), opener=_opener(payload, fail_after=5),
                                     runner=_runner(True))

    assert result is None
    _assert_a_still_active(pinned_a)


def test_a_hash_failure_leaves_the_working_pair_active(
        sandbox, monkeypatch, pinned_a):
    payload = _archive_bytes()
    monkeypatch.setattr(ffmpeg_portable, "PORTABLE_FFMPEG_SHA256", "11" * 32)

    result = ffmpeg_portable.acquire(_Log(), opener=_opener(payload),
                                     runner=_runner(True))

    assert result is None
    _assert_a_still_active(pinned_a)


def test_an_unsafe_archive_leaves_the_working_pair_active(
        sandbox, monkeypatch, pinned_a):
    payload = _archive_bytes(members={"../escape.txt": "x"})

    result = _acquire(monkeypatch, payload)

    assert result is None
    _assert_a_still_active(pinned_a)


def test_a_missing_ffprobe_leaves_the_working_pair_active(
        sandbox, monkeypatch, pinned_a):
    result = _acquire(monkeypatch, _archive_bytes(with_ffprobe=False))

    assert result is None
    _assert_a_still_active(pinned_a)


def test_a_staging_proof_failure_leaves_the_working_pair_active(
        sandbox, monkeypatch, pinned_a):
    result = _acquire(monkeypatch, _archive_bytes(), runner_ok=False)

    assert result is None
    _assert_a_still_active(pinned_a)


def test_a_final_proof_failure_leaves_the_working_pair_active(
        sandbox, monkeypatch, pinned_a):
    """The seam establish() would have clobbered: proved staged, failed final."""
    calls = {"n": 0}

    def fails_the_second_time(executable):
        # Two probes per prove_pair call; the staging pair passes, the promoted
        # pair does not.
        calls["n"] += 1
        return (True, "ok") if calls["n"] <= 2 else (False, "blocked")

    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    result = ffmpeg_portable.acquire(_Log(), opener=_opener(payload),
                                     runner=fails_the_second_time)

    assert result is None
    _assert_a_still_active(pinned_a)


def test_adopt_pair_never_clobbers_the_incumbent_on_failure(sandbox, pinned_a):
    """The narrow primitive, stated directly."""
    candidate_dir = sandbox.tmp / "candidate"
    _install_pair(candidate_dir)
    candidate = ffmpeg_health.pair_in(candidate_dir)

    assert not ffmpeg_health.adopt_pair(candidate, _Log(), runner=_runner(False))
    _assert_a_still_active(pinned_a)


def test_a_failed_adoption_still_remembers_the_rejection(sandbox, pinned_a):
    """Remembering a rejection must not cost the pin — both things are true."""
    candidate_dir = sandbox.tmp / "candidate"
    _install_pair(candidate_dir)
    candidate = ffmpeg_health.pair_in(candidate_dir)

    ffmpeg_health.adopt_pair(candidate, _Log(), runner=_runner(False))

    state = ffmpeg_health.load_state()
    assert state.pair is not None
    assert state.rejects(candidate)


def test_adopt_pair_refuses_an_incoherent_pair(sandbox):
    left = sandbox.tmp / "left"
    right = sandbox.tmp / "right"
    _install_pair(left)
    _install_pair(right)
    good = ffmpeg_health.pair_in(left)
    other = ffmpeg_health.pair_in(right)
    from dataclasses import replace as _replace
    mixed = _replace(good, ffprobe=other.ffprobe)

    outcome = ffmpeg_health.adopt_pair(mixed, _Log(), runner=_runner(True))
    assert not outcome.pinned
    assert outcome.status == ffmpeg_health.ADOPT_INCOHERENT


def test_a_successful_replacement_does_take_over(sandbox, monkeypatch, pinned_a):
    pinned = _acquire(monkeypatch, _archive_bytes())

    assert pinned is not None
    active = ffmpeg_health.pinned_pair()
    assert active.directory == ffmpeg_portable.final_bin_dir()
    assert active.directory != pinned_a.directory


# --------------------------------------------------------------------------- #
# G. Interruption after promotion
# --------------------------------------------------------------------------- #
def test_an_already_promoted_build_is_adopted_without_downloading(
        sandbox, monkeypatch):
    """Promoted, then the process died before the pin. Evidence of a move only."""
    _install_pair(ffmpeg_portable.final_bin_dir())

    def refuse(url):
        pytest.fail("re-downloaded a build that was already installed")

    pinned = ffmpeg_portable.acquire(_Log(), opener=refuse, runner=_runner(True))

    assert pinned is not None
    assert pinned.directory == ffmpeg_portable.final_bin_dir()


def test_an_existing_but_unusable_promoted_build_is_not_treated_as_success(
        sandbox, monkeypatch, pinned_a):
    _install_pair(ffmpeg_portable.final_bin_dir())

    result = ffmpeg_portable.adopt_existing_final(_Log(), runner=_runner(False))

    assert not result.pinned
    assert result.status == ffmpeg_health.ADOPT_NOT_PROVED
    _assert_a_still_active(pinned_a)


def test_an_existing_promoted_directory_without_a_pair_is_not_success(sandbox):
    ffmpeg_portable.final_bin_dir().mkdir(parents=True)
    (ffmpeg_portable.final_bin_dir() / _exe("ffmpeg")).write_text("x",
                                                                 encoding="utf-8")

    log = _Log()
    assert not ffmpeg_portable.adopt_existing_final(log, runner=_runner(True))
    assert "no ffmpeg + ffprobe pair" in log.text


def test_an_occupied_destination_is_replaced_not_merged(sandbox, monkeypatch):
    """Refusing outright was fail-closed but not retryable.

    An incomplete or non-running 9.0.1 directory used to block every future
    attempt forever, and the only way out was for someone to delete it by hand —
    the exact recovery this drop exists to remove. ``promote`` is only reached
    once a fresh candidate has been hash-verified, extracted safely and
    **proved**, so the occupant is known to be the worse of the two. It is moved
    aside, replaced wholesale, and never merged into.
    """
    ffmpeg_portable.final_dir().mkdir(parents=True)
    (ffmpeg_portable.final_dir() / "leftover.txt").write_text("x", encoding="utf-8")
    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)
    build = ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), _Log())

    promoted = ffmpeg_portable.promote(build, _Log())

    assert promoted == ffmpeg_portable.final_dir()
    assert not (ffmpeg_portable.final_dir() / "leftover.txt").exists()
    assert (ffmpeg_portable.final_bin_dir() / _exe("ffmpeg")).is_file()
    assert not ffmpeg_portable._unusable_final_aside().exists()


def test_a_failed_replacement_puts_the_occupant_back(sandbox, monkeypatch):
    """A repair that cannot finish leaves the machine as it found it."""
    ffmpeg_portable.final_dir().mkdir(parents=True)
    (ffmpeg_portable.final_dir() / "leftover.txt").write_text("x", encoding="utf-8")
    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    ffmpeg_portable.staging_root().mkdir(parents=True, exist_ok=True)
    ffmpeg_portable.archive_path().write_bytes(payload)
    build = ffmpeg_portable.extract_archive(ffmpeg_portable.archive_path(), _Log())

    real_replace = os.replace
    calls = {"n": 0}

    def fail_the_second_move(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:            # the aside move works, the install does not
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(ffmpeg_portable.os, "replace", fail_the_second_move)
    log = _Log()

    assert ffmpeg_portable.promote(build, log) is None
    assert (ffmpeg_portable.final_dir() / "leftover.txt").exists()
    assert "put the previous build directory back" in log.text.lower()


def test_a_second_acquisition_after_success_is_a_no_op_adoption(
        sandbox, monkeypatch):
    _acquire(monkeypatch, _archive_bytes())

    def refuse(url):
        pytest.fail("downloaded again after a successful install")

    again = ffmpeg_portable.acquire(_Log(), opener=refuse, runner=_runner(True))

    assert again is not None
    assert again.directory == ffmpeg_portable.final_bin_dir()


# --------------------------------------------------------------------------- #
# H. Bounded repo-local discovery
# --------------------------------------------------------------------------- #
def test_the_versioned_build_is_discoverable(sandbox):
    _install_pair(ffmpeg_portable.final_bin_dir())

    assert ffmpeg_portable.final_bin_dir() in ffmpeg_health.candidate_directories()


def test_discovery_of_the_portable_root_is_bounded_and_ordered(sandbox):
    """One level of version directories, deterministic order, no walking.

    The order is reverse-lexicographic on the directory name, not semver — which
    is why "9.0.1" sorts above "10.0.0" here. That is fine for its purpose (a
    tiebreak among repo-local builds this app installed itself) and stated
    rather than implied, so nobody later reads it as version comparison.
    """
    for version in ("9.0.1", "8.0.0", "10.0.0"):
        _install_pair(ffmpeg_health.portable_root() / version / "bin")
    # Something deeper must not be found: this is one level, not a walk.
    deep = ffmpeg_health.portable_root() / "9.0.1" / "extra" / "nested" / "bin"
    _install_pair(deep)

    found = [d for d in ffmpeg_health.candidate_directories()
             if ffmpeg_health.portable_root() in d.parents]

    assert deep not in found
    assert [d.parent.name for d in found] == ["9.0.1", "8.0.0", "10.0.0"]
    assert all(d.name == "bin" for d in found)


def test_discovery_requires_the_sibling_pair(sandbox):
    half = ffmpeg_health.portable_root() / "9.0.1" / "bin"
    half.mkdir(parents=True)
    (half / _exe("ffmpeg")).write_text("x", encoding="utf-8")

    assert ffmpeg_health.pair_in(half) is None


def test_discovery_executes_nothing(sandbox, monkeypatch):
    _install_pair(ffmpeg_portable.final_bin_dir())
    monkeypatch.setattr(ffmpeg_health, "_run_version",
                        lambda exe: pytest.fail("enumeration executed a binary"))

    ffmpeg_health.candidate_directories()
    ffmpeg_health.discover_pairs()


# --------------------------------------------------------------------------- #
# I. What each pin does and does not prove
# --------------------------------------------------------------------------- #
def test_the_source_pin_is_not_a_runtime_claim(sandbox, monkeypatch):
    """A verified archive says nothing about whether the binaries run."""
    payload = _archive_bytes()
    _pin(monkeypatch, payload)

    archive = ffmpeg_portable.download_archive(_Log(), opener=_opener(payload))

    assert archive is not None                      # source pin satisfied
    assert ffmpeg_health.pinned_pair() is None      # runtime pin untouched


def test_the_runtime_pin_is_not_a_provenance_claim(sandbox):
    """A pair proved by execution says nothing about where it came from."""
    directory = sandbox.tmp / "from-anywhere"
    _install_pair(directory)

    adopted = ffmpeg_health.adopt_pair(ffmpeg_health.pair_in(directory), _Log(),
                                       runner=_runner(True))

    assert adopted.pinned
    proved = adopted.pair
    text = ffmpeg_health.state_path().read_text(encoding="utf-8")
    payload = json.loads(text)
    # It records the *binaries* it executed, and nothing about an archive.
    assert payload["pair"]["ffprobe"]["sha256"] == proved.ffprobe.sha256
    assert ffmpeg_portable.PORTABLE_FFMPEG_SHA256 not in text
    assert ffmpeg_portable.PORTABLE_FFMPEG_URL not in text
    assert "archive" not in text.lower()


def test_the_pin_is_re_proved_later_rather_than_trusted_forever(sandbox):
    """ensure_ready still owns that; the pin is not a permanent guarantee."""
    _install_pair(ffmpeg_portable.final_bin_dir())
    assert ffmpeg_health.adopt_pair(
        ffmpeg_health.pair_in(ffmpeg_portable.final_bin_dir()),
        _Log(), runner=_runner(True)).pinned

    assert ffmpeg_health.ensure_ready(_Log(), runner=_runner(False)) is None


def test_there_is_no_second_health_state_file(sandbox, monkeypatch):
    _acquire(monkeypatch, _archive_bytes())

    states = list(sandbox.resources.rglob("*.json"))
    assert [p.name for p in states] == [ffmpeg_health.HEALTH_STATE_NAME]


# --------------------------------------------------------------------------- #
# J. Normal-launch reachability seal
# --------------------------------------------------------------------------- #
def _reaches(entry: str, target: str) -> bool:
    """Whether ``target`` is reachable from ``entry`` in bootstrap's call graph."""
    import ast
    from shared import bootstrap

    src = Path(bootstrap.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    functions = {n.name: n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)}

    seen: set[str] = set()

    def walk(name: str) -> bool:
        if name in seen:
            return False
        seen.add(name)
        fn = functions.get(name)
        if fn is None:
            return False
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            called = None
            if isinstance(node.func, ast.Name):
                called = node.func.id
            elif isinstance(node.func, ast.Attribute):
                called = node.func.attr
            if called == target:
                return True
            if called and walk(called):
                return True
        return False

    return walk(entry)


@pytest.mark.parametrize("entry", ["_venv_check", "_launch_with_kokoro_healthcheck",
                                   "repair_venv", "_repair_and_launch"])
@pytest.mark.parametrize("target", ["acquire", "_download_portable_ffmpeg_windows",
                                    "_install_ffmpeg", "ensure_ffmpeg"])
def test_no_ordinary_launch_path_reaches_acquisition(entry, target):
    """Phase 5 wires provisioning into launches. Phase 3 must not have."""
    assert not _reaches(entry, target), f"{entry} can reach {target}"


def test_setup_still_owns_the_acquisition_route():
    """The fallback is still reachable where it always was: explicit setup."""
    assert _reaches("run_setup", "ensure_ffmpeg")
    assert _reaches("_install_ffmpeg", "_download_portable_ffmpeg_windows")


def test_bootstrap_has_exactly_one_portable_implementation():
    from shared import bootstrap
    text = Path(bootstrap.__file__).read_text(encoding="utf-8")
    assert text.count("def _download_portable_ffmpeg_windows") == 1
    assert "ffmpeg_portable.acquire" in text
    assert "urlretrieve" not in text


def test_no_archive_or_binary_is_tracked():
    import subprocess as sp
    tracked = sp.run(["git", "ls-files"], cwd=REPO_ROOT,
                     capture_output=True, text=True).stdout.splitlines()
    for path in tracked:
        assert not path.endswith((".exe", ".zip")), path
        assert "ffmpeg-staging" not in path
        assert not path.startswith("files/bin/")


# --------------------------------------------------------------------------- #
# K. Persistence is part of the pin (Phase 3 remediation, gap 1)
#
# adopt_pair used to prove the pair, call save_state -- which swallowed OSError
# and returned nothing -- log "Verified", and hand the pair back. So a disk-full
# or permission failure produced "acquisition succeeded, pair pinned" while
# pinned_pair() still returned the incumbent, or None. Proving a pair and
# durably recording it as the active one are different facts; only the second
# makes it the runtime pin, and Phase 4 is about to make consumers trust exactly
# that. Hence blocking rather than cosmetic.
#
# save_state also wrote straight over the live file, so a failure part-way
# through could leave neither the old state nor the new one -- an attempt to
# record a replacement destroying the record of a pair that worked.
# --------------------------------------------------------------------------- #
def _state_bytes() -> bytes:
    return ffmpeg_health.state_path().read_bytes()


def _fails(monkeypatch_ctx, attr: str, exc=OSError("simulated failure")):
    """Make one os operation fail inside a scoped context."""
    def boom(*a, **k):
        raise exc
    monkeypatch_ctx.setattr(ffmpeg_health.os, attr, boom)


def test_a_write_failure_before_the_swap_is_reported_as_not_pinned(
        sandbox, pinned_a):
    """Gap 1, stated directly: proved, not persisted, therefore not pinned.

    The failure is injected at ``fsync`` -- inside the temporary write, before
    the atomic replace -- so this exercises the real persistence primitive
    rather than stubbing ``save_state`` out.
    """
    before = _state_bytes()
    candidate_dir = sandbox.tmp / "candidate"
    _install_pair(candidate_dir)
    candidate = ffmpeg_health.pair_in(candidate_dir)

    with pytest.MonkeyPatch.context() as inner:
        _fails(inner, "fsync")
        outcome = ffmpeg_health.adopt_pair(candidate, _Log(), runner=_runner(True))

    assert not outcome.pinned
    assert outcome.status == ffmpeg_health.ADOPT_NOT_PERSISTED
    assert outcome.pair is None
    assert outcome.proved is True          # the binaries did run; say so honestly
    _assert_a_still_active(pinned_a)
    assert _state_bytes() == before


def test_a_failure_at_the_atomic_replace_is_reported_as_not_pinned(
        sandbox, pinned_a):
    """The temporary file wrote fine; making it live did not."""
    before = _state_bytes()
    candidate_dir = sandbox.tmp / "candidate"
    _install_pair(candidate_dir)
    candidate = ffmpeg_health.pair_in(candidate_dir)

    with pytest.MonkeyPatch.context() as inner:
        _fails(inner, "replace")
        outcome = ffmpeg_health.adopt_pair(candidate, _Log(), runner=_runner(True))

    assert not outcome.pinned
    assert outcome.status == ffmpeg_health.ADOPT_NOT_PERSISTED
    _assert_a_still_active(pinned_a)
    assert _state_bytes() == before


def test_a_not_persisted_result_never_claims_success_in_the_log(sandbox, pinned_a):
    candidate_dir = sandbox.tmp / "candidate"
    _install_pair(candidate_dir)
    candidate = ffmpeg_health.pair_in(candidate_dir)
    log = _Log()

    with pytest.MonkeyPatch.context() as inner:
        _fails(inner, "replace")
        ffmpeg_health.adopt_pair(candidate, log, runner=_runner(True))

    assert "Verified" not in log.text
    assert "Not pinned" in log.text


def test_a_successful_adoption_does_persist_and_resolve(sandbox, pinned_a):
    candidate_dir = sandbox.tmp / "candidate"
    _install_pair(candidate_dir)
    candidate = ffmpeg_health.pair_in(candidate_dir)

    outcome = ffmpeg_health.adopt_pair(candidate, _Log(), runner=_runner(True))

    assert outcome.pinned and outcome.pair is not None
    active = ffmpeg_health.pinned_pair()
    assert active is not None and active.directory == candidate_dir


def test_the_live_state_is_never_the_file_being_written(sandbox, pinned_a):
    """It is replaced into position, never written in place."""
    moves: list = []
    real_replace = os.replace
    candidate_dir = sandbox.tmp / "candidate"
    _install_pair(candidate_dir)

    with pytest.MonkeyPatch.context() as inner:
        inner.setattr(ffmpeg_health.os, "replace",
                      lambda src, dst: (moves.append((Path(src), Path(dst))),
                                        real_replace(src, dst))[1])
        ffmpeg_health.adopt_pair(ffmpeg_health.pair_in(candidate_dir), _Log(),
                                 runner=_runner(True))

    assert len(moves) == 1
    source, destination = moves[0]
    assert destination == ffmpeg_health.state_path()
    assert source.parent == ffmpeg_health.state_path().parent   # same filesystem
    assert source != destination
    assert source.name.endswith(".tmp")


def test_no_temporary_state_file_survives_a_success(sandbox, pinned_a):
    candidate_dir = sandbox.tmp / "candidate"
    _install_pair(candidate_dir)
    ffmpeg_health.adopt_pair(ffmpeg_health.pair_in(candidate_dir), _Log(),
                             runner=_runner(True))

    assert list(ffmpeg_health.state_path().parent.glob("*.tmp")) == []


def test_an_abandoned_temporary_state_never_becomes_authoritative(sandbox, pinned_a):
    """Only os.replace makes a state live; a stray sibling is inert."""
    stray = ffmpeg_health.state_path().with_name(
        ffmpeg_health.state_path().name + ".999999.tmp")
    stray.write_text('{"proof_version": 1, "pair": null, "rejected": []}',
                     encoding="utf-8")

    active = ffmpeg_health.pinned_pair()

    assert active is not None and active.directory == pinned_a.directory


def test_a_partial_temporary_file_is_cleaned_up_on_failure(sandbox, pinned_a):
    candidate_dir = sandbox.tmp / "candidate"
    _install_pair(candidate_dir)

    with pytest.MonkeyPatch.context() as inner:
        _fails(inner, "replace")
        ffmpeg_health.adopt_pair(ffmpeg_health.pair_in(candidate_dir), _Log(),
                                 runner=_runner(True))

    assert list(ffmpeg_health.state_path().parent.glob("*.tmp")) == []


def test_failing_to_record_a_rejection_never_costs_the_incumbent(sandbox, pinned_a):
    """Best-effort metadata must not be able to damage the active pin."""
    before = _state_bytes()
    candidate_dir = sandbox.tmp / "candidate"
    _install_pair(candidate_dir)

    with pytest.MonkeyPatch.context() as inner:
        _fails(inner, "replace")
        outcome = ffmpeg_health.adopt_pair(ffmpeg_health.pair_in(candidate_dir),
                                           _Log(), runner=_runner(False))

    assert outcome.status == ffmpeg_health.ADOPT_NOT_PROVED
    _assert_a_still_active(pinned_a)
    assert _state_bytes() == before


def test_an_inability_to_record_a_rejection_is_not_evidence_against_the_incumbent(
        sandbox, pinned_a):
    log = _Log()
    candidate_dir = sandbox.tmp / "candidate"
    _install_pair(candidate_dir)

    with pytest.MonkeyPatch.context() as inner:
        inner.setattr(ffmpeg_health, "save_state", lambda state: False)
        ffmpeg_health.adopt_pair(ffmpeg_health.pair_in(candidate_dir), log,
                                 runner=_runner(False))

    assert "could not record this rejection" in log.text
    _assert_a_still_active(pinned_a)


def test_acquisition_reports_failure_when_the_pin_cannot_be_written(
        sandbox, monkeypatch, pinned_a):
    """End to end: promoted and proved, but not pinned, so not success."""
    payload = _archive_bytes()
    _pin(monkeypatch, payload)

    with pytest.MonkeyPatch.context() as inner:
        inner.setattr(ffmpeg_health, "save_state", lambda state: False)
        result = ffmpeg_portable.acquire(_Log(), opener=_opener(payload),
                                         runner=_runner(True))

    assert result is None
    _assert_a_still_active(pinned_a)


def test_a_build_promoted_but_unpinned_is_kept_for_the_next_run(
        sandbox, monkeypatch, pinned_a):
    """Case C: the files are good, the disk was not. Do not destroy them."""
    payload = _archive_bytes()
    _pin(monkeypatch, payload)

    with pytest.MonkeyPatch.context() as inner:
        inner.setattr(ffmpeg_health, "save_state", lambda state: False)
        ffmpeg_portable.acquire(_Log(), opener=_opener(payload),
                                runner=_runner(True))

    assert (ffmpeg_portable.final_bin_dir() / _exe("ffmpeg")).is_file()

    # Persistence recovers; the next run adopts it without downloading again.
    def refuse(url):
        pytest.fail("re-downloaded a build that was already installed and proved")

    pinned = ffmpeg_portable.acquire(_Log(), opener=refuse, runner=_runner(True))

    assert pinned is not None
    assert pinned.directory == ffmpeg_portable.final_bin_dir()


# --------------------------------------------------------------------------- #
# L. An unusable installed build is repairable (Phase 3 remediation, gap 2)
#
# adopt_existing_final returned None for an incomplete or non-running build, so
# acquire went on to download, extract and prove a fresh candidate -- and then
# promote() refused the occupied destination and returned None. Every later
# attempt did exactly the same thing. Fail-closed, but a dead end that only a
# human deleting the directory could clear, which is the recovery this whole
# drop exists to remove.
# --------------------------------------------------------------------------- #
def test_an_installed_build_missing_a_half_is_repaired(sandbox, monkeypatch):
    half = ffmpeg_portable.final_bin_dir()
    half.mkdir(parents=True)
    (half / _exe("ffmpeg")).write_text("only half a build", encoding="utf-8")

    pinned = _acquire(monkeypatch, _archive_bytes())

    assert pinned is not None
    assert pinned.directory == ffmpeg_portable.final_bin_dir()
    assert (ffmpeg_portable.final_bin_dir() / _exe("ffprobe")).is_file()
    assert not ffmpeg_portable._unusable_final_aside().exists()


def _runner_rejecting(bad_marker: str):
    """Refuse any executable whose bytes contain ``bad_marker``.

    Keyed on content rather than call count on purpose: ``prove_pair``
    short-circuits after the first half fails, so counting probes silently
    describes a different scenario than the one the test names.
    """
    def run(executable):
        try:
            data = pathlib.Path(executable).read_text(encoding="utf-8",
                                                      errors="replace")
        except OSError:
            return (False, "unreadable")
        if bad_marker in data:
            return (False, "blocked")
        return (True, "ffmpeg version 9.0.1")
    return run


def test_an_installed_build_that_will_not_run_is_repaired(sandbox, monkeypatch):
    """Present, complete, and refused by the machine. Still repairable."""
    _install_pair(ffmpeg_portable.final_bin_dir())      # writes "a" / "b"
    (ffmpeg_portable.final_bin_dir() / "stale.txt").write_text("old",
                                                               encoding="utf-8")
    payload = _archive_bytes()                          # writes "ffmpeg-bytes"
    _pin(monkeypatch, payload)

    pinned = ffmpeg_portable.acquire(_Log(), opener=_opener(payload),
                                     runner=_runner_rejecting("a"))

    assert pinned is not None
    assert not (ffmpeg_portable.final_bin_dir() / "stale.txt").exists()
    assert not ffmpeg_portable._unusable_final_aside().exists()


def test_repairing_a_bad_build_is_idempotent_on_the_next_run(sandbox, monkeypatch):
    """After the repair there is no stale blocking destination left."""
    half = ffmpeg_portable.final_bin_dir()
    half.mkdir(parents=True)
    (half / _exe("ffmpeg")).write_text("only half", encoding="utf-8")
    _acquire(monkeypatch, _archive_bytes())

    def refuse(url):
        pytest.fail("downloaded again after a successful repair")

    again = ffmpeg_portable.acquire(_Log(), opener=refuse, runner=_runner(True))

    assert again is not None
    assert again.directory == ffmpeg_portable.final_bin_dir()


def test_no_manual_deletion_is_ever_required_to_clear_a_bad_build(sandbox,
                                                                  monkeypatch):
    """The whole point: the user never has to delete a directory by hand."""
    ffmpeg_portable.final_dir().mkdir(parents=True)
    (ffmpeg_portable.final_dir() / "garbage.txt").write_text("x", encoding="utf-8")

    first = _acquire(monkeypatch, _archive_bytes())

    assert first is not None
    assert not (ffmpeg_portable.final_dir() / "garbage.txt").exists()


def test_a_bad_build_with_a_failed_staging_proof_is_left_alone(
        sandbox, monkeypatch, pinned_a):
    """Case A: nothing better exists yet, so nothing is disturbed."""
    _install_pair(ffmpeg_portable.final_bin_dir())
    (ffmpeg_portable.final_bin_dir() / "marker.txt").write_text("keep",
                                                                encoding="utf-8")

    result = _acquire(monkeypatch, _archive_bytes(), runner_ok=False)

    assert result is None
    assert (ffmpeg_portable.final_bin_dir() / "marker.txt").exists()
    _assert_a_still_active(pinned_a)


def test_a_working_pair_elsewhere_survives_a_failed_build_repair(
        sandbox, monkeypatch, pinned_a):
    """Case B: the repair cannot finish, and A is untouched throughout."""
    _install_pair(ffmpeg_portable.final_bin_dir())      # unusable: bytes "a"/"b"
    payload = _archive_bytes()
    _pin(monkeypatch, payload)
    real_replace = os.replace
    failed = {"once": False}

    def fail_the_install(src, dst):
        # Transient: the install fails, the rollback that follows does not.
        # A permanently broken filesystem would also block the restore, which
        # is a different scenario and is reported rather than silently retried.
        if Path(dst) == ffmpeg_portable.final_dir() and not failed["once"]:
            failed["once"] = True
            raise OSError("disk full")
        return real_replace(src, dst)

    with pytest.MonkeyPatch.context() as inner:
        inner.setattr(ffmpeg_portable.os, "replace", fail_the_install)
        result = ffmpeg_portable.acquire(
            _Log(), opener=_opener(payload),
            runner=_runner_rejecting("a"))

    assert result is None
    _assert_a_still_active(pinned_a)
    # And the occupant was put back rather than lost.
    assert (ffmpeg_portable.final_bin_dir() / _exe("ffmpeg")).is_file()


def test_a_stale_pin_naming_a_dead_build_is_not_treated_as_working(
        sandbox, monkeypatch):
    """Stale JSON naming a directory is not evidence that it still runs."""
    _install_pair(ffmpeg_portable.final_bin_dir())
    assert ffmpeg_health.adopt_pair(
        ffmpeg_health.pair_in(ffmpeg_portable.final_bin_dir()),
        _Log(), runner=_runner(True)).pinned

    # It stops running; the recorded pin still names it.
    assert ffmpeg_health.ensure_ready(_Log(), runner=_runner(False)) is None
