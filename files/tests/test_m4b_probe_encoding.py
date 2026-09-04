"""The probe reads ffprobe's JSON, not the user's code page — Plan 5, Phase 15.

**The real report.** A maintainer imported ``ToA 4 - The Tyrant's Tomb.m4b`` and
the Converter refused it at preflight with ``probe status probe_failed:
UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d in position 6528``.
The book is an ordinary, valid AAC-LC audiobook: 48,123.24 s, 44 chapters, one
PNG cover, five readable tags. ffprobe read it perfectly — exit 0, empty stderr,
22,545 bytes of valid UTF-8 JSON that ``json.loads`` parses without complaint.

**What actually failed was ours.** ``probe_source`` asked
``subprocess.check_output`` for ``text=True`` and named no encoding, so Python
decoded ffprobe's UTF-8 with ``locale.getpreferredencoding(False)`` — **cp1252**
on a stock English Windows install. Byte 6528 is the third byte of
``b"\\xe2\\x80\\x9d"``, the UTF-8 encoding of U+201D RIGHT DOUBLE QUOTATION MARK,
inside chapter 4's title *A simple “no” works*. cp1252 has no mapping for
``0x9d``, so it raised, and the existing ``except Exception`` reported the
failure it was handed. ``ProbeStatus.PROBE_FAILED`` was truthful; the book was
never the problem.

**Crashing is only the loud half.** cp1252 *maps* most of the bytes it should not
touch: U+2014 arrives as ``â€”``, U+2019 as ``â€™``, U+00E9 as ``Ã©``. So a book
whose titles avoided the handful of unmapped bytes would have converted happily
with mojibake baked into every chapter name. That is why these tests assert the
text comes back **exactly**, and never merely that no exception was raised.

**The fix.** ``check_output`` is asked for bytes, and the bytes go to
``json.loads``, which decodes JSON's own way (UTF-8/16/32, per RFC 4627) with no
reference to the host locale. ``shared.metadata.read_chapter_titles`` has always
done exactly this; the Converter's probe was the one that did not.

Nothing here needs the private book. The unit payloads carry the real failing
byte sequence, and the media section builds a small book whose chapter titles and
tags hold the same characters — an ASCII fixture is what let this ship.
"""

from __future__ import annotations

import ast
import inspect
import json
import subprocess
from pathlib import Path

import pytest

from mp3_tools import m4b_probe
from mp3_tools.m4b_chapters import ProbeStatus
from shared import ffmpeg_utils

from test_m4b_metadata import require_ffmpeg  # noqa: E402

# PRE-PLAN-6 Phase 4 closed the runtime trust boundary: ``ffprobe_cmd()``
# resolves only a proved, pinned pair and refuses otherwise. These tests build
# and parse real probe command lines without executing anything, so they need a
# pinned pair to build from -- modelled honestly with a sandbox pair rather than
# by relaxing the production contract.
pytestmark = pytest.mark.usefixtures("pinned_ffmpeg")

#: The exact character that broke the real book, and three that cp1252 would
#: have silently mangled rather than refused.
BREAKS_CP1252 = "”"                     # utf-8 tail byte 0x9d, unmapped
MANGLED_BY_CP1252 = "—’é"     # EM DASH, RIGHT SINGLE QUOTE, é

TITLE = f"4 — Ukulele song? / A simple “no{BREAKS_CP1252} works"
ALBUM = f"The Trials of Apollo {MANGLED_BY_CP1252}"


def payload(*, streams=None, chapters=None, tags=None, duration="48123.239909") -> dict:
    """One ffprobe answer, in the shape the production parser consumes."""
    audio = {"index": 0, "codec_type": "audio", "codec_name": "aac",
             "profile": "LC", "duration": duration}
    return {
        "format": {"duration": duration,
                   "tags": {"title": "ToA 4", "artist": "Rick Riordan",
                            "album_artist": "Rick Riordan", "album": ALBUM,
                            "track": "4/5", **(tags or {})}},
        "streams": [audio] if streams is None else streams,
        "chapters": [{"id": 0, "start_time": "0.000000",
                      "tags": {"title": TITLE}}] if chapters is None else chapters,
    }


def as_bytes(doc: dict) -> bytes:
    """What ffprobe actually writes: UTF-8 bytes, non-ASCII unescaped."""
    return json.dumps(doc, ensure_ascii=False).encode("utf-8")


def runner_returning(value):
    def runner(argv):
        assert isinstance(argv, list) and argv, "the argv seam is unchanged"
        return value
    return runner


# --------------------------------------------------------------------------- #
# The fixture has to be genuinely dangerous, or it guards nothing
# --------------------------------------------------------------------------- #


