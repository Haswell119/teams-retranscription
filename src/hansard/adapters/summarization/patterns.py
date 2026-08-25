from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

ENGLISH_STRONG_DECISIONS: tuple[str, ...] = (
    r"\bwe (?:have |'ve )?agreed\b",
    r"\bwe (?:have |'ve )?decided\b",
    r"\bwe (?:have |'ve )?settled on\b",
    r"\bit'?s? (?:been )?decided\b",
    r"\bit (?:is|has been|was) decided\b",
    r"\bthe decision is\b",
    r"\bdecision *: ",
    r"\blet'?s go with\b",
    r"\bwe'?re going with\b",
    r"\bwe(?:'ll| will) go with\b",
    r"\bwe are aligned on\b",
    r"\bwe'?re locking\b",
    r"\bwe lock (?:in|down)\b",
    r"\bsigned off on\b",
    r"\bthat'?s (?:a go|agreed|settled|final)\b",
    r"\bfinal call is\b",
    r"\bit is agreed\b",
)

ENGLISH_WEAK_DECISIONS: tuple[str, ...] = (
    r"\bwe agree\b",
    r"\bwe decide\b",
    r"\bwe approve\b",
    r"\bapproved\b",
    r"\bconfirmed\b",
    r"\bwe confirm\b",
    r"\bwe'?re dropping\b",
    r"\bwe drop\b",
    r"\bwe'?re keeping\b",
    r"\bwe keep\b",
    r"\bwe ship\b",
    r"\bwe'?re shipping\b",
    r"\bno[- ]go\b",
    r"\bwe stick (?:with|to)\b",
)

FRENCH_STRONG_DECISIONS: tuple[str, ...] = (
    r"\bon part sur\b",
    r"\bon valide\b",
    r"\bc'est valide\b",
    r"\bon retient\b",
    r"\bon acte\b",
    r"\bc'est acte\b",
    r"\bil est decide\b",
    r"\bla decision est\b",
    r"\bdecision *: ",
    r"\bnous decidons\b",
    r"\bon decide\b",
    r"\bon a decide\b",
    r"\bc'est decide\b",
    r"\bon tranche pour\b",
    r"\bon opte pour\b",
    r"\bon est aligne[s]? sur\b",
    r"\bon y va (?:avec|pour|sur)\b",
    r"\bon fige\b",
    r"\badjuge\b",
)

FRENCH_WEAK_DECISIONS: tuple[str, ...] = (
    r"\bon choisit\b",
    r"\bon confirme\b",
    r"\bon garde\b",
    r"\bon maintient\b",
    r"\bon abandonne\b",
    r"\bon annule\b",
    r"\bon reporte\b",
    r"\bon livre\b",
    r"\bon ne (?:fait|prend|livre) pas\b",
    r"\bd'accord pour\b",
    r"\bvalide par\b",
)

ENGLISH_BLOCKERS: tuple[str, ...] = (
    r"\bif we\b",
    r"\bif you\b",
    r"\bwhat if\b",
    r"\bmaybe\b",
    r"\bperhaps\b",
    r"\bpossibly\b",
    r"\bprobably\b",
    r"\bwe could\b",
    r"\bwe might\b",
    r"\bwe may\b",
    r"\bwe should\b",
    r"\bwe would\b",
    r"\bi (?:propose|suggest|wonder|think we)\b",
    r"\bshould we\b",
    r"\bdo we want\b",
    r"\blet'?s consider\b",
    r"\bin theory\b",
    r"\bhypothetically\b",
    r"\bnot sure\b",
    r"\bto be confirmed\b",
    r"\btbd\b",
)

FRENCH_BLOCKERS: tuple[str, ...] = (
    r"\bsi on\b",
    r"\bsi nous\b",
    r"\bsi jamais\b",
    r"\bet si\b",
    r"\bau cas ou\b",
    r"\bpeut-etre\b",
    r"\beventuellement\b",
    r"\bon pourrait\b",
    r"\bpourrait-on\b",
    r"\bil faudrait\b",
    r"\bon devrait\b",
    r"\bje propose\b",
    r"\bje suggere\b",
    r"\bje pense qu\b",
    r"\bon verra\b",
    r"\ba voir\b",
    r"\bhypothese\b",
    r"\bimaginons\b",
    r"\ba confirmer\b",
    r"\bpas sur que\b",
)

