import argparse
import asyncio
import concurrent.futures
import contextlib
import contextvars
import copy
import io
import os
import random
import re
import subprocess
import threading
import time
import sys
from tqdm import tqdm


import edge_tts
from mutagen import mp4
import nltk
from nltk.tokenize import _get_punkt_tokenizer
from pydub import AudioSegment
from pydub.silence import detect_leading_silence
from pathlib import Path as _Path


def _ensure_shared_on_path() -> None:
    """Put the import root (scripts) on sys.path so `shared.*` imports resolve."""
    root = str(_Path(__file__).resolve().parents[2])  # scripts
    if root not in sys.path:
        sys.path.insert(0, root)


_ensure_shared_on_path()
from tts import ffmpeg_watch  # noqa: E402

ffmpeg_watch.install()  # every FFmpeg pydub starts for this engine can be stopped, and cannot hang it


def _run_ffmpeg(cmd):
    """Run an ffmpeg command through the shared console-suppressing wrapper.

    Resolves the ffmpeg binary (bundled portable build or PATH) and hides the
    console window on Windows. Replaces the upstream raw ``subprocess.run``.
    """
    _ensure_shared_on_path()
    from shared import subprocess_utils as _sp
    from shared import ffmpeg_utils as _ff

    if cmd and cmd[0] == "ffmpeg":
        cmd = [_ff.ffmpeg_cmd()] + list(cmd[1:])
    # check=True (v0.6.6 Phase 10): a failed step used to be ignored, and
    # make_m4b went on to clean up and return an output that was never written.
    return _sp.run(cmd, check=True)


DEFAULT_SPEAKER = "en-US-SteffanNeural"
# Natural-flow defaults: light gap between sentences; trim only sentence clips (never chapter title).
DEFAULT_SENTENCE_PAUSE_MS = 800
DEFAULT_PARAGRAPH_PAUSE_MS = 850
DEFAULT_TITLE_PAUSE_MS = 1200
DEFAULT_CHAPTER_PAUSE_MS = 2000
# v0.7.0 (owner decision Q1): a narration ends with its last sound. The sentence/paragraph/chapter pauses above are
# placed only *between* rendered content, and ``end_of_book_pause`` is still accepted by ``read_book``, the runner and
# the command line for compatibility but adds nothing.
DEFAULT_END_OF_BOOK_PAUSE_MS = 0
# Intra-sentence gaps (edge-tts escapes XML so we split and glue with silence instead of SSML breaks).
COMMA_PAUSE_MS = 300
ELLIPSIS_PAUSE_MS = 600
EM_DASH_PAUSE_MS = 400
# A chunk must contain at least one letter or digit to be worth sending to TTS.
_SPEAKABLE = re.compile(r"[A-Za-z0-9]")
# Quieter than this (dBFS) counts as silence for trimming; more negative = trim less aggressively.
DEFAULT_TRIM_SILENCE_DB = -58.0
DEFAULT_TRIM_CHUNK_MS = 10


def ensure_punkt():
    """Make the app's own verified English sentence data the only thing NLTK reads, or raise.

    v0.7.0: this used to call ``nltk.download`` -- a silent, unhashed download into the user's profile at the start of
    every narration. Now it never downloads: it points NLTK at ``files/runtime-data/nltk_data`` (``shared.nltk_store``)
    and proves the four English files intact, raising ``SentenceDataMissing`` (a message saying what to do) when they
    are not. Setup fetches them with the rest of the base, and the app asks before fetching them otherwise.
    """
    _ensure_shared_on_path()
    from shared import nltk_store

    nltk_store.require(nltk)


_SENTENCE_TOKENIZER = None
#: v0.7.1: several files can convert at once, so the first use can come from several threads together; this lock
#: makes the tokenizer get built (and NLTK's shared loader cleared) exactly once.
_SENTENCE_TOKENIZER_LOCK = threading.Lock()


def _in_workdir(workdir, name):
    """``name`` inside the conversion's own working folder, or bare (relative to the current folder) without one.

    v0.7.1: the runner hands every conversion a private ``workdir`` instead of changing the process-wide current
    folder, so several files can convert at once without writing into each other's scratch files.
    """
    return os.path.join(workdir, name) if workdir else name


def _sentence_tokenizer():
    """NLTK's own English Punkt model, extended with two abbreviations its
    default set omits: "i.e" and "e.g".

    v0.6.5 Phase 5 (iterations 2 and 4) proved the stock abbreviation set
    false-splits e.g. "...theory, i.e. two turns." into separate NLTK
    "sentences" at "i.e."/"e.g." -- each boundary earning an unwanted
    mid-sentence ``sentencepause`` on this direct/rich path only -- and that
    extending the tokenizer's own ``abbrev_types`` set (rather than adopting
    a new dependency such as pysbd) fixes it with zero regression on every
    other false-boundary marker tested (Dr./Mr./Mrs./Prof., initials, "vs.",
    decimals, times, ratios, URLs, ellipses, dialogue, parentheticals).
    Approved for integration by the maintainer's iteration 4 listening
    verdict.

    Built once per process and cached here. ``_get_punkt_tokenizer`` memoizes
    and returns NLTK's own shared instance, so a deep copy is extended
    instead of mutating it in place -- nothing else in this process that
    also calls NLTK's stock ``nltk.tokenize.sent_tokenize`` is affected.

    v0.7.0: the data is the app's verified local copy (``ensure_punkt``), proved
    before the model is first loaded, so no copy in the user's profile is ever read.
    """
    global _SENTENCE_TOKENIZER
    tokenizer = _SENTENCE_TOKENIZER
    if tokenizer is not None:
        return tokenizer
    with _SENTENCE_TOKENIZER_LOCK:
        if _SENTENCE_TOKENIZER is None:
            ensure_punkt()
            _get_punkt_tokenizer.cache_clear()  # never a model NLTK loaded earlier from another folder
            tokenizer = copy.deepcopy(_get_punkt_tokenizer("english"))
            tokenizer._params.abbrev_types.add("i.e")
            tokenizer._params.abbrev_types.add("e.g")
            _SENTENCE_TOKENIZER = tokenizer
        return _SENTENCE_TOKENIZER


