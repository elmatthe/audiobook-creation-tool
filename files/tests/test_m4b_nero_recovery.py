"""Alternate Nero chapters require independent provenance and strict validation.

All metadata and media here are generated; no owner audiobook is a fixture.
"""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess

import pytest

from m4b import m4b_probe
from m4b.m4b_chapters import InvalidReason, plan_timeline, validate_chapters
from shared import ffmpeg_utils


def atom(name, payload):
    return struct.pack('>I4s', len(payload) + 8, name) + payload


def nero(starts, titles=None):
    titles = titles or [f'Chapter {i + 1:02d}' for i in range(len(starts))]
    entries = []
    for start, title in zip(starts, titles):
        encoded = title.encode('utf-8')
        entries.append(struct.pack('>QB', round(start * 10_000_000), len(encoded)) + encoded)
    return atom(b'chpl', b'\x01' + b'\0' * 7 + bytes([len(starts)]) + b''.join(entries))


def track(track_id, handler, *, reference=None):
    tkhd = bytearray(84)
    struct.pack_into('>I', tkhd, 12, track_id)
    hdlr = atom(b'hdlr', b'\0' * 8 + handler + b'\0' * 13)
    mdhd = bytearray(24)
    struct.pack_into('>II', mdhd, 12, 4_410_000, 236_943_701)
    # Two QT samples reproduce the owner's damaged representation, including
    # the first positive sub-sample interval and the final-chapter label.
    stts = atom(b'stts', struct.pack('>IIIIII', 0, 2, 1, 1, 1, 236_943_700))
    stsz = atom(b'stsz', struct.pack('>IIIII', 0, 0, 2, 12, 12))
    mdia = atom(b'mdia', atom(b'mdhd', bytes(mdhd)) + hdlr +
                atom(b'minf', atom(b'stbl', stts + stsz)))
    tref = b'' if reference is None else atom(b'tref', atom(b'chap', struct.pack('>I', reference)))
    return atom(b'trak', atom(b'tkhd', bytes(tkhd)) + tref + mdia)


def container(chpl, *, qt=True, reference=2, handler=b'text', duplicate=False):
    tracks = track(1, b'soun', reference=reference if qt else None)
    if qt:
        tracks += track(2, handler)
    return atom(b'ftyp', b'M4A ' + b'\0' * 4 + b'isom') + atom(
        b'moov', tracks + atom(b'udta', chpl + (chpl if duplicate else b'')))


def payload(starts=(0, 0, 2), *, duration=6, audio_duration=6, audio_start=0):
    return {'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2', 'duration': duration},
            'streams': [{'index': 0, 'id': '0x1', 'codec_type': 'audio', 'codec_name': 'aac',
                         'profile': 'LC', 'duration': audio_duration, 'start_time': audio_start,
                         'start_pts': 0, 'sample_rate': '44100', 'channels': 2,
                         'time_base': '1/44100'}],
            'chapters': [{'id': i, 'start_time': str(start), 'tags': {'title': f'QT {i}'}}
                         for i, start in enumerate(starts)]}


@pytest.fixture
def read(tmp_path, monkeypatch):
    monkeypatch.setattr(ffmpeg_utils, 'ffprobe_cmd', lambda: 'ffprobe')

    def probe(data, facts=None):
        source = tmp_path / 'generated.m4b'
        source.write_bytes(data)
        before = hashlib.sha256(data).digest()
        report = m4b_probe.probe_source(source, runner=lambda argv: json.dumps(facts or payload()))
        assert hashlib.sha256(source.read_bytes()).digest() == before
        return report
    return probe