ENGLISH_COMMITMENT_VERBS = (
    "take|handle|own|draft|send|write|prepare|open|check|review|book|set up|follow up|circulate|"
    "update|fix|raise|rerun|run|share|schedule|create|add|close|file|publish|deploy|test|chase|ping|"
    "look at|put together|sync|document|escalate|merge|land|call|email|ask|confirm|collect|clean up"
)

FRENCH_INFINITIVE_VERBS = (
    "faire|envoyer|ouvrir|preparer|rediger|verifier|regarder|relancer|planifier|mettre|corriger|"
    "creer|partager|ajouter|fermer|publier|deployer|tester|documenter|escalader|valider|contacter|"
    "appeler|organiser|caler|confirmer|transmettre|reprendre|relire|chiffrer|prevenir|demander"
)

FRENCH_PRESENT_VERBS = (
    "fais|envoie|redige|prepare|ouvre|verifie|relance|planifie|corrige|cree|partage|ajoute|ferme|"
    "publie|deploie|teste|documente|valide|contacte|appelle|organise|cale|confirme|transmets|mets|"
    "regarde|reviens|reprends|relis|chiffre|previens|demande"
)

ENGLISH_SELF_ACTIONS: tuple[str, ...] = (
    rf"\bi(?:'ll| will| can| shall| am going to)\s+(?:\w+\s+){{0,2}}?(?:{ENGLISH_COMMITMENT_VERBS})\b",
    rf"\bi'?m\s+(?:\w+\s+){{0,2}}?(?:{ENGLISH_COMMITMENT_VERBS})ing\b",
    r"\bi'?ve got (?:it|this)\b",
    rf"\blet me\s+(?:\w+\s+){{0,2}}?(?:{ENGLISH_COMMITMENT_VERBS})\b",
    r"\bon me\b",
    r"\bi'?ll do (?:it|that)\b",
    r"\bi'?ll take (?:it|that|care)\b",
)

ENGLISH_DIRECTED_ACTIONS: tuple[str, ...] = (
    r"\b(?:can|could|would|will) you\b",
    r"\bplease\b",
    rf"\byou (?:{ENGLISH_COMMITMENT_VERBS})\b",
    r"\bover to you\b",
    r"\bit'?s on you\b",
    r"\bmake sure you\b",
    r"\bi'?ll let you\b",
    rf"\byou'?ll (?:{ENGLISH_COMMITMENT_VERBS})\b",
)

ENGLISH_IMPERSONAL_ACTIONS: tuple[str, ...] = (
    r"\bwe need to\b",
    r"\bwe have to\b",
    r"\bwe must\b",
    r"\bwe still (?:need|have)\b",
    r"\baction item\b",
    r"\bto-?do\b",
    r"\bfollow[- ]up on\b",
    r"\bsomeone (?:needs|has) to\b",
    r"\bnext step is\b",
    r"\bthe task is\b",
)

FRENCH_SELF_ACTIONS: tuple[str, ...] = (
    r"\bje m'en (?:occupe|charge)\b",
    r"\bje m'occupe\b",
    r"\bje me charge\b",
    r"\bje prends\b",
    rf"\bje (?:vais|dois|peux)\s+(?:\w+\s+){{0,2}}?(?:{FRENCH_INFINITIVE_VERBS})\b",
    rf"\bje (?:t'|te |le |la |lui |leur |vous |les )?(?:{FRENCH_PRESENT_VERBS})\b",
    r"\bje le fais\b",
    r"\bc'est pour moi\b",
    r"\bc'est moi qui\b",
)

FRENCH_DIRECTED_ACTIONS: tuple[str, ...] = (
    r"\bpeux-tu\b",
    r"\bpouvez-vous\b",
    r"\btu peux\b",
    r"\bvous pouvez\b",
    rf"\btu (?:{FRENCH_PRESENT_VERBS}|prends)\b",
    r"\bvous (?:prenez|faites|envoyez|regardez|verifiez|preparez|validez)\b",
    r"\bil faut que (?:tu|vous)\b",
    r"\bje te laisse\b",
    r"\bje vous laisse\b",
    r"\ba toi de\b",
    r"\ba vous de\b",
    r"\bcharge-toi\b",
    r"\bmerci de\b",
    r"\bmerci d'\b",
    r"\btu t'en (?:occupes|charges)\b",
)

