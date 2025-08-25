from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional
import os
import shutil
import tempfile

from src.api.reposition_core import process_subtitle

openapi_tags = [
    {"name": "Health", "description": "Service health and metadata endpoints"},
    {"name": "Subtitle Reposition", "description": "Upload video + subtitles to reposition against burnt-in text"},
]

app = FastAPI(
    title="Subtitle Repositioning API",
    description=(
        "API to detect burnt-in text regions in videos and reposition subtitle tracks to avoid overlap.\n\n"
        "Usage notes:\n"
        "- Upload a video and a subtitle file (.srt, .ass, .ssa, .vtt) via multipart/form-data.\n"
        "- The service analyzes likely regions of burnt-in text and moves subtitles to the side with fewer conflicts.\n"
        "- Returns the processed subtitle file for download in the same format."
    ),
    version="1.0.0",
    openapi_tags=openapi_tags,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# PUBLIC_INTERFACE
@app.get("/", tags=["Health"], summary="Health Check")
def health_check():
    """Health check endpoint."""
    return {"message": "Healthy"}

class UploadResponse(BaseModel):
    """Response containing details about the processed subtitle result."""
    filename: str = Field(..., description="Suggested filename for the processed subtitle download")
    note: Optional[str] = Field(None, description="Additional information about processing")

# PUBLIC_INTERFACE
@app.post(
    "/reposition",
    tags=["Subtitle Reposition"],
    summary="Reposition subtitles to avoid burnt-in text",
    description=(
        "Accepts a video file and a subtitle file (.srt, .ass, .ssa, .vtt). "
        "Runs the repositioning logic (as defined in reposition_subtitles7.py) and returns the processed subtitle.\n\n"
        "Form fields:\n"
        "- video: binary video file\n"
        "- subtitle: subtitle file in one of the supported formats\n"
        "\nResponse: Returns the processed subtitle as file download."
    ),
    responses={
        200: {
            "content": {"application/octet-stream": {}},
            "description": "Processed subtitle file",
        },
        400: {"description": "Invalid input"},
        500: {"description": "Processing error"},
    },
)
async def reposition_subtitles(
    video: UploadFile = File(..., description="Video file for detecting burnt-in text regions"),
    subtitle: UploadFile = File(..., description="Subtitle file (.srt, .ass, .ssa, .vtt) to reposition"),
):
    """
    PUBLIC_INTERFACE
    Endpoint to reposition subtitles based on burnt-in text detection.

    Parameters:
      - video: UploadFile - the input video file
      - subtitle: UploadFile - subtitle file (.srt, .ass, .ssa, .vtt)

    Returns:
      - FileResponse: processed subtitle file for download, with the same extension as the input subtitle.
    """
    # Validate subtitle extension
    _, sub_ext = os.path.splitext(subtitle.filename or "")
    if sub_ext.lower() not in [".srt", ".ass", ".ssa", ".vtt"]:
        raise HTTPException(status_code=400, detail="Unsupported subtitle format. Use .srt, .ass, .ssa, or .vtt")

    # Save uploads to temp files
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(video.filename or '')[1] or ".mp4") as vtmp:
            video_tmp_path = vtmp.name
            await video.seek(0)
            shutil.copyfileobj(video.file, vtmp)

        with tempfile.NamedTemporaryFile(delete=False, suffix=sub_ext) as stmp:
            subtitle_tmp_path = stmp.name
            await subtitle.seek(0)
            shutil.copyfileobj(subtitle.file, stmp)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded files: {e}")

    # Process
    try:
        out_path = process_subtitle(video_tmp_path, subtitle_tmp_path)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")

    # Build download filename
    base, ext = os.path.splitext(subtitle.filename or "subtitle")
    download_name = f"{base}.repositioned{ext}"

    # Return file for download
    return FileResponse(
        path=out_path,
        filename=download_name,
        media_type="application/octet-stream",
    )
