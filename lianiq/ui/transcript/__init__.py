"""The paired transcript view shared by Conversation and Listen (paired-transcript spec §3.2)."""

from lianiq.ui.transcript.host import TranscriptHost
from lianiq.ui.transcript.model import PairedTranscriptModel
from lianiq.ui.transcript.view import PairedTranscriptView

__all__ = ["PairedTranscriptModel", "PairedTranscriptView", "TranscriptHost"]
