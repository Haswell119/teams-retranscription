from __future__ import annotations

from datetime import UTC, datetime

from hansard.domain.minutes import ActionItem, Citation, Decision, Minutes, OpenQuestion, Topic
from hansard.domain.speakers import UNKNOWN_SPEAKER, Participant
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word
from hansard.rendering.ports import ModelProvenance, RenderContext

MEETING_TITLE = "Weekly platform sync"
MEETING_START = datetime(2026, 6, 3, 9, 30, tzinfo=UTC)
MEETING_DURATION = 1500.0

AMARA = Participant(
    identifier="amara.okafor",
    display_name="Amara Okafor",
    email="amara.okafor@example.org",
    is_organizer=True,
)
LEA = Participant(identifier="lea.fontaine", display_name="Léa Fontaine", email="lea.fontaine@example.org")
JONAS = Participant(
    identifier="jonas.weber",
    display_name="Jonas Weber",
    email="jonas.weber@partner.example",
    is_external=True,
)

PROVENANCE = (
    ModelProvenance(component="asr", engine="parakeet", model_id="nemo-parakeet-tdt-0.6b-v3"),
    ModelProvenance(component="diarization", engine="sortformer", model_id="diar_streaming_sortformer_4spk"),
    ModelProvenance(component="minutes", engine="qwen3", model_id="qwen3-8b-instruct"),
)


def _words(text: str, span: TimeSpan, speaker: str) -> tuple[Word, ...]:
    tokens = text.split()
    step = span.duration / len(tokens)
    return tuple(
        Word(
            text=token,
            span=TimeSpan(span.start + index * step, span.start + (index + 1) * step),
            confidence=0.95,
            speaker=speaker,
        )
        for index, token in enumerate(tokens)
    )


def sample_context(language: str = "en", timezone: str = "UTC") -> RenderContext:
    return RenderContext(
        title=MEETING_TITLE,
        started_at=MEETING_START,
        duration_seconds=MEETING_DURATION,
        participants=(AMARA, LEA, JONAS),
        language=language,
        timezone=timezone,
        provenance=PROVENANCE,
    )


def sample_transcript() -> Transcript:
    opening = "Good morning everyone, let us start with the release four point two readiness."
    opening_span = TimeSpan(8.0, 14.6)
    utterances = (
        Utterance(
            span=opening_span,
            text=opening,
            speaker=AMARA.display_name,
            language="en",
            confidence=0.94,
            words=_words(opening, opening_span, AMARA.display_name),
        ),
        Utterance(
            span=TimeSpan(15.2, 24.9),
            text=(
                "The build is green on every runner, but the German locale files still have "
                "forty seven untranslated strings and nobody has proof-read them yet."
            ),
            speaker=LEA.display_name,
            language="en",
            confidence=0.91,
        ),
        Utterance(
            span=TimeSpan(25.4, 29.1),
            text="Sorry, could you repeat the last figure?",
            speaker=UNKNOWN_SPEAKER,
            language="en",
            confidence=0.62,
        ),
        Utterance(
            span=TimeSpan(29.6, 33.0),
            text="Forty seven strings, all of them in the billing screens.",
            speaker=LEA.display_name,
            language="en",
            confidence=0.93,
        ),
        Utterance(
            span=TimeSpan(33.4, 34.2),
            text="Understood.",
            speaker=AMARA.display_name,
            language="en",
            confidence=0.96,
        ),
        Utterance(
            span=TimeSpan(370.5, 379.8),
            text=(
                "Then we ship four point two on the twelfth of June with the German locale "
                "disabled, and we open a follow-up ticket for the translations."
            ),
            speaker=AMARA.display_name,
            language="en",
            confidence=0.95,
        ),
        Utterance(
            span=TimeSpan(640.0, 651.5),
            text=(
                "On the incident of last Tuesday: the pager fired at two in the morning, the "
                "responder had already worked a full week, and the hand-over notes were missing."
            ),
            speaker=JONAS.display_name,
            language="en",
            confidence=0.89,
        ),
        Utterance(
            span=TimeSpan(812.0, 818.4),
            text="Agreed, we move the rotation to a two-week cycle starting in July.",
            speaker=AMARA.display_name,
            language="en",
            confidence=0.94,
        ),
        Utterance(
            span=TimeSpan(1180.0, 1189.2),
            text=(
                "For the transcription cluster we need two more GPU nodes to keep the queue "
                "under ten minutes at peak."
            ),
            speaker=LEA.display_name,
            language="en",
            confidence=0.92,
        ),
        Utterance(
            span=TimeSpan(1425.0, 1431.8),
            text="Approved. Please draft the procurement request before the board meeting.",
            speaker=AMARA.display_name,
            language="en",
            confidence=0.95,
        ),
    )
    return Transcript(utterances=utterances, language="en", audio_duration=MEETING_DURATION)