def test_two_quicktime_entries_and_33_nero_chapters_recover_complete_timeline(read):
    starts = [0, 16.5779592] + [736.1869388 + i * 850 for i in range(30)] + [29223.5462812]
    titles = [f'Chapter {i + 1:02d} — “text”' for i in range(33)]
    facts = payload((0, 0, *starts[2:]), duration=29277.275011, audio_duration=29277.275011)
    report = read(container(nero(starts, titles)), facts)
    assert len(report.probe.chapters) == 33
    assert tuple(c.start for c in report.probe.chapters) == tuple(starts)
    assert tuple(c.title for c in report.probe.chapters) == tuple(titles)
    assert validate_chapters(report.probe).chaptered
    assert validate_chapters(report.original_probe).reason is InvalidReason.DUPLICATE_START
    assert report.original_probe.chapters[1].title == 'QT 1'
    assert 'Nero' in report.chapter_recovery
    spans = plan_timeline(report.probe)
    assert spans[0].start == 0 and spans[-1].end == 29277.275011
    assert all(s.duration > 0 for s in spans)
    assert all(a.end == b.start for a, b in zip(spans, spans[1:]))


@pytest.mark.parametrize('kind', ['quicktime', 'nero', 'agree'])
def test_valid_primary_chapters_are_unchanged_without_recovery(read, kind):
    chpl = b'' if kind == 'quicktime' else nero([0, 2, 4])
    facts = payload((0, 2, 4))
    report = read(container(chpl, qt=kind != 'nero'), facts)
    assert [(c.start, c.title) for c in report.probe.chapters] == [(0, 'QT 0'), (2, 'QT 1'), (4, 'QT 2')]
    assert getattr(report, 'original_probe', None) is None
    assert not getattr(report, 'chapter_recovery', '')


@pytest.mark.parametrize('starts', [[0, 2, 2], [0, 4, 2], [0, 2, 6], [0, 2, 7], [1, 2, 4], []])
def test_invalid_nero_sequence_keeps_original_rejection(read, starts):
    report = read(container(nero(starts)))
    assert validate_chapters(report.probe).reason is InvalidReason.DUPLICATE_START
    assert [c.start for c in report.probe.chapters] == [0, 0, 2]
    assert getattr(report, 'original_probe', None) is None


@pytest.mark.parametrize('duration', [None, 0, -1, float('nan'), float('inf')])
def test_missing_or_invalid_duration_cannot_recover(read, duration):
    report = read(container(nero([0, 2, 4])), payload(duration=duration, audio_duration=duration))
    assert validate_chapters(report.probe).reason is InvalidReason.NO_DURATION
    assert getattr(report, 'original_probe', None) is None


@pytest.mark.parametrize('options', [dict(qt=False), dict(reference=99), dict(handler=b'meta'), dict(duplicate=True)])
def test_unknown_or_ambiguous_provenance_cannot_recover(read, options):
    report = read(container(nero([0, 2, 4]), **options))
    assert validate_chapters(report.probe).reason is InvalidReason.DUPLICATE_START


@pytest.mark.parametrize('damage', ['missing', 'truncated', 'bad_version', 'bad_utf8', 'trailing', 'bad_atom'])
def test_corrupt_chapter_metadata_fails_closed(read, damage):
    valid = nero([0, 2, 4])
    corrupt = {'missing': b'', 'truncated': valid[:-1],
               'bad_version': valid[:8] + b'\x02' + valid[9:],
               'bad_utf8': nero([0], ['X'])[:-1] + b'\xff',
               'trailing': atom(b'chpl', valid[8:] + b'X'),
               'bad_atom': struct.pack('>I4s', 4, b'chpl')}[damage]
    report = read(container(corrupt))
    assert validate_chapters(report.probe).reason is InvalidReason.DUPLICATE_START
    assert getattr(report, 'original_probe', None) is None


@pytest.mark.parametrize('changes', [dict(audio_duration=7), dict(audio_start=1), dict(audio_duration=None)])
def test_recovery_cannot_hide_audio_outside_container_timeline(read, changes):
    report = read(container(nero([0, 2, 4])), payload(**changes))
    assert validate_chapters(report.probe).reason is InvalidReason.DUPLICATE_START


def test_normal_invalid_chapter_list_without_secondary_metadata_stays_invalid(read):
    report = read(b'ordinary unrecognized source')
    assert validate_chapters(report.probe).reason is InvalidReason.DUPLICATE_START


