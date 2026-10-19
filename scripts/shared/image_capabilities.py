"""Centralized image-format capability detection.

Pillow gives every machine JPEG and PNG unconditionally. **HEIC/HEIF does not
work that way.** It needs the optional ``pillow-heif`` plugin, and that plugin
in turn wraps a ``libheif`` build which may have been compiled with a *decoder*
and no *encoder*. Decision 54A asks for HEIC/HEIF to be a pinned, probed, tested
capability rather than a silent ``try: import … except: pass``; Decision 3A adds
that a HEIC input must produce a HEIC output and must **never** be quietly
written as a ``.jpg`` instead.

Two consequences shape this module:

**Decode and encode are separate capabilities and are reported separately.**
They are never collapsed into one boolean. A build that reads HEIC but cannot
write it is a real configuration, and a panel that offers HEIC output on such a
machine would either crash or silently substitute JPEG — under the Cover tool's
source-side replacement mode that substitution would destroy the original's
format irreversibly.

**Capability is proved by behaviour, not by an import succeeding.** Importing
``pillow_heif`` and calling ``register_heif_opener()`` proves only that a plugin
registered itself. Whether an encoder actually exists behind that registration
is answered here by encoding one real pixel and seeing what happens. That also
means this module depends on no upstream symbol beyond
``register_heif_opener`` — a version whose capability-query helpers are renamed
or removed still probes correctly.

Nothing here raises on its way to an answer. An unusable, missing or broken
optional codec yields a capability that says so, with a truthful ``detail``
string for the log; it never prevents a panel, the launcher or an unrelated tool
from importing or starting. The one function that *does* raise,
:func:`require_encoder`, is the deliberate refusal to write the wrong format.
"""

from __future__ import annotations

import io
import threading
from dataclasses import dataclass

#: Formats Pillow itself always provides. No probe, no plugin, no optional wheel.
BASELINE_SUFFIXES: tuple[str, ...] = (".jpg", ".jpeg", ".png")

#: The optional pair this module exists for.
HEIF_SUFFIXES: tuple[str, ...] = (".heic", ".heif")

#: The Pillow format name ``pillow-heif`` registers for both suffixes above.
HEIF_FORMAT = "HEIF"


class UnsupportedImageFormat(Exception):
    """Refusal to write an image in a format this machine cannot produce.

    Carries the same ``message`` / ``detail`` shape as
    :class:`shared.output_paths.OutputPathError`: ``message`` is written for a
    person and is safe to show in a dialog, ``detail`` keeps the technical
    remainder for the log. Raised *instead of* silently writing a different
    format, which is the whole point of Decision 3A.
    """

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


@dataclass(frozen=True)
class FormatCapability:
    """What this machine can actually do with one image-format family.

    ``decode`` and ``encode`` are independent on purpose — see the module
    docstring. ``detail`` is empty when everything works and otherwise explains,
    truthfully and specifically, what is missing.
    """

    name: str
    suffixes: tuple[str, ...]
    decode: bool
    encode: bool
    detail: str = ""

    @property
    def available(self) -> bool:
        """True when the format is usable in *either* direction.

        Deliberately not "fully working": a decode-only build is still worth
        offering for import, and the encode side refuses separately.
        """
        return self.decode or self.encode

    @property
    def fully_supported(self) -> bool:
        """True only when this machine can both read and write the format."""
        return self.decode and self.encode


def _describe(exc: BaseException) -> str:
    """A one-line, log-safe rendering of a failure. Never a traceback."""
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0]}" if text else type(exc).__name__


# --------------------------------------------------------------------------- #
# The four probe steps.
#
# Each is a separate injectable seam so the suite can construct available,
# unavailable, decode-only, encode-only, failing-registration and
# failing-probe machines without needing any of them to be true of the host.
# --------------------------------------------------------------------------- #


def _default_import():
    """Import the optional plugin. Raises ``ImportError`` when it is absent."""
    import pillow_heif

    return pillow_heif


def _default_register(module) -> None:
    """Register the plugin with Pillow. Idempotent upstream and here."""
    module.register_heif_opener()


def _default_decode_check() -> bool:
    """True when Pillow will now open a HEIF file.

    Read from Pillow's own registries rather than from ``pillow_heif``, because
    the question is whether *Pillow* gained the reader — that is what every
    ``Image.open`` call in this project actually goes through.
    """
    from PIL import Image

    extensions = Image.registered_extensions()
    return HEIF_FORMAT in Image.OPEN and all(
        extensions.get(suffix) == HEIF_FORMAT for suffix in HEIF_SUFFIXES
    )


def _default_encode_check() -> None:
    """Encode one real pixel to memory. Raises when encoding is unavailable.

    This is the only honest test. ``register_heif_opener`` registers a *saver*
    whether or not the underlying libheif build has an HEVC encoder compiled in,
    so asking the registry would report an encoder that does not exist. One
    1×1 image costs nothing and answers the real question.
    """
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, format=HEIF_FORMAT)
    if not buffer.getvalue():
        raise ValueError("the HEIF encoder produced no bytes")


