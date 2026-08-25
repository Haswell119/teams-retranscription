from __future__ import annotations

import os
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Final

NAMESPACE: Final[str] = "hansard"

CONTENT_TYPE_LATEST: Final[str] = "text/plain; version=0.0.4; charset=utf-8"

FORBIDDEN_LABEL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "address",
        "email",
        "join_url",
        "joinurl",
        "meeting",
        "meeting_id",
        "meetingid",
        "participant",
        "participant_id",
        "path",
        "recipient",
        "request_id",
        "speaker",
        "subject",
        "tenant",
        "tenant_id",
        "title",
        "url",
        "user",
        "user_id",
        "userid",
    }
)

_DURATION_BUCKETS: Final[tuple[float, ...]] = (
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
    1800.0,
    3600.0,
)

_JOIN_BUCKETS: Final[tuple[float, ...]] = (
    1.0,
    2.5,
    5.0,
    10.0,
    20.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
)

_RTF_BUCKETS: Final[tuple[float, ...]] = (
    0.02,
    0.05,
    0.1,
    0.2,
    0.35,
    0.5,
    0.75,
    1.0,
    1.5,
    2.0,
    4.0,
)

_SPEAKER_BUCKETS: Final[tuple[float, ...]] = (1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0)


class UnsafeLabelError(ValueError):
    pass


def _reject_unsafe_labels(name: str, labelnames: Sequence[str]) -> None:
    unsafe = sorted(set(labelnames) & FORBIDDEN_LABEL_NAMES)
    if unsafe:
        raise UnsafeLabelError(f"metric {name!r} would carry high-cardinality or identifying labels {unsafe}")


class _NullRegistry:
    def register(self, _collector: Any) -> None:
        return None

    def unregister(self, _collector: Any) -> None:
        return None

    def collect(self) -> Iterator[Any]:
        return iter(())


def _load_backend() -> tuple[Any | None, Any]:
    try:
        import prometheus_client
    except ImportError:
        return None, _NullRegistry()
    return prometheus_client, prometheus_client.CollectorRegistry(auto_describe=True)


_BACKEND, REGISTRY = _load_backend()


def backend_available() -> bool:
    return _BACKEND is not None


class _Metric:
    __slots__ = ("_impl", "_labelnames", "_name")

    def __init__(self, impl: Any | None, name: str, labelnames: Sequence[str]) -> None:
        self._impl = impl
        self._name = name
        self._labelnames = tuple(labelnames)

    @property
    def name(self) -> str:
        return self._name

    @property
    def labelnames(self) -> tuple[str, ...]:
        return self._labelnames

    def _child(self, values: Mapping[str, str]) -> Any | None:
        if self._impl is None:
            return None
        missing = set(self._labelnames) - set(values)
        if missing:
            raise UnsafeLabelError(f"metric {self._name!r} missing labels {sorted(missing)}")
        return self._impl.labels(**{key: str(values[key]) for key in self._labelnames})


class Counter(_Metric):
    __slots__ = ()

    def labels(self, **values: str) -> _BoundCounter:
        return _BoundCounter(self._child(values), self._name, ())

    def inc(self, amount: float = 1.0) -> None:
        if self._impl is not None:
            self._impl.inc(amount)


class _BoundCounter(Counter):
    __slots__ = ()


class Gauge(_Metric):
    __slots__ = ()

    def labels(self, **values: str) -> _BoundGauge:
        return _BoundGauge(self._child(values), self._name, ())

    def set(self, value: float) -> None:
        if self._impl is not None:
            self._impl.set(value)

    def inc(self, amount: float = 1.0) -> None:
        if self._impl is not None:
            self._impl.inc(amount)

    def dec(self, amount: float = 1.0) -> None:
        if self._impl is not None:
            self._impl.dec(amount)


class _BoundGauge(Gauge):
    __slots__ = ()


class Histogram(_Metric):
    __slots__ = ()

    def labels(self, **values: str) -> _BoundHistogram:
        return _BoundHistogram(self._child(values), self._name, ())

    def observe(self, value: float) -> None:
        if self._impl is not None:
            self._impl.observe(value)

    @contextmanager
    def time(self) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.observe(time.perf_counter() - started)


class _BoundHistogram(Histogram):
    __slots__ = ()


class Info(_Metric):
    __slots__ = ()

    def set(self, values: Mapping[str, str]) -> None:
        if self._impl is not None:
            self._impl.info(dict(values))


def _counter(name: str, documentation: str, labelnames: Sequence[str] = ()) -> Counter:
    _reject_unsafe_labels(name, labelnames)
    if _BACKEND is None:
        return Counter(None, f"{NAMESPACE}_{name}", labelnames)
    impl = _BACKEND.Counter(
        name, documentation, labelnames=list(labelnames), namespace=NAMESPACE, registry=REGISTRY
    )
    return Counter(impl, f"{NAMESPACE}_{name}", labelnames)


def _gauge(name: str, documentation: str, labelnames: Sequence[str] = ()) -> Gauge:
    _reject_unsafe_labels(name, labelnames)
    if _BACKEND is None:
        return Gauge(None, f"{NAMESPACE}_{name}", labelnames)
    impl = _BACKEND.Gauge(
        name, documentation, labelnames=list(labelnames), namespace=NAMESPACE, registry=REGISTRY
    )
    return Gauge(impl, f"{NAMESPACE}_{name}", labelnames)