FRENCH_IMPERSONAL_ACTIONS: tuple[str, ...] = (
    r"\bil faut\b",
    r"\bil faudra\b",
    r"\bon doit\b",
    r"\bon va devoir\b",
    r"\bil reste a\b",
    r"\bprochaine etape\b",
    r"\ba faire\b",
    r"\bto-?do\b",
    r"\bpoint d'action\b",
    r"\bquelqu'un doit\b",
)

ENGLISH_QUESTION_OPENERS: tuple[str, ...] = (
    r"^(?:so |and |but |ok |okay )?(?:what|why|how|when|who|where|which|whose)\b",
    r"^(?:so |and |but )?(?:should|shall|do|does|did|can|could|would|will|is|are|was|were|have|has)"
    r" (?:we|you|i|they|it|there)\b",
    r"\bany (?:idea|thoughts|update)\b",
    r"\bwho (?:owns|takes|is taking|will)\b",
)

FRENCH_QUESTION_OPENERS: tuple[str, ...] = (
    r"^(?:alors |et |mais |donc |bon )?(?:pourquoi|comment|quand|qui|combien|quel|quelle|quels|quelles|ou)\b",
    r"\best-ce (?:que|qu')\b",
    r"\bqu'est-ce\b",
    r"^(?:faut-il|doit-on|peut-on|a-t-on|y a-t-il|va-t-on|sait-on)\b",
    r"\bqui (?:prend|s'en occupe|se charge|fait)\b",
)

ENGLISH_ANSWER_MARKERS: tuple[str, ...] = (
    r"^(?:yes|yep|yeah|no|nope|sure|right|correct|exactly|indeed)\b",
    r"\bthe answer is\b",
    r"\bit'?s (?:because|about|the)\b",
    r"\bi (?:checked|confirmed|know)\b",
)

FRENCH_ANSWER_MARKERS: tuple[str, ...] = (
    r"^(?:oui|non|si|exactement|tout a fait|effectivement|voila|absolument)\b",
    r"\bla reponse est\b",
    r"\bc'est (?:parce que|pour|le|la)\b",
    r"\bj'ai (?:verifie|confirme)\b",
)

ENGLISH_CAUSAL: tuple[str, ...] = (
    r"\bbecause\b",
    r"\bsince\b",
    r"\bas (?:the|we|it|they)\b",
    r"\bthe reason is\b",
    r"\bso (?:that|the|we|it|they)\b",
    r"\bgiven that\b",
    r"\bin order to\b",
)

FRENCH_CAUSAL: tuple[str, ...] = (
    r"\bparce qu\b",
    r"\bcar\b",
    r"\bpuisque\b",
    r"\ben raison de\b",
    r"\bla raison est\b",
    r"\bvu que\b",
    r"\betant donne\b",
    r"\bafin de\b",
    r"\bpour [a-z]+er\b",
    r"\bpour eviter\b",
)

ENGLISH_THIRD_PERSON_VERBS: tuple[str, ...] = (
    "will",
    "is going to",
    "takes",
    "owns",
    "handles",
    "drafts",
    "sends",
    "prepares",
    "is taking",
    "is on it",
)

FRENCH_THIRD_PERSON_VERBS: tuple[str, ...] = (
    "va",
    "prend",
    "prendra",
    "s'occupe",
    "se charge",
    "gere",
    "redige",
    "envoie",
    "prepare",
    "fera",
)

NAME_CHARACTERS = "[A-ZÀ-ÖØ-Þ][\\w\u2019'-]+"

MENTION = re.compile(r"@([\w.\-]+)")
VOCATIVE_HEAD = re.compile(rf"^({NAME_CHARACTERS}(?:\s+{NAME_CHARACTERS})?)\s*[,:]")
VOCATIVE_TAIL = re.compile(rf"[,]\s*({NAME_CHARACTERS}(?:\s+{NAME_CHARACTERS})?)\s*[.?!]?$")