def _unavailable(detail: str) -> FormatCapability:
    return FormatCapability("heif", HEIF_SUFFIXES, False, False, detail)


def probe_heif(
    *,
    importer=None,
    register=None,
    decode_check=None,
    encode_check=None,
) -> FormatCapability:
    """Determine HEIC/HEIF decode and encode capability. **Never raises.**

    The four keyword seams default to the real implementations above and exist
    so the suite can prove every branch — installed, absent, decode-only,
    encode-only, registration blowing up, a probe blowing up — on any machine.
    Production calls this with no arguments, through :func:`heif_capability`.
    """
    importer = _default_import if importer is None else importer
    register = _default_register if register is None else register
    decode_check = _default_decode_check if decode_check is None else decode_check
    encode_check = _default_encode_check if encode_check is None else encode_check

    try:
        module = importer()
    except Exception as exc:  # noqa: BLE001 - report it, never crash a panel
        return _unavailable(
            f"HEIC/HEIF support is not installed ({_describe(exc)}); "
            "install pillow-heif to enable it"
        )

    try:
        register(module)
    except Exception as exc:  # noqa: BLE001
        return _unavailable(
            f"HEIC/HEIF support is installed but could not register with Pillow "
            f"({_describe(exc)})"
        )

    try:
        decode = bool(decode_check())
        decode_detail = "" if decode else "pillow-heif registered no HEIF reader with Pillow"
    except Exception as exc:  # noqa: BLE001
        decode = False
        decode_detail = f"the HEIF decoder probe failed ({_describe(exc)})"

    try:
        encode_check()
        encode = True
        encode_detail = ""
    except Exception as exc:  # noqa: BLE001
        encode = False
        encode_detail = f"this HEIC/HEIF build cannot write HEIF ({_describe(exc)})"

    detail = "; ".join(part for part in (decode_detail, encode_detail) if part)
    return FormatCapability("heif", HEIF_SUFFIXES, decode, encode, detail)


# --------------------------------------------------------------------------- #
# The cached, process-wide answer.
# --------------------------------------------------------------------------- #

_lock = threading.Lock()
_cached: FormatCapability | None = None


def heif_capability(*, refresh: bool = False, probe=None) -> FormatCapability:
    """The HEIC/HEIF capability of this machine, probed once per process.

    Caching is what makes plugin registration happen **exactly once**: the probe
    body — and therefore ``register_heif_opener()`` — runs on the first call and
    never again unless ``refresh`` is passed. The lock is held across the probe
    so two worker threads asking at the same moment cannot both register.

    ``probe`` is a test seam (the same pattern ``verify.check_doc_names`` uses):
    production never passes it.
    """
    global _cached
    prober = probe_heif if probe is None else probe
    with _lock:
        if _cached is None or refresh:
            _cached = prober()
        return _cached


def reset_cache() -> None:
    """Forget the cached probe result. For tests; production never calls it."""
    global _cached
    with _lock:
        _cached = None


# --------------------------------------------------------------------------- #
# What consumers ask.
# --------------------------------------------------------------------------- #


def decodable_suffixes() -> tuple[str, ...]:
    """Every extension a panel may offer for *import* on this machine.

    JPG/JPEG/PNG always; HEIC/HEIF only when the probe says this machine can
    actually read them. Offering a type that cannot be opened is the untruthful
    case this replaces.
    """
    return BASELINE_SUFFIXES + (HEIF_SUFFIXES if heif_capability().decode else ())


def encodable_suffixes() -> tuple[str, ...]:
    """Every extension this machine can actually *write*."""
    return BASELINE_SUFFIXES + (HEIF_SUFFIXES if heif_capability().encode else ())


def can_decode(suffix: str) -> bool:
    return (suffix or "").lower() in decodable_suffixes()


def can_encode(suffix: str) -> bool:
    return (suffix or "").lower() in encodable_suffixes()


def require_encoder(suffix: str) -> None:
    """Pass silently when ``suffix`` can be written; otherwise refuse.

    Decision 3A in one function: when HEIF encoding is unavailable the caller
    gets a truthful :class:`UnsupportedImageFormat` naming the missing
    capability, **not** a file quietly written as something else.
    """
    lowered = (suffix or "").lower()
    if can_encode(lowered):
        return
    if lowered in HEIF_SUFFIXES:
        capability = heif_capability()
        raise UnsupportedImageFormat(
            f"This computer cannot write {lowered} images, so the original "
            f"format cannot be preserved. Nothing was converted to another "
            f"format. Install HEIC/HEIF support and try again.",
            capability.detail or "HEIF encoding unavailable",
        )
    raise UnsupportedImageFormat(
        f"{lowered or '(no extension)'} is not an image format this tool can write.",
        "unsupported output suffix",
    )
