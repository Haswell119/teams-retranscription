from __future__ import annotations

import json
import logging

import pytest
from pydantic import SecretStr

from hansard.config import RuntimeSettings
from hansard.observability.logging import (
    REDACTED,
    configure_logging,
    content_elider,
    get_logger,
    is_secret_name,
    log_level_number,
    redact_secrets,
    stage_span,
)


def redacted(**fields):
    return redact_secrets(None, "info", dict(fields))


def elided(preview=0, **fields):
    return content_elider(preview)(None, "info", dict(fields))


def emitted(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


@pytest.mark.parametrize(
    "name",
    [
        "password",
        "passphrase",
        "smtp_password",
        "client_secret",
        "secret_key",
        "api_key",
        "access_key",
        "token",
        "access_token",
        "authorization",
        "authorisation",
        "cookie",
        "bearer",
        "signature",
        "credentials",
        "key",
        "keys",
    ],
)
def test_secret_field_names_are_recognised(name):
    assert is_secret_name(name)


@pytest.mark.parametrize("name", ["meeting", "stage", "artifact", "monkey", "keyword", "duration"])
def test_ordinary_field_names_are_left_alone(name):
    assert not is_secret_name(name)


def test_secret_str_values_are_replaced_wherever_they_appear():
    event = redacted(
        endpoint="https://llm.internal",
        credential=SecretStr("hunter2"),
        smtp={"host": "smtp.internal", "password": SecretStr("hunter2")},
        chain=[SecretStr("one"), "two"],
    )
    assert event["endpoint"] == "https://llm.internal"
    assert event["credential"] == REDACTED
    assert event["smtp"] == {"host": "smtp.internal", "password": REDACTED}
    assert event["chain"] == [REDACTED, "two"]


def test_secret_named_fields_are_replaced_even_when_they_are_plain_strings():
    event = redacted(api_key="AKIAIOSFODNN7EXAMPLE", bucket="hansard")
    assert event["api_key"] == REDACTED
    assert event["bucket"] == "hansard"


def test_meeting_content_is_dropped_by_default():
    event = elided(text="Bonjour à tous", transcript="x" * 100, body="b", quote="q", stage="minutes")
    assert event["text"] == "<elided 14 characters>"
    assert event["transcript"] == "<elided 100 characters>"
    assert event["body"] == "<elided 1 characters>"
    assert event["quote"] == "<elided 1 characters>"
    assert event["stage"] == "minutes"


def test_meeting_content_can_be_truncated_to_a_short_prefix():
    event = elided(preview=8, text="Bonjour à toutes et à tous")
    assert event["text"].startswith("Bonjour ")
    assert "26 characters" in event["text"]


def test_levels_are_resolved_by_name():
    assert log_level_number("debug") == logging.DEBUG
    assert log_level_number(" WARNING ") == logging.WARNING
    assert log_level_number("nonsense") == logging.INFO


def test_a_real_json_log_line_is_redacted_and_free_of_content(capsys):
    configure_logging(RuntimeSettings(log_format="json", log_level="INFO"))
    get_logger("hansard.test").info(
        "delivery.attempted",
        meeting="9f2c",
        channel="email",
        smtp_password=SecretStr("hunter2"),
        body="Relevé de décisions du comité",
        duration_seconds=0.42,
    )
    record = emitted(capsys)[0]
    assert record["event"] == "delivery.attempted"
    assert record["level"] == "info"
    assert record["logger"] == "hansard.test"
    assert record["meeting"] == "9f2c"
    assert record["smtp_password"] == REDACTED
    assert record["body"] == "<elided 29 characters>"
    assert "hunter2" not in json.dumps(record)
    assert "décisions" not in json.dumps(record)
    assert record["timestamp"].endswith("Z")


def test_the_console_format_stays_human_readable(capsys):
    configure_logging(RuntimeSettings(log_format="console", log_level="INFO"))
    get_logger("hansard.test").info("stage.completed", stage="recognise", duration_seconds=1.5)
    output = capsys.readouterr().out
    assert "stage.completed" in output
    assert "stage=recognise" in output


def test_the_configured_level_filters_quieter_events(capsys):
    configure_logging(RuntimeSettings(log_format="json", log_level="WARNING"))
    logger = get_logger("hansard.test")
    logger.info("ignored")
    logger.warning("kept")
    assert [record["event"] for record in emitted(capsys)] == ["kept"]


def test_third_party_logging_is_captured_in_the_same_format(capsys):
    configure_logging(RuntimeSettings(log_format="json", log_level="INFO"))
    logging.getLogger("botocore.credentials").warning("found credentials in %s", "environment")
    record = emitted(capsys)[0]
    assert record["event"] == "found credentials in environment"
    assert record["logger"] == "botocore.credentials"


def test_stage_spans_report_durations_and_measurements(capsys):
    configure_logging(RuntimeSettings(log_format="json", log_level="INFO"))
    logger = get_logger("hansard.test")
    with stage_span(logger, "recognise", meeting="9f2c") as measured:
        measured["words"] = 128.0
    record = emitted(capsys)[0]
    assert record["event"] == "stage.completed"
    assert record["stage"] == "recognise"
    assert record["meeting"] == "9f2c"
    assert record["words"] == 128.0
    assert record["duration_seconds"] >= 0.0


def test_a_failing_stage_is_reported_by_type_and_reraised(capsys):
    configure_logging(RuntimeSettings(log_format="json", log_level="INFO"))
    with pytest.raises(ValueError), stage_span(get_logger("hansard.test"), "diarise"):
        raise ValueError("boom")
    record = emitted(capsys)[0]
    assert record["event"] == "stage.failed"
    assert record["error"] == "ValueError"
    assert "boom" not in json.dumps(record)


def test_library_code_stays_silent_until_logging_is_configured(capsys):
    logging.getLogger().handlers = []
    get_logger("hansard.test").info("stage.completed", stage="enhance")
    assert capsys.readouterr().out == ""
