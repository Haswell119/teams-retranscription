import pytest

from hansard.evaluation.french_numbers import spell_cardinal, spell_digits, spell_ordinal
from hansard.evaluation.normalizers import (
    BasicNormalizer,
    EnglishNormalizer,
    FrenchNormalizer,
    normalizer_for,
)

FRENCH = FrenchNormalizer()
ENGLISH_BUILTIN = EnglishNormalizer(prefer_installed_whisper=False)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "zéro"),
        (16, "seize"),
        (17, "dix-sept"),
        (21, "vingt-et-un"),
        (70, "soixante-dix"),
        (71, "soixante-et-onze"),
        (77, "soixante-dix-sept"),
        (80, "quatre-vingts"),
        (81, "quatre-vingt-un"),
        (90, "quatre-vingt-dix"),
        (91, "quatre-vingt-onze"),
        (99, "quatre-vingt-dix-neuf"),
        (100, "cent"),
        (200, "deux-cents"),
        (201, "deux-cent-un"),
        (1000, "mille"),
        (1995, "mille-neuf-cent-quatre-vingt-quinze"),
        (2024, "deux-mille-vingt-quatre"),
        (1_000_000, "un-million"),
    ],
)
def test_french_cardinals(value, expected):
    assert spell_cardinal(value) == expected


@pytest.mark.parametrize(
    ("value", "feminine", "expected"),
    [
        (1, False, "premier"),
        (1, True, "première"),
        (2, False, "deuxième"),
        (4, False, "quatrième"),
        (5, False, "cinquième"),
        (9, False, "neuvième"),
        (11, False, "onzième"),
        (21, False, "vingt-et-unième"),
        (80, False, "quatre-vingtième"),
        (1000, False, "millième"),
    ],
)
def test_french_ordinals(value, feminine, expected):
    assert spell_ordinal(value, feminine=feminine) == expected


def test_french_digit_by_digit():
    assert spell_digits("0612") == "zéro-six-un-deux"


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("M. Dupont arrive à 9h30.", "Monsieur Dupont arrive à neuf heures trente"),
        ("Il y a 21 postes ouverts.", "il y a vingt et un postes ouverts"),
        ("Le budget de 1 200 € augmente.", "le budget de mille deux cents euros augmente"),
        ("Une hausse de 3,5 %.", "une hausse de trois virgule cinq pour cent"),
        ("Le n° 42 du 1er trimestre", "le numéro quarante-deux du premier trimestre"),
        ("quatre-vingt-dix pour cent", "quatre vingt dix pour cent"),
        ("l'équipe et l'usine", "l équipe et l usine"),
        ("Le cœur et la sœur", "le coeur et la soeur"),
        ("Mme Martin est arrivée", "madame Martin est arrivée"),
        ("C'est en 1995 que tout a changé", "c est en mille neuf cent quatre-vingt-quinze que tout a changé"),
    ],
)
def test_french_written_and_spoken_forms_converge(written, spoken):
    assert FRENCH.normalize(written) == FRENCH.normalize(spoken)


def test_french_removes_fillers_and_keeps_accents():
    assert FRENCH.normalize("Euh, bah, c'est très bien, hein.") == "c est très bien"


def test_french_accent_stripping_is_opt_in():
    assert FrenchNormalizer(strip_accents=True).normalize("Très élégant") == "tres elegant"


def test_french_apostrophe_variants_are_equivalent():
    assert FRENCH.normalize("l\u2019équipe") == FRENCH.normalize("l'équipe")


def test_french_elision_prevents_word_gluing():
    assert FRENCH.normalize("aujourd'hui") == "aujourd hui"


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        (
            "Mr. Quilter's manner, uh, isn't less interesting!",
            "mister quilter is manner is not less interesting",
        ),
        ("I've got twenty five dollars", "i have got $25"),
        ("HE TELLS US THAT AT THIS FESTIVE SEASON", "he tells us that at this festive season"),
        ("The colour of the centre programme", "the color of the center program"),
    ],
)
def test_english_builtin_matches_whisper_rules(written, expected):
    assert ENGLISH_BUILTIN.normalize(written) == expected


def test_english_default_agrees_with_builtin_on_core_rules():
    default = EnglishNormalizer()
    phrases = [
        "Mr. Smith didn't answer, um, the question.",
        "We'll travel to St. Louis tomorrow",
        "She's got three cats and the colour red",
    ]
    assert [default.normalize(phrase) for phrase in phrases] == [
        ENGLISH_BUILTIN.normalize(phrase) for phrase in phrases
    ]


def test_english_spelling_map_can_be_disabled():
    assert EnglishNormalizer(british_to_american=False).normalize("colour") == "colour"


def test_basic_normalizer_is_language_agnostic():
    assert BasicNormalizer().normalize("  Héllo,   WORLD!! ") == "héllo world"
    assert BasicNormalizer(strip_accents=True).normalize("Héllo") == "hello"


def test_normalizer_factory_dispatches_on_language():
    assert isinstance(normalizer_for("fr-FR"), FrenchNormalizer)
    assert isinstance(normalizer_for("en_US"), EnglishNormalizer)
    assert isinstance(normalizer_for("de"), BasicNormalizer)
    assert isinstance(normalizer_for(None), BasicNormalizer)


@pytest.mark.parametrize(
    ("abbreviated", "expanded"),
    [
        ("Mme Kirchner", "mme kirchner"),
        ("M. Dupont", "m. dupont"),
        ("Dr Martin", "dr martin"),
        ("Pr. Curie", "pr curie"),
        ("St-Étienne", "st-étienne"),
    ],
)
def test_french_titles_expand_independently_of_case(abbreviated, expanded):
    assert FRENCH.normalize(abbreviated) == FRENCH.normalize(expanded)


@pytest.mark.parametrize(
    "phrase",
    ["Premier ministre", "Premièrement", "Stéréotype", "Drapeau", "Mlleret", "Stern"],
)
def test_french_titles_do_not_swallow_longer_words(phrase):
    assert FRENCH.normalize(phrase) == phrase.lower()


@pytest.mark.parametrize("written", ["30 %", "trente pour cent", "trente pourcent", "trente pour-cent"])
def test_french_percent_spellings_converge(written):
    assert FRENCH.normalize(written) == "trente pour cent"


@pytest.mark.parametrize("token", ["m16", "a320", "35mm", "covid19"])
def test_french_numbers_glued_to_letters_are_left_alone(token):
    assert FRENCH.normalize(f"le {token} arrive") == f"le {token} arrive"


def test_french_standalone_numbers_still_expand():
    assert FRENCH.normalize("le 35 mm en 2005") == "le trente cinq mm en deux mille cinq"
