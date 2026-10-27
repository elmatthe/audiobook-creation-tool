"""Fixed trusted-producer admission, independent of runtime/engine imports.

Bytes include raw metadata reads, canonical JSON representations of enumerated
names and constructed identity/state rows, and the complete canonical Plan.
Repeated representations are deliberately charged again; this is an admission
budget, not a measurement of peak Python memory. Weight content is not metadata.
The clock starts on first metadata use. One OS call cannot be preempted by polls.
"""
from __future__ import annotations

import contextlib
import json
import time

MAX_OPERATIONS = 32
MAX_EVENTS = 4096
MAX_PARTIALS = 256
MAX_ENTRIES = 8192
MAX_BYTES = 16 * 1024 * 1024
MAX_SECONDS = 30
COUNTS = {'operations': MAX_OPERATIONS, 'events': MAX_EVENTS,
          'partials': MAX_PARTIALS, 'entries': MAX_ENTRIES}


class ResourceLimit(ValueError):
    """Complete metadata cannot be admitted; no partial result is authority."""


class Cancelled(Exception):
    """Cancellation, deliberately distinct from corrupt persisted metadata."""


class Budget:
    """One trusted evaluation; ceilings cannot be supplied by a request/caller.

    Only clock/cancellation are injectable. Content verification may explicitly
    suspend elapsed metadata time without resetting counters or prior elapsed time.
    """
    def __init__(self, *, cancelled=lambda: False, clock=time.monotonic):
        self.cancelled, self.clock = cancelled, clock
        self.started = None
        self.used_bytes = 0
        self.counts = dict.fromkeys(COUNTS, 0)

    def check(self, cancelled=lambda: False):
        if self.cancelled() or cancelled():
            raise Cancelled('metadata cancelled')
        now = self.clock()
        if self.started is None:
            self.started = now
        if now - self.started > MAX_SECONDS:
            raise ResourceLimit('metadata deadline exceeded')

    @staticmethod
    def _integer(value):
        if type(value) is not int or value < 0:
            raise ValueError('invalid metadata counter')

    def ensure(self, kind, amount=1):
        self.check()
        self._integer(amount)
        if kind not in COUNTS:
            raise ValueError('unknown metadata counter')
        if amount > COUNTS[kind] - self.counts[kind]:
            raise ResourceLimit('metadata ' + kind + ' limit exceeded')

    def take(self, kind, amount=1):
        self.ensure(kind, amount)
        self.counts[kind] += amount

    def ensure_bytes(self, amount):
        self.check()
        self._integer(amount)
        if amount > MAX_BYTES - self.used_bytes:
            raise ResourceLimit('metadata byte limit exceeded')

    def charge(self, amount):
        self.ensure_bytes(amount)
        self.used_bytes += amount

    @contextlib.contextmanager
    def content(self):
        """Exclude actual content work only; cancellation is still checked by its caller."""
        before = self.clock()
        try:
            yield
        finally:
            if self.started is not None:
                self.started += self.clock() - before

    def chunks(self, value):
        """Canonical ASCII, sorted keys, compact separators, no NaN.

        Unlike JSONEncoder.iterencode, even one string is emitted in bounded
        pieces. Container minimum output is admitted before sorting keys. Output
        is charged before retention, including punctuation and escaped scalars.
        """
        def emit(raw):
            self.charge(len(raw))
            return raw

        def string(text):
            yield emit(b'"')
            for start in range(0, len(text), 256):
                self.check()
                yield emit(json.encoder.encode_basestring_ascii(text[start:start + 256])[1:-1].encode('ascii'))
            yield emit(b'"')

        def walk(item):
            self.check()
            if type(item) is str:
                yield from string(item)
            elif type(item) is dict:
                self.ensure_bytes(2 + max(0, len(item) - 1) + 4 * len(item))
                yield emit(b'{')
                for index, key in enumerate(sorted(item)):
                    if type(key) is not str:
                        raise ValueError('metadata object keys must be strings')
                    if index:
                        yield emit(b',')
                    yield from string(key)
                    yield emit(b':')
                    yield from walk(item[key])
                yield emit(b'}')
            elif type(item) in (list, tuple):
                self.ensure_bytes(2 + max(0, len(item) - 1) + len(item))
                yield emit(b'[')
                for index, child in enumerate(item):
                    if index:
                        yield emit(b',')
                    yield from walk(child)
                yield emit(b']')
            else:
                if type(item) is int and item.bit_length() > (MAX_BYTES - self.used_bytes) * 4:
                    raise ResourceLimit('metadata byte limit exceeded')
                yield emit(json.dumps(item, allow_nan=False, separators=(',', ':')).encode('ascii'))
        yield from walk(value)
        self.check()

    def account(self, value):
        for _ in self.chunks(value):
            pass

    def encode(self, value):
        result = bytearray()
        for chunk in self.chunks(value):
            result.extend(chunk)
        return bytes(result)
