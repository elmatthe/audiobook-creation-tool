"""Recovered navigation reaches real outputs through the existing execution paths."""
from __future__ import annotations

from dataclasses import replace
import json

import numpy as np
import pytest
from mutagen.id3 import ID3

from m4b import m4b_continuous, m4b_execution, m4b_probe
from m4b.m4b_chapters import ChapterSpan
from m4b.converter.m4b_metadata import MetadataMode
from m4b.converter.m4b_plan import ConversionMode
from shared import ffmpeg_utils
from test_m4b_conversion_plan import direct, plan_for
from test_m4b_nero_recovery import real_conflicting_book, run


def inspected(path):
    return json.loads(run([ffmpeg_utils.ffprobe_cmd(), '-v', 'error', '-show_format',
                           '-show_chapters', '-of', 'json', str(path)]))


def pcm(path):
    return run([ffmpeg_utils.ffmpeg_cmd(), '-v', 'error', '-i', str(path),
                '-map', '0:a:0', '-f', 'f32le', '-'])


def planned(tmp_path, *, mode=ConversionMode.WHOLE, metadata_mode=MetadataMode.PRESERVE, covered=False):
    source = real_conflicting_book(tmp_path, covered=covered)
    report = m4b_probe.probe_source(source)
    entry, = direct(source)
    plan = plan_for((entry,), {entry.occurrence_id: report}, tmp_path / 'outputs',
                    mode=mode, metadata_mode=metadata_mode)
    assert not plan.unusable
    return source, plan.items[0]


def work_for(item, segment, metadata_mode=MetadataMode.PRESERVE):
    return m4b_execution.SegmentWork(
        source=item.source, destination=segment.destination, quality=2,
        expected_duration=segment.duration, metadata_mode=metadata_mode,
        tags={'artist': 'Generated author', 'title': segment.title or 'Generated book'},
        picture=item.picture,
        span=(segment.start, segment.end) if item.fragment else None,
        chapter_titles=item.chapter_titles, recovered_chapters=item.recovered_chapters)


def convert(work, **kwargs):
    result = m4b_execution.convert_segment(
        work, ffmpeg=ffmpeg_utils.ffmpeg_cmd(), cancelled=lambda: False,
        measure=lambda path: float(inspected(path)['format']['duration']),
        sources=(work.source,), **kwargs)
    assert result.finalised, result.detail
    return result


@pytest.mark.parametrize('mode', list(MetadataMode))
def test_recovered_whole_writes_selected_navigation_and_keeps_audio(tmp_path, mode):
    source, item = planned(tmp_path, metadata_mode=mode, covered=True)
    assert len(item.recovered_chapters) == 3
    work = work_for(item, item.segments[0], mode)
    convert(work)
    actual = inspected(work.destination)
    if mode is MetadataMode.STRIP:
        assert not actual.get('chapters')
        assert not ID3(work.destination).getall('APIC')
    else:
        assert [float(c['start_time']) for c in actual['chapters']] == [0, 2, 4]
        assert [float(c['end_time']) for c in actual['chapters']] == [2, 4, 6]
        assert [c['tags']['title'] for c in actual['chapters']] == ['Part 1', 'Part 2', 'Part 3']
        tags = ID3(work.destination)
        assert tags.version == (2, 3, 0)
        assert str(tags['TPE1']) == 'Generated author'
        assert tags.getall('APIC')[0].data == (tmp_path / 'cover.jpg').read_bytes()
    # Compare decoded sample count and content independently of the planner.
    reference = np.frombuffer(pcm(source), dtype='<f4')
    output = np.frombuffer(pcm(work.destination), dtype='<f4')
    # AAC's final packet can contain padded samples beyond the declared extent;
    # Whole mode preserves the existing unbounded decode, including that tail.
    assert len(output) == len(reference)
    assert np.corrcoef(reference, output)[0, 1] > 0.9