def sent_tokenize(text: str) -> list[str]:
    """Sentence-boundary splitting used throughout this module.

    Wraps the abbreviation-extended tokenizer above so both call sites in
    this file (``get_book`` and ``read_book``) share one definition instead
    of calling NLTK's stock ``sent_tokenize`` directly.
    """
    return _sentence_tokenizer().tokenize(text)


#: The name a chapter gets when the source gives it no heading of its own (also its M4B chapter title). It is a
#: name, never a word filter: whether a title is spoken is the chapter's ``narrate_title``, set by ``get_book``.
PLACEHOLDER_TITLE = "blank"
#: Only for chapter dicts built by older callers without ``narrate_title``: the historical text rule.
LEGACY_UNSPOKEN_TITLES = ("Title", "blank")


def _join_headings(first: str, second: str) -> str:
    """Two headings with no text between them, spoken as one title ("Part One. Chapter 1")."""
    first = first.rstrip()
    return f"{first} {second}" if first[-1:] in ".!?:;,-—–" else f"{first}. {second}"


def get_book(sourcefile, speech_prep=None):
    """Parse a TXT into chapters: ``{"title", "narrate_title", "paragraphs"}`` plus the M4B chapter titles.

    v0.7.1: ``narrate_title`` is True only for a heading the author wrote with something speakable in it; a chapter
    with no heading (text before the first ``#``, or a decorative ``#`` line) is named :data:`PLACEHOLDER_TITLE` and
    has nothing extra spoken. A heading written straight after another, with no text between, joins it rather than
    replacing it, so neither is lost and the chapter keeps one metadata title.
    """
    book_contents = []
    book_title = sourcefile
    book_author = "Unknown"
    chapter_titles = []

    # utf-8-sig, not utf-8 (v0.6.6 Phase 10): a Windows "UTF-8 with BOM" file
    # otherwise keeps U+FEFF on its first line, which ``strip`` leaves in place,
    # so its "Title:"/"Author:"/"#" line was spoken aloud instead of parsed.
    # The decode boundary is shared (Plan 01B A1); get_book keeps its own chapter parsing. Speech preparation (A3)
    # runs on the decoded text before it and never touches the Title:/Author:/# markers; ``speech_prep`` is the run's
    # frozen snapshot, and None or "off" leaves the text exactly as decoded.
    _ensure_shared_on_path()
    from tts.speech.document import read_source_text
    from tts.speech.pipeline import prepare
    from tts.speech.profiles import EDGE_DIRECT

    prepared = prepare(read_source_text(sourcefile), speech_prep, EDGE_DIRECT)
    for detail in prepared.details():
        print(detail)
    with io.StringIO(prepared.spoken_source) as file:
        current_chapter = {"title": PLACEHOLDER_TITLE, "narrate_title": False, "paragraphs": []}
        initialized_first_chapter = False
        header_done = False
        for line in file:
            stripped_header = line.strip()
            if not header_done:
                if stripped_header.startswith("Title: "):
                    book_title = stripped_header[len("Title: ") :].strip()
                    continue
                if stripped_header.startswith("Author: "):
                    book_author = stripped_header[len("Author: ") :].strip()
                    continue
                if not stripped_header:
                    continue
                header_done = True

            line = stripped_header
            if line.startswith("#"):
                heading = line[1:].strip()
                speakable = any(c.isalnum() for c in heading)
                if current_chapter["paragraphs"] or not initialized_first_chapter:
                    if initialized_first_chapter:
                        book_contents.append(current_chapter)
                    current_chapter = {"title": heading if speakable else PLACEHOLDER_TITLE,
                                       "narrate_title": speakable, "paragraphs": []}
                    initialized_first_chapter = True
                    chapter_titles.append(current_chapter["title"])
                elif speakable:
                    # Another heading before any text: the author wrote both, so both are spoken, as one title.
                    current_chapter["title"] = (_join_headings(current_chapter["title"], heading)
                                                if current_chapter["narrate_title"] else heading)
                    current_chapter["narrate_title"] = True
                    chapter_titles[-1] = current_chapter["title"]
                # A decorative heading straight after another adds nothing (and removes nothing).
            elif line:
                if not initialized_first_chapter:
                    chapter_titles.append(PLACEHOLDER_TITLE)
                    initialized_first_chapter = True
                if any(char.isalnum() for char in line):
                    sentences = sent_tokenize(line)
                    cleaned_sentences = [s for s in sentences if any(char.isalnum() for char in s)]
                    line = ' '.join(cleaned_sentences)
                    current_chapter["paragraphs"].append(line)

        # Append the last chapter if it contains any paragraphs.
        if current_chapter["paragraphs"]:
            book_contents.append(current_chapter)

    return book_contents, book_title, book_author, chapter_titles