@dataclass(frozen=True, slots=True)
class CueSet:
    language: str
    strong_decisions: tuple[re.Pattern[str], ...]
    weak_decisions: tuple[re.Pattern[str], ...]
    blockers: tuple[re.Pattern[str], ...]
    self_actions: tuple[re.Pattern[str], ...]
    directed_actions: tuple[re.Pattern[str], ...]
    impersonal_actions: tuple[re.Pattern[str], ...]
    question_openers: tuple[re.Pattern[str], ...]
    answer_markers: tuple[re.Pattern[str], ...]
    causal: tuple[re.Pattern[str], ...]
    third_person_verbs: tuple[str, ...]


def _compile(expressions: Sequence[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(expression) for expression in expressions)


ENGLISH_CUES = CueSet(
    language="en",
    strong_decisions=_compile(ENGLISH_STRONG_DECISIONS),
    weak_decisions=_compile(ENGLISH_WEAK_DECISIONS),
    blockers=_compile(ENGLISH_BLOCKERS),
    self_actions=_compile(ENGLISH_SELF_ACTIONS),
    directed_actions=_compile(ENGLISH_DIRECTED_ACTIONS),
    impersonal_actions=_compile(ENGLISH_IMPERSONAL_ACTIONS),
    question_openers=_compile(ENGLISH_QUESTION_OPENERS),
    answer_markers=_compile(ENGLISH_ANSWER_MARKERS),
    causal=_compile(ENGLISH_CAUSAL),
    third_person_verbs=ENGLISH_THIRD_PERSON_VERBS,
)

FRENCH_CUES = CueSet(
    language="fr",
    strong_decisions=_compile(FRENCH_STRONG_DECISIONS),
    weak_decisions=_compile(FRENCH_WEAK_DECISIONS),
    blockers=_compile(FRENCH_BLOCKERS),
    self_actions=_compile(FRENCH_SELF_ACTIONS),
    directed_actions=_compile(FRENCH_DIRECTED_ACTIONS),
    impersonal_actions=_compile(FRENCH_IMPERSONAL_ACTIONS),
    question_openers=_compile(FRENCH_QUESTION_OPENERS),
    answer_markers=_compile(FRENCH_ANSWER_MARKERS),
    causal=_compile(FRENCH_CAUSAL),
    third_person_verbs=FRENCH_THIRD_PERSON_VERBS,
)

BILINGUAL_CUES = CueSet(
    language="mixed",
    strong_decisions=ENGLISH_CUES.strong_decisions + FRENCH_CUES.strong_decisions,
    weak_decisions=ENGLISH_CUES.weak_decisions + FRENCH_CUES.weak_decisions,
    blockers=ENGLISH_CUES.blockers + FRENCH_CUES.blockers,
    self_actions=ENGLISH_CUES.self_actions + FRENCH_CUES.self_actions,
    directed_actions=ENGLISH_CUES.directed_actions + FRENCH_CUES.directed_actions,
    impersonal_actions=ENGLISH_CUES.impersonal_actions + FRENCH_CUES.impersonal_actions,
    question_openers=ENGLISH_CUES.question_openers + FRENCH_CUES.question_openers,
    answer_markers=ENGLISH_CUES.answer_markers + FRENCH_CUES.answer_markers,
    causal=ENGLISH_CUES.causal + FRENCH_CUES.causal,
    third_person_verbs=ENGLISH_THIRD_PERSON_VERBS + FRENCH_THIRD_PERSON_VERBS,
)

CUES_BY_LANGUAGE: Mapping[str, CueSet] = {"en": ENGLISH_CUES, "fr": FRENCH_CUES}


def cues_for(language: str) -> CueSet:
    return CUES_BY_LANGUAGE.get(language, BILINGUAL_CUES)


def first_match(text: str, patterns: Sequence[re.Pattern[str]]) -> str | None:
    for pattern in patterns:
        found = pattern.search(text)
        if found is not None:
            return found.group(0).strip()
    return None


def matches_any(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) is not None for pattern in patterns)