@pytest.mark.parametrize('damage', ['short_extended', 'outside_extended', 'multiple_moov', 'multiple_references'])
def test_ambiguous_or_corrupt_container_headers_fail_closed(read, damage):
    valid = container(nero([0, 2, 4]))
    if damage == 'short_extended':
        data = struct.pack('>I4sQ', 1, b'moov', 15)
    elif damage == 'outside_extended':
        data = struct.pack('>I4sQ', 1, b'moov', 10_000)
    elif damage == 'multiple_moov':
        data = valid + valid[valid.index(b'moov') - 4:]
    else:
        data = atom(b'moov', track(1, b'soun', reference=2) + track(3, b'soun', reference=2) +
                    track(2, b'text') + atom(b'udta', nero([0, 2, 4])))
    report = read(data)
    assert validate_chapters(report.probe).reason is InvalidReason.DUPLICATE_START
    assert getattr(report, 'original_probe', None) is None


def test_multiple_audio_streams_are_not_a_trustworthy_recovery_source(read):
    facts = payload()
    facts['streams'].append({**facts['streams'][0], 'index': 1, 'id': '0x3'})
    report = read(container(nero([0, 2, 4])), facts)
    assert validate_chapters(report.probe).reason is InvalidReason.DUPLICATE_START


def test_recovery_rejects_a_positive_span_that_encodes_to_zero_samples(read):
    report = read(container(nero([0, 0.0000001, 4])))
    assert validate_chapters(report.probe).reason is InvalidReason.DUPLICATE_START
    assert getattr(report, 'original_probe', None) is None


@pytest.mark.parametrize('extra_sound_track', [False, True])
def test_chapter_reference_must_belong_to_the_probed_audio_track(read, extra_sound_track):
    extra = track(1, b'soun') if extra_sound_track else b''
    data = atom(b'moov', extra + track(3, b'soun', reference=2) +
                track(2, b'text') + atom(b'udta', nero([0, 2, 4])))
    report = read(data)  # FFprobe's one audio stream has track id 0x1, not 0x3.
    assert validate_chapters(report.probe).reason is InvalidReason.DUPLICATE_START
    assert getattr(report, 'original_probe', None) is None


def test_zero_sized_child_box_cannot_hide_metadata_extending_into_audio(read):
    chpl = nero([0, 2, 4])
    # A size=0 box extends to EOF, which includes mdat outside its parent here.
    data = container(b'\0\0\0\0' + chpl[4:]) + atom(b'mdat', b'outside')
    report = read(data)
    assert validate_chapters(report.probe).reason is InvalidReason.DUPLICATE_START
    assert getattr(report, 'original_probe', None) is None


@pytest.mark.parametrize('header', ['tkhd', 'hdlr'])
def test_truncated_track_provenance_headers_cannot_recover(read, header):
    tkhd = b'\0' * 12 + struct.pack('>I', 1)
    if header != 'tkhd':
        tkhd += b'\0' * 68
    hdlr = b'\0' * 8 + b'soun'
    if header != 'hdlr':
        hdlr += b'\0' * 13
    audio = atom(b'trak', atom(b'tkhd', tkhd) + atom(b'mdia', atom(b'hdlr', hdlr)) +
                 atom(b'tref', atom(b'chap', struct.pack('>I', 2))))
    report = read(atom(b'moov', audio + track(2, b'text') + atom(b'udta', nero([0, 2, 4]))))
    assert validate_chapters(report.probe).reason is InvalidReason.DUPLICATE_START
    assert getattr(report, 'original_probe', None) is None


def run(argv):
    completed = subprocess.run(argv, capture_output=True)
    assert completed.returncode == 0, completed.stderr.decode('utf-8', 'replace')[-1000:]
    return completed.stdout


