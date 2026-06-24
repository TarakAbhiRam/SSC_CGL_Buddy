"""FastAPI HTTP server for CGL Buddy.

Exposes the same API surface as the PyWebView bridge, but over HTTP.
Used for:
1. Android/Capacitor apps (local bridge)
2. Development/testing (alternative to PyWebView)
3. Future web deployment

This server can be run alongside or instead of the PyWebView window.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.api_routes import Api

log = logging.getLogger("CGL_Buddy.http_api")

app = FastAPI(title="CGL Buddy API")

# CORS for Capacitor/WebView access from file:// and local URLs
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Capacitor allows local file access
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global API instance (shared with desktop if applicable)
_api_instance: Optional[Api] = None


def get_api() -> Api:
    """Get or create the shared API instance."""
    global _api_instance
    if _api_instance is None:
        _api_instance = Api()
    return _api_instance


# ---- Request/Response Models ----

class GenericRequest(BaseModel):
    """Generic request body for flexible JSON payloads."""
    class Config:
        extra = "allow"  # Allow arbitrary fields


# ---- Settings endpoints ----

@app.post("/api/get_settings")
async def get_settings():
    """Get current settings."""
    api = get_api()
    try:
        return api.get_settings()
    except Exception as e:
        log.error("get_settings error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/save_settings")
async def save_settings(payload: GenericRequest):
    """Save settings."""
    api = get_api()
    try:
        return api.save_settings(payload.dict(exclude_unset=True))
    except Exception as e:
        log.error("save_settings error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/test_api_key")
async def test_api_key(payload: GenericRequest):
    """Test an API key."""
    api = get_api()
    try:
        provider = payload.dict().get("provider")
        api_key = payload.dict().get("api_key")
        return api.test_api_key(provider, api_key)
    except Exception as e:
        log.error("test_api_key error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/delete_api_key")
async def delete_api_key(payload: GenericRequest):
    """Delete an API key."""
    api = get_api()
    try:
        provider = payload.dict().get("provider")
        return api.delete_api_key(provider)
    except Exception as e:
        log.error("delete_api_key error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---- Catalog endpoints ----

@app.post("/api/get_syllabus")
async def get_syllabus():
    """Get syllabus (subjects and topics)."""
    api = get_api()
    try:
        return api.get_syllabus()
    except Exception as e:
        log.error("get_syllabus error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/list_categories")
async def list_categories():
    """List quiz categories."""
    api = get_api()
    try:
        return api.list_categories()
    except Exception as e:
        log.error("list_categories error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/list_topics")
async def list_topics(payload: GenericRequest):
    """List topics for a subject."""
    api = get_api()
    try:
        subject = payload.dict().get("subject")
        return api.list_topics(subject)
    except Exception as e:
        log.error("list_topics error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/bank_count")
async def bank_count(payload: GenericRequest):
    """Get question bank count."""
    api = get_api()
    try:
        data = payload.dict()
        return api.bank_count(
            category=data.get("category"),
            difficulty=data.get("difficulty"),
            topics=data.get("topics"),
        )
    except Exception as e:
        log.error("bank_count error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---- Quiz endpoints ----

@app.post("/api/start_quiz")
async def start_quiz(payload: GenericRequest):
    """Start a new quiz."""
    api = get_api()
    try:
        options = payload.dict(exclude_unset=True)
        return api.start_quiz(options)
    except Exception as e:
        log.error("start_quiz error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/submit_quiz")
async def submit_quiz(payload: GenericRequest):
    """Submit quiz answers."""
    api = get_api()
    try:
        data = payload.dict()
        quiz_id = data.get("quiz_id")
        responses = data.get("responses", [])
        return api.submit_quiz(quiz_id, responses)
    except Exception as e:
        log.error("submit_quiz error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/save_ai_questions")
async def save_ai_questions(payload: GenericRequest):
    """Save AI-generated questions."""
    api = get_api()
    try:
        quiz_id = payload.dict().get("quiz_id")
        return api.save_ai_questions(quiz_id)
    except Exception as e:
        log.error("save_ai_questions error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---- Sessions endpoints ----

@app.post("/api/list_sessions")
async def list_sessions():
    """List quiz sessions."""
    api = get_api()
    try:
        return api.list_sessions()
    except Exception as e:
        log.error("list_sessions error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/clear_sessions")
async def clear_sessions():
    """Clear all sessions."""
    api = get_api()
    try:
        return api.clear_sessions()
    except Exception as e:
        log.error("clear_sessions error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---- Database endpoints ----

@app.post("/api/db_overview")
async def db_overview():
    """Get database overview."""
    api = get_api()
    try:
        return api.db_overview()
    except Exception as e:
        log.error("db_overview error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/list_db_questions")
async def list_db_questions(payload: GenericRequest):
    """List questions from database."""
    api = get_api()
    try:
        data = payload.dict()
        subject = data.get("subject")
        source = data.get("source")
        return api.list_db_questions(subject, source)
    except Exception as e:
        log.error("list_db_questions error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/delete_db_question")
async def delete_db_question(payload: GenericRequest):
    """Delete a question from database."""
    api = get_api()
    try:
        question_id = payload.dict().get("question_id")
        return api.delete_db_question(question_id)
    except Exception as e:
        log.error("delete_db_question error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/delete_db_source")
async def delete_db_source(payload: GenericRequest):
    """Delete a source from database."""
    api = get_api()
    try:
        source = payload.dict().get("source")
        return api.delete_db_source(source)
    except Exception as e:
        log.error("delete_db_source error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---- Import/Export endpoints (desktop file operations) ----

@app.post("/api/pick_pdf")
async def pick_pdf():
    """Desktop only: open file dialog for PDF."""
    api = get_api()
    try:
        path = api.pick_pdf()
        return {"ok": True, "path": path}
    except Exception as e:
        log.error("pick_pdf error: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


@app.post("/api/pick_import_file")
async def pick_import_file():
    """Desktop only: open file dialog for image import."""
    api = get_api()
    try:
        path = api.pick_import_file()
        return {"ok": True, "path": path}
    except Exception as e:
        log.error("pick_import_file error: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


@app.post("/api/pick_database_import_file")
async def pick_database_import_file():
    """Desktop only: open file dialog for database import."""
    api = get_api()
    try:
        path = api.pick_database_import_file()
        return {"ok": True, "path": path}
    except Exception as e:
        log.error("pick_database_import_file error: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


@app.post("/api/import_questions")
async def import_questions(payload: GenericRequest):
    """Import questions from file."""
    api = get_api()
    try:
        data = payload.dict()
        file_path = data.get("file_path")
        options = data.get("options", {})
        return api.import_questions(file_path, options)
    except Exception as e:
        log.error("import_questions error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/import_database")
async def import_database(payload: GenericRequest):
    """Import database JSON file."""
    api = get_api()
    try:
        file_path = payload.dict().get("file_path")
        return api.import_database(file_path)
    except Exception as e:
        log.error("import_database error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/export_database")
async def export_database():
    """Export database JSON file."""
    api = get_api()
    try:
        return api.export_database()
    except Exception as e:
        log.error("export_database error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---- Health check ----

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    uvicorn.run(app, host="127.0.0.1", port=8000)
