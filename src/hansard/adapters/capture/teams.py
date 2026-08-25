from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final

from hansard.adapters.capture.audio.pulse import PulseAudioSink, PulseSinkPlan
from hansard.adapters.capture.audio.recorder import FfmpegRecorder, RecorderSettings, SilenceReport
from hansard.adapters.capture.browser.events import (
    CaptureEvent,
    CaptureEventReducer,
    CsrcActivityEvent,
    DominantSpeakerEvent,
    DomRosterEvent,
    DomSpeakingEvent,
    RosterUpdateEvent,
    SignalHealth,
    SignalSource,
    SpeakerTimeline,
    TimelineSettings,
)
from hansard.adapters.capture.browser.session import (
    DEFAULT_UI_LOCALE,
    BrowserOptions,
    JoinOutcome,
    MeetingState,
    PlaywrightRuntimeFactory,
    TeamsBrowserSession,
)
from hansard.config import CaptureSettings
from hansard.domain.errors import (
    CaptureError,
    MeetingAdmissionTimeoutError,
    MeetingJoinRefusedError,
)
from hansard.domain.meeting import Capture, MeetingRequest
from hansard.observability.metrics import bot_session, record_bot_join

SessionBuilder = Callable[[Callable[[CaptureEvent], None]], TeamsBrowserSession]
RecorderBuilder = Callable[[str], FfmpegRecorder]

JOIN_ADMITTED: Final[str] = "admitted"
JOIN_REFUSED: Final[str] = "refused"
JOIN_TIMED_OUT: Final[str] = "timeout"
JOIN_FAILED: Final[str] = "error"

DEFAULT_ANNOUNCEMENTS: Final[dict[str, str]] = {
    "en": (
        "This meeting is being transcribed locally by Hansard. No audio or text leaves this organisation."
    ),
    "fr": (
        "Cette réunion est transcrite localement par Hansard. "
        "Aucun enregistrement audio ni aucun texte ne quitte cette organisation."
    ),
}


def language_key(language: str | None) -> str:
    if not language:
        return "en"
    return language.replace("_", "-").split("-")[0].strip().lower()


def announcement_for(settings: CaptureSettings, language: str | None) -> str:
    configured = settings.announcement_text.strip()
    shipped_default = str(CaptureSettings.model_fields["announcement_text"].default).strip()
    if configured and configured != shipped_default:
        return configured
    return DEFAULT_ANNOUNCEMENTS.get(language_key(language), DEFAULT_ANNOUNCEMENTS["en"])


class StopReason(StrEnum):
    MEETING_ENDED = "meeting_ended"
    REMOVED = "removed"
    MAX_DURATION = "max_duration"
    SILENCE_TIMEOUT = "silence_timeout"
    ALONE_TIMEOUT = "alone_timeout"
    RECORDER_FAILED = "recorder_failed"


@dataclass(frozen=True, slots=True)
class CaptureDiagnostics:
    stop_reason: StopReason
    timeline: SpeakerTimeline
    health: SignalHealth
    silence: SilenceReport | None
    waited_in_lobby: bool
    join_attempts: int
    announced: bool

    @property
    def degraded_signals(self) -> tuple[SignalSource, ...]:
        return self.health.silent_signals


def _default_session_builder(settings: CaptureSettings, locale: str) -> SessionBuilder:
    options = BrowserOptions(
        headless=settings.headless,
        executable_path=settings.browser_binary,
        locale=locale,
    )

    def build(sink: Callable[[CaptureEvent], None]) -> TeamsBrowserSession:
        return TeamsBrowserSession(
            settings=settings,
            factory=PlaywrightRuntimeFactory(),
            event_sink=sink,
            options=options,
        )

    return build


def _default_recorder_builder(sample_rate: int) -> RecorderBuilder:
    def build(source: str) -> FfmpegRecorder:
        return FfmpegRecorder(source=source, settings=RecorderSettings(sample_rate=sample_rate))

    return build


