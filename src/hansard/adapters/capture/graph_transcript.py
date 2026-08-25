from __future__ import annotations

import asyncio
import re
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from hansard.config import GraphSettings
from hansard.domain.errors import CaptureError
from hansard.domain.speakers import UNKNOWN_SPEAKER, ActiveSpeakerObservation, Participant, Roster
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance

REQUIRED_APPLICATION_PERMISSION: Final[str] = "OnlineMeetingTranscript.Read.All"
REQUIRED_ACCESS_POLICY_CMDLET: Final[str] = "New-CsApplicationAccessPolicy"
METERED_USD_PER_MINUTE: Final[float] = 0.0022
FREE_MINUTES_PER_MONTH: Final[int] = 600

SOVEREIGNTY_WARNING: Final[str] = (
    "Hansard is fetching a Microsoft-generated transcript through Graph. This is the NON-SOVEREIGN "
    "fallback: Microsoft performed the speech recognition, the audio and text were processed in "
    f"Microsoft's cloud, and the call is metered at ${METERED_USD_PER_MINUTE:.4f} per minute beyond "
    f"{FREE_MINUTES_PER_MONTH} free minutes per month per tenant per application. It also requires the "
    f"{REQUIRED_APPLICATION_PERMISSION} application permission plus a {REQUIRED_ACCESS_POLICY_CMDLET} "
    "grant. Prefer the browser notetaker with local ASR."
)

