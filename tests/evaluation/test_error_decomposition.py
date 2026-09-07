from hansard.evaluation.metrics.decomposition import (
    CODE_SWITCHED,
    CONTENT_WORD,
    FILLER,
    FUNCTION_WORD,
    NUMBER,
    PROPER_NOUN,
    decompose,
    decompose_many,
    proper_nouns,
)


def test_capitalised_words_inside_a_sentence_are_proper_nouns():
    assert proper_nouns("le rapport de Bloomberg arrive") == frozenset({"bloomberg"})


def test_a_sentence_initial_capital_is_not_a_proper_noun():
    assert proper_nouns("Bonjour tout le monde") == frozenset()


def test_a_capital_after_a_full_stop_is_not_a_proper_noun():
    assert proper_nouns("c'est fait. Ensuite on avance") == frozenset()


def test_every_reference_word_lands_in_exactly_one_category():
    result = decompose(
        "le rapport bloomberg contient douze euh chiffres",
        "le rapport bloomberg contient douze euh chiffres",
        "fr",
        raw_reference="le rapport Bloomberg contient douze euh chiffres",
    )
    assert result.reference_words == 7
    assert sum(item.reference_words for item in result.categories) == 7


def test_a_missing_proper_noun_is_charged_to_the_proper_noun_bucket():
    result = decompose(
        "on parle avec bloomberg demain",
        "on parle avec demain",
        "fr",
        raw_reference="on parle avec Bloomberg demain",
    )
    assert result.counts_for(PROPER_NOUN).deletions == 1
    assert result.counts_for(PROPER_NOUN).recall == 0.0
    assert result.counts_for(CONTENT_WORD).deletions == 0


def test_a_glossary_term_counts_as_a_proper_noun_without_capitals():
    result = decompose("le nav du fonds", "le du fonds", "fr", glossary=("NAV",))
    assert result.counts_for(PROPER_NOUN).reference_words == 1
    assert result.counts_for(PROPER_NOUN).deletions == 1


def test_english_words_in_french_are_flagged_as_code_switched():
    result = decompose("je vais the deploy demain", "je vais the deploy demain", "fr")
    assert result.counts_for(CODE_SWITCHED).reference_words >= 1
    assert result.counts_for(CODE_SWITCHED).hits >= 1


def test_digits_and_number_words_are_numbers():
    result = decompose("il en reste 12 et trois", "il en reste 12 et trois", "fr")
    assert result.counts_for(NUMBER).reference_words == 2


def test_fillers_are_separated_from_content():
    result = decompose("euh le budget", "le budget", "fr")
    assert result.counts_for(FILLER).deletions == 1
    assert result.counts_for(CONTENT_WORD).deletions == 0


def test_function_words_are_separated_from_content():
    result = decompose("le budget", "budget", "fr")
    assert result.counts_for(FUNCTION_WORD).deletions == 1


def test_insertions_are_counted_once_and_not_charged_to_a_category():
    result = decompose("le budget", "le budget final", "fr")
    assert result.insertions == 1
    assert result.deletions == 0
    assert result.substitutions == 0


def test_an_empty_hypothesis_deletes_every_reference_word():
    result = decompose("le budget final", "", "fr")
    assert result.deletions == 3
    assert result.error_rate == 1.0


def test_decompositions_add_up_across_utterances():
    total = decompose_many(
        [("le budget", "le budget"), ("le rapport", "rapport")],
        "fr",
    )
    assert total.reference_words == 4
    assert total.deletions == 1


def test_a_word_that_also_appears_lowercase_is_not_a_proper_noun():
    from hansard.evaluation.metrics.decomposition import proper_nouns

    assert proper_nouns("on garde Le budget et le reste") == frozenset()


def test_a_name_that_only_ever_appears_capitalised_is_kept():
    from hansard.evaluation.metrics.decomposition import proper_nouns

    assert "sarah" in proper_nouns("on voit Sarah demain et Sarah confirme")


def test_the_english_pronoun_is_not_mistaken_for_a_name():
    from hansard.evaluation.metrics.decomposition import proper_nouns

    assert proper_nouns("we said I would and I will") == frozenset()


def test_single_letters_are_not_names():
    from hansard.evaluation.metrics.decomposition import proper_nouns

    assert proper_nouns("the point is D and then more") == frozenset()


def test_utterances_are_joined_with_a_sentence_boundary():
    from hansard.evaluation.metrics.decomposition import proper_nouns, sentence_joined

    joined = sentence_joined(["And then we left", "And then we arrived"])
    assert proper_nouns(joined) == frozenset()
