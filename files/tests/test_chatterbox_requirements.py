"""v0.6.1 Plan 4 Phase 8 — the Chatterbox dependency contract, asserted by value.

Phase 8a proved a *specific* resolver result in an isolated Python 3.12 venv, and
the maintainer accepted exactly that stack. These tests assert the committed
``scripts/requirements.txt`` still expresses it, by parsed name/version — never by
searching the comment prose, which would pass even if a pin drifted.

The one non-additive change is ``setuptools``: Chatterbox's Perth watermarker
imports ``pkg_resources``, which setuptools 82 removed, so the pin steps back to
80.9.0. That is deliberate compatibility debt and is asserted here so it cannot
be "tidied" forward without a failing test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REQUIREMENTS = REPO_ROOT / "scripts" / "requirements.txt"


def _normalize(name: str) -> str:
    """PEP 503 name normalization (``spacy_pkuseg`` and ``spacy-pkuseg`` are one)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(text: str) -> dict[str, tuple[str, str]]:
    """``{normalized name: (version, marker)}`` for every real requirement line."""
    parsed: dict[str, tuple[str, str]] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        spec, _, marker = line.partition(";")
        name, sep, version = spec.strip().partition("==")
        assert sep, f"requirement is not '=='-pinned: {line!r}"
        parsed[_normalize(name.strip())] = (version.strip(), marker.strip())
    return parsed


@pytest.fixture(scope="module")
def pins() -> dict[str, tuple[str, str]]:
    return parse_requirements(REQUIREMENTS.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# The engine package itself
# --------------------------------------------------------------------------- #
def test_the_chatterbox_engine_package_is_pinned_to_the_proven_release(pins):
    assert pins["chatterbox-tts"][0] == "0.1.7"


def test_chatterbox_is_gated_to_the_python_kokoro_also_requires(pins):
    """The venv is capped <3.13 by Kokoro's wheels; nothing above it was proven."""
    assert pins["chatterbox-tts"][1] == 'python_version < "3.13"'


# --------------------------------------------------------------------------- #
# The setuptools compatibility debt — the reason the engine can construct at all
# --------------------------------------------------------------------------- #
def test_setuptools_is_pinned_to_the_release_that_still_ships_pkg_resources(pins):
    assert pins["setuptools"][0] == "80.9.0"


def test_the_setuptools_pin_carries_no_marker_because_the_debt_is_global(pins):
    assert pins["setuptools"][1] == ""


def test_the_removed_pkg_resources_setuptools_is_gone(pins):
    """82.0.1 is what broke ``perth.PerthImplicitWatermarker`` construction."""
    assert pins["setuptools"][0] != "82.0.1"


def test_the_reason_for_the_downgrade_is_recorded_beside_the_pin():
    """Prose check *in addition to* the value checks above, never instead of them."""
    text = REQUIREMENTS.read_text(encoding="utf-8").lower()
    assert "pkg_resources" in text
    assert "perth" in text


# --------------------------------------------------------------------------- #
# The compatibility pins Chatterbox itself leaves floating — Phase 8a resolved
# these, so they are pinned here or the stack is not reproducible.
# --------------------------------------------------------------------------- #
FLOATING_UPSTREAM = {
    "numpy": "1.26.4",          # chatterbox declares >=1.24,<2.0 — a range
    "resemble-perth": "1.0.1",  # chatterbox declares >=1.0.0
    "s3tokenizer": "0.3.0",     # chatterbox declares no version at all
    "spacy-pkuseg": "1.0.1",    # chatterbox declares no version at all
    "pyloudnorm": "0.2.0",      # chatterbox declares no version at all
    "omegaconf": "2.3.1",       # chatterbox declares no version at all
}


@pytest.mark.parametrize("name,version", sorted(FLOATING_UPSTREAM.items()))
def test_every_upstream_floating_dependency_is_pinned_here(pins, name, version):
    assert name in pins, f"{name} is unpinned upstream and must be pinned here"
    assert pins[name][0] == version


# --------------------------------------------------------------------------- #
# The three headline downgrades — pinned explicitly so the effect is visible in
# the file rather than buried in a transitive resolution.
# --------------------------------------------------------------------------- #
HEADLINE_DOWNGRADES = {
    "torch": "2.6.0",
    "torchaudio": "2.6.0",
    "transformers": "5.2.0",
    "safetensors": "0.5.3",
}


@pytest.mark.parametrize("name,version", sorted(HEADLINE_DOWNGRADES.items()))
def test_the_constrained_stack_is_stated_not_merely_implied(pins, name, version):
    assert pins[name][0] == version


@pytest.mark.parametrize("name", sorted(set(HEADLINE_DOWNGRADES) | set(FLOATING_UPSTREAM)))
def test_the_chatterbox_stack_shares_chatterboxs_own_python_gate(pins, name):
    if name in ("torch", "torchaudio", "transformers", "safetensors", "numpy"):
        assert pins[name][1] == 'python_version < "3.13"'


def test_no_cuda_specific_torch_build_is_pinned():
    """Nothing CUDA is authorized: no +cu local version, no extra index URL."""
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert "+cu" not in text
    assert "--index-url" not in text
    assert "--extra-index-url" not in text
    assert "download.pytorch.org" not in text


def test_no_dependency_is_sourced_from_a_git_or_master_reference():
    text = REQUIREMENTS.read_text(encoding="utf-8")
    for token in ("git+", "@ http", "#egg=", "/master", "/main"):
        assert token not in text, f"unpinned source reference {token!r} in requirements"


# --------------------------------------------------------------------------- #
# Preservation — the pre-existing project pins are untouched by Phase 8
# --------------------------------------------------------------------------- #
UNCHANGED_PROJECT_PINS = {
    "edge-tts": "7.2.8",
    "mutagen": "1.47.0",
    "nltk": "3.9.4",
    "pillow": "12.2.0",
    "pydub": "0.25.1",
    "pymupdf": "1.27.2.3",
    "tqdm": "4.67.3",
    "soundfile": "0.13.1",
    "scipy": "1.17.1",
    "kokoro": "0.9.4",
    "pytest": "9.1.1",
    "pillow-heif": "1.5.0",
    "audioop-lts": "0.2.2",
}


@pytest.mark.parametrize("name,version", sorted(UNCHANGED_PROJECT_PINS.items()))
def test_phase_eight_changed_no_pre_existing_pin(pins, name, version):
    assert pins[name][0] == version


def test_kokoro_still_carries_its_original_python_gate(pins):
    assert pins["kokoro"][1] == 'python_version < "3.13"'


def test_the_pinned_numpy_satisfies_the_scipy_kokoro_audio_path(pins):
    """scipy 1.17.1 declares numpy>=1.26.4,<2.7 — the overlap is exactly 1.26.4."""
    assert pins["numpy"][0] == "1.26.4"
    assert pins["scipy"][0] == "1.17.1"


def test_every_requirement_line_is_exactly_pinned(pins):
    """The project rule, re-asserted over the widened list."""
    for name, (version, _marker) in pins.items():
        assert version, f"{name} has no pinned version"
        assert not re.search(r"[<>~!*]", version), f"{name} pin is not exact: {version}"
