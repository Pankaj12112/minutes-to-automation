"""Audio transcription with speaker diarization via AssemblyAI or Deepgram."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from config import Settings

logger = logging.getLogger(__name__)

SpeakerLine = dict[str, str]


class TranscriptionError(Exception):
    """Raised when transcription fails."""


class BaseTranscriptionService(ABC):
    """Abstract transcription service with speaker diarization support."""

    @abstractmethod
    def transcribe(self, audio_path: Path) -> tuple[str, list[SpeakerLine]]:
        """
        Transcribe an audio file with speaker diarization enabled.

        Returns:
            A tuple of (formatted_transcript, structured_utterances).
        """


class AssemblyAITranscriptionService(BaseTranscriptionService):
    """AssemblyAI transcription with speaker_labels enabled."""

    def __init__(self, api_key: str) -> None:
        import assemblyai as aai

        aai.settings.api_key = api_key
        self._aai = aai

    def transcribe(self, audio_path: Path) -> tuple[str, list[SpeakerLine]]:
        logger.info("Starting AssemblyAI transcription for %s", audio_path.name)

        try:
            config = self._aai.TranscriptionConfig(
                speaker_labels=True,
                speech_model=self._aai.SpeechModel.best,
            )
            transcriber = self._aai.Transcriber()
            transcript = transcriber.transcribe(str(audio_path), config=config)
        except Exception as exc:
            logger.exception("AssemblyAI network/API call failed")
            raise TranscriptionError(f"AssemblyAI transcription failed: {exc}") from exc

        if transcript.status == self._aai.TranscriptStatus.error:
            message = transcript.error or "Unknown AssemblyAI error"
            logger.error("AssemblyAI returned error status: %s", message)
            raise TranscriptionError(f"AssemblyAI transcription error: {message}")

        utterances: list[SpeakerLine] = []
        lines: list[str] = []

        if transcript.utterances:
            for utterance in transcript.utterances:
                speaker = f"Speaker {utterance.speaker}"
                text = utterance.text.strip()
                utterances.append({"speaker": speaker, "text": text})
                lines.append(f"{speaker}: {text}")
        elif transcript.text:
            fallback_text = transcript.text.strip()
            utterances.append({"speaker": "Speaker Unknown", "text": fallback_text})
            lines.append(f"Speaker Unknown: {fallback_text}")
        else:
            raise TranscriptionError("AssemblyAI returned an empty transcript")

        formatted = "\n".join(lines)
        logger.info("AssemblyAI transcription completed (%d utterances)", len(utterances))
        return formatted, utterances


class DeepgramTranscriptionService(BaseTranscriptionService):
    """Deepgram prerecorded transcription with diarization enabled."""

    def __init__(self, api_key: str) -> None:
        from deepgram import DeepgramClient

        self._client = DeepgramClient(api_key=api_key)

    def transcribe(self, audio_path: Path) -> tuple[str, list[SpeakerLine]]:
        logger.info("Starting Deepgram transcription for %s", audio_path.name)

        try:
            # READ INTO RAW BYTES: The SDK requires literal binary data matching the target format
            with open(audio_path, "rb") as audio_file:
                audio_data = audio_file.read()

            options = {
                "model": "nova-2",
                "smart_format": True,
                "diarize": True,
                "punctuate": True,
                "utterances": True,
            }

            # RESOLVED FINAL FIX: Passing raw bytes to request directly to comply with modern types
            response = self._client.listen.v1.media.transcribe_file(
                request=audio_data,
                **options
            )
                
        except Exception as exc:
            logger.exception("Deepgram network/API call failed")
            raise TranscriptionError(f"Deepgram transcription failed: {exc}") from exc

        # Safe parsing fallback layer (handles dict and schema models seamlessly across versions)
        try:
            if isinstance(response, dict):
                results = response.get("results", {})
                channels = results.get("channels", [{}])
                alternative = channels[0].get("alternatives", [{}])[0]
                utterance_source = results.get("utterances", [])
                word_source = alternative.get("words", [])
                fallback_transcript = alternative.get("transcript", "")
            else:
                results = getattr(response, "results", None)
                channel = results.channels[0]
                alternative = channel.alternatives[0]
                utterance_source = getattr(results, "utterances", [])
                word_source = getattr(alternative, "words", [])
                fallback_transcript = getattr(alternative, "transcript", "")
        except (AttributeError, IndexError, TypeError) as exc:
            logger.exception("Unexpected structural access mismatch during token parsing")
            raise TranscriptionError("Deepgram parsing structural validation failed") from exc

        utterances: list[SpeakerLine] = []
        lines: list[str] = []

        if utterance_source:
            for utterance in utterance_source:
                if isinstance(utterance, dict):
                    speaker_id = utterance.get("speaker")
                    text = utterance.get("transcript", "").strip()
                else:
                    speaker_id = getattr(utterance, "speaker", None)
                    text = utterance.transcript.strip()
                
                speaker = f"Speaker {speaker_id}" if speaker_id is not None else "Speaker Unknown"
                utterances.append({"speaker": speaker, "text": text})
                lines.append(f"{speaker}: {text}")
                
        elif word_source:
            current_speaker: str | None = None
            current_words: list[str] = []

            for word in word_source:
                if isinstance(word, dict):
                    speaker_id = word.get("speaker")
                    word_text = word.get("word", "")
                else:
                    speaker_id = getattr(word, "speaker", None)
                    word_text = getattr(word, "word", "")
                    
                speaker = f"Speaker {speaker_id}" if speaker_id is not None else "Speaker Unknown"

                if current_speaker is None:
                    current_speaker = speaker

                if speaker != current_speaker and current_words:
                    text = " ".join(current_words).strip()
                    utterances.append({"speaker": current_speaker, "text": text})
                    lines.append(f"{current_speaker}: {text}")
                    current_words = []
                    current_speaker = speaker

                current_words.append(word_text)

            if current_words and current_speaker:
                text = " ".join(current_words).strip()
                utterances.append({"speaker": current_speaker, "text": text})
                lines.append(f"{current_speaker}: {text}")
                
        elif fallback_transcript:
            fallback_text = fallback_transcript.strip()
            utterances.append({"speaker": "Speaker Unknown", "text": fallback_text})
            lines.append(f"Speaker Unknown: {fallback_text}")
        else:
            raise TranscriptionError("Deepgram returned an empty transcript payload")

        formatted = "\n".join(lines)
        logger.info("Deepgram transcription completed (%d utterances)", len(utterances))
        return formatted, utterances


def get_transcription_service(settings: Settings) -> BaseTranscriptionService:
    """Factory for the configured transcription provider."""
    settings.validate_transcription_credentials()

    if settings.transcription_provider == "assemblyai":
        return AssemblyAITranscriptionService(api_key=settings.assemblyai_api_key)  # type: ignore[arg-type]
    return DeepgramTranscriptionService(api_key=settings.deepgram_api_key)  # type: ignore[arg-type]


def transcribe_audio(
    audio_path: Path,
    settings: Settings,
) -> tuple[str, list[SpeakerLine]]:
    """Convenience wrapper that selects and runs the configured transcription service."""
    service = get_transcription_service(settings)
    return service.transcribe(audio_path)