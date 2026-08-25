from __future__ import annotations


class HansardError(Exception):
    pass


class ConfigurationError(HansardError):
    pass


class CaptureError(HansardError):
    pass


class MeetingJoinRefused(CaptureError):
    pass


class MeetingAdmissionTimeout(CaptureError):
    pass


class RecognitionError(HansardError):
    pass


class DiarizationError(HansardError):
    pass


class SummarizationError(HansardError):
    pass


class DeliveryError(HansardError):
    pass


class ArtifactNotFound(HansardError):
    pass


class QualityGateFailed(HansardError):
    pass