def real_conflicting_book(tmp_path, *, conflict=True, representation='both', covered=False):
    """Three generated Nero chapters plus a deliberately damaged QT track.

    FFmpeg creates all sample data and offsets; in-place edits only change
    existing QT sample durations and timescale, leaving Nero independent.
    """
    source = tmp_path / 'synthetic.m4b'
    metadata = tmp_path / 'chapters.ffmeta'
    metadata.write_text(';FFMETADATA1\n' + ''.join(
        f'[CHAPTER]\nTIMEBASE=1/1000\nSTART={i * 2000}\nEND={(i + 1) * 2000}\ntitle=Part {i + 1}\n'
        for i in range(3)), encoding='utf-8')
    cover_args = []
    if covered:
        from PIL import Image
        cover = tmp_path / 'cover.jpg'
        Image.new('RGB', (16, 16), 'blue').save(cover)
        cover_args = ['-i', str(cover)]
    run([ffmpeg_utils.ffmpeg_cmd(), '-v', 'error', '-f', 'lavfi', '-i',
         'anoisesrc=d=6:r=44100:seed=73:amplitude=0.1', '-i', str(metadata), *cover_args,
         '-map', '0:a', *(['-map', '2:v', '-c:v', 'copy', '-disposition:v:0', 'attached_pic'] if covered else []),
         '-map_metadata', '1', '-map_chapters', '1', '-c:a', 'aac', '-ac', '2', str(source)])
    # Mutagen's locator is used by tests only, never as the recovery boundary.
    from mutagen.mp4._atom import Atoms
    with source.open('r+b') as stream:
        atoms = Atoms(stream)
        if representation == 'quicktime':
            stream.seek(atoms[b'moov', b'udta', b'chpl'].offset + 4)
            stream.write(b'free')
        elif representation == 'nero':
            audio = next(t for t in atoms[b'moov'].children if t.name == b'trak' and
                         t[b'mdia', b'hdlr'].read(stream)[1][8:12] == b'soun')
            tref = audio[b'tref',]
            ok, reference = tref.read(stream)
            assert ok and reference[4:8] == b'chap' and len(reference) == 12
            stream.seek(tref.offset + 12)
            stream.write(b'free')
        if not conflict:
            return source
        qt = next(t for t in atoms[b'moov'].children if t.name == b'trak' and
                  t[b'mdia', b'hdlr'].read(stream)[1][8:12] == b'text')
        mdhd = qt[b'mdia', b'mdhd']
        stream.seek(mdhd.offset + 8 + 12)
        stream.write(struct.pack('>I', 4_410_000))
        stts = qt[b'mdia', b'minf', b'stbl', b'stts']
        ok, data = stts.read(stream)
        assert ok and struct.unpack_from('>I', data, 4)[0] >= 1
        # With a fixed stts box we can preserve the sample count while forcing
        # consecutive starts to round to the same six-decimal FFprobe time.
        stream.seek(stts.offset + 8 + 12)
        stream.write(struct.pack('>I', 1))
    return source


@pytest.mark.parametrize('representation', ['quicktime', 'nero', 'both'])
def test_real_normal_books_keep_existing_chapters(tmp_path, representation):
    source = real_conflicting_book(tmp_path, conflict=False, representation=representation)
    report = m4b_probe.probe_source(source)
    assert [c.start for c in report.probe.chapters] == [0, 2, 4]
    assert [c.title for c in report.probe.chapters] == ['Part 1', 'Part 2', 'Part 3']
    assert not getattr(report, 'chapter_recovery', '')
    assert getattr(report, 'original_probe', None) is None


def test_real_ffmpeg_conflict_is_recovered_from_independent_nero_atom(tmp_path):
    source = real_conflicting_book(tmp_path)
    before = hashlib.sha256(source.read_bytes()).digest()
    raw = json.loads(run([ffmpeg_utils.ffprobe_cmd(), '-v', 'error', '-show_chapters',
                          '-show_format', '-show_streams', '-of', 'json', str(source)]))
    starts = [float(c['start_time']) for c in raw['chapters']]
    assert starts[0] == starts[1] == 0
    report = m4b_probe.probe_source(source)
    assert [c.start for c in report.probe.chapters] == [0, 2, 4]
    assert [c.title for c in report.probe.chapters] == ['Part 1', 'Part 2', 'Part 3']
    assert validate_chapters(report.original_probe).reason is InvalidReason.DUPLICATE_START
    assert hashlib.sha256(source.read_bytes()).digest() == before
