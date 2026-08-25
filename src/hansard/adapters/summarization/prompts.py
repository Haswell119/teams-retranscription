from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

MAP_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "statement": {"type": "string"},
                    "rationale": {"type": "string"},
                    "quote": {"type": "string"},
                    "utterance": {"type": "integer"},
                },
                "required": ["statement", "quote", "utterance"],
            },
        },
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "description": {"type": "string"},
                    "owner": {"type": "string"},
                    "due": {"type": "string"},
                    "quote": {"type": "string"},
                    "utterance": {"type": "integer"},
                },
                "required": ["description", "quote", "utterance"],
            },
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "question": {"type": "string"},
                    "raised_by": {"type": "string"},
                    "quote": {"type": "string"},
                    "utterance": {"type": "integer"},
                },
                "required": ["question", "quote", "utterance"],
            },
        },
        "entities": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "decisions", "actions", "questions"],
}

REDUCE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "abstract": {"type": "string"},
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "index": {"type": "integer"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "key_points": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["index", "title", "summary"],
            },
        },
    },
    "required": ["abstract", "topics"],
}

ENGLISH_MAP_SYSTEM = (
    "You are a meeting clerk. You read one excerpt of a verbatim meeting transcript and you write "
    "down only what it actually contains.\n"
    "Absolute rules:\n"
    "1. Never invent a fact, a name, a number or a date. Everything you write must be supported by "
    "the excerpt you were given.\n"
    "2. Every item you produce must carry a verbatim quote copied character for character from the "
    "excerpt, together with the number in square brackets of the line it comes from.\n"
    "3. A DECISION is a commitment the group actually made: it is settled, it is not conditional and "
    "it is not a proposal. 'We could', 'maybe', 'I suggest', 'we should probably', 'if we' and any "
    "open question are NOT decisions. When in doubt, leave it out.\n"
    "4. An ACTION is a task somebody committed to. Give an owner only when the excerpt names the "
    "person or when the person commits in the first person; otherwise leave the owner empty. Never "
    "guess an owner. Copy a deadline only when it is said out loud; otherwise leave it empty.\n"
    "5. A QUESTION is a question that was raised and left without an answer in this excerpt.\n"
    "6. If a category has nothing in this excerpt, return an empty list. An empty list is a correct "
    "answer; a plausible invention is a wrong answer.\n"
    "7. Write in English, in the language of the meeting for quotes.\n"
    "8. Answer with a single JSON object and nothing else."
)

FRENCH_MAP_SYSTEM = (
    "Vous êtes secrétaire de séance. Vous lisez un extrait de transcription verbatim d'une réunion "
    "et vous ne consignez que ce qu'il contient réellement.\n"
    "Règles absolues :\n"
    "1. N'inventez jamais un fait, un nom, un chiffre ou une date. Tout ce que vous écrivez doit être "
    "étayé par l'extrait fourni.\n"
    "2. Chaque élément produit doit porter une citation verbatim, copiée caractère pour caractère "
    "depuis l'extrait, avec le numéro entre crochets de la ligne dont elle provient.\n"
    "3. Une DÉCISION est un engagement réellement pris par le groupe : elle est tranchée, elle n'est "
    "ni conditionnelle ni une proposition. « on pourrait », « peut-être », « je propose », « il "
    "faudrait », « si on » et toute question ouverte ne sont PAS des décisions. Dans le doute, "
    "n'inscrivez rien.\n"
    "4. Une ACTION est une tâche prise en charge. N'indiquez un responsable que si l'extrait nomme la "
    "personne ou si la personne s'engage à la première personne ; sinon laissez le responsable vide. "
    "Ne devinez jamais un responsable. Ne reportez une échéance que si elle est prononcée ; sinon "
    "laissez-la vide.\n"
    "5. Une QUESTION est une question posée et restée sans réponse dans cet extrait.\n"
    "6. Si une catégorie est vide dans cet extrait, renvoyez une liste vide. Une liste vide est une "
    "bonne réponse ; une invention plausible est une mauvaise réponse.\n"
    "7. Rédigez en français.\n"
    "8. Répondez par un unique objet JSON, sans rien d'autre."
)