def _export_audio(path, segment):
    ext = os.path.splitext(path)[1].lower()
    fmt = "mp3" if ext == ".mp3" else "flac"
    segment.export(path, format=fmt)


def trim_silence_segment(
    sound,
    silence_threshold=DEFAULT_TRIM_SILENCE_DB,
    chunk_size=DEFAULT_TRIM_CHUNK_MS,
    keep_trailing=False,
):
    """Drop leading/trailing silence (e.g. Edge TTS padding) without changing middle audio.

    The trailing cut lands exactly on the last chunk louder than ``silence_threshold``, so it also removes the quieter
    decay of the final sound. Between chunks that is the approved pacing; the book's last chunk passes
    ``keep_trailing=True`` and leaves its ending to the v0.7.0 final-tail policy (``tts.audio_tail``), which keeps
    every sound down to -70 dBFS (a final plosive's release, a breath) and then at most the budgeted silence.
    """
    if len(sound) == 0:
        return sound
    start = detect_leading_silence(
        sound, silence_threshold=silence_threshold, chunk_size=chunk_size
    )
    duration = len(sound)
    if keep_trailing:
        end = duration
    else:
        end_rev = detect_leading_silence(
            sound.reverse(), silence_threshold=silence_threshold, chunk_size=chunk_size
        )
        end = duration - end_rev
    if end <= start:
        return sound
    return sound[start:end]


def trim_tts_chunk_file(
    path,
    silence_threshold=DEFAULT_TRIM_SILENCE_DB,
    chunk_size=DEFAULT_TRIM_CHUNK_MS,
):
    seg = AudioSegment.from_file(path)
    trimmed = trim_silence_segment(seg, silence_threshold, chunk_size)
    _export_audio(path, trimmed)


def append_silence(tempfile, duration=1200):
    if duration <= 0:
        return
    audio = AudioSegment.from_file(tempfile)
    silence = AudioSegment.silent(duration)
    combined = audio + silence
    _export_audio(tempfile, combined)


def _merge_nonspeakable_intra_chunks(
    chunks: list[tuple[str, int]],
) -> list[tuple[str, int]]:
    """Merge punctuation-only fragments into the previous chunk so Edge TTS never sees them alone."""
    merged: list[tuple[str, int]] = []
    for text, pause in chunks:
        text = text.strip()
        if not text:
            continue
        if not _SPEAKABLE.search(text):
            if merged:
                prev_text, prev_pause = merged[-1]
                merged[-1] = (prev_text + text, prev_pause)
            continue
        merged.append((text, pause))
    return merged


def intra_sentence_chunks(sentence: str) -> list[tuple[str, int]]:
    """
    Split one sentence into TTS segments; each tuple is (text, pause_ms after this
    segment when another segment follows in the same sentence). Edge TTS wraps all
    input in escaped SSML, so <break> tags cannot be used; splitting reproduces
    comma / ellipsis / dash pauses.
    """
    events: list[tuple[int, int]] = []
    for m in re.finditer(r",(?!\d)(\s)", sentence):
        events.append((m.end(), COMMA_PAUSE_MS))
    for m in re.finditer(r"\.\.\.", sentence):
        events.append((m.end(), ELLIPSIS_PAUSE_MS))
    for m in re.finditer(r"—|--", sentence):
        events.append((m.end(), EM_DASH_PAUSE_MS))
    if not events:
        merged = _merge_nonspeakable_intra_chunks([(sentence, 0)])
        return merged if merged else [(sentence, 0)]
    by_end: dict[int, int] = {}
    for end, p in events:
        by_end[end] = max(by_end.get(end, 0), p)
    sorted_ends = sorted(by_end.items())
    chunks: list[tuple[str, int]] = []
    start = 0
    for end, pause_ms in sorted_ends:
        segment = sentence[start:end]
        if segment.strip():
            chunks.append((segment, pause_ms))
        start = end
    tail = sentence[start:]
    if tail.strip():
        chunks.append((tail, 0))
    raw = chunks if chunks else [(sentence, 0)]
    merged = _merge_nonspeakable_intra_chunks(raw)
    return merged if merged else [(sentence, 0)]


def _decoded_size(paths):
    """The PCM bytes these finished audio files decode to, read from their headers (``worker_limits``)."""
    _ensure_shared_on_path()
    from tts import worker_limits

    return worker_limits.decoded_size(paths)


def _is_memory_failure(exc):
    _ensure_shared_on_path()
    from tts import worker_limits

    return worker_limits.is_memory_failure(exc)


