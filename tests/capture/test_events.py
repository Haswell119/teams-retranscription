from __future__ import annotations

import pytest

from hansard.adapters.capture.browser.events import (
    CallEndEvent,
    CaptureEventReducer,
    RosterUpdateEvent,
    SignalSource,
    SpeakerState,
    TimelineSettings,
    parse_event,
)

ORIGIN = 1_700_000_000_000


def roster_payload(at, *entries):
    return {
        "kind": "roster",
        "at_epoch_ms": at,
        "call_id": "chain-1",
        "participants": [
            {
                "id": identifier,
                "display_name": name,
                "state": "active",
                "meeting_role": role,
                "audio_sources": list(sources),
            }
            for identifier, name, role, sources in entries
        ],
    }


def csrc_payload(at, *sources):
    return {"kind": "csrc", "at_epoch_ms": at, "sources": list(sources)}


def build_reducer(**overrides):
    settings = TimelineSettings(
        metadata_lag_seconds=overrides.pop("lag", 1.0),
        contest_window_seconds=overrides.pop("contest_window", 0.0),
        min_slice_seconds=overrides.pop("min_slice", 0.0),
        cross_check_signals=overrides.pop("cross_check", True),
        ignore_display_names=overrides.pop("ignore", ()),
    )
    reducer = CaptureEventReducer(settings)
    reducer.set_origin(ORIGIN)
    return reducer


def test_parse_event_rejects_unknown_and_malformed_payloads():
    assert parse_event({"kind": "nope", "at_epoch_ms": 1}) is None
    assert parse_event({"kind": "csrc"}) is None
    assert parse_event({"at_epoch_ms": 1}) is None


def test_parse_roster_drops_entries_without_a_display_name():
    event = parse_event(
        {
            "kind": "roster",
            "at_epoch_ms": 1,
            "participants": [
                {"id": "a", "display_name": "Alice", "state": "active", "audio_sources": [11]},
                {"id": "meeting", "display_name": "", "state": "active"},
            ],
        }
    )
    assert isinstance(event, RosterUpdateEvent)
    assert [record.display_name for record in event.participants] == ["Alice"]
    assert event.participants[0].audio_sources == (11,)


@pytest.mark.parametrize("sub_code", [5723, 5854])
def test_call_end_refusal_sub_codes(sub_code):
    event = CallEndEvent(at_epoch_ms=1, code=5000, sub_code=sub_code)
    assert event.is_refusal
    assert not event.is_termination
    assert str(sub_code) in event.explanation


@pytest.mark.parametrize("sub_code", [5000, 5300])
def test_call_end_termination_sub_codes(sub_code):
    event = CallEndEvent(at_epoch_ms=1, code=5000, sub_code=sub_code)
    assert event.is_termination
    assert not event.is_refusal


def test_roster_folds_participants_and_audio_sources():
    reducer = build_reducer()
    reducer.push_payload(
        roster_payload(
            ORIGIN,
            ("a", "Alice", "organizer", (11,)),
            ("b", "Bob", "anonymous", (22,)),
        )
    )
    participants = reducer.participants()
    assert [participant.display_name for participant in participants] == ["Alice", "Bob"]
    assert participants[0].is_organizer
    assert participants[1].is_external
    assert reducer.active_participant_count() == 2
    assert reducer.call_id == "chain-1"


def test_bot_display_name_is_never_part_of_the_roster():
    reducer = build_reducer(ignore=("Hansard Notetaker",))
    reducer.push_payload(
        roster_payload(
            ORIGIN,
            ("a", "Alice", "presenter", (11,)),
            ("bot", "Hansard Notetaker", "presenter", (33,)),
        )
    )
    assert [participant.display_name for participant in reducer.participants()] == ["Alice"]


def test_csrc_activity_becomes_an_attributed_observation_with_lag_compensation():
    reducer = build_reducer(lag=1.0)
    reducer.push_payload(roster_payload(ORIGIN, ("a", "Alice", "presenter", (11,))))
    reducer.push_payload(csrc_payload(ORIGIN + 3_000, 11))
    reducer.push_payload(csrc_payload(ORIGIN + 5_000))
    timeline = reducer.timeline(ORIGIN + 10_000)
    observations = timeline.observations()
    assert len(observations) == 1
    assert observations[0].display_name == "Alice"
    assert observations[0].participant_id == "a"
    assert observations[0].span.start == pytest.approx(2.0)
    assert observations[0].span.end == pytest.approx(4.0)
    assert timeline.lag_seconds == 1.0


