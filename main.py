"""FastAPI application entry point for the meeting intelligence pipeline."""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import Settings, get_settings
from services.llm_processor import LLMProcessingError, LLMProcessor, MeetingAnalysis
from services.notifier import NotificationError, Notifier
from services.transcription import SpeakerLine, TranscriptionError, transcribe_audio

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"}


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


class ProcessMeetingResponse(BaseModel):
    """API response for a completed meeting processing run."""

    job_id: str
    transcript: str
    utterances: list[dict[str, str]]
    analysis: MeetingAnalysis
    notifications: dict[str, object] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    app_name: str
    transcription_provider: str
    notification_mode: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "Upload meeting audio to generate a diarized transcript, "
            "extract structured action items with GPT-4o, and trigger notifications."
        ),
    )

    # FIXED: CORS Middleware is now registered directly to the active application instance
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def validate_configuration() -> None:
        logger = logging.getLogger(__name__)
        try:
            settings.validate_transcription_credentials()
            settings.validate_notification_settings()
        except ValueError as exc:
            logger.error("Configuration validation failed: %s", exc)
            raise

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health_check() -> HealthResponse:
        return HealthResponse(
            status="ok",
            app_name=settings.app_name,
            transcription_provider=settings.transcription_provider,
            notification_mode=settings.notification_mode,
        )

    @app.post(
        "/process-meeting",
        response_model=ProcessMeetingResponse,
        tags=["meetings"],
        summary="Process meeting audio end-to-end",
    )
    async def process_meeting(
        audio: UploadFile = File(..., description="Meeting audio file (.mp3, .wav, etc.)"),
        current_settings: Settings = Depends(get_settings),
    ) -> ProcessMeetingResponse:
        logger = logging.getLogger(__name__)
        job_id = str(uuid.uuid4())

        if not audio.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file must include a filename.",
            )

        suffix = Path(audio.filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported audio format '{suffix}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
            )

        temp_dir = Path(tempfile.mkdtemp(prefix="meeting_pipeline_"))
        temp_audio_path = temp_dir / f"{job_id}{suffix}"

        try:
            with temp_audio_path.open("wb") as buffer:
                shutil.copyfileobj(audio.file, buffer)

            logger.info("Job %s: saved upload to %s", job_id, temp_audio_path)

            try:
                transcript, utterances = transcribe_audio(temp_audio_path, current_settings)
            except TranscriptionError as exc:
                logger.error("Job %s: transcription failed: %s", job_id, exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Transcription failed: {exc}",
                ) from exc

            llm_processor = LLMProcessor(current_settings)
            try:
                analysis = llm_processor.extract_action_items(transcript)
            except LLMProcessingError as exc:
                logger.error("Job %s: LLM extraction failed: %s", job_id, exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"LLM extraction failed: {exc}",
                ) from exc

            notifications: dict[str, object] = {}
            try:
                notifier = Notifier(current_settings)
                notifications = notifier.dispatch(analysis)
            except NotificationError as exc:
                logger.error("Job %s: notification dispatch failed: %s", job_id, exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Notification dispatch failed: {exc}",
                ) from exc

            return ProcessMeetingResponse(
                job_id=job_id,
                transcript=transcript,
                utterances=utterances,
                analysis=analysis,
                notifications=notifications,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            await audio.close()

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: object, exc: Exception) -> JSONResponse:
        logging.getLogger(__name__).exception("Unhandled server error")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An unexpected server error occurred.", "error": str(exc)},
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8005, reload=True)