class _ParagraphOnDisk:
    """The part of one paragraph's finished audio already written out, in order, as FLAC: lossless, so what is later joined
    is what was held. A paragraph reaches this only when it is too long to hold while it is synthesised
    (``worker_limits.SYNTHESIS_HELD_PCM_BYTES``); then the chapter join takes these files in its place.
    """

    def __init__(self, workdir, pindex, title_clip, title_pause):
        self._workdir, self._pindex = workdir, pindex
        self._title_clip, self._title_pause = title_clip, title_pause
        self.parts = []
        self.rate = None

    def _next(self):
        return _in_workdir(self._workdir, f"pgraphs{self._pindex}.{len(self.parts)}.flac")

    def write(self, segments):
        """What is held in memory, as the next file. The chapter's title, if it is still waiting, goes first. Joining it takes
        memory of its own: if there is none, each piece becomes a file, which the chapter join treats the same."""
        failed = False
        try:
            combined = AudioSegment.empty()
            titled = os.path.exists(self._title_clip)
            if titled:
                combined += AudioSegment.from_file(self._title_clip)
                if self._title_pause > 0:
                    combined += AudioSegment.silent(self._title_pause)
            for seg in segments:
                combined += seg
            if not combined.raw_data:
                return
            part = self._next()
            combined.export(part, format="flac")
        except Exception as exc:  # noqa: BLE001 - only an allocation failure goes further
            if not _is_memory_failure(exc):
                raise
            failed = True
        if failed:  # out of the block above, so what the attempt built has gone
            combined = None
            self._write_each(segments)
            return
        if titled:
            os.remove(self._title_clip)
        self.parts.append(part)
        self.rate = combined.frame_rate

    def _write_each(self, segments):
        if os.path.exists(self._title_clip):
            self.write_clip(self._title_clip, pause_ms=self._title_pause)
        for seg in segments:
            if seg.raw_data:
                part = self._next()
                seg.export(part, format="flac")
                self.parts.append(part)
                self.rate = seg.frame_rate

    def write_clip(self, clip, *, trim=None, pause_ms=0):
        """One clip too long to hold, which never comes into memory at all (``disk_assembly``)."""
        _ensure_shared_on_path()
        from tts import disk_assembly

        part = self._next()
        self.rate = disk_assembly.clip_to_flac(clip, part, f"{part}.wav", trim=trim, pause_ms=pause_ms)
        with contextlib.suppress(FileNotFoundError):
            os.remove(clip)
        self.parts.append(part)


def _append_chapter_pause(files, duration, pause_file):
    """The pause after a chapter goes on its last file, unless that file is too long to bring back into memory."""
    _ensure_shared_on_path()
    from tts import worker_limits

    if duration <= 0 or _decoded_size(files[-1:]) < worker_limits.SYNTHESIS_HELD_PCM_BYTES:
        try:
            append_silence(files[-1], duration)
            return
        except Exception as exc:  # noqa: BLE001 - only an allocation failure goes further
            if not _is_memory_failure(exc):
                raise
    from tts import disk_assembly

    disk_assembly.pause_as_file(duration, worker_limits.sample_rate(files[-1]), pause_file)
    files.append(pause_file)