def test_recovered_split_one_decode_matches_seeks_and_actual_source_samples(tmp_path):
    source, item = planned(tmp_path, mode=ConversionMode.SPLIT)
    assert [s.track for s in item.segments] == [1, 2, 3]
    assert [s.destination.name for s in item.segments] == ['01 - Part 1.mp3', '02 - Part 2.mp3', '03 - Part 3.mp3']
    report = m4b_probe.probe_source(source)
    route = m4b_continuous.ContinuousRoute(44100, 2, report.stream.duration_ts)
    assert m4b_continuous.static_refusal(report, split=True) is None
    assert m4b_continuous.scan_packets(source, total=route.total_samples, priming=1024,
                                      duration_seconds=6, cancelled=lambda: False) is None
    decoder = m4b_continuous.ContinuousDecoder(route, ffmpeg=ffmpeg_utils.ffmpeg_cmd(),
                                              source=source, workspace=tmp_path)
    decoder.start()
    decoded = np.frombuffer(pcm(source), dtype='<f4').reshape(-1, 2)
    try:
        for number, segment in enumerate(item.segments):
            sought = work_for(item, segment)
            convert(sought)
            first, count = m4b_continuous.chapter_frames(segment.start, segment.end, 44100)
            once = replace(sought, destination=segment.destination.with_name(f'once-{number}.mp3'),
                           continuous_decode=True, pcm_args=route.pcm_args())
            convert(once, feed=lambda write: decoder.feed(write, first, count, last=number == 2),
                    stop_feed=decoder.close)
            assert pcm(once.destination) == pcm(sought.destination)
            actual = np.frombuffer(pcm(sought.destination), dtype='<f4').reshape(-1, 2)
            assert len(actual) == count == 88200
            assert np.corrcoef(decoded[first:first + count].ravel(), actual.ravel())[0, 1] > 0.9
            assert not inspected(sought.destination).get('chapters')
    finally:
        assert decoder.close()


def test_cancel_after_recovered_navigation_write_publishes_nothing(tmp_path, monkeypatch):
    from m4b import m4b_nero
    _, item = planned(tmp_path)
    work = work_for(item, item.segments[0])
    stopped = False
    original = m4b_nero.write_recovered_chapters

    def write(path, spans):
        nonlocal stopped
        original(path, spans)
        stopped = True

    monkeypatch.setattr(m4b_nero, 'write_recovered_chapters', write)
    result = m4b_execution.convert_segment(
        work, ffmpeg=ffmpeg_utils.ffmpeg_cmd(), cancelled=lambda: stopped,
        measure=lambda path: pytest.fail('cancel must precede measurement'), sources=(work.source,))
    assert result.cancelled and not result.finalised
    assert not work.destination.exists()
    assert not list(work.destination.parent.glob('.act-tmp-*'))


def test_failed_navigation_write_leaves_destination_and_retry_plan_intact(tmp_path, monkeypatch):
    from m4b import m4b_nero
    _, item = planned(tmp_path)
    work = work_for(item, item.segments[0])
    original = m4b_nero.write_recovered_chapters

    def broken(path, spans):
        raise OSError('generated write failure')

    monkeypatch.setattr(m4b_nero, 'write_recovered_chapters', broken)
    result = m4b_execution.convert_segment(work, ffmpeg=ffmpeg_utils.ffmpeg_cmd(),
        cancelled=lambda: False, measure=lambda path: 6, sources=(work.source,))
    assert not result.finalised and 'generated write failure' in result.detail
    assert not work.destination.exists()
    monkeypatch.setattr(m4b_nero, 'write_recovered_chapters', original)
    convert(work)
    before = work.destination.read_bytes()
    result = m4b_execution.convert_segment(work, ffmpeg=ffmpeg_utils.ffmpeg_cmd(),
        cancelled=lambda: False, measure=lambda path: 6, sources=(work.source,))
    assert not result.finalised and work.destination.read_bytes() == before


def test_maximum_nero_navigation_reuses_header_without_moving_audio(tmp_path, monkeypatch):
    from m4b import m4b_nero
    _, item = planned(tmp_path)
    spans = tuple(ChapterSpan(order=i + 1, source_index=i, start=i * 6 / 255,
                              end=(i + 1) * 6 / 255, title='A' * 255) for i in range(255))
    work = replace(work_for(item, item.segments[0]), recovered_chapters=spans)
    original = m4b_nero.write_recovered_chapters

    def write(path, recovered):
        before = path.stat().st_size
        audio_before = path.read_bytes()[ID3(path).size:]
        original(path, recovered)
        assert path.stat().st_size == before, 'navigation must not move an eight-hour audio payload'
        assert path.read_bytes()[ID3(path).size:] == audio_before

    monkeypatch.setattr(m4b_nero, 'write_recovered_chapters', write)
    convert(work)
    assert len(ID3(work.destination).getall('CHAP')) == 255
