from __future__ import annotations

"""
Module entrypoint to run the FastAPI app with uvicorn when executed as:
  python -m src.api

This is optional; in production use a process manager to run:
  uvicorn src.api.main:app --host 0.0.0.0 --port 3001
"""

import os
import uvicorn

# PUBLIC_INTERFACE
def main() -> None:
    """Start the FastAPI server on host/port specified by env or defaults (0.0.0.0:3001)."""
    host = os.getenv("HOST", "0.0.0.0")
    try:
        port = int(os.getenv("PORT", "3001"))
    except ValueError:
        port = 3001
    uvicorn.run("src.api.main:app", host=host, port=port, reload=False, factory=False)

if __name__ == "__main__":
    main()