def read_book(
    book_contents,
    speaker,
    paragraphpause,
    sentencepause,
    title_trailing_pause=DEFAULT_TITLE_PAUSE_MS,
    chapter_trailing_pause=DEFAULT_CHAPTER_PAUSE_MS,
    end_of_book_pause=DEFAULT_END_OF_BOOK_PAUSE_MS,
    trim_tts_padding=True,
    trim_silence_db=DEFAULT_TRIM_SILENCE_DB,
    trim_chunk_ms=DEFAULT_TRIM_CHUNK_MS,
    cancel_check=None,
    progress_callback=None,
    *,
    workdir=None,
):
    """Synthesize every chapter into ``part<i>.flac`` and return their paths.

    ``workdir`` (v0.7.1) is the conversion's own private folder: every scratch file (``part<i>.flac``,
    ``pgraphs<n>.flac``, ``pgraphs<n>.<m>.flac`` for a paragraph too long to hold, ``sntnc*.mp3``) is written there and
    the returned paths are inside it. ``None`` keeps the historical behaviour (bare names, relative to the current folder)
    for direct callers.
    """
    segments = []
    _ensure_shared_on_path()
    from tts import worker_limits

    held_limit = worker_limits.SYNTHESIS_HELD_PCM_BYTES

    # progress_callback(done, total) reports whole-book progress in paragraph
    # units (the natural work step: each paragraph is a batch of network TTS
    # round-trips). It runs on the calling (worker) thread, so a GUI caller
    # must enqueue from it, never touch Tk widgets directly.
    total_paragraphs = sum(len(ch["paragraphs"]) for ch in book_contents)
    done_paragraphs = 0

    def _tick(count=1):
        nonlocal done_paragraphs
        done_paragraphs += count
        if progress_callback is not None and total_paragraphs > 0:
            progress_callback(done_paragraphs, total_paragraphs)

    def _checkpoint():
        # Cooperative cancellation: only does work (and lazy-imports the exception)
        # when the user has actually requested cancel, so it is free in the hot loop.
        if cancel_check is None or not cancel_check():
            return
        _ensure_shared_on_path()
        from shared.cancellation import ConversionCancelled
        raise ConversionCancelled("Conversion cancelled by user.")

    for i, chapter in enumerate(book_contents, start=1):
        _checkpoint()  # between chapters
        # v0.7.0 (Q1): the book's final sentence gets no sentence/paragraph pause and its chapter no chapter pause;
        # every pause between rendered content is unchanged. ``end_of_book_pause`` adds nothing (see its default).
        last_chapter = i == len(book_contents)
        files = []
        partname = _in_workdir(workdir, f"part{i}.flac")
        title_clip = _in_workdir(workdir, "sntnc0.mp3")
        print(f"\n\n")

        if os.path.isfile(partname):
            print(f"{partname} exists, skipping to next chapter")
            segments.append(partname)
            _tick(len(chapter["paragraphs"]))
        else:
            # v0.7.1: a title is spoken because the author wrote it as a heading (``narrate_title``), never because of
            # what it says -- "# Blank" and "# Title" are spoken like any other heading. A chapter built without the
            # flag (an older caller) keeps the historical rule.
            narrate_title = chapter.get("narrate_title")
            if narrate_title is None:
                narrate_title = bool(chapter["title"]) and chapter["title"] not in LEGACY_UNSPOKEN_TITLES
            if narrate_title:
                print(f"Chapter name: \"{chapter['title']}\"")
            else:
                print("Chapter name: none (no heading in the source here, so no chapter title is spoken)")

            if narrate_title:
                asyncio.run(
                    parallel_edgespeak([chapter["title"]], [speaker], [title_clip])
                )
                # Title pause is applied in-memory when merging (below) so the gap is exact
                # and survives MP3/FLAC round-trips; do not rely on silence baked into sntnc0.mp3 alone.

            # position=0: each conversion keeps its bar on its own line. Left automatic, tqdm stacks the bars of files
            # converting at once with newlines and cursor-up codes, which the app's log pane shows as empty lines and
            # raw escape characters (v0.7.1). With one bar at a time the output is byte-for-byte what it always was.
            for pindex, paragraph in enumerate(
                tqdm(chapter["paragraphs"], desc=f"Generating audio files: ", unit='pg', position=0)
            ):
                _checkpoint()  # between paragraphs
                ptemp = _in_workdir(workdir, f"pgraphs{pindex}.flac")
                if os.path.isfile(ptemp):
                    print(f"{ptemp} exists, skipping to next paragraph")
                else:
                    sentences = sent_tokenize(paragraph)
                    n_sents = len(sentences)
                    last_paragraph = last_chapter and pindex == len(chapter["paragraphs"]) - 1
                    # Trim/intra-pause/sentence-pause work stays in memory as PCM
                    # (pydub AudioSegment) from the raw Edge network bytes all the
                    # way to this paragraph's one FLAC export below -- no avoidable
                    # intermediate lossy MP3 re-encode per sub-chunk/sentence.
                    # Approved by the maintainer's Phase 5 iteration 1/4 listening
                    # verdict (v0.6.5 Phase 6 integration).
                    # v0.7.1: a paragraph too long to hold writes what it has as lossless FLAC and carries on, so what one
                    # file holds in memory while it is synthesised has a limit, whatever the plan believed about it.
                    sentence_segments: list[AudioSegment] = []
                    written = _ParagraphOnDisk(workdir, pindex, title_clip, title_trailing_pause)
                    if os.path.exists(title_clip) and _decoded_size([title_clip]) >= held_limit:
                        written.write_clip(title_clip, pause_ms=title_trailing_pause)  # a title clip is never trimmed
                    sent_counter = 1
                    for _si, sentence in enumerate(sentences):
                        _checkpoint()  # between sentence chunks (each is a network round-trip)
                        sentence = re.sub(r"[!]+", "!", sentence)
                        sentence = re.sub(r"[?]+", "?", sentence)
                        subs = intra_sentence_chunks(sentence)
                        sub_segments: list[AudioSegment] = []
                        for sub_idx, (sub_text, intra_pause_ms) in enumerate(subs):
                            sub_path = _in_workdir(workdir, f"sntnc{sent_counter}_sub{sub_idx}.mp3")
                            run_edgespeak(sub_text, speaker, sub_path)
                            # The book's final sub-chunk: its ending is the final-tail policy's (make_mp3).
                            final_chunk = (last_paragraph and _si == n_sents - 1
                                           and sub_idx == len(subs) - 1)
                            on_disk = _decoded_size([sub_path]) >= held_limit  # minutes of speech with no sentence end, comma or dash
                            if not on_disk:
                                try:
                                    seg = AudioSegment.from_file(sub_path)
                                    if trim_tts_padding:
                                        seg = trim_silence_segment(
                                            seg,
                                            silence_threshold=trim_silence_db,
                                            chunk_size=trim_chunk_ms,
                                            keep_trailing=final_chunk,
                                        )
                                    if intra_pause_ms > 0:
                                        seg = seg + AudioSegment.silent(duration=intra_pause_ms)
                                except Exception as exc:  # noqa: BLE001 - only an allocation failure goes further
                                    if not _is_memory_failure(exc):
                                        raise
                                    seg = None
                                    on_disk = True  # this clip has been paid for: it does not need asking for again
                            if on_disk:
                                # Never brought into memory.
                                written.write(sentence_segments + sub_segments)
                                sentence_segments, sub_segments = [], []
                                written.write_clip(
                                    sub_path, pause_ms=intra_pause_ms,
                                    trim=(lambda sound, keep=final_chunk: trim_silence_segment(
                                        sound, silence_threshold=trim_silence_db, chunk_size=trim_chunk_ms,
                                        keep_trailing=keep)) if trim_tts_padding else None)
                                continue
                            with contextlib.suppress(FileNotFoundError):
                                os.remove(sub_path)
                            sub_segments.append(seg)
                            if sum(len(s.raw_data) for s in sentence_segments + sub_segments) >= held_limit:
                                written.write(sentence_segments + sub_segments)
                                sentence_segments, sub_segments = [], []
                        merged_sent = AudioSegment.empty()
                        for seg in sub_segments:
                            merged_sent += seg
                        # The final word of the book takes no pause: nothing follows it.
                        if not (last_paragraph and _si == n_sents - 1):
                            pause = AudioSegment.silent(
                                duration=sentencepause if _si < n_sents - 1 else paragraphpause
                            )
                            # With all of this sentence on disk, the pause takes the rate appending it would have given it.
                            merged_sent = (pause.set_frame_rate(written.rate) if written.rate and not merged_sent.raw_data
                                           else merged_sent + pause)
                        sentence_segments.append(merged_sent)
                        sent_counter += 1

                    if written.parts:
                        written.write(sentence_segments)
                        files.extend(written.parts)
                        _tick()
                        continue
                    joined = True
                    try:
                        combined = AudioSegment.empty()
                        if os.path.exists(title_clip):
                            combined += AudioSegment.from_file(title_clip)
                            if title_trailing_pause > 0:
                                combined += AudioSegment.silent(title_trailing_pause)
                        for seg in sentence_segments:
                            combined += seg
                        combined.export(ptemp, format="flac")
                    except Exception as exc:  # noqa: BLE001 - only an allocation failure goes further
                        if not _is_memory_failure(exc):
                            raise
                        joined = False
                    if not joined:
                        combined = None
                        written.write(sentence_segments)
                        files.extend(written.parts)
                        _tick()
                        continue
                    if os.path.exists(title_clip):
                        os.remove(title_clip)
                files.append(ptemp)
                _tick()
            # combine paragraphs into chapter. A Cancel by now stops here too: finished speech is not joined after it (v0.7.2).
            _checkpoint()
            if not last_chapter:
                _append_chapter_pause(files, chapter_trailing_pause, _in_workdir(workdir, f"part{i}.pause.flac"))
            def _join_in_memory(files=files, partname=partname):
                combined = AudioSegment.empty()
                for file in files:
                    combined += AudioSegment.from_file(file)
                combined.export(partname, format="flac")

            def _join_on_disk(files=files, partname=partname):
                from tts import disk_assembly

                disk_assembly.join_to_flac(files, partname, f"{partname}.wav")

            worker_limits.assemble(_decoded_size(files), _join_in_memory, _join_on_disk, note=print, cancel_check=cancel_check)
            for file in files:
                os.remove(file)
            segments.append(partname)
    return segments

