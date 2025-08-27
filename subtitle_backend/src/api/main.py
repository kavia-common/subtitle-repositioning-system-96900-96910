from typing import List, Optional, Tuple
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
import io

from src.core.reposition import reposition_subtitles_for_video


app = FastAPI(
    title="Subtitle Repositioning API",
    description=(
        "Backend service for detecting burnt-in text in videos and repositioning "
        "subtitle cues to avoid overlap. Upload a video and an SRT/VTT subtitle "
        "file and receive a repositioned subtitle file."
    ),
    version="0.1.0",
    openapi_tags=[
        {"name": "health", "description": "Health and status endpoints"},
        {"name": "reposition", "description": "Subtitle repositioning operations"},
        {"name": "docs", "description": "Documentation and usage"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Frontend integration; tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["health"], summary="Health Check", description="Simple health check endpoint.")
def health_check():
    """
    Health check endpoint to verify the service is running.

    Returns:
        JSON with a simple message indicating service health.
    """
    return {"message": "Healthy"}


class Cue(BaseModel):
    start: float = Field(..., description="Cue start time in seconds")
    end: float = Field(..., description="Cue end time in seconds")
    text: str = Field(..., description="Cue text content")


class RepositionedCue(Cue):
    position: str = Field(..., description="Suggested position, e.g., 'top' or 'bottom'")


class RepositionResponse(BaseModel):
    cues: List[RepositionedCue] = Field(..., description="List of repositioned cues")
    format: str = Field(..., description="Subtitle output format (e.g., srt)")
    note: Optional[str] = Field(None, description="Additional info about the processing")


def _parse_srt_to_cues(srt_bytes: bytes) -> List[Tuple[float, float, str]]:
    """
    Parse basic SRT content into a list of (start, end, text) tuples.

    This minimal parser handles common SRTs. For edge-cases, consider using
    a library like 'pysrt'. Here we avoid adding new dependencies.
    """
    text = srt_bytes.decode("utf-8", errors="replace")
    lines = [ln.strip("﻿") for ln in text.splitlines()]
    blocks: List[List[str]] = []
    current: List[str] = []

    def flush():
        nonlocal current
        if current:
            blocks.append(current)
            current = []

    for ln in lines:
        if ln.strip() == "":
            flush()
        else:
            current.append(ln)
    flush()

    cues: List[Tuple[float, float, str]] = []
    for block in blocks:
        if not block:
            continue
        # Typical block:
        # 1
        # 00:00:01,000 --> 00:00:04,000
        # Hello world
        # (possibly multiple text lines)
        idx = 0
        if block[0].isdigit():
            idx = 1
        if idx >= len(block):
            continue
        timing = block[idx]
        if "-->" not in timing:
            # Try next line
            idx += 1
            if idx >= len(block) or "-->" not in block[idx]:
                continue
            timing = block[idx]
        try:
            left, right = [p.strip() for p in timing.split("-->")]
            start = _hhmmss_to_seconds(left)
            end = _hhmmss_to_seconds(right)
        except Exception:
            continue
        text_lines = block[idx + 1 :]
        text_joined = "\n".join(text_lines).strip()
        if text_joined:
            cues.append((start, end, text_joined))
    return cues


def _seconds_to_srt_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def _hhmmss_to_seconds(ts: str) -> float:
    # Supports "HH:MM:SS,mmm" or "H:MM:SS.mmm"
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    if len(parts) != 3:
        raise ValueError("Invalid timestamp")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def _serialize_cues_to_srt(cues: List[Tuple[float, float, str]]) -> str:
    out_lines: List[str] = []
    for i, (start, end, text) in enumerate(cues, start=1):
        out_lines.append(str(i))
        out_lines.append(f"{_seconds_to_srt_timestamp(start)} --> {_seconds_to_srt_timestamp(end)}")
        out_lines.extend(text.split("\n"))
        out_lines.append("")  # blank line
    return "\n".join(out_lines)


@app.post(
    "/reposition/subtitles",
    tags=["reposition"],
    summary="Upload video and SRT to get repositioned subtitles as JSON",
    description=(
        "Accepts a video file and an SRT subtitle file and returns repositioned cues "
        "as JSON. Use this for UI previews and debugging."
    ),
    response_model=RepositionResponse,
    responses={
        200: {"description": "Repositioned cues successfully computed"},
        400: {"description": "Invalid inputs"},
        500: {"description": "Processing error"},
    },
)
async def reposition_subtitles_json(
    video: UploadFile = File(..., description="Video file"),
    subtitles_file: UploadFile = File(..., description="SRT subtitle file"),
):
    """
    PUBLIC_INTERFACE
    Endpoint to compute repositioned subtitles and return JSON.

    Parameters:
        - video: Binary upload of the video file.
        - subtitles_file: SRT subtitle file.

    Returns:
        A JSON object containing repositioned cues with suggested positions.
    """
    if not subtitles_file.filename.lower().endswith(".srt"):
        raise HTTPException(status_code=400, detail="Only .srt files are supported in this endpoint.")

    # Read inputs; video content is not required by the placeholder algorithm
    await video.read()
    srt_content = await subtitles_file.read()

    # Persisting files is not necessary for the stub. We pass a marker path.
    video_path = f"/tmp/{video.filename or 'uploaded_video'}"

    cues = _parse_srt_to_cues(srt_content)
    if not cues:
        raise HTTPException(status_code=400, detail="Failed to parse SRT or no cues found.")

    repositioned = reposition_subtitles_for_video(video_path, cues)
    resp = RepositionResponse(
        cues=[RepositionedCue(start=s, end=e, text=t, position=p) for (s, e, t, p) in repositioned],
        format="srt",
        note="Positions are suggested; timing unchanged. Placeholder logic.",
    )
    return JSONResponse(resp.model_dump())


@app.post(
    "/reposition/subtitles/download",
    tags=["reposition"],
    summary="Upload video and SRT to get a downloadable repositioned SRT",
    description=(
        "Accepts a video and an SRT subtitle file and returns a generated SRT file. "
        "Currently embeds position hints as bracketed notes on text lines (e.g., '[pos: top]') "
        "for quick preview. Replace with style tags or SSA/ASS as needed."
    ),
    responses={
        200: {"description": "Returns an SRT file", "content": {"application/x-subrip": {}}},
        400: {"description": "Invalid inputs"},
        500: {"description": "Processing error"},
    },
)
async def reposition_subtitles_download(
    video: UploadFile = File(..., description="Video file"),
    subtitles_file: UploadFile = File(..., description="SRT subtitle file"),
    include_position_hint: bool = Form(True, description="If true, annotate text with '[pos: ...]'"),
):
    """
    PUBLIC_INTERFACE
    Endpoint to compute repositioned subtitles and return an SRT file stream.

    Returns:
        StreamingResponse with Content-Disposition for download.
    """
    if not subtitles_file.filename.lower().endswith(".srt"):
        raise HTTPException(status_code=400, detail="Only .srt files are supported in this endpoint.")

    # Read inputs; video content is not required by the placeholder algorithm
    await video.read()
    srt_content = await subtitles_file.read()
    video_path = f"/tmp/{video.filename or 'uploaded_video'}"

    cues = _parse_srt_to_cues(srt_content)
    if not cues:
        raise HTTPException(status_code=400, detail="Failed to parse SRT or no cues found.")

    repositioned = reposition_subtitles_for_video(video_path, cues)

    # For SRT output, we embed the position hint as a simple annotation for now.
    out_cues: List[Tuple[float, float, str]] = []
    for (s, e, t, p) in repositioned:
        annotated = f"{t} [pos: {p}]" if include_position_hint else t
        out_cues.append((s, e, annotated))

    srt_text = _serialize_cues_to_srt(out_cues)
    buf = io.BytesIO(srt_text.encode("utf-8"))

    headers = {"Content-Disposition": f'attachment; filename="repositioned_{subtitles_file.filename or "subtitles.srt"}"'}
    return StreamingResponse(buf, media_type="application/x-subrip", headers=headers)


@app.get(
    "/docs/usage",
    tags=["docs"],
    summary="API usage note",
    description="High-level notes on using the WebSocket (if added later) and REST endpoints.",
)
def docs_usage():
    """
    PUBLIC_INTERFACE
    Documentation helper endpoint.

    Details:
        - Use POST /reposition/subtitles for JSON results.
        - Use POST /reposition/subtitles/download to receive an SRT file.
        - Future: WebSocket endpoints for progress updates during heavier processing.
    """
    return {"message": "Use POST /reposition/subtitles (JSON) or /reposition/subtitles/download (SRT). WebSocket TBD."}
