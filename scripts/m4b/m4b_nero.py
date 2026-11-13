"""Read one independently stored Nero table, only for conflicting MOV chapters.

This is a bounded box locator, not a media demuxer: it skips audio payloads and
visits only moov/udta and track identity/reference headers. The caller still
uses validate_chapters for every timestamp rule. Nero's chpl timestamps use
100 ns units (FFmpeg's mov_read_chpl), independent of the movie timescale.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from m4b.m4b_chapters import SourceChapter


@dataclass(frozen=True)
class _Box:
    kind: bytes
    start: int  # payload, after the header
    end: int


def _boxes(source, start: int, end: int, *, top_level: bool = False) -> list[_Box]:
    boxes = []
    while start < end:
        if len(boxes) >= 1024 or end - start < 8:
            raise ValueError("invalid or excessive MOV box headers")
        source.seek(start)
        size, kind = struct.unpack('>I4s', source.read(8))
        header = 8
        if size == 1:
            size, = struct.unpack('>Q', source.read(8))
            header = 16
        elif size == 0:
            if not top_level:
                raise ValueError("unsupported zero-sized nested MOV box")
            size = end - start
        if size < header or size > end - start:
            raise ValueError("MOV box extends outside its parent")
        boxes.append(_Box(kind, start + header, start + size))
        start += size
    return boxes


def _one(boxes: list[_Box], kind: bytes) -> _Box:
    found = [box for box in boxes if box.kind == kind]
    if len(found) != 1:
        raise ValueError(f"expected exactly one {kind.decode('ascii')} box")
    return found[0]


def _children(source, box: _Box) -> list[_Box]:
    return _boxes(source, box.start, box.end)


def _data(source, box: _Box, maximum: int) -> bytes:
    size = box.end - box.start
    if size > maximum:
        raise ValueError("excessive chapter metadata size")
    source.seek(box.start)
    data = source.read(size)
    if len(data) != size:
        raise ValueError("truncated chapter metadata")
    return data


def read_nero_chapters(path, *, audio_track_id: int) -> tuple[SourceChapter, ...]:
    """Require a unique Nero v1 table AND a separate referenced QT text track.

    Unsupported/ambiguous layouts raise rather than selecting the largest table.
    Every entry is returned in stored order, with strict UTF-8 titles. No source
    is opened for writing, and no mdat/sample-table payload is loaded.
    """
    with Path(path).open('rb') as source:
        source.seek(0, 2)
        moov = _one(_boxes(source, 0, source.tell(), top_level=True), b'moov')
        movie = _children(source, moov)
        udta = _one(movie, b'udta')
        table = _one(_children(source, udta), b'chpl')
        tracks = {}
        references = []
        for track in (box for box in movie if box.kind == b'trak'):
            children = _children(source, track)
            header = _data(source, _one(children, b'tkhd'), 256)
            if not header or header[0] not in (0, 1):
                raise ValueError("unsupported track header")
            if len(header) < (96 if header[0] == 1 else 84):
                raise ValueError("truncated track header")
            offset = 20 if header[0] == 1 else 12
            track_id, = struct.unpack_from('>I', header, offset)
            media = _children(source, _one(children, b'mdia'))
            handler = _data(source, _one(media, b'hdlr'), 4096)
            if (len(handler) < 24 or handler[:4] != b'\x00' * 4
                    or track_id == 0 or track_id in tracks):
                raise ValueError("ambiguous track identity")
            tracks[track_id] = handler[8:12]
            if any(box.kind == b'tref' for box in children):
                refs = _children(source, _one(children, b'tref'))
                if any(box.kind == b'chap' for box in refs):
                    link = _data(source, _one(refs, b'chap'), 4)
                    target, = struct.unpack('>I', link)
                    references.append((track_id, target))
        if len(references) != 1:
            raise ValueError("no unique QuickTime chapter reference")
        audio_id, text_id = references[0]
        if (audio_id != audio_track_id or list(tracks.values()).count(b'soun') != 1
                or audio_id == text_id or tracks.get(audio_id) != b'soun'
                or tracks.get(text_id) != b'text'):
            raise ValueError("chapter reference is not from audio to a separate text track")

        # v1 FullBox + reserved uint32 + uint8 count, then count entries:
        # uint64 timestamp, uint8 UTF-8 byte count, exactly that many title bytes.
        data = _data(source, table, 9 + 255 * (9 + 255))
        if len(data) < 9 or data[:8] != b'\x01' + b'\x00' * 7 or not data[8]:
            raise ValueError("unsupported or empty Nero chapter table")
        chapters = []
        position = 9
        for index in range(data[8]):
            ticks, length = struct.unpack_from('>QB', data, position)
            position += 9
            title = data[position:position + length]
            if len(title) != length or b'\x00' in title:
                raise ValueError("truncated or invalid Nero chapter title")
            chapters.append(SourceChapter(index, ticks / 10_000_000, title.decode('utf-8')))
            position += length
        if position != len(data):
            raise ValueError("unexpected trailing Nero chapter data")
        return tuple(chapters)


def write_recovered_chapters(path, spans) -> None:
    """Put frozen navigation on a staged whole-book MP3; audio is untouched.

    ID3 CHAP stores milliseconds, as FFmpeg's ordinary MP3 chapter writer does.
    This only writes navigation; the audio partition retains the Nero starts.
    Mutagen is already an application dependency. Publication and Cancel remain
    the execution layer's existing responsibility.
    """
    from mutagen.id3 import CHAP, CTOC, ID3, TIT2

    tags = ID3(path)
    tags.delall('CHAP')
    tags.delall('CTOC')
    ids = []
    for span in spans:
        element_id = f'ch{span.order}'
        ids.append(element_id)
        tags.add(CHAP(element_id=element_id, start_time=round(span.start * 1000),
                      end_time=round(span.end * 1000), start_offset=0xFFFFFFFF,
                      end_offset=0xFFFFFFFF,
                      sub_frames=[TIT2(encoding=1, text=[span.title])]))
    tags.add(CTOC(element_id='toc', flags=3, child_element_ids=ids, sub_frames=[]))
    tags.update_to_v23()

    def keep_allocation(info):
        if info.padding < 0:
            raise ValueError("recovered navigation exceeds the reserved ID3 header")
        return info.padding

    tags.save(path, v2_version=3, padding=keep_allocation)