TIMESTAMP_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?P<start>(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*(?P<end>(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)
VOICE_PATTERN: Final[re.Pattern[str]] = re.compile(r"<v(?:\.[^\s>]+)*\s+([^>]+)>(.*?)(?:</v>)?\s*$", re.S)
TAG_PATTERN: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
SPEAKER_PREFIX_PATTERN: Final[re.Pattern[str]] = re.compile(r"^([^:<>]{1,80}):\s+(.*)$", re.S)


class NonSovereignFallbackWarning(UserWarning):
    pass


@dataclass(frozen=True, slots=True)
class VttCue:
    span: TimeSpan
    text: str
    speaker: str = UNKNOWN_SPEAKER


def parse_timestamp(value: str) -> float:
    normalised = value.strip().replace(",", ".")
    parts = normalised.split(":")
    if len(parts) not in {2, 3}:
        raise CaptureError(f"malformed WebVTT timestamp: {value!r}")
    seconds = float(parts[-1])
    minutes = int(parts[-2])
    hours = int(parts[-3]) if len(parts) == 3 else 0
    return hours * 3600 + minutes * 60 + seconds


def _clean(text: str) -> str:
    return TAG_PATTERN.sub("", text).replace("&nbsp;", " ").strip()


def _split_speaker(payload: str) -> tuple[str, str]:
    voice = VOICE_PATTERN.match(payload.strip())
    if voice is not None:
        return voice.group(1).strip() or UNKNOWN_SPEAKER, _clean(voice.group(2))
    prefixed = SPEAKER_PREFIX_PATTERN.match(payload.strip())
    if prefixed is not None:
        candidate = prefixed.group(1).strip()
        if candidate and not candidate.replace(".", "").isdigit():
            return candidate, _clean(prefixed.group(2))
    return UNKNOWN_SPEAKER, _clean(payload)


def parse_vtt(document: str) -> tuple[VttCue, ...]:
    cues: list[VttCue] = []
    pending: TimeSpan | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal pending
        if pending is None:
            return
        speaker, text = _split_speaker("\n".join(buffer).strip())
        if text:
            cues.append(VttCue(span=pending, text=text, speaker=speaker))
        pending = None
        buffer.clear()

    for raw_line in document.splitlines():
        line = raw_line.strip()
        match = TIMESTAMP_PATTERN.search(line)
        if match is not None:
            flush()
            pending = TimeSpan(parse_timestamp(match.group("start")), parse_timestamp(match.group("end")))
            continue
        if not line:
            flush()
            continue
        if pending is not None:
            buffer.append(line)
    flush()
    return tuple(cues)


def cues_to_transcript(cues: Sequence[VttCue], language: str | None = None) -> Transcript:
    utterances = tuple(
        Utterance(span=cue.span, text=cue.text, speaker=cue.speaker, language=language) for cue in cues
    )
    duration = max((cue.span.end for cue in cues), default=0.0)
    return Transcript(utterances=utterances, language=language, audio_duration=duration)


def cues_to_roster(cues: Sequence[VttCue]) -> Roster:
    names: dict[str, None] = {}
    for cue in cues:
        if cue.speaker != UNKNOWN_SPEAKER:
            names.setdefault(cue.speaker, None)
    participants = tuple(
        Participant(identifier=f"graph-{index}", display_name=name) for index, name in enumerate(names)
    )
    observations = tuple(
        ActiveSpeakerObservation(span=cue.span, display_name=cue.speaker)
        for cue in cues
        if cue.speaker != UNKNOWN_SPEAKER
    )
    return Roster(participants=participants, observations=observations)


class HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


class HttpClient(Protocol):
    async def get(
        self, url: str, *, headers: Mapping[str, str], params: Mapping[str, str]
    ) -> HttpResponse: ...


class TokenProvider(Protocol):
    async def token(self) -> str: ...


@dataclass(slots=True)
class HttpxClient:
    timeout_seconds: float = 60.0

    async def get(self, url: str, *, headers: Mapping[str, str], params: Mapping[str, str]) -> HttpResponse:
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            return await client.get(url, headers=dict(headers), params=dict(params))


@dataclass(slots=True)
class MsalApplicationTokenProvider:
    settings: GraphSettings

    async def token(self) -> str:
        if not (self.settings.tenant_id and self.settings.client_id and self.settings.client_secret):
            raise CaptureError(
                "Graph transcript fallback needs delivery.graph.tenant_id, client_id and client_secret"
            )
        return await asyncio.to_thread(self._acquire)

    def _acquire(self) -> str:
        try:
            import msal
        except ImportError as error:
            raise CaptureError(
                "msal is not installed; install the 'capture-graph-fallback' extra to use the Graph fallback"
            ) from error
        secret = self.settings.client_secret
        application = msal.ConfidentialClientApplication(
            client_id=self.settings.client_id,
            client_credential=secret.get_secret_value() if secret else "",
            authority=f"{self.settings.authority.rstrip('/')}/{self.settings.tenant_id}",
        )
        result = application.acquire_token_for_client(scopes=[self.settings.scope])
        token = result.get("access_token") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            detail = result.get("error_description") if isinstance(result, dict) else "no response"
            raise CaptureError(f"could not obtain a Graph application token: {detail}")
        return token


@dataclass(slots=True)
class GraphTranscriptFallback:
    settings: GraphSettings = field(default_factory=GraphSettings)
    enabled: bool = False
    http: HttpClient = field(default_factory=HttpxClient)
    token_provider: TokenProvider | None = None

    @property
    def name(self) -> str:
        return "graph-transcript-non-sovereign"

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise CaptureError(
                "the Microsoft Graph transcript fallback is disabled by default because it forfeits "
                "sovereignty; enable it explicitly to use it"
            )
        warnings.warn(SOVEREIGNTY_WARNING, NonSovereignFallbackWarning, stacklevel=3)

    async def _authorisation(self) -> Mapping[str, str]:
        provider = self.token_provider or MsalApplicationTokenProvider(self.settings)
        return {"Authorization": f"Bearer {await provider.token()}"}

    def _base(self, user_id: str, meeting_id: str) -> str:
        root = self.settings.base_url.rstrip("/")
        return f"{root}/users/{user_id}/onlineMeetings/{meeting_id}/transcripts"

    def _raise_for_status(self, response: HttpResponse, url: str) -> None:
        if response.status_code in {200, 201}:
            return
        if response.status_code in {401, 403}:
            raise CaptureError(
                f"Graph refused the transcript request ({response.status_code}). The application needs the "
                f"{REQUIRED_APPLICATION_PERMISSION} application permission AND a "
                f"{REQUIRED_ACCESS_POLICY_CMDLET} grant for the organiser: {response.text[:300]}"
            )
        if response.status_code == 404:
            raise CaptureError(
                f"Graph has no transcript at {url}; Teams only produces one when transcription was "
                "started in the meeting, and it can take minutes to appear after the meeting ends"
            )
        raise CaptureError(f"Graph transcript request failed ({response.status_code}): {response.text[:300]}")

    async def list_transcripts(self, user_id: str, meeting_id: str) -> tuple[str, ...]:
        self._require_enabled()
        url = self._base(user_id, meeting_id)
        response = await self.http.get(url, headers=await self._authorisation(), params={})
        self._raise_for_status(response, url)
        payload = response.json()
        entries = payload.get("value") if isinstance(payload, Mapping) else None
        if not isinstance(entries, Sequence):
            return ()
        return tuple(str(entry["id"]) for entry in entries if isinstance(entry, Mapping) and entry.get("id"))

    async def fetch_vtt(self, user_id: str, meeting_id: str, transcript_id: str) -> str:
        self._require_enabled()
        url = f"{self._base(user_id, meeting_id)}/{transcript_id}/content"
        response = await self.http.get(
            url, headers=await self._authorisation(), params={"$format": "text/vtt"}
        )
        self._raise_for_status(response, url)
        return response.text

    async def fetch(
        self, user_id: str, meeting_id: str, transcript_id: str, language: str | None = None
    ) -> tuple[Transcript, Roster]:
        cues = parse_vtt(await self.fetch_vtt(user_id, meeting_id, transcript_id))
        return cues_to_transcript(cues, language), cues_to_roster(cues)