ENGLISH_REDUCE_SYSTEM = (
    "You are a meeting clerk consolidating notes taken on successive excerpts of the same meeting.\n"
    "Absolute rules:\n"
    "1. Use only the material given below. Never add a fact, a name, a number or a date that is not "
    "in it.\n"
    "2. Write the abstract as plain prose that a participant could verify line by line against the "
    "transcript. No adjectives that the transcript does not support.\n"
    "3. Keep the topic numbering you are given. Summarise each topic with what was actually said "
    "about it. If a topic contains nothing worth reporting, say that it was mentioned without being "
    "discussed rather than inventing content.\n"
    "4. Never turn a suggestion into a decision.\n"
    "5. Write in English.\n"
    "6. Answer with a single JSON object and nothing else."
)

FRENCH_REDUCE_SYSTEM = (
    "Vous êtes secrétaire de séance et vous consolidez des notes prises sur des extraits successifs "
    "de la même réunion.\n"
    "Règles absolues :\n"
    "1. N'utilisez que la matière fournie ci-dessous. N'ajoutez jamais un fait, un nom, un chiffre ou "
    "une date qui n'y figure pas.\n"
    "2. Rédigez la synthèse en prose sobre, vérifiable ligne à ligne dans la transcription. Aucun "
    "qualificatif que la transcription n'étaye pas.\n"
    "3. Conservez la numérotation des sujets fournie. Résumez chaque sujet avec ce qui a réellement "
    "été dit. Si un sujet ne contient rien à consigner, indiquez qu'il a été évoqué sans être traité "
    "plutôt que d'inventer du contenu.\n"
    "4. Ne transformez jamais une suggestion en décision.\n"
    "5. Rédigez en français.\n"
    "6. Répondez par un unique objet JSON, sans rien d'autre."
)

ENGLISH_MAP_USER = (
    "Meeting: {title}\n"
    "Participants: {participants}\n"
    "Excerpt {position} of {total}, covering {period}.\n\n"
    "{context}"
    "TRANSCRIPT EXCERPT (each line is numbered in square brackets):\n"
    "{excerpt}\n\n"
    "Fill the JSON object with these keys:\n"
    "- summary: two or three sentences on what this excerpt is about.\n"
    "- decisions: list of objects with statement, rationale, quote, utterance.\n"
    "- actions: list of objects with description, owner, due, quote, utterance.\n"
    "- questions: list of objects with question, raised_by, quote, utterance.\n"
    "- entities: names, products, systems and figures that appear in the excerpt.\n"
    "utterance is the number in square brackets of the line the quote was copied from."
)

FRENCH_MAP_USER = (
    "Réunion : {title}\n"
    "Participants : {participants}\n"
    "Extrait {position} sur {total}, couvrant {period}.\n\n"
    "{context}"
    "EXTRAIT DE TRANSCRIPTION (chaque ligne est numérotée entre crochets) :\n"
    "{excerpt}\n\n"
    "Remplissez l'objet JSON avec ces clés :\n"
    "- summary : deux ou trois phrases sur l'objet de cet extrait.\n"
    "- decisions : liste d'objets avec statement, rationale, quote, utterance.\n"
    "- actions : liste d'objets avec description, owner, due, quote, utterance.\n"
    "- questions : liste d'objets avec question, raised_by, quote, utterance.\n"
    "- entities : noms, produits, systèmes et chiffres présents dans l'extrait.\n"
    "utterance est le numéro entre crochets de la ligne d'où la citation est copiée."
)

