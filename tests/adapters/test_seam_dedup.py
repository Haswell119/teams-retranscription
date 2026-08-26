from __future__ import annotations

from hansard.adapters.asr.seams import drop_seam_repeats, trim_to_regions
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Utterance, Word


def _spoken(start: float, end: float, text: str, speaker: str = "Speaker 1") -> Utterance:
    pieces = text.split()
    step = (end - start) / len(pieces)
    words = tuple(
        Word(text=piece, span=TimeSpan(start + index * step, start + (index + 1) * step))
        for index, piece in enumerate(pieces)
    )
    return Utterance(span=TimeSpan(start, end), text=text, speaker=speaker, words=words)


def _written(start: float, end: float, text: str) -> Utterance:
    return Utterance(span=TimeSpan(start, end), text=text)


def _joined(utterances: list[Utterance]) -> str:
    return " ".join(utterance.text for utterance in utterances)


def test_a_word_decoded_on_both_sides_of_a_seam_is_kept_once():
    kept = drop_seam_repeats([_spoken(0.0, 6.67, "on va se pencher sur"), _spoken(6.77, 9.33, "sur un cas")])
    assert _joined(kept) == "on va se pencher sur un cas"


def test_a_repeated_run_of_several_words_collapses():
    kept = drop_seam_repeats(
        [
            _spoken(0.0, 4.0, "à un patient juste avant"),
            _spoken(4.1, 8.0, "juste avant qu'il ne subisse"),
        ]
    )
    assert _joined(kept) == "à un patient juste avant qu'il ne subisse"


def test_punctuation_and_case_do_not_hide_a_repeat():
    kept = drop_seam_repeats(
        [_spoken(0.0, 4.0, "ce qui est catastrophique."), _spoken(4.1, 8.0, "Catastrophique on parle")]
    )
    assert _joined(kept) == "ce qui est Catastrophique on parle"


def test_the_later_copy_survives_because_it_carries_the_better_punctuation():
    kept = drop_seam_repeats(
        [_spoken(0.0, 4.0, "imaginez un peu."), _spoken(4.1, 8.0, "peu, vous vous enfilez")]
    )
    assert _joined(kept) == "imaginez un peu, vous vous enfilez"


def test_two_different_words_at_a_seam_are_both_kept():
    kept = drop_seam_repeats(
        [_spoken(0.0, 4.0, "notre espace d'analyse et de regard."), _spoken(4.19, 6.67, "croisés.")]
    )
    assert _joined(kept) == "notre espace d'analyse et de regard. croisés."


def test_a_genuine_repetition_inside_one_utterance_is_never_touched():
    kept = drop_seam_repeats([_spoken(0.0, 4.0, "c'est très très bien"), _spoken(4.1, 8.0, "on continue")])
    assert _joined(kept) == "c'est très très bien on continue"


def test_utterances_far_apart_in_time_are_left_alone():
    kept = drop_seam_repeats([_spoken(0.0, 4.0, "je propose oui"), _spoken(30.0, 34.0, "oui bien sûr")])
    assert _joined(kept) == "je propose oui oui bien sûr"


def test_an_utterance_entirely_repeated_by_the_next_one_disappears():
    kept = drop_seam_repeats([_spoken(0.0, 4.0, "d'accord"), _spoken(4.1, 8.0, "d'accord tout à fait")])
    assert _joined(kept) == "d'accord tout à fait"
    assert len(kept) == 1


def test_a_repeat_longer_than_the_window_is_left_alone_rather_than_half_removed():
    earlier = _spoken(0.0, 4.0, "un deux trois quatre cinq")
    later = _spoken(4.1, 8.0, "un deux trois quatre cinq")
    assert _joined(drop_seam_repeats([earlier, later], max_repeat_words=3)) == (
        "un deux trois quatre cinq un deux trois quatre cinq"
    )
    assert _joined(drop_seam_repeats([earlier, later], max_repeat_words=8)) == ("un deux trois quatre cinq")


def test_utterances_without_word_timings_are_deduplicated_on_their_text():
    kept = drop_seam_repeats([_written(0.0, 4.0, "we agreed on"), _written(4.1, 8.0, "on the schedule")])
    assert _joined(kept) == "we agreed on the schedule"


def test_a_single_utterance_is_returned_unchanged():
    only = [_spoken(0.0, 4.0, "bonjour à tous")]
    assert drop_seam_repeats(only) is only


def test_temporal_trimming_removes_what_it_can_but_not_everything():
    decoded = [_spoken(0.0, 4.0, "on va se pencher"), _spoken(2.67, 6.67, "se pencher sur un")]
    trimmed = trim_to_regions(decoded, [utterance.span for utterance in decoded])
    assert trimmed[1].text == "pencher sur un"
    assert "pencher pencher" in _joined(trimmed)


def test_trimming_then_deduplicating_recovers_the_sentence():
    decoded = [_spoken(0.0, 4.0, "on va se pencher sur"), _spoken(2.67, 6.67, "pencher sur un cas")]
    spans = [utterance.span for utterance in decoded]
    kept = drop_seam_repeats(trim_to_regions(decoded, spans))
    assert "sur sur" not in _joined(kept)
    assert "pencher" in _joined(kept)