def test_the_test_payload_really_is_undecodable_under_the_windows_ansi_codepage():
    """Without this, a future edit could soften the payload to something cp1252
    tolerates and every test below would keep passing while proving nothing."""
    raw = as_bytes(payload())
    with pytest.raises(UnicodeDecodeError) as caught:
        raw.decode("cp1252")
    assert caught.value.object[caught.value.start] == 0x9D, (
        "the real report failed on byte 0x9d; the fixture must reproduce it")


def test_cp1252_would_silently_corrupt_the_characters_it_does_not_reject():
    """The reason the fix is bytes-to-json rather than errors='replace'."""
    for char in MANGLED_BY_CP1252:
        decoded = char.encode("utf-8").decode("cp1252")
        assert decoded != char, f"expected {char!r} to be corrupted by cp1252"


# --------------------------------------------------------------------------- #
# The defect itself
# --------------------------------------------------------------------------- #


def test_a_payload_the_ansi_codepage_cannot_decode_is_read_successfully():
    """The whole report in one assertion: a valid book stops being refused."""
    found = m4b_probe.probe_source(
        "book.m4b", runner=runner_returning(as_bytes(payload())))
    assert found.probe.status is ProbeStatus.OK
    assert found.probe.duration == pytest.approx(48123.239909)


def test_unicode_chapter_titles_survive_exactly():
    found = m4b_probe.probe_source(
        "book.m4b", runner=runner_returning(as_bytes(payload())))
    assert [c.title for c in found.probe.chapters] == [TITLE]
    assert BREAKS_CP1252 in found.probe.chapters[0].title
    assert "�" not in found.probe.chapters[0].title, "never errors='replace'"
    assert "â€" not in found.probe.chapters[0].title, "never mojibake"


def test_unicode_metadata_survives_exactly_into_the_source_tags():
    found = m4b_probe.probe_source(
        "book.m4b", runner=runner_returning(as_bytes(payload())))
    assert found.tags.album == ALBUM
    assert found.tags.title == "ToA 4"
    assert found.tags.track == 4, "the /5 total is still discarded"


def test_every_non_ascii_character_round_trips_untouched():
    """Character by character, so a partial corruption cannot hide in a pass."""
    exotic = "—‘’“”éü日本\U0001f4d6"
    doc = payload(chapters=[{"id": 0, "start_time": "0.000000",
                             "tags": {"title": exotic}}])
    found = m4b_probe.probe_source("book.m4b", runner=runner_returning(as_bytes(doc)))
    assert found.probe.chapters[0].title == exotic


# --------------------------------------------------------------------------- #
# The seam still accepts both, and every typed failure is unchanged
# --------------------------------------------------------------------------- #


def test_a_str_returning_runner_is_still_accepted():
    """The injected seam predates this change and is not being migrated."""
    found = m4b_probe.probe_source(
        "book.m4b",
        runner=runner_returning(json.dumps(payload(), ensure_ascii=False)))
    assert found.probe.status is ProbeStatus.OK
    assert [c.title for c in found.probe.chapters] == [TITLE]


@pytest.mark.parametrize("doc", [
    pytest.param(payload(), id="aac-lc-chaptered"),
    pytest.param(payload(streams=[{"index": 0, "codec_type": "audio",
                                   "codec_name": "aac", "profile": "xHE-AAC",
                                   "duration": "35199.62"}]), id="xhe-aac"),
    pytest.param(payload(streams=[
        {"index": 0, "codec_type": "audio", "codec_name": "aac", "profile": "LC",
         "duration": "6.0"},
        {"index": 2, "codec_type": "video", "codec_name": "mjpeg",
         "disposition": {"attached_pic": 1}}]), id="one-cover"),
    pytest.param(payload(streams=[
        {"index": 0, "codec_type": "audio", "codec_name": "aac", "profile": "LC",
         "duration": "6.0"},
        {"index": 1, "codec_type": "video", "codec_name": "mjpeg",
         "disposition": {"attached_pic": 1}},
        {"index": 2, "codec_type": "video", "codec_name": "png",
         "disposition": {"attached_pic": 1}}]), id="two-covers"),
    pytest.param(payload(streams=[]), id="no-audio"),
    pytest.param(payload(duration=None), id="no-duration"),
    pytest.param(payload(chapters=[]), id="chapterless"),
])
def test_bytes_and_str_deliver_an_identical_report(doc):
    """The one invariant that keeps this change from altering any other answer.

    Every typed outcome — NO_AUDIO, NO_DURATION, the chapterless success, the
    cover decision, the xHE classification and the ordinary AAC-LC one — is
    compared across both routes rather than restated, so nothing can drift on
    only one of them.
    """
    from_bytes = m4b_probe.probe_source(
        "book.m4b", runner=runner_returning(as_bytes(doc)))
    from_str = m4b_probe.probe_source(
        "book.m4b", runner=runner_returning(json.dumps(doc, ensure_ascii=False)))
    assert from_bytes == from_str