def generate_metadata(files, author, title, chapter_titles, *, workdir=None):
    # v0.6.6 Phase 10: UTF-8 rather than the locale encoding (cp1252 on Windows
    # raised on any title outside it), and every value escaped, because a ";",
    # "=", "#" or backslash in a title garbled it. The CLI's --format m4b is the
    # only caller; the GUI always writes MP3. ``workdir``: see ``read_book``.
    _ensure_shared_on_path()
    from shared.metadata import ffmetadata_escape as _esc

    chap = 0
    start_time = 0
    with open(_in_workdir(workdir, "FFMETADATAFILE"), "w", encoding="utf-8") as file:
        file.write(";FFMETADATA1\n")
        file.write(f"ARTIST={_esc(author)}\n")
        file.write(f"ALBUM={_esc(title)}\n")
        file.write(f"TITLE={_esc(title)}\n")
        file.write("DESCRIPTION=Made with https://github.com/aedocw/epub2tts-edge\n")
        for file_name in files:
            duration = get_duration(file_name)
            file.write("[CHAPTER]\n")
            file.write("TIMEBASE=1/1000\n")
            file.write(f"START={start_time}\n")
            file.write(f"END={start_time + duration}\n")
            file.write(f"title={_esc(chapter_titles[chap])}\n")
            chap += 1
            start_time += duration

def get_duration(file_path):
    audio = AudioSegment.from_file(file_path)
    duration_milliseconds = len(audio)
    return duration_milliseconds

def make_m4b(files, sourcefile, speaker, *, workdir=None):
    # ``workdir``: see ``read_book``. FFmpeg resolves a relative name in the concat list against the list's own
    # folder, and with a workdir every listed part is already an absolute path inside it.
    filelist = _in_workdir(workdir, "filelist.txt")
    metadata_file = _in_workdir(workdir, "FFMETADATAFILE")
    basefile = sourcefile.replace(".txt", "")
    outputm4a = f"{basefile} ({speaker}).m4a"
    outputm4b = f"{basefile} ({speaker}).m4b"
    with open(filelist, "w") as f:
        for filename in files:
            filename = filename.replace("'", "'\\''")
            f.write(f"file '{filename}'\n")
    ffmpeg_command = [
        "ffmpeg",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        filelist,
        "-codec:a",
        "flac",
        "-f",
        "mp4",
        "-strict",
        "-2",
        outputm4a,
    ]
    _run_ffmpeg(ffmpeg_command)
    ffmpeg_command = [
        "ffmpeg",
        "-i",
        outputm4a,
        "-i",
        metadata_file,
        "-map_metadata",
        "1",
        "-codec",
        "aac",
        outputm4b,
    ]
    _run_ffmpeg(ffmpeg_command)
    os.remove(filelist)
    os.remove(metadata_file)
    os.remove(outputm4a)
    for f in files:
        os.remove(f)
    return outputm4b


