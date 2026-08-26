from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from hansard.domain.language import MIXED

DEFAULT_LANGUAGE = "en"


class Phrase(StrEnum):
    TRANSCRIPT = "transcript"
    MINUTES = "minutes"
    DATE = "date"
    DURATION = "duration"
    PARTICIPANTS = "participants"
    ATTENDEES = "attendees"
    LANGUAGE = "language"
    AND = "and"
    PRODUCED_WITH = "produced_with"
    GENERATED_AT = "generated_at"
    EXECUTIVE_SUMMARY = "executive_summary"
    KEY_DECISIONS = "key_decisions"
    ACTION_ITEMS = "action_items"
    DISCUSSION_BY_TOPIC = "discussion_by_topic"
    OPEN_QUESTIONS = "open_questions"
    SPEAKING_TIME = "speaking_time"
    KEY_POINTS = "key_points"
    OWNER = "owner"
    ACTION = "action"
    DUE = "due"
    SOURCE = "source"
    SPEAKER = "speaker"
    SHARE = "share"
    RATIONALE = "rationale"
    RAISED_BY = "raised_by"
    UNASSIGNED = "unassigned"
    UNKNOWN_SPEAKER = "unknown_speaker"
    NO_DECISIONS = "no_decisions"
    NO_ACTIONS = "no_actions"
    NO_TOPICS = "no_topics"
    NO_QUESTIONS = "no_questions"
    NO_SPEAKING_TIME = "no_speaking_time"
    NO_SPEECH = "no_speech"
    CONTENTS = "contents"
    SKIP_TO_CONTENT = "skip_to_content"
    SOVEREIGNTY = "sovereignty"
    SOVEREIGNTY_TRANSCRIPT = "sovereignty_transcript"
    SOVEREIGNTY_SHORT = "sovereignty_short"
    DATE_PATTERN = "date_pattern"
    UNIT_HOUR = "unit_hour"
    UNIT_MINUTE = "unit_minute"
    UNIT_SECOND = "unit_second"
    DECIMAL_SEPARATOR = "decimal_separator"
    PERCENT_PATTERN = "percent_pattern"
    LABEL_PATTERN = "label_pattern"


ENGLISH_PHRASES: Mapping[Phrase, str] = {
    Phrase.TRANSCRIPT: "Transcript",
    Phrase.MINUTES: "Minutes",
    Phrase.DATE: "Date",
    Phrase.DURATION: "Duration",
    Phrase.PARTICIPANTS: "Participants",
    Phrase.ATTENDEES: "Attendees",
    Phrase.LANGUAGE: "Language",
    Phrase.PRODUCED_WITH: "Produced with",
    Phrase.GENERATED_AT: "Generated on {moment}",
    Phrase.EXECUTIVE_SUMMARY: "Executive summary",
    Phrase.KEY_DECISIONS: "Key decisions",
    Phrase.ACTION_ITEMS: "Action items",
    Phrase.DISCUSSION_BY_TOPIC: "Discussion by topic",
    Phrase.OPEN_QUESTIONS: "Open questions",
    Phrase.SPEAKING_TIME: "Speaking time",
    Phrase.KEY_POINTS: "Key points",
    Phrase.OWNER: "Owner",
    Phrase.ACTION: "Action",
    Phrase.DUE: "Due",
    Phrase.SOURCE: "Source",
    Phrase.SPEAKER: "Speaker",
    Phrase.SHARE: "Share",
    Phrase.RATIONALE: "Rationale",
    Phrase.RAISED_BY: "raised by {speaker}",
    Phrase.AND: "and",
    Phrase.UNASSIGNED: "Unassigned",
    Phrase.UNKNOWN_SPEAKER: "Unidentified speaker",
    Phrase.NO_DECISIONS: "No decision was recorded.",
    Phrase.NO_ACTIONS: "No action item was recorded.",
    Phrase.NO_TOPICS: "No topic was identified.",
    Phrase.NO_QUESTIONS: "No open question was recorded.",
    Phrase.NO_SPEAKING_TIME: "Speaking time was not measured.",
    Phrase.NO_SPEECH: "No speech was transcribed.",
    Phrase.CONTENTS: "Contents",
    Phrase.SKIP_TO_CONTENT: "Skip to content",
    Phrase.SOVEREIGNTY: (
        "Transcribed and summarised locally by {generator} using {models}. "
        "No audio, transcript or minutes left the organisation."
    ),
    Phrase.SOVEREIGNTY_TRANSCRIPT: (
        "Transcribed locally by {generator} using {models}. No audio and no transcript left the organisation."
    ),
    Phrase.SOVEREIGNTY_SHORT: ("Transcribed locally by {generator}. No data left the organisation."),
    Phrase.DATE_PATTERN: "{day} {month} {year} at {time} ({timezone})",
    Phrase.UNIT_HOUR: "h",
    Phrase.UNIT_MINUTE: "min",
    Phrase.UNIT_SECOND: "s",
    Phrase.DECIMAL_SEPARATOR: ".",
    Phrase.PERCENT_PATTERN: "{value}%",
    Phrase.LABEL_PATTERN: "{label}:",
}