def test_configurable_lag_shifts_the_metadata_timeline():
    reducer = build_reducer(lag=2.0)
    reducer.push_payload(roster_payload(ORIGIN, ("a", "Alice", "presenter", (11,))))
    reducer.push_payload(csrc_payload(ORIGIN + 3_000, 11))
    reducer.push_payload(csrc_payload(ORIGIN + 5_000))
    observation = reducer.timeline(ORIGIN + 10_000).observations()[0]
    assert observation.span.start == pytest.approx(1.0)
    assert observation.span.end == pytest.approx(3.0)


def test_two_simultaneous_sources_are_contested_and_unnamed():
    reducer = build_reducer()
    reducer.push_payload(
        roster_payload(ORIGIN, ("a", "Alice", "presenter", (11,)), ("b", "Bob", "presenter", (22,)))
    )
    reducer.push_payload(csrc_payload(ORIGIN + 3_000, 11, 22))
    timeline = reducer.timeline(ORIGIN + 6_000)
    assert timeline.observations() == ()
    contested = timeline.contested()
    assert len(contested) == 1
    assert contested[0].candidates == ("a", "b")
    assert contested[0].state is SpeakerState.CONTESTED


def test_disagreeing_signals_are_contested_rather_than_guessed():
    reducer = build_reducer()
    reducer.push_payload(
        roster_payload(ORIGIN, ("a", "Alice", "presenter", (11,)), ("b", "Bob", "presenter", (22,)))
    )
    reducer.push_payload(csrc_payload(ORIGIN + 3_000, 11))
    reducer.push_payload(
        {"kind": "dom_speaking", "at_epoch_ms": ORIGIN + 3_000, "display_names": ["Bob"]}
    )
    timeline = reducer.timeline(ORIGIN + 6_000)
    assert timeline.observations() == ()
    assert timeline.contested()[0].candidates == ("a",)


def test_cross_check_can_be_disabled():
    reducer = build_reducer(cross_check=False)
    reducer.push_payload(
        roster_payload(ORIGIN, ("a", "Alice", "presenter", (11,)), ("b", "Bob", "presenter", (22,)))
    )
    reducer.push_payload(csrc_payload(ORIGIN + 3_000, 11))
    reducer.push_payload(
        {"kind": "dom_speaking", "at_epoch_ms": ORIGIN + 3_000, "display_names": ["Bob"]}
    )
    assert reducer.timeline(ORIGIN + 6_000).observations()[0].display_name == "Alice"


def test_dominant_speaker_channel_carries_the_timeline_without_csrc():
    reducer = build_reducer()
    reducer.push_payload(roster_payload(ORIGIN, ("b", "Bob", "presenter", (2331,))))
    reducer.push_payload(
        {"kind": "dominant", "at_epoch_ms": ORIGIN + 2_000, "source_id": 2331, "history": [2331, 1053]}
    )
    reducer.push_payload({"kind": "dominant", "at_epoch_ms": ORIGIN + 4_000, "source_id": None})
    observations = reducer.timeline(ORIGIN + 8_000).observations()
    assert [observation.display_name for observation in observations] == ["Bob"]
    assert reducer.health().transitions[SignalSource.DOMINANT] == 2


def test_unmapped_audio_source_stays_unknown():
    reducer = build_reducer()
    reducer.push_payload(roster_payload(ORIGIN, ("a", "Alice", "presenter", (11,))))
    reducer.push_payload(csrc_payload(ORIGIN + 2_000, 99))
    timeline = reducer.timeline(ORIGIN + 5_000)
    assert timeline.observations() == ()
    assert any(item.state is SpeakerState.UNKNOWN for item in timeline.slices)


