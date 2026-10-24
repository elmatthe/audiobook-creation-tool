"""Edge TTS failure classification, bounded retries and recovery advice (v0.6.7 final hardening).

Offline and deterministic: the edge_tts ``Communicate`` class -- the one network boundary both Edge routes call -- is
replaced by a scripted fake, so every failure here is an exception the real client can raise (real aiohttp handshake
errors, real edge_tts exceptions) and no request leaves the machine. What is pinned:

* which failures are retried (transient) and which are not (HTTP 401/403, a changed protocol, a local file problem);
* that the bounded retry counts the routes always had are unchanged for transient failures (frozen constants);
* that a successful request is exactly what it always was (voice, text, rate, no extra arguments);
* that cancellation is never taken for a service failure, and never sits out a back-off;
* that a failed item publishes no audio while a completed sibling keeps its own;
* that the advice is one nontechnical line, carries no token or source text, and reaches the panel's failure record.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import socket
import time
from pathlib import Path

import aiohttp
import edge_tts
import pytest
from edge_tts import exceptions as edge_exc
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

import tts.batch_convert as bc
from shared import ffmpeg_utils
from shared.cancellation import ConversionCancelled
from shared.importing import ensure_display_safe
from tts import edge_failures
from tts.edge_failures import EdgeFailureKind as Kind
from tts.edge_failures import EdgeServiceError
from tts.epub2tts_edge import epub2tts_edge as engine

REQUIREMENTS = Path(__file__).resolve().parents[2] / "scripts" / "requirements.txt"
TOKEN_URL = (
    "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1"
    "?TrustedClientToken=6A5AA1D4EAFF4E9FB37E23D68491D6F4&Sec-MS-GEC=ABCDEF0123456789&Sec-MS-GEC-Version=1-143.0.1"
    "&ConnectionId=0123456789abcdef"
)
SECRET_PARTS = ("6A5AA1D4EAFF4E9FB37E23D68491D6F4", "ABCDEF0123456789", "0123456789abcdef")
SENTENCE = "Zanzibar quokkas whisper marmalade secrets."


def handshake_error(status: int, message: str = "Invalid response status") -> aiohttp.WSServerHandshakeError:
    info = aiohttp.RequestInfo(
        url=URL(TOKEN_URL), method="GET", headers=CIMultiDictProxy(CIMultiDict()), real_url=URL(TOKEN_URL))
    return aiohttp.WSServerHandshakeError(info, (), status=status, message=message)


def response_error(status: int) -> aiohttp.ClientResponseError:
    info = aiohttp.RequestInfo(
        url=URL(TOKEN_URL), method="GET", headers=CIMultiDictProxy(CIMultiDict()), real_url=URL(TOKEN_URL))
    return aiohttp.ClientResponseError(info, (), status=status, message="Server said no")


# --------------------------------------------------------------------------- #
# 1. Classification, from real exception types and attributes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "exc, kind",
    [
        (handshake_error(403), Kind.SERVICE_REFUSED),
        (handshake_error(401), Kind.SERVICE_REFUSED),
        (response_error(403), Kind.SERVICE_REFUSED),
        (edge_exc.SkewAdjustmentError("no date header"), Kind.SERVICE_REFUSED),
        (handshake_error(404), Kind.PROTOCOL),
        (handshake_error(426), Kind.PROTOCOL),
        (handshake_error(400), Kind.PROTOCOL),
        (edge_exc.UnknownResponse("Unknown path received"), Kind.PROTOCOL),
        (edge_exc.UnexpectedResponse("header length"), Kind.PROTOCOL),
        (handshake_error(429), Kind.NETWORK),
        (handshake_error(408), Kind.NETWORK),
        (handshake_error(500), Kind.NETWORK),
        (handshake_error(503), Kind.NETWORK),
        (edge_exc.WebSocketError("closed"), Kind.NETWORK),
        (aiohttp.ClientConnectionError("down"), Kind.NETWORK),
        (aiohttp.ServerDisconnectedError(), Kind.NETWORK),
        (aiohttp.ClientPayloadError("cut"), Kind.NETWORK),
        (asyncio.TimeoutError(), Kind.NETWORK),
        (TimeoutError(), Kind.NETWORK),
        (ConnectionResetError(), Kind.NETWORK),
        (socket.gaierror(11001, "getaddrinfo failed"), Kind.NETWORK),
        (edge_exc.NoAudioReceived("No audio was received."), Kind.UNKNOWN),
        (RuntimeError("Failed to save file from edge_tts"), Kind.UNKNOWN),
        (PermissionError(13, "denied"), Kind.LOCAL),
        (FileNotFoundError(2, "gone"), Kind.LOCAL),
        (OSError(28, "No space left on device"), Kind.LOCAL),
        (ValueError("Invalid voice 'x'."), Kind.LOCAL),
        (ConversionCancelled("Conversion cancelled by user."), Kind.CANCELLED),
        (asyncio.CancelledError(), Kind.CANCELLED),
        (KeyboardInterrupt(), Kind.CANCELLED),
    ],
    ids=lambda value: type(value).__name__ if isinstance(value, BaseException) else value.name,
)
def test_each_failure_is_classified_from_its_real_type_and_status(exc, kind):
    assert edge_failures.classify(exc) is kind


def test_only_transient_and_unrecognised_failures_are_retryable():
    assert {kind for kind in Kind if kind.retryable} == {Kind.NETWORK, Kind.UNKNOWN}


def test_the_classification_does_not_depend_on_the_message_text():
    """A 403 is a 403 whatever the library words it as; a connection error is not a refusal by name."""
    assert edge_failures.classify(handshake_error(403, "Totally different words")) is Kind.SERVICE_REFUSED
    assert edge_failures.classify(aiohttp.ClientConnectionError("403 Invalid response status")) is Kind.NETWORK


def test_a_wrapped_service_error_keeps_its_kind_so_an_outer_loop_does_not_retry_it():
    wrapped = edge_failures.final_error(handshake_error(403), 1)
    assert isinstance(wrapped, EdgeServiceError)
    assert edge_failures.classify(wrapped) is Kind.SERVICE_REFUSED
    assert edge_failures.is_retryable(wrapped) is False
    network = edge_failures.final_error(aiohttp.ClientConnectionError("down"), 3)
    assert edge_failures.is_retryable(network) is True, "exhausting a transient failure does not make it permanent"


# --------------------------------------------------------------------------- #
# 2. The wording: one nontechnical line, honest, token-free
# --------------------------------------------------------------------------- #


def test_the_advice_for_a_refusal_is_one_honest_line_that_promises_no_fix():
    error = edge_failures.final_error(handshake_error(403), 1)
    advice = error.advice
    ensure_display_safe("advice", advice)  # the panel's own rule: one line, no traceback
    assert "HTTP 403" in advice and "Microsoft" in advice
    assert "may not fix" in advice and "report" in advice and "date and time" in advice
    assert "will fix" not in advice and "should fix" not in advice
    assert "Traceback" not in advice


def test_every_kind_has_a_single_line_of_advice():
    for kind in (Kind.SERVICE_REFUSED, Kind.PROTOCOL, Kind.NETWORK, Kind.UNKNOWN):
        ensure_display_safe("advice", edge_failures.guidance(kind, 403))


def test_setup_and_run_is_pointed_to_only_when_the_installed_component_drifted_from_the_pin(monkeypatch):
    monkeypatch.setattr(edge_failures, "installed_edge_tts", lambda: edge_failures.EXPECTED_EDGE_TTS)
    assert "Setup_and_Run" not in edge_failures.guidance(Kind.SERVICE_REFUSED, 403)
    monkeypatch.setattr(edge_failures, "installed_edge_tts", lambda: "7.2.8")
    drifted = edge_failures.guidance(Kind.SERVICE_REFUSED, 403)
    assert "Setup_and_Run" in drifted and "7.2.8" in drifted and edge_failures.EXPECTED_EDGE_TTS in drifted
    ensure_display_safe("advice", drifted)
    assert "Setup_and_Run" not in edge_failures.guidance(Kind.NETWORK), "a network problem is not a repair matter"


def test_the_technical_detail_keeps_the_diagnosis_and_drops_tokens():
    error = edge_failures.final_error(handshake_error(403), 1)
    assert "WSServerHandshakeError (HTTP 403)" in error.technical
    assert "Invalid response status" in error.technical
    assert "1 attempt" in error.technical and f"edge-tts {edge_tts.__version__}" in error.technical
    text = str(error)
    for secret in SECRET_PARTS:
        assert secret not in text
    assert "\n" not in text and edge_failures.GUIDANCE_SEPARATOR in text


def test_scrub_removes_url_queries_and_bare_token_parameters_but_keeps_the_host():
    raw = f"failed wss://example.test/path?TrustedClientToken={SECRET_PARTS[0]}&x=1 and Sec-MS-GEC={SECRET_PARTS[1]}"
    cleaned = edge_failures.scrub(raw)
    assert "wss://example.test/path" in cleaned
    assert not any(secret in cleaned for secret in SECRET_PARTS)
    assert "hunter2" not in edge_failures.scrub("see https://example.test/x?someNewParam=hunter2 now"), (
        "a URL query is dropped whole, so a parameter the service adds later cannot leak")


def test_the_expected_version_constant_is_the_pinned_one():
    pins = re.findall(r"^edge-tts==(\S+)", REQUIREMENTS.read_text(encoding="utf-8"), re.MULTILINE)
    assert pins == [edge_failures.EXPECTED_EDGE_TTS]
    assert edge_tts.__version__ == edge_failures.EXPECTED_EDGE_TTS


def test_split_failure_text_reads_the_bare_and_the_panel_forms_and_ignores_a_following_traceback():
    error = edge_failures.final_error(handshake_error(403), 1)
    assert edge_failures.split_failure_text(str(error)) == error.advice
    assert edge_failures.split_failure_text(f"EdgeServiceError: {error}") == error.advice
    assert edge_failures.split_failure_text(f"{error}\nTraceback (most recent call last):\n  ...") == error.advice
    assert edge_failures.split_failure_text("RuntimeError: engine refused this book") is None
    assert edge_failures.split_failure_text("") is None


def test_cancellation_and_local_problems_keep_their_own_type():
    cancelled = ConversionCancelled("stop")
    local = PermissionError(13, "denied")
    assert edge_failures.final_error(cancelled, 1) is cancelled
    assert edge_failures.final_error(local, 1) is local


# --------------------------------------------------------------------------- #
# 3. A scripted Communicate: the boundary both routes call
# --------------------------------------------------------------------------- #


@pytest.fixture
def silent_mp3(tmp_path_factory) -> bytes:
    if not ffmpeg_utils.have_ffmpeg():  # pragma: no cover - environment guard
        pytest.skip("ffmpeg not available for pydub")
    ffmpeg_utils.configure_pydub()
    from pydub import AudioSegment

    path = tmp_path_factory.mktemp("clip") / "silent.mp3"
    AudioSegment.silent(duration=120).export(str(path), format="mp3")
    return path.read_bytes()


class Script:
    """Replaces ``edge_tts.Communicate``. Each ``save`` consumes one scripted outcome: an exception or ``b"audio"``."""

    def __init__(self, monkeypatch, outcomes, audio: bytes = b"audio"):
        self.outcomes = list(outcomes)
        self.audio = audio
        self.constructed: list[tuple[tuple, dict]] = []
        self.sleeps: list[float] = []
        self.on_construct = None  # called with no arguments when a request is made
        script = self

        class FakeCommunicate:
            def __init__(self, *args, **kwargs):
                # What ACT passes must bind to the real client's signature (see also test_edge_tts_pin).
                inspect.signature(script.real.__init__).bind(None, *args, **kwargs)
                script.constructed.append((args, kwargs))
                if script.on_construct is not None:
                    script.on_construct()

            async def save(self, path, *_):
                outcome = script.outcomes.pop(0) if script.outcomes else script.outcomes_default
                if isinstance(outcome, BaseException):
                    Path(path).write_bytes(b"")  # the real save opens the file before the handshake can fail
                    raise outcome
                Path(path).write_bytes(script.audio)

        self.real = edge_tts.Communicate
        self.outcomes_default = RuntimeError("script exhausted")
        monkeypatch.setattr(edge_tts, "Communicate", FakeCommunicate)
        monkeypatch.setattr(time, "sleep", self.sleeps.append)

    @property
    def calls(self) -> int:
        return len(self.constructed)


# --------------------------------------------------------------------------- #
# 4. Edge direct (run_edgespeak)
# --------------------------------------------------------------------------- #


def test_direct_a_refused_handshake_is_not_retried_and_says_what_to_do(tmp_path, monkeypatch, capsys):
    script = Script(monkeypatch, [handshake_error(403)] * 3)
    target = tmp_path / "s.mp3"
    with pytest.raises(EdgeServiceError) as caught:
        engine.run_edgespeak(SENTENCE, "en-US-SteffanNeural", str(target))
    error = caught.value
    assert script.calls == 1, "retrying a remote 403 only repeats it"
    assert script.sleeps == []
    assert error.kind is Kind.SERVICE_REFUSED and "HTTP 403" in error.advice
    assert not target.exists(), "the failed attempt's partial audio is removed"
    shown = capsys.readouterr().out + str(error)
    assert SENTENCE not in shown and not any(secret in shown for secret in SECRET_PARTS)
    assert isinstance(error.__cause__, aiohttp.WSServerHandshakeError), "the original exception stays attached"


def test_direct_a_changed_protocol_is_not_retried(tmp_path, monkeypatch):
    script = Script(monkeypatch, [edge_exc.UnexpectedResponse("header")] * 3)
    with pytest.raises(EdgeServiceError) as caught:
        engine.run_edgespeak(SENTENCE, "en-US-SteffanNeural", str(tmp_path / "s.mp3"))
    assert script.calls == 1 and caught.value.kind is Kind.PROTOCOL
    assert "report" in caught.value.advice


def test_direct_a_transient_failure_keeps_the_three_bounded_attempts_and_keeps_its_diagnosis(tmp_path, monkeypatch):
    script = Script(monkeypatch, [aiohttp.ClientConnectionError("offline")] * 3)
    with pytest.raises(EdgeServiceError) as caught:
        engine.run_edgespeak(SENTENCE, "en-US-SteffanNeural", str(tmp_path / "s.mp3"))
    error = caught.value
    assert script.calls == 3 and script.sleeps == [3, 3], "no wait after the last attempt, none unbounded"
    assert error.kind is Kind.NETWORK
    assert "ClientConnectionError" in error.technical and "3 attempts" in error.technical
    assert SENTENCE not in str(error), "the book's text is not in the diagnosis"
    assert "Retry Failed" in error.advice


def test_direct_a_transient_failure_that_recovers_publishes_the_normal_result(tmp_path, monkeypatch):
    script = Script(monkeypatch, [aiohttp.ServerDisconnectedError(), b"audio"])
    target = tmp_path / "s.mp3"
    engine.run_edgespeak(SENTENCE, "en-US-SteffanNeural", str(target))
    assert script.calls == 2 and script.sleeps == [3]
    assert target.read_bytes() == b"audio"


def test_direct_a_local_file_problem_is_not_retried_and_keeps_its_own_type(tmp_path, monkeypatch):
    script = Script(monkeypatch, [PermissionError(13, "denied")] * 3)
    with pytest.raises(PermissionError):
        engine.run_edgespeak(SENTENCE, "en-US-SteffanNeural", str(tmp_path / "s.mp3"))
    assert script.calls == 1 and script.sleeps == []


def test_direct_a_cancelled_request_is_raised_as_cancellation_not_as_a_service_failure(tmp_path, monkeypatch):
    script = Script(monkeypatch, [ConversionCancelled("Conversion cancelled by user.")] * 3)
    with pytest.raises(ConversionCancelled):
        engine.run_edgespeak(SENTENCE, "en-US-SteffanNeural", str(tmp_path / "s.mp3"))
    assert script.calls == 1 and script.sleeps == []


def test_direct_a_successful_request_is_exactly_the_request_it_always_was(tmp_path, monkeypatch):
    script = Script(monkeypatch, [b"audio"])
    engine.run_edgespeak(SENTENCE, "en-US-SteffanNeural", str(tmp_path / "s.mp3"))
    assert script.constructed == [((SENTENCE, "en-US-SteffanNeural"), {})]
    assert script.sleeps == []


def test_direct_an_unspeakable_chunk_still_makes_no_request(tmp_path, monkeypatch):
    script = Script(monkeypatch, [])
    pytest.importorskip("pydub")
    if not ffmpeg_utils.have_ffmpeg():  # pragma: no cover
        pytest.skip("ffmpeg not available for pydub")
    ffmpeg_utils.configure_pydub()
    engine.run_edgespeak("...", "en-US-SteffanNeural", str(tmp_path / "s.mp3"))
    assert script.calls == 0


def test_direct_a_failure_publishes_no_output_through_the_runner(tmp_path, monkeypatch):
    """The real runner: a refused service ends in a clear error and leaves nothing in the output folder."""
    from tts.epub2tts_edge import runner

    monkeypatch.setattr(engine, "ensure_punkt", lambda: None)
    script = Script(monkeypatch, [handshake_error(403)] * 20)
    source = tmp_path / "book.txt"
    source.write_text("Title: T\nAuthor: A\n# One\n\nA single paragraph to read.\n", encoding="utf-8")
    out = tmp_path / "out"
    with pytest.raises(EdgeServiceError) as caught:
        runner.run_conversion_job(str(source), output_dir=str(out), audio_format="mp3")
    assert caught.value.kind is Kind.SERVICE_REFUSED
    assert script.calls <= 2, "the title and the first sentence at most, never a retry storm"
    assert not out.exists() or not list(out.iterdir())


# --------------------------------------------------------------------------- #
# 5. Edge folder (convert_single_pdf / run_batch_convert)
# --------------------------------------------------------------------------- #


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "INTER_CHUNK_DELAY_SEC", 0)
    source = tmp_path / "in" / "chapter.txt"
    source.parent.mkdir()
    source.write_text(SENTENCE + "\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    return source, out


def convert(source: Path, out: Path, log, **kwargs):
    return bc.convert_single_pdf(source, out, "en-US-SteffanNeural", "+0%", log=log, out_mp3=out / "chapter.mp3", **kwargs)


def test_folder_a_refused_handshake_makes_one_request_not_fifteen(folder, monkeypatch):
    source, out = folder
    script = Script(monkeypatch, [handshake_error(403)] * 50)
    lines: list[str] = []
    status, path, message = convert(source, out, lines.append)
    assert status == "failed" and path == source
    assert script.calls == 1, "before: 5 chunk attempts x 3 whole-file attempts = 15 requests"
    assert script.sleeps == [], "no back-off, no 5 s whole-file pause for a permanent refusal"
    first = message.splitlines()[0]
    assert "HTTP 403" in first and edge_failures.GUIDANCE_SEPARATOR in first
    assert edge_failures.split_failure_text(message) is not None
    assert not any(secret in message for secret in SECRET_PARTS), "the traceback in the log is scrubbed too"
    assert "Traceback" in message, "the diagnosis is kept"
    assert not (out / "chapter.mp3").exists()
    assert not (out / ".tmp_chunks").exists() or not any((out / ".tmp_chunks").iterdir())


def test_folder_a_transient_failure_keeps_its_approved_bounded_retries(folder, monkeypatch):
    source, out = folder
    script = Script(monkeypatch, [aiohttp.ClientConnectionError("offline")] * 100)
    lines: list[str] = []
    status, _path, message = convert(source, out, lines.append)
    attempts = bc.CHUNK_MAX_RETRIES * (bc.PDF_MAX_RETRIES + 1)
    assert status == "failed" and script.calls == attempts
    assert script.sleeps.count(5) == bc.PDF_MAX_RETRIES
    assert [s for s in script.sleeps if s != 5] == [2, 4, 8, 16] * (bc.PDF_MAX_RETRIES + 1)
    assert "Check your internet connection" in message.splitlines()[0]
    assert "ClientConnectionError" in message and f"{bc.CHUNK_MAX_RETRIES} attempts" in message
    retry_lines = [line for line in lines if "[retry" in line]
    assert retry_lines and not any(SENTENCE in line for line in retry_lines)


def test_folder_a_transient_failure_that_recovers_publishes_the_normal_result(folder, monkeypatch, silent_mp3):
    source, out = folder
    script = Script(monkeypatch, [aiohttp.ServerDisconnectedError(), handshake_error(503), silent_mp3], audio=silent_mp3)
    status, _path, message = convert(source, out, lambda s: None)
    assert (status, message) == ("success", None)
    assert script.calls == 3 and [s for s in script.sleeps if s] == [2, 4]  # 0 s is the inter-chunk delay
    assert (out / "chapter.mp3").is_file()


def test_folder_a_successful_request_is_exactly_the_request_it_always_was(folder, monkeypatch, silent_mp3):
    source, out = folder
    script = Script(monkeypatch, [silent_mp3], audio=silent_mp3)
    status, *_ = convert(source, out, lambda s: None)
    assert status == "success"
    assert script.constructed == [((), {"text": SENTENCE, "voice": "en-US-SteffanNeural", "rate": "+0%"})]


def test_folder_a_local_error_is_not_retried_as_a_whole_file(folder, monkeypatch):
    source, out = folder
    script = Script(monkeypatch, [PermissionError(13, "denied")] * 50)
    status, _path, message = convert(source, out, lambda s: None)
    assert status == "failed" and script.calls == 1 and script.sleeps == []
    assert message.startswith("[Errno 13]") and edge_failures.split_failure_text(message) is None


def test_folder_cancelling_during_a_back_off_stops_without_waiting(folder, monkeypatch):
    source, out = folder
    script = Script(monkeypatch, [aiohttp.ClientConnectionError("offline")] * 50)
    state = {"cancel": False}
    script.on_construct = lambda: state.update(cancel=True)  # the user presses Cancel as the first request fails
    status, _path, message = convert(source, out, lambda s: None, cancel_check=lambda: state["cancel"])
    assert (status, message) == ("cancelled", None)
    assert script.calls == 1 and script.sleeps == []
    assert not (out / "chapter.mp3").exists()


def test_folder_a_failing_file_leaves_a_completed_sibling_untouched(tmp_path, monkeypatch, silent_mp3):
    monkeypatch.setattr(bc, "INTER_CHUNK_DELAY_SEC", 0)
    src = tmp_path / "in"
    src.mkdir()
    (src / "a good.txt").write_text("Good sentence one.\n", encoding="utf-8")
    (src / "b bad.txt").write_text("Bad sentence two.\n", encoding="utf-8")
    out = tmp_path / "out"

    class Fake:
        def __init__(self, text, voice, rate):
            self.text = text

        async def save(self, path):
            if "Bad" in self.text:
                Path(path).write_bytes(b"")
                raise handshake_error(403)
            Path(path).write_bytes(silent_mp3)

    monkeypatch.setattr(edge_tts, "Communicate", Fake)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    ok, fail, error_log = bc.run_batch_convert(src, out, workers=1, use_tqdm=False, log=lambda s: None)
    assert (ok, fail) == (1, 1)
    label = "Edge Male - Steffan (en-US)"  # v0.7.0 P02B: <stem>-<display label>.mp3
    assert (out / f"a good-{label}.mp3").is_file() and not (out / f"b bad-{label}.mp3").exists()
    logged = error_log.read_text(encoding="utf-8")
    assert "refused the connection" in logged and not any(secret in logged for secret in SECRET_PARTS)
    assert not (out / ".tmp_chunks").exists()