FRENCH_PHRASES: Mapping[Phrase, str] = {
    Phrase.TRANSCRIPT: "Transcription",
    Phrase.MINUTES: "Compte rendu",
    Phrase.DATE: "Date",
    Phrase.DURATION: "Durée",
    Phrase.PARTICIPANTS: "Participants",
    Phrase.ATTENDEES: "Participants",
    Phrase.LANGUAGE: "Langue",
    Phrase.PRODUCED_WITH: "Produit avec",
    Phrase.GENERATED_AT: "Généré le {moment}",
    Phrase.EXECUTIVE_SUMMARY: "Synthèse",
    Phrase.KEY_DECISIONS: "Relevé de décisions",
    Phrase.ACTION_ITEMS: "Actions à mener",
    Phrase.DISCUSSION_BY_TOPIC: "Déroulé par sujet",
    Phrase.OPEN_QUESTIONS: "Points ouverts",
    Phrase.SPEAKING_TIME: "Temps de parole",
    Phrase.KEY_POINTS: "Points clés",
    Phrase.OWNER: "Responsable",
    Phrase.ACTION: "Action",
    Phrase.DUE: "Échéance",
    Phrase.SOURCE: "Source",
    Phrase.SPEAKER: "Intervenant",
    Phrase.SHARE: "Part",
    Phrase.RATIONALE: "Justification",
    Phrase.RAISED_BY: "soulevé par {speaker}",
    Phrase.AND: "et",
    Phrase.UNASSIGNED: "Non attribué",
    Phrase.UNKNOWN_SPEAKER: "Intervenant non identifié",
    Phrase.NO_DECISIONS: "Aucune décision n'a été consignée.",
    Phrase.NO_ACTIONS: "Aucune action n'a été consignée.",
    Phrase.NO_TOPICS: "Aucun sujet n'a été identifié.",
    Phrase.NO_QUESTIONS: "Aucun point ouvert n'a été consigné.",
    Phrase.NO_SPEAKING_TIME: "Le temps de parole n'a pas été mesuré.",
    Phrase.NO_SPEECH: "Aucune parole n'a été transcrite.",
    Phrase.CONTENTS: "Sommaire",
    Phrase.SKIP_TO_CONTENT: "Aller au contenu",
    Phrase.SOVEREIGNTY: (
        "Transcription et compte rendu produits localement par {generator} avec {models}. "
        "Aucun enregistrement, aucune transcription et aucun compte rendu n'est sorti de l'organisation."
    ),
    Phrase.SOVEREIGNTY_TRANSCRIPT: (
        "Transcription produite localement par {generator} avec {models}. "
        "Aucun enregistrement et aucune transcription n'est sorti de l'organisation."
    ),
    Phrase.SOVEREIGNTY_SHORT: (
        "Transcription produite localement par {generator}. Aucune donnée n'est sortie de l'organisation."
    ),
    Phrase.DATE_PATTERN: "{day} {month} {year} à {time} ({timezone})",
    Phrase.UNIT_HOUR: "h",
    Phrase.UNIT_MINUTE: "min",
    Phrase.UNIT_SECOND: "s",
    Phrase.DECIMAL_SEPARATOR: ",",
    Phrase.PERCENT_PATTERN: "{value} %",
    Phrase.LABEL_PATTERN: "{label} :",
}

ENGLISH_MONTHS: tuple[str, ...] = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

FRENCH_MONTHS: tuple[str, ...] = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)

ENGLISH_LANGUAGE_NAMES: Mapping[str, str] = {
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "nl": "Dutch",
    "pt": "Portuguese",
    MIXED: "several languages",
}

FRENCH_LANGUAGE_NAMES: Mapping[str, str] = {
    "de": "allemand",
    "en": "anglais",
    "es": "espagnol",
    "fr": "français",
    "it": "italien",
    "nl": "néerlandais",
    "pt": "portugais",
    MIXED: "plusieurs langues",
}


@dataclass(frozen=True, slots=True)
class Translations:
    language: str
    phrases: Mapping[Phrase, str]
    months: tuple[str, ...]
    language_names: Mapping[str, str]

    def text(self, phrase: Phrase) -> str:
        return self.phrases.get(phrase, ENGLISH_PHRASES[phrase])

    def format(self, phrase: Phrase, **values: object) -> str:
        return self.text(phrase).format(**values)

    def month_name(self, month_number: int) -> str:
        return self.months[month_number - 1]

    def language_name(self, tag: str) -> str:
        return self.language_names.get(normalise_language(tag), tag)

    def language_names_of(self, tags: Sequence[str]) -> str:
        return self.join(tuple(self.language_name(tag) for tag in tags))

    def join(self, items: Sequence[str]) -> str:
        if len(items) < 2:
            return items[0] if items else ""
        return f"{', '.join(items[:-1])} {self.text(Phrase.AND)} {items[-1]}"


ENGLISH = Translations(
    language="en",
    phrases=ENGLISH_PHRASES,
    months=ENGLISH_MONTHS,
    language_names=ENGLISH_LANGUAGE_NAMES,
)

FRENCH = Translations(
    language="fr",
    phrases=FRENCH_PHRASES,
    months=FRENCH_MONTHS,
    language_names=FRENCH_LANGUAGE_NAMES,
)

CATALOGUES: Mapping[str, Translations] = {ENGLISH.language: ENGLISH, FRENCH.language: FRENCH}


def normalise_language(language: str | None) -> str:
    if not language:
        return DEFAULT_LANGUAGE
    return language.strip().replace("_", "-").split("-")[0].lower()


def translations_for(language: str | None) -> Translations:
    return CATALOGUES.get(normalise_language(language), ENGLISH)


def available_languages() -> tuple[str, ...]:
    return tuple(sorted(CATALOGUES))