def sample_minutes() -> Minutes:
    return Minutes(
        title=MEETING_TITLE,
        abstract=(
            "The team confirmed that release 4.2 is ready apart from the German locale, agreed a "
            "two-week on-call rotation after last Tuesday's night incident, and approved two "
            "additional GPU nodes for the sovereign transcription cluster."
        ),
        language="en",
        generated_at=datetime(2026, 6, 3, 10, 2, tzinfo=UTC),
        participants=(AMARA, LEA, JONAS),
        topics=(
            Topic(
                title="Release 4.2 readiness",
                span=TimeSpan(0.0, 420.0),
                summary=(
                    "Every runner is green and the only blocker is the German locale, where 47 "
                    "billing strings are still untranslated and unreviewed."
                ),
                key_points=(
                    "Build and integration suites pass on all runners.",
                    "47 untranslated strings remain, all in the billing screens.",
                    "The release window on 12 June cannot be moved.",
                ),
            ),
            Topic(
                title="On-call rotation and incident review",
                span=TimeSpan(420.0, 1020.0),
                summary=(
                    "Last Tuesday's night incident showed that the weekly rotation concentrates "
                    "fatigue and that hand-over notes are not written down."
                ),
                key_points=(
                    "The pager fired at 02:00 for a responder at the end of a full week.",
                    "Hand-over notes were missing entirely.",
                ),
            ),
            Topic(
                title="Transcription cluster capacity",
                span=TimeSpan(1020.0, 1500.0),
                summary=(
                    "Peak queue time exceeds ten minutes; two additional GPU nodes bring it back "
                    "within the service target without leaving the data centre."
                ),
                key_points=("Queue time at peak is above the ten-minute target.",),
            ),
        ),
        decisions=(
            Decision(
                statement="Release 4.2 ships on 12 June with the German locale disabled.",
                rationale=(
                    "The billing strings are neither translated nor proof-read, "
                    "and the release window is fixed."
                ),
                citations=(
                    Citation(
                        span=TimeSpan(370.5, 379.8),
                        speaker=AMARA.display_name,
                        quote=(
                            "Then we ship four point two on the twelfth of June "
                            "with the German locale disabled."
                        ),
                    ),
                ),
            ),
            Decision(
                statement="The on-call rotation moves to a two-week cycle from July.",
                rationale="A weekly cycle concentrates night work on a single responder.",
                citations=(
                    Citation(
                        span=TimeSpan(812.0, 818.4),
                        speaker=AMARA.display_name,
                        quote="We move the rotation to a two-week cycle starting in July.",
                    ),
                ),
            ),
            Decision(
                statement="Two additional GPU nodes are approved for the transcription cluster.",
                rationale=None,
                citations=(
                    Citation(
                        span=TimeSpan(1425.0, 1431.8),
                        speaker=AMARA.display_name,
                        quote="Approved. Please draft the procurement request before the board meeting.",
                    ),
                ),
            ),
        ),
        actions=(
            ActionItem(
                description=(
                    "Disable the German locale in the 4.2 release branch and open a translation ticket."
                ),
                owner=LEA.display_name,
                due_date="2026-06-10",
                citations=(
                    Citation(
                        span=TimeSpan(379.8, 384.0),
                        speaker=LEA.display_name,
                        quote="I will disable the locale in the release branch today.",
                    ),
                ),
            ),
            ActionItem(
                description="Circulate the incident review notes and the new hand-over template.",
                owner=JONAS.display_name,
                due_date="2026-06-05",
                citations=(
                    Citation(
                        span=TimeSpan(651.5, 658.0),
                        speaker=JONAS.display_name,
                        quote="I will write the review up and share the template.",
                    ),
                ),
            ),
            ActionItem(
                description="Draft the procurement request for the two GPU nodes.",
                owner=None,
                due_date=None,
            ),
            ActionItem(
                description="Compare on-premises | cloud costs for the cluster before the board meeting.",
                owner=AMARA.display_name,
                due_date="2026-06-18",
            ),
        ),
        open_questions=(
            OpenQuestion(
                question="Do we need a second reviewer for the German locale before the next release?",
                raised_by=LEA.display_name,
                citations=(
                    Citation(
                        span=TimeSpan(455.0, 460.2),
                        speaker=LEA.display_name,
                        quote="Should a second reviewer sign off the locale?",
                    ),
                ),
            ),
            OpenQuestion(
                question="Who owns the monthly cost report once the cluster is live?",
                raised_by=None,
            ),
        ),
        speaking_time=(
            (AMARA.display_name, 612.5),
            (LEA.display_name, 498.2),
            (JONAS.display_name, 310.4),
            (UNKNOWN_SPEAKER, 78.9),
        ),
    )


