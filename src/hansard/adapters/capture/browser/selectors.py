from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Final

APOSTROPHES: Final[dict[int, str]] = {
    0x2019: "'",
    0x2018: "'",
    0x02BC: "'",
    0x00B4: "'",
}

WHITESPACE: Final[re.Pattern[str]] = re.compile(r"[\s\u00a0\u202f\u2009\u200b]+")


def normalise_text(value: str) -> str:
    folded = unicodedata.normalize("NFC", value).translate(APOSTROPHES)
    return WHITESPACE.sub(" ", folded).strip().casefold()


def matches_any(haystack: str, needles: Sequence[str]) -> str | None:
    normalised = normalise_text(haystack)
    if not normalised:
        return None
    for needle in needles:
        candidate = normalise_text(needle)
        if candidate and candidate in normalised:
            return needle
    return None


def any_of(candidates: Sequence[str]) -> str:
    return ", ".join(candidates)


JOIN_ON_WEB: Final[tuple[str, ...]] = (
    'button[data-tid="joinOnWeb"]',
    'button[aria-label="Join meeting from this browser"]',
    'button[aria-label="Continue on this browser"]',
    'button[aria-label="Rejoindre la réunion à partir de ce navigateur"]',
    'button[aria-label="Continuer sur ce navigateur"]',
    'button:has-text("Join from browser")',
    'button:has-text("Continue on this browser")',
    'button:has-text("Rejoindre la réunion à partir de ce navigateur")',
    'button:has-text("Continuer sur ce navigateur")',
    'button:has-text("Poursuivre sur ce navigateur")',
)

PREJOIN_DISPLAY_NAME: Final[tuple[str, ...]] = (
    '[data-tid="prejoin-display-name-input"]',
    'input[placeholder="Type your name"]',
    'input[aria-label="Type your name"]',
    'input[placeholder="Tapez votre nom"]',
    'input[aria-label="Tapez votre nom"]',
    'input[placeholder="Entrez votre nom"]',
    'input[aria-label="Entrez votre nom"]',
)

PREJOIN_JOIN_BUTTON: Final[tuple[str, ...]] = (
    '[data-tid="prejoin-join-button"]',
    'button:has-text("Join now")',
    'button:has-text("Rejoindre maintenant")',
)

TOGGLE_MICROPHONE: Final[tuple[str, ...]] = (
    '[data-tid="toggle-mute"]',
    'button[aria-label="Mute microphone"]',
    'button[aria-label="Désactiver le micro"]',
    'button[aria-label="Couper le micro"]',
)

TOGGLE_CAMERA: Final[tuple[str, ...]] = (
    '[data-tid="toggle-video"]',
    'button[aria-label="Turn camera off"]',
    'button[aria-label="Désactiver la caméra"]',
)

CONTINUE_WITHOUT_MEDIA: Final[tuple[str, ...]] = (
    'button:has-text("Continue without audio or video")',
    '[role="dialog"] button:has-text("Continue without audio or video")',
    'button:has-text("Continue without audio")',
    'button:has-text("Poursuivre sans audio ni vidéo")',
    '[role="dialog"] button:has-text("Poursuivre sans audio ni vidéo")',
    'button:has-text("Continuer sans audio ni vidéo")',
)

HANGUP_BUTTON: Final[tuple[str, ...]] = (
    "button#hangup-button",
    'button[data-tid="hangup-main-btn"]',
    'button[aria-label^="Leave"]',
    'button[aria-label^="Quitter"]',
)

CHAT_MESSAGE_BOX: Final[tuple[str, ...]] = (
    '[aria-label="Type a message"]',
    '[placeholder="Type a message"]',
    '[aria-label="Écrivez un message"]',
    '[placeholder="Écrivez un message"]',
    '[aria-label="Tapez un message"]',
    '[placeholder="Tapez un message"]',
    '[data-tid="ckeditor"]',
)

CHAT_PANEL_TOGGLE: Final[tuple[str, ...]] = (
    '[data-tid="chat-button"]',
    '[data-tid="toggle-chat"]',
    'button[aria-label="Chat"]',
    'button[aria-label="Conversation"]',
)

ROSTER_PANEL_TOGGLE: Final[tuple[str, ...]] = (
    '[data-tid="roster-button"]',
    '[data-tid="toggle-roster"]',
    'button[aria-label="People"]',
    'button[aria-label="Show participants"]',
    'button[aria-label="Participants"]',
    'button[aria-label="Personnes"]',
    'button[aria-label="Afficher les participants"]',
)

ROSTER_PANEL: Final[tuple[str, ...]] = (
    '[data-tid="roster"]',
    '[data-tid="roster-list"]',
)

ROSTER_PARTICIPANT_ROW: Final[tuple[str, ...]] = (
    '[data-tid="roster-participant"]',
    '[role="treeitem"]',
)

SPEAKING_INDICATOR: Final[str] = '[data-tid="voice-level-stream-outline"]'

SPEAKING_INDICATOR_CONTAINER: Final[str] = "[data-stream-type][data-tid]"

LOBBY_TEXTS: Final[tuple[str, ...]] = (
    "Someone will let you in shortly",
    "Someone in the meeting should let you in soon",
    "Someone will let you in soon",
    "When the meeting starts, we'll let people know you're waiting",
    "Quelqu'un vous laissera bientôt entrer",
    "Quelqu'un vous fera bientôt entrer",
    "Quelqu'un devrait vous laisser entrer sous peu",
    "Vous êtes dans la salle d'attente",
)

DENIED_TEXTS: Final[tuple[str, ...]] = (
    "Sorry, but you were denied",
    "You were denied access to this meeting",
    "Your request to join was denied",
    "Désolé, mais vous avez été refusé",
    "Vous avez été refusé",
    "Votre demande de participation a été refusée",
)

REMOVED_TEXTS: Final[tuple[str, ...]] = (
    "You've been removed from this meeting",
    "You were removed from the meeting",
    "Vous avez été supprimé de cette réunion",
    "Vous avez été retiré de la réunion",
    "Vous avez été supprimé de la réunion",
)

MEETING_ENDED_TEXTS: Final[tuple[str, ...]] = (
    "Meeting ended",
    "The meeting has ended",
    "This meeting has ended",
    "Réunion terminée",
    "La réunion est terminée",
    "Cette réunion est terminée",
)

BLOCKED_TEXTS: Final[tuple[str, ...]] = (
    "Your organization's policies don't allow you to join",
    "Couldn't join the meeting",
    "We couldn't connect you",
    "Les stratégies de votre organisation ne vous permettent pas",
    "Impossible de rejoindre la réunion",
    "Nous n'avons pas pu vous connecter",
)

LIGHT_EXPERIENCE_MARKER: Final[str] = "lightExperience=false"
