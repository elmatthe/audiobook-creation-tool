import argparse
import asyncio
import concurrent.futures
import contextlib
import os
import re
import subprocess
import time
import warnings
import sys
from tqdm import tqdm


from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub
import edge_tts
from lxml import etree
from mutagen import mp4
import nltk
from nltk.tokenize import sent_tokenize
from PIL import Image
from pydub import AudioSegment
from pydub.silence import detect_leading_silence
import zipfile
from pathlib import Path as _Path


def _ensure_shared_on_path() -> None:
    """Put the scripts/ root on sys.path so `shared.*` imports resolve."""
    root = str(_Path(__file__).resolve().parents[2])  # scripts/
    if root not in sys.path:
        sys.path.insert(0, root)


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
    return _sp.run(cmd)


namespaces = {
   "calibre":"http://calibre.kovidgoyal.net/2009/metadata",
   "dc":"http://purl.org/dc/elements/1.1/",
   "dcterms":"http://purl.org/dc/terms/",
   "opf":"http://www.idpf.org/2007/opf",
   "u":"urn:oasis:names:tc:opendocument:xmlns:container",
   "xsi":"http://www.w3.org/2001/XMLSchema-instance",
}

warnings.filterwarnings("ignore", module="ebooklib.epub")

DEFAULT_SPEAKER = "en-US-SteffanNeural"
# Natural-flow defaults: light gap between sentences; trim only sentence clips (never chapter title).
DEFAULT_SENTENCE_PAUSE_MS = 800
DEFAULT_PARAGRAPH_PAUSE_MS = 850
DEFAULT_TITLE_PAUSE_MS = 1200
DEFAULT_CHAPTER_PAUSE_MS = 2000
DEFAULT_END_OF_BOOK_PAUSE_MS = 3000
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
    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        nltk.download("punkt")
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt_tab")

def chap2text_epub(chap):
    blacklist = [
        "[document]",
        "noscript",
        "header",
        "html",
        "meta",
        "head",
        "input",
        "script",
    ]
    paragraphs = []
    soup = BeautifulSoup(chap, "html.parser")

    # Extract chapter title (assuming it's in an <h1> tag)
    chapter_title = soup.find("h1")
    if chapter_title:
        chapter_title_text = chapter_title.text.strip()
    else:
        chapter_title_text = None

    # Always skip reading links that are just a number (footnotes)
    for a in soup.findAll("a", href=True):
        if not any(char.isalpha() for char in a.text):
            a.extract()

    chapter_paragraphs = soup.find_all("p")
    if len(chapter_paragraphs) == 0:
        print(f"Could not find any paragraph tags <p> in \"{chapter_title_text}\". Trying with <div>.")
        chapter_paragraphs = soup.find_all("div")

    for p in chapter_paragraphs:
        paragraph_text = "".join(p.strings).strip()
        paragraphs.append(paragraph_text)

    return chapter_title_text, paragraphs

def get_epub_cover(epub_path):
    try:
        with zipfile.ZipFile(epub_path) as z:
            t = etree.fromstring(z.read("META-INF/container.xml"))
            rootfile_path =  t.xpath("/u:container/u:rootfiles/u:rootfile",
                                        namespaces=namespaces)[0].get("full-path")

            t = etree.fromstring(z.read(rootfile_path))
            cover_meta = t.xpath("//opf:metadata/opf:meta[@name='cover']",
                                        namespaces=namespaces)
            if not cover_meta:
                print("No cover image found.")
                return None
            cover_id = cover_meta[0].get("content")

            cover_item = t.xpath("//opf:manifest/opf:item[@id='" + cover_id + "']",
                                            namespaces=namespaces)
            if not cover_item:
                print("No cover image found.")
                return None
            cover_href = cover_item[0].get("href")
            cover_path = os.path.join(os.path.dirname(rootfile_path), cover_href)
            if os.name == 'nt' and '\\' in cover_path:
                cover_path = cover_path.replace("\\", "/")
            return z.open(cover_path)
    except FileNotFoundError:
        print(f"Could not get cover image of {epub_path}")