def make_mp3(files, sourcefile, speaker, bitrate="192k"):
    basefile = sourcefile.replace(".txt", "")
    outputmp3 = f"{basefile} ({speaker}).mp3"
    if os.path.isfile(outputmp3):
        os.remove(outputmp3)
    combined = AudioSegment.empty()
    for fname in files:
        combined += AudioSegment.from_file(fname)
    # v0.7.0 final-tail policy, on the lossless assembly inside this one MP3 encode (no extra generation).
    _ensure_shared_on_path()
    from tts import audio_tail, publication

    combined, tail = audio_tail.apply_final_tail_policy_to_segment(combined)
    print(tail.summary())
    publication.check_narration(combined)
    combined.export(outputmp3, format="mp3", bitrate=bitrate)
    publication.verify_finished_mp3(outputmp3, len(combined))
    for f in files:
        os.remove(f)
    return outputmp3


def make_mp3_on_disk(files, sourcefile, speaker, bitrate="192k"):
    """:func:`make_mp3`, to the byte, for a narration that does not fit in memory (``tts.disk_assembly``)."""
    basefile = sourcefile.replace(".txt", "")
    outputmp3 = f"{basefile} ({speaker}).mp3"
    if os.path.isfile(outputmp3):
        os.remove(outputmp3)
    _ensure_shared_on_path()
    from tts import disk_assembly

    print(disk_assembly.encode_mp3(files, outputmp3, f"{basefile}.assembly.wav", bitrate=bitrate))
    for f in files:
        os.remove(f)
    return outputmp3


def add_cover(cover_img, filename):
    try:
        if os.path.isfile(cover_img):
            m4b = mp4.MP4(filename)
            cover_image = open(cover_img, "rb").read()
            m4b["covr"] = [mp4.MP4Cover(cover_image)]
            m4b.save()
        else:
            print(f"Cover image {cover_img} not found")
    except:
        print(f"Cover image {cover_img} not found")

#: v0.7.1: several files can be requesting at once, and a transient service failure tends to hit them together; a
#: fixed wait would make them all retry at the same instant. Waits double per attempt and are spread by +/-50 %:
#: 1-3 s, then 2-6 s (the same 6 s on average as the fixed 3 s + 3 s before; at most 9 s). Still 3 attempts in all.
RETRY_BASE_DELAY_SEC = 2.0
RETRY_JITTER = 0.5


def _retry_delay(failed_attempt: int, draw=None) -> float:
    """Seconds to wait after the 0-based ``failed_attempt``; ``draw`` returns a number in [0, 1]."""
    base = RETRY_BASE_DELAY_SEC * (2 ** failed_attempt)
    return base * (1 - RETRY_JITTER + 2 * RETRY_JITTER * (random.random() if draw is None else draw()))


def run_edgespeak(sentence, speaker, filename, cancel_check=None):
    """One clip from the service, with up to three attempts.

    The conversion's Cancel (v0.7.2) is read before every attempt, during the request itself and through every back-off: a
    Cancel makes no further request, sits out no wait, and leaves no partial file, raising
    :class:`~shared.cancellation.ConversionCancelled`. ``cancel_check`` defaults to the check of the :func:`ffmpeg_watch.controlled`
    block this thread is converting inside, so callers hand it nothing new.
    """
    if not _SPEAKABLE.search(sentence):
        AudioSegment.silent(duration=50).export(filename, format="mp3")
        return
    _ensure_shared_on_path()
    from shared.cancellation import ConversionCancelled, raise_if_cancelled, wait_unless_cancelled
    from tts import edge_failures

    if cancel_check is None:
        cancel_check = ffmpeg_watch.current_cancel_check()
    for speakattempt in range(3):
        raise_if_cancelled(cancel_check, "Conversion cancelled by user.")
        try:
            communicate = edge_tts.Communicate(sentence, speaker)
            run_save(communicate, filename, cancel_check)
            if os.path.getsize(filename) == 0:
                raise RuntimeError("Failed to save file from edge_tts")
            break
        except ConversionCancelled:
            with contextlib.suppress(OSError):
                os.remove(filename)  # whatever the abandoned request had written
            raise
        except Exception as e:
            # Only a failure another attempt can plausibly cure is retried: a refused handshake (HTTP 401/403),
            # a changed protocol or a local file problem would fail identically three times. The log names the
            # failure, never the sentence (source text).
            print(f"Attempt {speakattempt+1}/3 failed in run_edgespeak: {edge_failures.describe(e)}")
            if not edge_failures.is_retryable(e) or speakattempt == 2:
                with contextlib.suppress(OSError):
                    os.remove(filename)  # never leave the failed attempt's partial audio behind
                final = edge_failures.final_error(e, speakattempt + 1)
                if final is e:
                    raise
                raise final from e
            # wait a few seconds in case it is a transient network issue (growing, spread: see _retry_delay); a Cancel ends it
            try:
                wait_unless_cancelled(_retry_delay(speakattempt), cancel_check)
            except ConversionCancelled:
                with contextlib.suppress(OSError):
                    os.remove(filename)
                raise

def run_save(communicate, filename, cancel_check=None):
    """The request itself. With a ``cancel_check`` the request is abandoned as soon as a Cancel is seen (v0.7.2)."""
    _ensure_shared_on_path()
    from shared.cancellation import await_unless_cancelled

    asyncio.run(await_unless_cancelled(communicate.save(filename), cancel_check))