def test_the_xhe_classification_is_untouched_by_the_decoding_change():
    doc = payload(streams=[{"index": 0, "codec_type": "audio", "codec_name": "aac",
                            "profile": "xHE-AAC", "duration": "35199.62"}])
    found = m4b_probe.probe_source("book.m4b", runner=runner_returning(as_bytes(doc)))
    info = {"codec_name": "aac", "profile": "xHE-AAC", "sample_rate": None,
            "channels": None, "channel_layout": None, "duration": 48123.239909}
    assert found.undecodable_xhe is bool(
        not tuple(ffmpeg_utils.input_decoder_args(info))
        and ffmpeg_utils.needs_special_aac_decoder(info))
    assert found.codec_name == "aac"


def test_an_ordinary_aac_lc_source_is_still_ordinary():
    found = m4b_probe.probe_source(
        "book.m4b", runner=runner_returning(as_bytes(payload())))
    assert found.undecodable_xhe is False
    assert found.codec_name == "aac"


def test_the_single_cover_is_still_selected_by_absolute_index():
    doc = payload(streams=[
        {"index": 0, "codec_type": "audio", "codec_name": "aac", "profile": "LC",
         "duration": "6.0"},
        {"index": 2, "codec_type": "video", "codec_name": "png",
         "disposition": {"attached_pic": 1}}])
    found = m4b_probe.probe_source("book.m4b", runner=runner_returning(as_bytes(doc)))
    assert found.picture is not None
    assert (found.picture.stream_index, found.picture.codec_name) == (2, "png")
    assert found.artwork is None


@pytest.mark.parametrize("bad", [
    pytest.param(b"", id="empty-bytes"),
    pytest.param(b"not json at all", id="bytes-garbage"),
    pytest.param(b'{"format":', id="bytes-truncated"),
    pytest.param("", id="empty-str"),
    pytest.param("not json at all", id="str-garbage"),
    pytest.param(b"[1, 2, 3]", id="json-but-not-an-object"),
])
def test_unparseable_output_still_fails_closed(bad):
    found = m4b_probe.probe_source("book.m4b", runner=runner_returning(bad))
    assert found.probe.status is ProbeStatus.PROBE_FAILED
    assert found.probe.detail


def test_truly_undecodable_bytes_still_fail_closed_rather_than_being_repaired():
    """Bytes that are not valid UTF-8 must still be refused, not salvaged."""
    def runner(argv):
        return b'{"format": {"tags": {"title": "\xff\xfe bad"}}}'

    found = m4b_probe.probe_source("book.m4b", runner=runner)
    assert found.probe.status is ProbeStatus.PROBE_FAILED


def test_a_runner_that_raises_is_still_probe_failed():
    def runner(argv):
        raise subprocess.CalledProcessError(1, argv)

    found = m4b_probe.probe_source("book.m4b", runner=runner)
    assert found.probe.status is ProbeStatus.PROBE_FAILED
    assert "CalledProcessError" in found.probe.detail


def test_no_audio_and_no_duration_keep_their_own_statuses():
    no_audio = m4b_probe.probe_source(
        "book.m4b", runner=runner_returning(as_bytes(payload(streams=[]))))
    assert no_audio.probe.status is ProbeStatus.NO_AUDIO
    no_duration = m4b_probe.probe_source(
        "book.m4b", runner=runner_returning(as_bytes(payload(duration=None))))
    assert no_duration.probe.status is ProbeStatus.NO_DURATION


# --------------------------------------------------------------------------- #
# Structural: the production call may not ask for locale decoding again
# --------------------------------------------------------------------------- #


def _production_check_output_call() -> ast.Call:
    """The one ``check_output`` inside ``probe_source``, located by AST."""
    tree = ast.parse(inspect.getsource(m4b_probe))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "probe_source":
            calls = [c for c in ast.walk(node) if isinstance(c, ast.Call)
                     and isinstance(c.func, ast.Attribute)
                     and c.func.attr == "check_output"]
            assert len(calls) == 1, f"expected one check_output, found {len(calls)}"
            return calls[0]
    raise AssertionError("probe_source was not found")


@pytest.mark.parametrize("banned", ["text", "encoding", "universal_newlines", "errors"])
def test_the_production_probe_never_asks_for_locale_text_decoding(banned):
    """Parsed, not grepped: a substring guard would trip over the docstring that
    explains the defect, and would miss the kwarg written any other way."""
    call = _production_check_output_call()
    assert banned not in {kw.arg for kw in call.keywords}, (
        f"{banned}= reintroduces host-locale decoding of ffprobe's JSON")