def export(book, sourcefile, overwrite=False):
    book_contents = []
    cover_image = get_epub_cover(sourcefile)
    image_path = None

    if cover_image is not None:
        image = Image.open(cover_image)
        image_filename = sourcefile.replace(".epub", ".png")
        image_path = os.path.join(image_filename)
        image.save(image_path)
        print(f"Cover image saved to {image_path}")

    spine_ids = []
    for spine_tuple in book.spine:
        if spine_tuple[1] == 'yes': # if item in spine is linear
            spine_ids.append(spine_tuple[0])

    items = {}
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            items[item.get_id()] = item

    for id in spine_ids:
        item = items.get(id, None)
        if item is None:
            continue
        chapter_title, chapter_paragraphs = chap2text_epub(item.get_content())
        book_contents.append({"title": chapter_title, "paragraphs": chapter_paragraphs})
    outfile = sourcefile.replace(".epub", ".txt")
    check_for_file(outfile, overwrite=overwrite)
    print(f"Exporting {sourcefile} to {outfile}")
    author = book.get_metadata("DC", "creator")[0][0]
    booktitle = book.get_metadata("DC", "title")[0][0]

    with open(outfile, "w", encoding='utf-8') as file:
        file.write(f"Title: {booktitle}\n")
        file.write(f"Author: {author}\n\n")

        file.write(f"# Title\n")
        file.write(f"{booktitle}, by {author}\n\n")
        for i, chapter in enumerate(book_contents, start=1):
            if chapter["paragraphs"] == [] or chapter["paragraphs"] == ['']:
                continue
            else:
                if chapter["title"] == None:
                    file.write(f"# Part {i}\n")
                else:
                    file.write(f"# {chapter['title']}\n\n")
                for paragraph in chapter["paragraphs"]:
                    clean = re.sub(r'[\s\n]+', ' ', paragraph)
                    clean = re.sub(r'[“”]', '"', clean)  # Curly double quotes to standard double quotes
                    clean = re.sub(r'[‘’]', "'", clean)  # Curly single quotes to standard single quotes
                    file.write(f"{clean}\n\n")

def get_book(sourcefile):
    book_contents = []
    book_title = sourcefile
    book_author = "Unknown"
    chapter_titles = []

    with open(sourcefile, "r", encoding="utf-8") as file:
        current_chapter = {"title": "blank", "paragraphs": []}
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
                if current_chapter["paragraphs"] or not initialized_first_chapter:
                    if initialized_first_chapter:
                        book_contents.append(current_chapter)
                    current_chapter = {"title": None, "paragraphs": []}
                    initialized_first_chapter = True
                chapter_title = line[1:].strip()
                if any(c.isalnum() for c in chapter_title):
                    current_chapter["title"] = chapter_title
                    chapter_titles.append(current_chapter["title"])
                else:
                    current_chapter["title"] = "blank"
                    chapter_titles.append("blank")
            elif line:
                if not initialized_first_chapter:
                    chapter_titles.append("blank")
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


def check_for_file(filename, overwrite=False):
    if os.path.isfile(filename):
        if overwrite:
            os.remove(filename)
        else:
            print(f"The file '{filename}' already exists.")
            ans = input("Do you want to overwrite the file? (y/n): ")
            if ans.lower() != "y":
                print("Exiting without overwriting the file.")
                sys.exit()
            else:
                os.remove(filename)

def _export_audio(path, segment):
    ext = os.path.splitext(path)[1].lower()
    fmt = "mp3" if ext == ".mp3" else "flac"
    segment.export(path, format=fmt)


