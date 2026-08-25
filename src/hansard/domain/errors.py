from __future__ import annotations


class HansardError(Exception):
    pass


class ConfigurationError(HansardError):
    pass


class CaptureError(HansardError):
    pass


class MeetingJoinRefusedError(CaptureError):
    pass


class MeetingAdmissionTimeoutError(CaptureError):
    pass


class RecognitionError(HansardError):
    pass


class DiarizationError(HansardError):
    pass


class SummarizationError(HansardError):
    pass


class DeliveryError(HansardError):
    pass


class ArtifactNotFoundError(HansardError):
    pass


class ArtifactKeyError(HansardError):
    pass


class QualityGateFailedError(HansardError):
    pass


MeetingJoinRefused = MeetingJoinRefusedError
MeetingAdmissionTimeout = MeetingAdmissionTimeoutError
ArtifactNotFound = ArtifactNotFoundError
QualityGateFailed = QualityGateFailedError
