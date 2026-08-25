from datetime import UTC, datetime

import pytest

from hansard.domain.errors import SummarizationError
from hansard.domain.minutes import ActionItem, Decision, Minutes, Topic
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.evaluation.metrics.minutes import (
    RubricJudge,
    TokenSetMatcher,
    action_item_f1,
    decision_recall,
    grounding_score,
    hallucination_rate,
    token_set_similarity,
)

TRANSCRIPT = Transcript(
    utterances=(
        Utterance(
            TimeSpan(0.0, 12.0),
            "we agreed to migrate the payroll system to the new server in june "
            "and paul will send the budget report to marie",
            "A",
        ),
    )
)


def minutes(**overrides):
    defaults = {
        "title": "Payroll",
        "abstract": "The team agreed to migrate the payroll system to the new server in June.",
        "language": "en",
        "generated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Minutes(**defaults)


class StubGenerator:
    def __init__(self, response):
        self._response = response
        self.calls = []

    @property
    def name(self):
        return "stub"

    @property
    def context_tokens(self):
        return 4096

    def complete(self, system, user, max_tokens, schema):
        self.calls.append((system, user, max_tokens, schema))
        return self._response


def test_token_set_similarity_ignores_word_order_and_extra_words():
    assert token_set_similarity("send budget report", "report budget send") == pytest.approx(1.0)
    assert token_set_similarity("send budget report", "buy a new laptop") < 0.5


def test_action_item_f1_matches_paraphrases_one_to_one():
    reference = (
        ActionItem("Send the budget report to Marie", owner="Paul"),
        ActionItem("Book the meeting room for Tuesday", owner="Marie"),
    )
    hypothesis = (
        ActionItem("Send budget report to Marie", owner="Paul"),
        ActionItem("Order new laptops", owner="Paul"),
    )
    score = action_item_f1(reference, hypothesis)
    assert score.matched == 1
    assert score.precision == pytest.approx(0.5)
    assert score.recall == pytest.approx(0.5)
    assert score.f1 == pytest.approx(0.5)
    assert score.owner_accuracy == pytest.approx(1.0)


def test_action_item_owner_accuracy_detects_wrong_owner():
    reference = (ActionItem("Send the budget report to Marie", owner="Paul"),)
    hypothesis = (ActionItem("Send the budget report to Marie", owner="Marie"),)
    score = action_item_f1(reference, hypothesis)
    assert score.f1 == pytest.approx(1.0)
    assert score.owner_accuracy == pytest.approx(0.0)


def test_action_item_threshold_is_configurable():
    reference = (ActionItem("Send the budget report to Marie"),)
    hypothesis = (ActionItem("Send the quarterly summary to Marie"),)
    assert action_item_f1(reference, hypothesis, TokenSetMatcher(threshold=0.9)).matched == 0
    assert action_item_f1(reference, hypothesis, TokenSetMatcher(threshold=0.5)).matched == 1


def test_token_set_similarity_treats_a_subset_as_a_full_match():
    assert token_set_similarity("send the budget report to marie", "send report") == pytest.approx(1.0)


def test_decision_recall():
    reference = (Decision("We will migrate to the new server"), Decision("We will freeze hiring"))
    hypothesis = (Decision("we will migrate to the new server in june"),)
    assert decision_recall(reference, hypothesis) == pytest.approx(0.5)
    assert decision_recall((), hypothesis) == pytest.approx(1.0)


def test_grounding_score_counts_supported_sentences():
    document = minutes(
        topics=(
            Topic(
                "Migration",
                TimeSpan(0.0, 12.0),
                "Marie approved the quarterly maintenance contract.",
                ("paul sends the budget report",),
            ),
        )
    )
    assert grounding_score(document, TRANSCRIPT) == pytest.approx(2 / 3)


def test_grounding_score_is_one_for_fully_supported_minutes():
    document = minutes(abstract="Paul will send the budget report to Marie.")
    assert grounding_score(document, TRANSCRIPT) == pytest.approx(1.0)


def test_hallucination_rate_flags_absent_entities_and_numbers():
    document = minutes(abstract="Jean Dupont approved a budget of 5000 euros.")
    assert hallucination_rate(document, TRANSCRIPT) == pytest.approx(1.0)


def test_hallucination_rate_is_zero_without_extractable_mentions():
    document = minutes(abstract="the team agreed to migrate the payroll system")
    assert hallucination_rate(document, TRANSCRIPT) == pytest.approx(0.0)


def test_rubric_judge_parses_json_scores():
    generator = StubGenerator('{"coverage": 4, "faithfulness": 5, "actionability": 3, "structure": 4}')
    scores = RubricJudge(generator).score(minutes(), TRANSCRIPT)
    assert scores.coverage == pytest.approx(4.0)
    assert scores.faithfulness == pytest.approx(5.0)
    assert scores.actionability == pytest.approx(3.0)
    assert scores.structure == pytest.approx(4.0)
    assert scores.overall == pytest.approx(4.0)
    assert generator.calls[0][3]["required"] == ["coverage", "faithfulness", "actionability", "structure"]


def test_rubric_judge_clamps_out_of_range_scores():
    payload = '{"coverage": 9, "faithfulness": 0, "actionability": 3, "structure": 4}'
    generator = StubGenerator(f"noise {payload} noise")
    scores = RubricJudge(generator).score(minutes(), TRANSCRIPT)
    assert scores.coverage == pytest.approx(5.0)
    assert scores.faithfulness == pytest.approx(1.0)


def test_rubric_judge_rejects_unusable_output():
    with pytest.raises(SummarizationError):
        RubricJudge(StubGenerator("no json here")).score(minutes(), TRANSCRIPT)
    with pytest.raises(SummarizationError):
        RubricJudge(StubGenerator('{"coverage": 4}')).score(minutes(), TRANSCRIPT)
