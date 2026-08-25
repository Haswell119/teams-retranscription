import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest
from pydantic import SecretStr

from hansard.adapters.summarization.registry import build_minutes_writer
from hansard.config import MinutesSettings
from hansard.domain.meeting import MeetingRequest
from hansard.domain.speakers import Participant, Roster
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word

FRENCH_TURNS = [
    (0.0, 6.0, "Camille Dubois", "Bonjour à tous, on ouvre le comité de lancement de la version 4.2."),
    (6.5, 14.0, "Marc Lefèvre", "Le périmètre est prêt, sauf la traduction allemande qui prendra du retard."),
    (14.5, 22.0, "Camille Dubois", "On part sur un lancement le douze juin sans la traduction allemande."),
    (22.5, 30.0, "Sofia Ben Ali", "Je m'occupe du communiqué de presse pour vendredi prochain."),
    (30.5, 36.0, "Marc Lefèvre", "Qui prend en charge la communication client sur cet incident ?"),
]


def build_transcript(turns):
    utterances = []
    for start, end, speaker, text in turns:
        tokens = text.split()
        step = (end - start) / max(len(tokens), 1)
        words = tuple(
            Word(token, TimeSpan(start + index * step, start + (index + 1) * step), speaker=speaker)
            for index, token in enumerate(tokens)
        )
        utterances.append(Utterance(TimeSpan(start, end), text, speaker=speaker, words=words))
    return Transcript(utterances=tuple(utterances), language="fr", audio_duration=turns[-1][1])


class CannedCompletionHandler(BaseHTTPRequestHandler):
    payloads: ClassVar[list[str]] = []
    received: ClassVar[list[dict]] = []

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).received.append(body)
        index = min(len(type(self).received) - 1, len(type(self).payloads) - 1)
        content = type(self).payloads[index]
        response = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args):
        return


@pytest.fixture
def canned_server():
    server = HTTPServer(("127.0.0.1", 0), CannedCompletionHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def test_the_llm_path_reaches_a_real_endpoint_and_produces_minutes(canned_server):
    CannedCompletionHandler.received = []
    CannedCompletionHandler.payloads = [
        json.dumps(
            {
                "summary": "Le comité valide le lancement de la version 4.2.",
                "decisions": [
                    {
                        "statement": "Lancement le douze juin sans la traduction allemande.",
                        "quote": "On part sur un lancement le douze juin sans la traduction allemande.",
                        "speaker": "Camille Dubois",
                    }
                ],
                "actions": [
                    {
                        "description": "Rédiger le communiqué de presse.",
                        "owner": "Sofia Ben Ali",
                        "quote": "Je m'occupe du communiqué de presse pour vendredi prochain.",
                    }
                ],
                "questions": [
                    {
                        "question": "Qui prend en charge la communication client sur cet incident ?",
                        "speaker": "Marc Lefèvre",
                    }
                ],
            }
        )
    ] * 6

    host, port = canned_server.server_address
    settings = MinutesSettings(
        enabled=True,
        engine="llm",
        endpoint=f"http://{host}:{port}/v1",
        api_key=SecretStr("not-a-real-key"),
        model_id="local-model",
    )
    writer = build_minutes_writer(settings)
    transcript = build_transcript(FRENCH_TURNS)
    roster = Roster(
        participants=tuple(
            Participant(identifier=name, display_name=name)
            for name in ("Camille Dubois", "Marc Lefèvre", "Sofia Ben Ali")
        )
    )

    minutes = writer.compose(
        transcript,
        roster,
        MeetingRequest(audio_path=None, join_url="https://example", title="Comité", language="fr"),
    )

    assert CannedCompletionHandler.received, "the writer never called the endpoint"
    assert minutes.language == "fr"
    assert minutes.abstract
    assert minutes.title == "Comité"


def test_an_unreachable_endpoint_still_produces_minutes():
    settings = MinutesSettings(
        enabled=True, engine="auto", endpoint="http://127.0.0.1:9/v1", model_id="local-model"
    )
    writer = build_minutes_writer(settings)
    transcript = build_transcript(FRENCH_TURNS)

    minutes = writer.compose(
        transcript,
        Roster(),
        MeetingRequest(audio_path=None, join_url="https://example", title="Comité", language="fr"),
    )

    assert minutes.abstract
    assert minutes.decisions or minutes.actions or minutes.topics