def trim_silence_segment(
    sound,
    silence_threshold=DEFAULT_TRIM_SILENCE_DB,
    chunk_size=DEFAULT_TRIM_CHUNK_MS,
):
    """Drop leading/trailing silence (e.g. Edge TTS padding) without changing middle audio."""
    if len(sound) == 0:
        return sound
    start = detect_leading_silence(
        sound, silence_threshold=silence_threshold, chunk_size=chunk_size
    )
    end_rev = detect_leading_silence(
        sound.reverse(), silence_threshold=silence_threshold, chunk_size=chunk_size
    )
    duration = len(sound)
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
):
    segments = []
    # Do not read these into the audio file:
    title_names_to_skip_reading = ['Title', 'blank']

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
        files = []
        partname = f"part{i}.flac"
        print(f"\n\n")

        if os.path.isfile(partname):
            print(f"{partname} exists, skipping to next chapter")
            segments.append(partname)
        else:
            if chapter["title"] in title_names_to_skip_reading:
                print(f"Chapter name: \"{chapter['title']}\"  -  Note: The word \"{chapter['title']}\" will not be read into audio file.")
            else:
                print(f"Chapter name: \"{chapter['title']}\"")

            if chapter["title"] == "":
                chapter["title"] = "blank"
            if chapter["title"] not in title_names_to_skip_reading:
                asyncio.run(
                    parallel_edgespeak([chapter["title"]], [speaker], ["sntnc0.mp3"])
                )
                # Title pause is applied in-memory when merging (below) so the gap is exact
                # and survives MP3/FLAC round-trips; do not rely on silence baked into sntnc0.mp3 alone.

            for pindex, paragraph in enumerate(
                tqdm(chapter["paragraphs"], desc=f"Generating audio files: ",unit='pg')
            ):
                _checkpoint()  # between paragraphs
                ptemp = f"pgraphs{pindex}.flac"
                if os.path.isfile(ptemp):
                    print(f"{ptemp} exists, skipping to next paragraph")
                else:
                    sentences = sent_tokenize(paragraph)
                    n_sents = len(sentences)
                    sentence_paths: list[str] = []
                    sent_counter = 1
                    for _si, sentence in enumerate(sentences):
                        _checkpoint()  # between sentence chunks (each is a network round-trip)
                        sentence = re.sub(r"[!]+", "!", sentence)
                        sentence = re.sub(r"[?]+", "?", sentence)
                        subs = intra_sentence_chunks(sentence)
                        if len(subs) == 1:
                            chunk_path = f"sntnc{sent_counter}.mp3"
                            run_edgespeak(subs[0][0], speaker, chunk_path)
                            if trim_tts_padding:
                                trim_tts_chunk_file(
                                    chunk_path,
                                    silence_threshold=trim_silence_db,
                                    chunk_size=trim_chunk_ms,
                                )
                            sentence_paths.append(chunk_path)
                        else:
                            sub_paths: list[str] = []
                            for sub_idx, (sub_text, intra_pause_ms) in enumerate(subs):
                                sub_path = f"sntnc{sent_counter}_sub{sub_idx}.mp3"
                                run_edgespeak(sub_text, speaker, sub_path)
                                if trim_tts_padding:
                                    trim_tts_chunk_file(
                                        sub_path,
                                        silence_threshold=trim_silence_db,
                                        chunk_size=trim_chunk_ms,
                                    )
                                if intra_pause_ms > 0:
                                    append_silence(sub_path, intra_pause_ms)
                                sub_paths.append(sub_path)
                            chunk_path = f"sntnc{sent_counter}.mp3"
                            merged_sent = AudioSegment.empty()
                            for sp in sub_paths:
                                merged_sent += AudioSegment.from_mp3(sp)
                            merged_sent.export(chunk_path, format="mp3")
                            for sp in sub_paths:
                                with contextlib.suppress(FileNotFoundError):
                                    os.remove(sp)
                            sentence_paths.append(chunk_path)
                        sent_counter += 1

                    for si, fname in enumerate(sentence_paths):
                        if si < n_sents - 1:
                            append_silence(fname, sentencepause)
                        else:
                            append_silence(fname, paragraphpause)
                    combined = AudioSegment.empty()
                    if os.path.exists("sntnc0.mp3"):
                        combined += AudioSegment.from_file("sntnc0.mp3")
                        if title_trailing_pause > 0:
                            combined += AudioSegment.silent(title_trailing_pause)
                    for fname in sentence_paths:
                        combined += AudioSegment.from_file(fname)
                    combined.export(ptemp, format="flac")
                    to_remove = list(sentence_paths)
                    if os.path.exists("sntnc0.mp3"):
                        to_remove.insert(0, "sntnc0.mp3")
                    for file in to_remove:
                        os.remove(file)
                files.append(ptemp)
            # combine paragraphs into chapter
            append_silence(files[-1], chapter_trailing_pause)
            combined = AudioSegment.empty()
            for file in files:
                combined += AudioSegment.from_file(file)
            combined.export(partname, format="flac")
            for file in files:
                os.remove(file)
            segments.append(partname)
    if segments and end_of_book_pause > 0:
        append_silence(segments[-1], end_of_book_pause)
    return segments