ENGLISH_REDUCE_USER = (
    "Meeting: {title}\n"
    "Participants: {participants}\n"
    "Duration: {duration}\n\n"
    "NOTES TAKEN ON EACH EXCERPT:\n{summaries}\n\n"
    "DECISIONS ALREADY RECORDED:\n{decisions}\n\n"
    "ACTIONS ALREADY RECORDED:\n{actions}\n\n"
    "OPEN QUESTIONS ALREADY RECORDED:\n{questions}\n\n"
    "TOPIC SEGMENTS (computed from the transcript, keep the numbering and the boundaries):\n"
    "{topics}\n\n"
    "Fill the JSON object with these keys:\n"
    "- abstract: at most {abstract_sentences} sentences summarising the whole meeting for somebody "
    "who did not attend.\n"
    "- topics: one object per topic segment above, with index, title, summary and key_points."
)

FRENCH_REDUCE_USER = (
    "Réunion : {title}\n"
    "Participants : {participants}\n"
    "Durée : {duration}\n\n"
    "NOTES PRISES SUR CHAQUE EXTRAIT :\n{summaries}\n\n"
    "DÉCISIONS DÉJÀ CONSIGNÉES :\n{decisions}\n\n"
    "ACTIONS DÉJÀ CONSIGNÉES :\n{actions}\n\n"
    "POINTS OUVERTS DÉJÀ CONSIGNÉS :\n{questions}\n\n"
    "SUJETS DÉCOUPÉS DANS LA TRANSCRIPTION (conservez la numérotation et les bornes) :\n"
    "{topics}\n\n"
    "Remplissez l'objet JSON avec ces clés :\n"
    "- abstract : au plus {abstract_sentences} phrases résumant toute la réunion pour une personne "
    "absente.\n"
    "- topics : un objet par sujet ci-dessus, avec index, title, summary et key_points."
)

ENGLISH_CONTEXT_HEADER = (
    "CONTEXT FROM THE PREVIOUS EXCERPT (for continuity only, do not report items from it):\n"
    "{context}\n\n"
)

FRENCH_CONTEXT_HEADER = (
    "CONTEXTE DE L'EXTRAIT PRÉCÉDENT (continuité seulement, n'en tirez aucun élément) :\n"
    "{context}\n\n"
)

ENGLISH_NOTHING = "(none)"
FRENCH_NOTHING = "(aucun)"


@dataclass(frozen=True, slots=True)
class PromptPack:
    language: str
    map_system: str
    map_user: str
    reduce_system: str
    reduce_user: str
    context_header: str
    nothing: str

    def context_block(self, rendered_context: str) -> str:
        if not rendered_context.strip():
            return ""
        return self.context_header.format(context=rendered_context)

    def listing(self, entries: tuple[str, ...]) -> str:
        return "\n".join(f"- {entry}" for entry in entries) if entries else self.nothing


ENGLISH_PROMPTS = PromptPack(
    language="en",
    map_system=ENGLISH_MAP_SYSTEM,
    map_user=ENGLISH_MAP_USER,
    reduce_system=ENGLISH_REDUCE_SYSTEM,
    reduce_user=ENGLISH_REDUCE_USER,
    context_header=ENGLISH_CONTEXT_HEADER,
    nothing=ENGLISH_NOTHING,
)

FRENCH_PROMPTS = PromptPack(
    language="fr",
    map_system=FRENCH_MAP_SYSTEM,
    map_user=FRENCH_MAP_USER,
    reduce_system=FRENCH_REDUCE_SYSTEM,
    reduce_user=FRENCH_REDUCE_USER,
    context_header=FRENCH_CONTEXT_HEADER,
    nothing=FRENCH_NOTHING,
)

PROMPTS_BY_LANGUAGE: Mapping[str, PromptPack] = {
    ENGLISH_PROMPTS.language: ENGLISH_PROMPTS,
    FRENCH_PROMPTS.language: FRENCH_PROMPTS,
}


def prompt_pack_for(language: str) -> PromptPack:
    return PROMPTS_BY_LANGUAGE.get(language, ENGLISH_PROMPTS)
