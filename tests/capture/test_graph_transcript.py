from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from hansard.adapters.capture.graph_transcript import (
    METERED_USD_PER_MINUTE,
    REQUIRED_ACCESS_POLICY_CMDLET,
    REQUIRED_APPLICATION_PERMISSION,
    GraphTranscriptFallback,
    NonSovereignFallbackWarning,
    cues_to_roster,
    cues_to_transcript,
    parse_timestamp,
    parse_vtt,
)
from hansard.config import GraphSettings
from hansard.domain.errors import CaptureError
from hansard.domain.speakers import UNKNOWN_SPEAKER

TEAMS_VTT = """WEBVTT

95e6d4a1-1/1
00:00:01.360 --> 00:00:04.120
<v Alice Dupont>Bonjour à toutes et à tous.</v>

95e6d4a1-2/1
00:00:04.500 --> 00:00:07.000
<v Bob Martin>Merci Alice,
on peut commencer.</v>
"""

PLAIN_VTT = """WEBVTT

01:02:03,500 --> 01:02:06,000
Chair: The meeting is now open.

00:00:10.000 --> 00:00:12.000
No speaker attribution here.
"""


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "", payload: Any = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class FakeHttp:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[tuple[str, Mapping[str, str], Mapping[str, str]]] = []

    async def get(self, url: str, *, headers: Mapping[str, str], params: Mapping[str, str]) -> FakeResponse:
        self.requests.append((url, dict(headers), dict(params)))
        return self.response


class FakeToken:
    async def token(self) -> str:
        return "app-only-token"


def build_fallback(response: FakeResponse, enabled: bool = True) -> tuple[GraphTranscriptFallback, FakeHttp]:
    http = FakeHttp(response)
    fallback = GraphTranscriptFallback(
        settings=GraphSettings(base_url="https://graph.microsoft.com/v1.0"),
        enabled=enabled,
        http=http,
        token_provider=FakeToken(),
    )
    return fallback, http


def test_parse_timestamp_supports_hours_and_comma_decimals():
    assert parse_timestamp("00:00:01.360") == pytest.approx(1.36)
    assert parse_timestamp("01:02:03,500") == pytest.approx(3723.5)
    assert parse_timestamp("02:03.250") == pytest.approx(123.25)


def test_parse_timestamp_rejects_rubbish():
    with pytest.raises(CaptureError):
        parse_timestamp("nonsense")


def test_parse_vtt_reads_voice_tags_and_multiline_cues():
    cues = parse_vtt(TEAMS_VTT)
    assert len(cues) == 2
    assert cues[0].speaker == "Alice Dupont"
    assert cues[0].text == "Bonjour à toutes et à tous."
    assert cues[0].span.start == pytest.approx(1.36)
    assert cues[1].speaker == "Bob Martin"
    assert cues[1].text == "Merci Alice,\non peut commencer."


def test_parse_vtt_reads_colon_prefixes_and_keeps_unattributed_text():
    cues = parse_vtt(PLAIN_VTT)
    assert cues[0].speaker == "Chair"
    assert cues[0].text == "The meeting is now open."
    assert cues[1].speaker == UNKNOWN_SPEAKER
    assert cues[1].text == "No speaker attribution here."


def test_cues_convert_to_transcript_and_roster():
    cues = parse_vtt(TEAMS_VTT)
    transcript = cues_to_transcript(cues, language="fr")
    assert transcript.language == "fr"
    assert transcript.audio_duration == pytest.approx(7.0)
    assert transcript.speakers == ("Alice Dupont", "Bob Martin")
    roster = cues_to_roster(cues)
    assert [participant.display_name for participant in roster.participants] == [
        "Alice Dupont",
        "Bob Martin",
    ]
    assert len(roster.observations) == 2


async def test_fallback_is_disabled_by_default():
    fallback, http = build_fallback(FakeResponse(text=TEAMS_VTT), enabled=False)
    with pytest.raises(CaptureError, match="sovereignty"):
        await fallback.fetch_vtt("user", "meeting", "transcript")
    assert http.requests == []


async def test_fetch_warns_loudly_and_hits_the_documented_endpoint():
    fallback, http = build_fallback(FakeResponse(text=TEAMS_VTT))
    with pytest.warns(NonSovereignFallbackWarning) as warnings_raised:
        document = await fallback.fetch_vtt("user-1", "meeting-1", "transcript-1")
    assert document == TEAMS_VTT
    url, headers, params = http.requests[0]
    assert url == (
        "https://graph.microsoft.com/v1.0/users/user-1/onlineMeetings/meeting-1/"
        "transcripts/transcript-1/content"
    )
    assert params == {"$format": "text/vtt"}
    assert headers["Authorization"] == "Bearer app-only-token"
    message = str(warnings_raised[0].message)
    assert REQUIRED_APPLICATION_PERMISSION in message
    assert f"{METERED_USD_PER_MINUTE:.4f}" in message


async def test_fetch_returns_transcript_and_roster():
    fallback, _ = build_fallback(FakeResponse(text=TEAMS_VTT))
    with pytest.warns(NonSovereignFallbackWarning):
        transcript, roster = await fallback.fetch("user", "meeting", "transcript", language="fr")
    assert transcript.word_count > 0
    assert len(roster.participants) == 2


@pytest.mark.parametrize("status", [401, 403])
async def test_authorisation_failures_name_the_missing_grants(status):
    fallback, _ = build_fallback(FakeResponse(status_code=status, text="Access denied"))
    with pytest.warns(NonSovereignFallbackWarning), pytest.raises(CaptureError) as failure:
        await fallback.fetch_vtt("user", "meeting", "transcript")
    assert REQUIRED_APPLICATION_PERMISSION in str(failure.value)
    assert REQUIRED_ACCESS_POLICY_CMDLET in str(failure.value)


async def test_missing_transcript_explains_that_teams_must_have_transcribed():
    fallback, _ = build_fallback(FakeResponse(status_code=404, text="not found"))
    with pytest.warns(NonSovereignFallbackWarning), pytest.raises(CaptureError, match="transcription"):
        await fallback.fetch_vtt("user", "meeting", "transcript")


async def test_list_transcripts_returns_identifiers():
    payload = {"value": [{"id": "t-1"}, {"id": "t-2"}, {"nope": True}]}
    fallback, http = build_fallback(FakeResponse(payload=payload))
    with pytest.warns(NonSovereignFallbackWarning):
        assert await fallback.list_transcripts("user", "meeting") == ("t-1", "t-2")
    assert http.requests[0][0].endswith("/onlineMeetings/meeting/transcripts")
