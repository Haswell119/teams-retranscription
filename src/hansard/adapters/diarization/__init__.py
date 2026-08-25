from hansard.adapters.diarization.registry import build_diarizer, register_diarizer
from hansard.adapters.diarization.sherpa import SherpaDiarizer

__all__ = ["SherpaDiarizer", "build_diarizer", "register_diarizer"]