@dataclass(slots=True)
class TeamsBrowserCapture:
    settings: CaptureSettings
    sample_rate: int = 16_000
    session_builder: SessionBuilder | None = None
    recorder_builder: RecorderBuilder | None = None
    pulse: PulseAudioSink | None = None
    timeline_settings: TimelineSettings | None = None
    ui_locale: str = DEFAULT_UI_LOCALE
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    last_diagnostics: CaptureDiagnostics | None = field(default=None, init=False)
    _last_speech_epoch_ms: int = field(default=0, init=False)
    _last_company_epoch_ms: int = field(default=0, init=False)
    _saw_roster: bool = field(default=False, init=False)

    @property
    def name(self) -> str:
        return "teams-browser"

    def _epoch_ms(self) -> int:
        return int(self.now().timestamp() * 1000)

    def _reducer(self) -> CaptureEventReducer:
        base = self.timeline_settings or TimelineSettings()
        ignore = tuple({*base.ignore_display_names, self.settings.display_name})
        return CaptureEventReducer(
            TimelineSettings(
                metadata_lag_seconds=base.metadata_lag_seconds,
                contest_window_seconds=base.contest_window_seconds,
                min_slice_seconds=base.min_slice_seconds,
                cross_check_signals=base.cross_check_signals,
                ignore_display_names=ignore,
            )
        )

    def _track_liveness(self, event: CaptureEvent) -> None:
        speaking = (
            (isinstance(event, CsrcActivityEvent) and bool(event.sources))
            or (isinstance(event, DominantSpeakerEvent) and event.source_id is not None)
            or (isinstance(event, DomSpeakingEvent) and bool(event.display_names))
        )
        if speaking:
            self._last_speech_epoch_ms = max(self._last_speech_epoch_ms, event.at_epoch_ms)
        if isinstance(event, RosterUpdateEvent):
            self._saw_roster = True
            others = [record for record in event.participants if record.is_active]
            if others:
                self._last_company_epoch_ms = max(self._last_company_epoch_ms, event.at_epoch_ms)
        if isinstance(event, DomRosterEvent):
            self._saw_roster = True
            if event.display_names:
                self._last_company_epoch_ms = max(self._last_company_epoch_ms, event.at_epoch_ms)

    async def capture(self, request: MeetingRequest, workspace: Path) -> Capture:
        if not request.join_url:
            raise CaptureError("TeamsBrowserCapture requires MeetingRequest.join_url")
        workspace.mkdir(parents=True, exist_ok=True)
        reducer = self._reducer()
        pulse = self.pulse or PulseAudioSink(plan=PulseSinkPlan(sink_name=self.settings.pulse_sink_name))
        build_recorder = self.recorder_builder or _default_recorder_builder(self.sample_rate)
        build_session = self.session_builder or _default_session_builder(self.settings, self.ui_locale)
        recorder = build_recorder(pulse.monitor_source)
        output = workspace / f"{request.identifier}.wav"

        def on_event(event: CaptureEvent) -> None:
            reducer.push(event)
            self._track_liveness(event)

        session = build_session(on_event)
        await pulse.start()
        started_at = self.now()
        origin_epoch_ms = int(started_at.timestamp() * 1000)
        self._last_speech_epoch_ms = origin_epoch_ms
        self._last_company_epoch_ms = origin_epoch_ms
        self._saw_roster = False
        reducer.set_origin(origin_epoch_ms)
        try:
            await recorder.start(output)
            outcome = await self._join(session, request.join_url)
            announced = await self._announce(session, request)
            with bot_session():
                reason = await self._monitor(session, recorder, reducer, request, origin_epoch_ms)
            await session.leave()
        except BaseException:
            await session.aclose()
            await self._discard(recorder, pulse)
            raise
        await session.aclose()
        audio_path = await self._finalise(recorder, pulse)
        ended_at = self.now()
        end_epoch_ms = int(ended_at.timestamp() * 1000)
        timeline = reducer.timeline(end_epoch_ms)
        silence = await recorder.assert_not_silent(audio_path)
        self.last_diagnostics = CaptureDiagnostics(
            stop_reason=reason,
            timeline=timeline,
            health=reducer.health(),
            silence=silence,
            waited_in_lobby=outcome.waited_in_lobby,
            join_attempts=outcome.attempts,
            announced=announced,
        )
        return Capture(
            audio_path=audio_path,
            roster=reducer.roster(end_epoch_ms),
            started_at=started_at,
            ended_at=ended_at,
            sample_rate=self.sample_rate,
        )

    async def _join(self, session: TeamsBrowserSession, join_url: str) -> JoinOutcome:
        started = time.monotonic()
        try:
            outcome = await session.join(join_url)
        except BaseException as error:
            record_bot_join(_join_result(error))
            raise
        record_bot_join(JOIN_ADMITTED, time.monotonic() - started)
        return outcome

    async def _announce(self, session: TeamsBrowserSession, request: MeetingRequest) -> bool:
        if not self.settings.announce_recording:
            return False
        return await session.announce(announcement_for(self.settings, request.language or self.ui_locale))

    async def _finalise(self, recorder: FfmpegRecorder, pulse: PulseAudioSink) -> Path:
        try:
            return await recorder.stop()
        finally:
            await pulse.stop()

    async def _discard(self, recorder: FfmpegRecorder, pulse: PulseAudioSink) -> None:
        try:
            await recorder.stop()
        except CaptureError:
            pass
        finally:
            await pulse.stop()

    def _duration_limit(self, request: MeetingRequest) -> int:
        return min(request.max_duration_seconds, self.settings.max_duration_seconds)

    async def _monitor(
        self,
        session: TeamsBrowserSession,
        recorder: FfmpegRecorder,
        reducer: CaptureEventReducer,
        request: MeetingRequest,
        origin_epoch_ms: int,
    ) -> StopReason:
        limit_ms = self._duration_limit(request) * 1000
        silence_ms = self.settings.silence_timeout_seconds * 1000
        alone_ms = self.settings.alone_timeout_seconds * 1000
        poll = max(self.settings.roster_poll_seconds, 0.1)
        while True:
            await recorder.ensure_progressing()
            end_event = reducer.call_end or session.call_end
            if end_event is not None and end_event.is_termination:
                return StopReason.MEETING_ENDED
            state = await session.detect_state()
            if state is MeetingState.REMOVED:
                return StopReason.REMOVED
            if state in {MeetingState.ENDED, MeetingState.DENIED}:
                return StopReason.MEETING_ENDED
            now_ms = self._epoch_ms()
            if now_ms - origin_epoch_ms >= limit_ms:
                return StopReason.MAX_DURATION
            if now_ms - self._last_speech_epoch_ms >= silence_ms:
                return StopReason.SILENCE_TIMEOUT
            if self._saw_roster and now_ms - self._last_company_epoch_ms >= alone_ms:
                return StopReason.ALONE_TIMEOUT
            await self.sleep(poll)


def _join_result(error: BaseException) -> str:
    if isinstance(error, MeetingJoinRefusedError):
        return JOIN_REFUSED
    if isinstance(error, MeetingAdmissionTimeoutError):
        return JOIN_TIMED_OUT
    return JOIN_FAILED