def french_context() -> RenderContext:
    return RenderContext(
        title="Comité de pilotage plateforme",
        started_at=datetime(2026, 6, 3, 9, 30, tzinfo=UTC),
        duration_seconds=1500.0,
        participants=(AMARA, LEA, JONAS),
        language="fr",
        timezone="UTC",
        provenance=PROVENANCE,
    )


def french_transcript() -> Transcript:
    return Transcript(
        utterances=(
            Utterance(
                span=TimeSpan(6.0, 12.4),
                text="Bonjour à tous, commençons par l'état de préparation de la version 4.2.",
                speaker=AMARA.display_name,
                language="fr",
                confidence=0.94,
            ),
            Utterance(
                span=TimeSpan(13.0, 22.6),
                text=(
                    "La compilation est verte partout, mais il reste quarante-sept chaînes non "
                    "traduites dans les écrans de facturation en allemand."
                ),
                speaker=LEA.display_name,
                language="fr",
                confidence=0.9,
            ),
            Utterance(
                span=TimeSpan(23.1, 29.8),
                text="Nous livrons donc le 12 juin en désactivant la locale allemande.",
                speaker=AMARA.display_name,
                language="fr",
                confidence=0.95,
            ),
        ),
        language="fr",
        audio_duration=1500.0,
    )


def french_minutes() -> Minutes:
    return Minutes(
        title="Comité de pilotage plateforme",
        abstract=(
            "L'équipe confirme la livraison de la version 4.2 sans la locale allemande, adopte une "
            "astreinte de deux semaines et valide deux nœuds GPU supplémentaires pour le cluster "
            "de transcription souverain."
        ),
        language="fr",
        generated_at=datetime(2026, 6, 3, 10, 2, tzinfo=UTC),
        participants=(AMARA, LEA, JONAS),
        topics=(
            Topic(
                title="Préparation de la version 4.2",
                span=TimeSpan(0.0, 420.0),
                summary=(
                    "Seule la locale allemande bloque la livraison : quarante-sept chaînes de "
                    "facturation restent à traduire et à relire."
                ),
                key_points=(
                    "Les suites d'intégration passent sur tous les exécuteurs.",
                    "La fenêtre de livraison du 12 juin est inamovible.",
                ),
            ),
            Topic(
                title="Astreinte et retour d'incident",
                span=TimeSpan(420.0, 1500.0),
                summary=(
                    "L'incident de nuit a montré que le rythme hebdomadaire concentre la fatigue "
                    "et que les notes de passation ne sont pas rédigées."
                ),
                key_points=("Aucune note de passation n'était disponible.",),
            ),
        ),
        decisions=(
            Decision(
                statement="La version 4.2 est livrée le 12 juin sans la locale allemande.",
                rationale="Les chaînes de facturation ne sont ni traduites ni relues.",
                citations=(
                    Citation(
                        span=TimeSpan(23.1, 29.8),
                        speaker=AMARA.display_name,
                        quote="Nous livrons donc le 12 juin en désactivant la locale allemande.",
                    ),
                ),
            ),
        ),
        actions=(
            ActionItem(
                description="Désactiver la locale allemande et ouvrir un ticket de traduction.",
                owner=LEA.display_name,
                due_date="2026-06-10",
                citations=(
                    Citation(
                        span=TimeSpan(29.8, 34.0),
                        speaker=LEA.display_name,
                        quote="Je désactive la locale dans la branche de livraison.",
                    ),
                ),
            ),
            ActionItem(
                description="Rédiger la demande d'achat des deux nœuds GPU.",
                owner=None,
                due_date=None,
            ),
        ),
        open_questions=(
            OpenQuestion(
                question="Faut-il un second relecteur pour la locale allemande ?",
                raised_by=LEA.display_name,
            ),
        ),
        speaking_time=((AMARA.display_name, 612.5), (LEA.display_name, 498.2), (JONAS.display_name, 310.4)),
    )