async def parallel_edgespeak(sentences, speakers, filenames):
    semaphore = asyncio.Semaphore(10)  # Limit the number of concurrent tasks

    with concurrent.futures.ThreadPoolExecutor() as executor:
        tasks = []
        for sentence, speaker, filename in zip(sentences, speakers, filenames):
            async with semaphore:
                loop = asyncio.get_running_loop()
                sentence = re.sub(r'[!]+', '!', sentence)
                sentence = re.sub(r'[?]+', '?', sentence)
                # The executor thread gets this conversion's context, so its request answers to the same Cancel (v0.7.2).
                context = contextvars.copy_context()
                task = loop.run_in_executor(executor, context.run, run_edgespeak, sentence, speaker, filename)
                tasks.append(task)
        await asyncio.gather(*tasks)


def main():
    parser = argparse.ArgumentParser(
        prog="epub2tts-edge",
        description="Read a text file to audiobook format",
    )
    parser.add_argument(
        "sourcefile",
        type=str,
        help="PDF or TXT file to process",
    )
    parser.add_argument(
        "--speaker",
        type=str,
        default=DEFAULT_SPEAKER,
        help=(
            "edge-tts voice (default: en-US-SteffanNeural; same neural voice as "
            "Natural Reader Steffan / Microsoft Azure en-US-SteffanNeural)"
        ),
    )
    parser.add_argument(
        "--cover",
        type=str,
        help="jpg image to use for cover",
    )
    parser.add_argument(
        "--sentencepause",
        type=int,
        default=DEFAULT_SENTENCE_PAUSE_MS,
        help=(
            "silence after each sentence within a paragraph, in milliseconds "
            f"(default: {DEFAULT_SENTENCE_PAUSE_MS}; use 0 for maximum density)"
        ),
    )
    parser.add_argument(
        "--paragraphpause",
        type=int,
        default=DEFAULT_PARAGRAPH_PAUSE_MS,
        help=(
            "silence after the last sentence of each paragraph block, in milliseconds "
            f"(default: {DEFAULT_PARAGRAPH_PAUSE_MS}; PDFs often have many short 'paragraphs')"
        ),
    )
    parser.add_argument(
        "--title-pause",
        type=int,
        default=DEFAULT_TITLE_PAUSE_MS,
        metavar="MS",
        help=f"silence after the spoken chapter title, in milliseconds (default: {DEFAULT_TITLE_PAUSE_MS})",
    )
    parser.add_argument(
        "--chapter-pause",
        type=int,
        default=DEFAULT_CHAPTER_PAUSE_MS,
        metavar="MS",
        help=(
            "extra silence on the last paragraph before merging a chapter, in milliseconds; "
            f"none after the final chapter (default: {DEFAULT_CHAPTER_PAUSE_MS})"
        ),
    )
    parser.add_argument(
        "--end-pause",
        type=int,
        default=DEFAULT_END_OF_BOOK_PAUSE_MS,
        dest="end_of_book_pause",
        metavar="MS",
        help=(
            "accepted for compatibility and ignored: since v0.7.0 the narration ends with "
            f"its last sound, with no closing pause (default: {DEFAULT_END_OF_BOOK_PAUSE_MS})"
        ),
    )
    parser.add_argument(
        "--no-trim-chunks",
        action="store_true",
        help="Disable trimming of Edge TTS padding on sentence clips (title clip is never trimmed)",
    )
    parser.add_argument(
        "--trim-silence-db",
        type=float,
        default=DEFAULT_TRIM_SILENCE_DB,
        metavar="DBFS",
        help=(
            "dBFS threshold for trimming sentence clips; more negative trims less "
            f"(default: {DEFAULT_TRIM_SILENCE_DB})"
        ),
    )
    parser.add_argument(
        "--format",
        choices=("m4b", "mp3"),
        default="m4b",
        help="Output audio format (default: m4b)",
    )
    parser.add_argument(
        "--mp3-bitrate",
        default="192k",
        help="MP3 bitrate for --format mp3 (default: 192k)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Write final audiobook to this folder (uses a private temp working directory)",
    )
    parser.add_argument(
        "--overwrite",
        "--yes",
        action="store_true",
        dest="overwrite",
        help="Overwrite existing output files without prompting",
    )

    args = parser.parse_args()
    print(args)

    _ensure_shared_on_path()
    from shared import nltk_store

    try:
        ensure_punkt()
    except nltk_store.SentenceDataMissing as exc:
        parser.exit(1, f"{exc}\nFrom a command line: python scripts/shared/nltk_store.py --install\n")

    from .runner import run_conversion_job

    run_conversion_job(
        args.sourcefile,
        output_dir=args.output_dir,
        speaker=args.speaker,
        audio_format=args.format,
        mp3_bitrate=args.mp3_bitrate,
        cover=args.cover,
        paragraphpause=args.paragraphpause,
        sentencepause=args.sentencepause,
        title_trailing_pause=args.title_pause,
        chapter_trailing_pause=args.chapter_pause,
        end_of_book_pause=args.end_of_book_pause,
        trim_tts_padding=not args.no_trim_chunks,
        trim_silence_db=args.trim_silence_db,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