def test_csrc_mapping_event_resolves_sources_the_roster_never_carried():
    reducer = build_reducer()
    reducer.push_payload(roster_payload(ORIGIN, ("a", "Alice", "presenter", ())))
    reducer.push_payload(csrc_payload(ORIGIN + 2_000, 99))
    reducer.push_payload({"kind": "csrc_map", "at_epoch_ms": ORIGIN + 2_500, "mapping": {"99": "a"}})
    observations = reducer.timeline(ORIGIN + 5_000).observations()
    assert [observation.display_name for observation in observations] == ["Alice"]


def test_late_joiner_names_are_revised_retroactively():
    reducer = build_reducer()
    reducer.push_payload(roster_payload(ORIGIN, ("b", "Guest", "anonymous", (22,))))
    reducer.push_payload(csrc_payload(ORIGIN + 2_000, 22))
    reducer.push_payload(csrc_payload(ORIGIN + 4_000))
    reducer.push_payload(roster_payload(ORIGIN + 6_000, ("b", "Bob Smith", "attendee", (22,))))
    observations = reducer.timeline(ORIGIN + 8_000).observations()
    assert [observation.display_name for observation in observations] == ["Bob Smith"]
    assert [participant.display_name for participant in reducer.participants()] == ["Bob Smith"]


def test_speaker_swap_carves_a_contested_bridge_around_the_boundary():
    reducer = build_reducer(contest_window=0.4)
    reducer.push_payload(
        roster_payload(ORIGIN, ("a", "Alice", "presenter", (11,)), ("b", "Bob", "presenter", (22,)))
    )
    reducer.push_payload(csrc_payload(ORIGIN + 2_000, 11))
    reducer.push_payload(csrc_payload(ORIGIN + 4_000, 22))
    reducer.push_payload(csrc_payload(ORIGIN + 6_000))
    timeline = reducer.timeline(ORIGIN + 8_000)
    states = [(item.state, item.display_name, item.span.start, item.span.end) for item in timeline.slices]
    speaking = [entry for entry in states if entry[0] is SpeakerState.SPEAKING]
    assert [entry[1] for entry in speaking] == ["Alice", "Bob"]
    assert speaking[0][3] == pytest.approx(2.8)
    assert speaking[1][2] == pytest.approx(3.2)
    assert timeline.contested_seconds() == pytest.approx(0.4)


def test_blips_shorter_than_the_minimum_slice_are_not_attributed():
    reducer = build_reducer(min_slice=0.3)
    reducer.push_payload(roster_payload(ORIGIN, ("a", "Alice", "presenter", (11,))))
    reducer.push_payload(csrc_payload(ORIGIN + 2_000, 11))
    reducer.push_payload(csrc_payload(ORIGIN + 2_100))
    timeline = reducer.timeline(ORIGIN + 5_000)
    assert timeline.observations() == ()
    assert timeline.attributed_seconds() == pytest.approx(0.0)


def test_roster_helper_returns_participants_and_observations_together():
    reducer = build_reducer()
    reducer.push_payload(roster_payload(ORIGIN, ("a", "Alice", "presenter", (11,))))
    reducer.push_payload(csrc_payload(ORIGIN + 2_000, 11))
    reducer.push_payload(csrc_payload(ORIGIN + 4_000))
    roster = reducer.roster(ORIGIN + 6_000)
    assert [participant.display_name for participant in roster.participants] == ["Alice"]
    assert roster.observation_time_by_name() == {"Alice": pytest.approx(2.0)}


def test_health_reports_signals_that_never_produced_a_transition():
    reducer = build_reducer()
    reducer.push_payload(csrc_payload(ORIGIN + 1_000, 11))
    reducer.push_payload({"kind": "health", "at_epoch_ms": ORIGIN + 2_000, "counters": {"ws_frames": 4}})
    reducer.push_payload({"kind": "error", "at_epoch_ms": ORIGIN + 2_100, "where": "csrc", "message": "x"})
    health = reducer.health()
    assert health.has_any_speaker_signal
    assert SignalSource.DOM in health.silent_signals
    assert SignalSource.DOMINANT in health.silent_signals
    assert health.browser_counters["ws_frames"] == 4
    assert health.instrumentation_errors == 1


def test_timeline_without_an_origin_is_empty():
    reducer = CaptureEventReducer(TimelineSettings())
    reducer.push_payload(csrc_payload(ORIGIN, 11))
    assert reducer.timeline(ORIGIN + 1_000).slices == ()