def _histogram(
    name: str,
    documentation: str,
    buckets: Sequence[float],
    labelnames: Sequence[str] = (),
) -> Histogram:
    _reject_unsafe_labels(name, labelnames)
    if _BACKEND is None:
        return Histogram(None, f"{NAMESPACE}_{name}", labelnames)
    impl = _BACKEND.Histogram(
        name,
        documentation,
        labelnames=list(labelnames),
        namespace=NAMESPACE,
        registry=REGISTRY,
        buckets=(*tuple(buckets), float("inf")),
    )
    return Histogram(impl, f"{NAMESPACE}_{name}", labelnames)


def _info(name: str, documentation: str) -> Info:
    if _BACKEND is None:
        return Info(None, f"{NAMESPACE}_{name}", ())
    impl = _BACKEND.Info(name, documentation, namespace=NAMESPACE, registry=REGISTRY)
    return Info(impl, f"{NAMESPACE}_{name}", ())


BUILD_INFO: Final[Info] = _info("build", "Hansard build, model and runtime identification")

MEETINGS_SCHEDULED: Final[Counter] = _counter(
    "meetings_scheduled_total", "Meetings accepted for capture or file transcription"
)

BOT_JOIN_ATTEMPTS: Final[Counter] = _counter(
    "bot_join_attempts_total", "Meeting join attempts by outcome", ("result",)
)

BOT_JOIN_DURATION: Final[Histogram] = _histogram(
    "bot_join_duration_seconds",
    "Wall clock seconds from bot start to admitted into the meeting",
    _JOIN_BUCKETS,
)

BOT_ACTIVE: Final[Gauge] = _gauge("bot_active", "Capture bots currently inside a meeting")

QUEUE_PENDING: Final[Gauge] = _gauge(
    "queue_pending", "Entries pending in a work queue consumer group", ("stream", "group")
)

ASR_TRANSCRIBE_DURATION: Final[Histogram] = _histogram(
    "asr_transcribe_duration_seconds",
    "Wall clock seconds spent transcribing one unit of audio",
    _DURATION_BUCKETS,
    ("model", "compute"),
)

ASR_REALTIME_FACTOR: Final[Histogram] = _histogram(
    "asr_realtime_factor",
    "Processing seconds divided by audio seconds; lower is faster than realtime",
    _RTF_BUCKETS,
    ("model", "compute"),
)

ASR_FAILURES: Final[Counter] = _counter(
    "asr_failures_total", "Recognition failures by coarse reason", ("reason",)
)

DIARIZATION_SPEAKERS: Final[Histogram] = _histogram(
    "diarization_speakers", "Distinct speakers found per diarized meeting", _SPEAKER_BUCKETS
)

MINUTES_GENERATED: Final[Counter] = _counter(
    "minutes_generated_total", "Minutes documents composed successfully"
)

DELIVERY_ATTEMPTS: Final[Counter] = _counter(
    "delivery_attempts_total", "Minutes delivery attempts", ("channel", "result")
)

OBJECT_STORAGE_REACHABLE: Final[Gauge] = _gauge(
    "object_storage_reachable", "1 when the artifact store answered its last health probe"
)


def set_build_info(
    version: str,
    component: str,
    asr_engine: str = "unknown",
    asr_model: str = "unknown",
    compute: str = "unknown",
) -> None:
    BUILD_INFO.set(
        {
            "version": version,
            "component": component,
            "asr_engine": asr_engine,
            "asr_model": asr_model,
            "compute": compute,
        }
    )


def record_meeting_scheduled() -> None:
    MEETINGS_SCHEDULED.inc()


def record_bot_join(result: str, duration_seconds: float | None = None) -> None:
    BOT_JOIN_ATTEMPTS.labels(result=result).inc()
    if duration_seconds is not None:
        BOT_JOIN_DURATION.observe(duration_seconds)


@contextmanager
def bot_session() -> Iterator[None]:
    BOT_ACTIVE.inc()
    try:
        yield
    finally:
        BOT_ACTIVE.dec()


def record_queue_depth(stream: str, group: str, pending: int) -> None:
    QUEUE_PENDING.labels(stream=stream, group=group).set(float(pending))


def record_transcription(model: str, compute: str, processing_seconds: float, audio_seconds: float) -> None:
    ASR_TRANSCRIBE_DURATION.labels(model=model, compute=compute).observe(processing_seconds)
    if audio_seconds > 0:
        ASR_REALTIME_FACTOR.labels(model=model, compute=compute).observe(processing_seconds / audio_seconds)


def record_asr_failure(reason: str) -> None:
    ASR_FAILURES.labels(reason=reason).inc()


def record_diarization(speaker_count: int) -> None:
    DIARIZATION_SPEAKERS.observe(float(speaker_count))


def record_minutes_generated() -> None:
    MINUTES_GENERATED.inc()


def record_delivery(channel: str, result: str) -> None:
    DELIVERY_ATTEMPTS.labels(channel=channel, result=result).inc()


def record_object_storage_reachable(reachable: bool) -> None:
    OBJECT_STORAGE_REACHABLE.set(1.0 if reachable else 0.0)


def render_latest() -> tuple[bytes, str]:
    if _BACKEND is None:
        return b"", CONTENT_TYPE_LATEST
    payload: bytes = _BACKEND.generate_latest(REGISTRY)
    content_type: str = _BACKEND.CONTENT_TYPE_LATEST
    return payload, content_type


def start_metrics_server(port: int | None = None, addr: str = "0.0.0.0") -> bool:
    if _BACKEND is None:
        return False
    resolved = port if port is not None else int(os.environ.get("HANSARD_METRICS_PORT", "9095"))
    _BACKEND.start_http_server(resolved, addr=addr, registry=REGISTRY)
    return True