def generate_metadata(files, author, title, chapter_titles):
    chap = 0
    start_time = 0
    with open("FFMETADATAFILE", "w") as file:
        file.write(";FFMETADATA1\n")
        file.write(f"ARTIST={author}\n")
        file.write(f"ALBUM={title}\n")
        file.write(f"TITLE={title}\n")
        file.write("DESCRIPTION=Made with https://github.com/aedocw/epub2tts-edge\n")
        for file_name in files:
            duration = get_duration(file_name)
            file.write("[CHAPTER]\n")
            file.write("TIMEBASE=1/1000\n")
            file.write(f"START={start_time}\n")
            file.write(f"END={start_time + duration}\n")
            file.write(f"title={chapter_titles[chap]}\n")
            chap += 1
            start_time += duration

def get_duration(file_path):
    audio = AudioSegment.from_file(file_path)
    duration_milliseconds = len(audio)
    return duration_milliseconds

def make_m4b(files, sourcefile, speaker):
    filelist = "filelist.txt"
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
        "FFMETADATAFILE",
        "-map_metadata",
        "1",
        "-codec",
        "aac",
        outputm4b,
    ]
    _run_ffmpeg(ffmpeg_command)
    os.remove(filelist)
    os.remove("FFMETADATAFILE")
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
    combined.export(outputmp3, format="mp3", bitrate=bitrate)
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

def run_edgespeak(sentence, speaker, filename):
    if not _SPEAKABLE.search(sentence):
        AudioSegment.silent(duration=50).export(filename, format="mp3")
        return
    for speakattempt in range(3):
        try:
            communicate = edge_tts.Communicate(sentence, speaker)
            run_save(communicate, filename)
            if os.path.getsize(filename) == 0:
                raise RuntimeError("Failed to save file from edge_tts")
            break
        except Exception as e:
            print(f"Attempt {speakattempt+1}/3 failed with '{sentence}' in run_edgespeak with error: {e}")
            # wait a few seconds in case its a transient network issue
            time.sleep(3)
    else:
        msg = f"Giving up on sentence after 3 attempts in run_edgespeak: {sentence!r}"
        print(msg)
        raise RuntimeError(msg)

def run_save(communicate, filename):
    asyncio.run(communicate.save(filename))

async def parallel_edgespeak(sentences, speakers, filenames):
    semaphore = asyncio.Semaphore(10)  # Limit the number of concurrent tasks

    with concurrent.futures.ThreadPoolExecutor() as executor:
        tasks = []
        for sentence, speaker, filename in zip(sentences, speakers, filenames):
            async with semaphore:
                loop = asyncio.get_running_loop()
                sentence = re.sub(r'[!]+', '!', sentence)
                sentence = re.sub(r'[?]+', '?', sentence)
                task = loop.run_in_executor(executor, run_edgespeak, sentence, speaker, filename)
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
        help="EPUB, PDF, or TXT file to process",
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
            "extra silence on the last paragraph before merging a chapter, in milliseconds "
            f"(default: {DEFAULT_CHAPTER_PAUSE_MS})"
        ),
    )
    parser.add_argument(
        "--end-pause",
        type=int,
        default=DEFAULT_END_OF_BOOK_PAUSE_MS,
        dest="end_of_book_pause",
        metavar="MS",
        help=(
            "silence appended at the very end of the output file, in milliseconds "
            f"(default: {DEFAULT_END_OF_BOOK_PAUSE_MS})"
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
    parser.add_argument(
        "--epub-convert",
        action="store_true",
        help="With .epub input, export to text and continue to audio (default: export txt only)",
    )

    args = parser.parse_args()
    print(args)

    ensure_punkt()

    if args.sourcefile.endswith(".epub") and not args.epub_convert:
        book = epub.read_epub(args.sourcefile)
        export(book, args.sourcefile, overwrite=args.overwrite)
        sys.exit(0)

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
        epub_convert=args.epub_convert,
    )


if __name__ == "__main__":
    main()