def test_the_production_call_survives_a_check_output_that_honours_the_codepage(
        monkeypatch):
    """The behavioural half of the guard above, with no media and no ffprobe.

    The stand-in reproduces what ``subprocess`` really does: given ``text=True``
    and no ``encoding``, it decodes with the host's preferred code page. Pinned
    to cp1252 rather than read from the host, so the regression holds on a
    machine whose locale would have hidden it.
    """
    raw = as_bytes(payload())
    seen: dict = {}

    def fake_check_output(cmd, **kwargs):
        seen.update(kwargs)
        if kwargs.get("text") or kwargs.get("universal_newlines"):
            return raw.decode(kwargs.get("encoding") or "cp1252")
        return raw

    monkeypatch.setattr(m4b_probe.sp, "check_output", fake_check_output)
    found = m4b_probe.probe_source("book.m4b")
    assert found.probe.status is ProbeStatus.OK
    assert [c.title for c in found.probe.chapters] == [TITLE]
    assert not {"text", "encoding", "universal_newlines", "errors"} & set(seen)


def test_the_probe_still_routes_through_the_no_window_subprocess_wrapper():
    """Losing this would flash a console window per book under pythonw.exe."""
    call = _production_check_output_call()
    assert isinstance(call.func.value, ast.Name)
    assert call.func.value.id == "sp"


def test_nothing_in_the_probe_module_decodes_bytes_by_hand():
    """``json.loads`` owns the decoding; a hand-rolled ``.decode`` would be a
    second authority on it, and the wrong one is what caused this."""
    tree = ast.parse(Path(m4b_probe.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "decode"):
            raise AssertionError("the probe decodes bytes itself; json.loads owns that")


# --------------------------------------------------------------------------- #
# Generated media — the shape of fixture that would have caught this
# --------------------------------------------------------------------------- #


def _ff(*args):
    out = subprocess.run(
        [ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-y", *args],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert out.returncode == 0, out.stdout.decode("utf-8", "replace")[-800:]


@pytest.fixture(scope="module")
def unicode_book(tmp_path_factory) -> Path:
    """A real M4B whose chapter titles carry the characters that broke ToA 4.

    The existing generated fixtures title their chapters ``Ch One``; a pure-ASCII
    book cannot fail this way, which is exactly why the suite was green while a
    real audiobook was being refused.
    """
    require_ffmpeg()
    w = tmp_path_factory.mktemp("m4b_unicode")
    meta = w / "meta.txt"
    meta.write_text(
        ";FFMETADATA1\n"
        "title=ToA 4 — The Tyrant’s Tomb\n"
        f"album={ALBUM}\nartist=Rick Riordan\nalbum_artist=Rick Riordan\ntrack=4/5\n"
        f"\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2000\ntitle={TITLE}\n"
        "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=2000\nEND=4000\n"
        "title=5 — Here’s a tune I call “All the Ways I Suck”\n"
        "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=4000\nEND=6000\n"
        "title=日本語 · café · naïve\n",
        encoding="utf-8")
    _ff("-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:a", "aac",
        "-b:a", "64k", str(w / "a.m4a"))
    book = w / "unicode-titles.m4b"
    _ff("-i", str(w / "a.m4a"), "-i", str(meta), "-map", "0:a",
        "-map_metadata", "1", "-map_chapters", "1", "-c:a", "copy", str(book))
    return book


def test_the_generated_book_really_defeats_the_ansi_codepage(unicode_book):
    """Proves the media fixture reproduces the real condition, on any host."""
    raw = subprocess.run(
        [ffmpeg_utils.ffprobe_cmd(), "-v", "error", "-print_format", "json",
         "-show_format", "-show_chapters", str(unicode_book)],
        stdout=subprocess.PIPE, check=True).stdout
    json.loads(raw)                      # valid JSON, straight from bytes
    raw.decode("utf-8")                  # and valid UTF-8
    with pytest.raises(UnicodeDecodeError):
        raw.decode("cp1252")             # undecodable exactly the way ToA 4 was


def test_the_production_probe_reads_a_real_book_with_unicode_titles(unicode_book):
    found = m4b_probe.probe_source(unicode_book)
    assert found.probe.status is ProbeStatus.OK
    assert [c.title for c in found.probe.chapters] == [
        TITLE,
        "5 — Here’s a tune I call “All the Ways I Suck”",
        "日本語 · café · naïve",
    ]
    assert found.tags.album == ALBUM
    assert found.tags.track == 4


def test_a_real_unicode_book_is_usable_rather_than_refused(unicode_book):
    """The user-visible promise: it converts instead of saying it cannot be read."""
    from mp3_tools.m4b_chapters import ChapterUsability, validate_chapters

    found = m4b_probe.probe_source(unicode_book)
    assert validate_chapters(found.probe).usability is ChapterUsability.CHAPTERED
