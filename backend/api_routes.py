"""The API surface exposed to the frontend through the PyWebView bridge.

Every public method here is callable from JavaScript as
``window.pywebview.api.<method>(...)``. Methods return plain dicts/lists (JSON
serialisable). Server-side quiz answer keys are held in memory keyed by quiz_id
so the correct answers never reach the client until scoring.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import analysis, config, llm_client, mcq_bank, pdf_processor, quiz_engine
from . import question_store, sessions, syllabus

log = logging.getLogger("CGL_Buddy.api")


class Api:
    def __init__(self) -> None:
        self._answer_keys: Dict[str, Dict[str, Any]] = {}
        self._quiz_meta: Dict[str, Dict[str, Any]] = {}
        # AI-generated questions awaiting a manual "save to bank" from the
        # analysis screen (used when auto-save is off), keyed by quiz_id.
        self._pending_saves: Dict[str, Dict[str, Any]] = {}
        # How many AI questions a quiz auto-saved (so the results screen can
        # confirm it happened), keyed by quiz_id.
        self._auto_saved: Dict[str, int] = {}
        self._lock = threading.Lock()
        # Collapse any legacy per-subject AI source tags into one "AI generated".
        try:
            question_store.collapse_ai_sources()
        except Exception as exc:  # pragma: no cover - best-effort migration
            log.warning("AI source migration failed: %s", exc)
        try:
            question_store.retag_ai_questions()
        except Exception as exc:  # pragma: no cover - best-effort migration
            log.warning("AI tag backfill failed: %s", exc)

    # --- Settings -----------------------------------------------------------

    def get_settings(self) -> Dict[str, Any]:
        cfg = config.load_config()
        # Don't echo full keys back to the UI; just whether they're set.
        return {
            "active_provider": cfg.get("active_provider", "groq"),
            "has_gemini_key": bool(cfg.get("gemini_key")),
            "has_groq_key": bool(cfg.get("groq_key")),
            "auto_save_ai": bool(cfg.get("auto_save_ai", False)),
            "last_settings": cfg.get("last_settings", {}),
        }

    def save_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Persist provider/keys/last_settings. Empty key strings are ignored."""
        update: Dict[str, Any] = {}
        if payload.get("active_provider") in llm_client.VALID_PROVIDERS:
            update["active_provider"] = payload["active_provider"]
        for field in ("gemini_key", "groq_key"):
            val = payload.get(field)
            if isinstance(val, str) and val.strip():
                update[field] = val.strip()
        if "auto_save_ai" in payload:
            update["auto_save_ai"] = bool(payload["auto_save_ai"])
        if isinstance(payload.get("last_settings"), dict):
            update["last_settings"] = payload["last_settings"]
        config.save_config(update)
        return {"ok": True, **self.get_settings()}

    def test_api_key(self, provider: str, api_key: Optional[str] = None) -> Dict[str, Any]:
        key = (api_key or config.get_api_key(provider)).strip()
        if not key:
            return {"ok": False, "message": f"No {provider} key provided."}
        return llm_client.test_api_key(provider, key)

    def delete_api_key(self, provider: str) -> Dict[str, Any]:
        """Remove the stored key for a provider (security)."""
        if provider not in llm_client.VALID_PROVIDERS:
            return {"ok": False, "error": f"Unknown provider: {provider}"}
        config.clear_key(provider)
        log.info("deleted %s API key", provider)
        return {"ok": True, **self.get_settings()}

    # --- Catalog ------------------------------------------------------------

    def get_syllabus(self) -> Dict[str, Any]:
        """SSC CGL subjects + subtopics for the setup UI."""
        return {
            "subjects": syllabus.subjects(),
            "topics": syllabus.as_dict(),
        }

    def list_categories(self) -> List[str]:
        """The four SSC CGL subjects (plus an "All" full-mock option)."""
        return ["All"] + syllabus.subjects()

    def list_topics(self, subject: Optional[str] = None) -> List[str]:
        """Subtopics for a subject (taxonomy + any present in the bank)."""
        if subject and subject != "All":
            topics = list(syllabus.topics(subject))
            for t in mcq_bank.list_topics(subject):
                if t not in topics:
                    topics.append(t)
            return topics
        return []

    def bank_count(
        self,
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
        topics: Optional[List[str]] = None,
    ) -> int:
        return mcq_bank.count(category, difficulty, topics)

    # --- Quiz ---------------------------------------------------------------

    def start_quiz(self, options: Dict[str, Any]) -> Dict[str, Any]:
        """Build a quiz from the given options and stash its answer key."""
        log.info("start_quiz options=%s", options)
        cfg = config.load_config()
        provider = options.get("provider") or cfg.get("active_provider", "groq")
        api_key = config.get_api_key(provider)
        mode = options.get("mode", "bank")

        if mode == "live" and not api_key:
            log.warning("start_quiz blocked: %s mode needs a %s key", mode, provider)
            return {
                "ok": False,
                "error": f"{provider} API key required for AI mode. Add it in Settings or use Bank + images mode.",
            }

        category = options.get("category") or "All"
        difficulty = options.get("difficulty") or "All"
        topics = options.get("topics") or []
        if not isinstance(topics, list):
            topics = []
        num_questions = int(options.get("num_questions", 10))
        duration_minutes = int(options.get("duration_minutes", 15))

        quiz = quiz_engine.build_quiz(
            mode=mode,
            num_questions=num_questions,
            category=category,
            difficulty=difficulty,
            duration_minutes=duration_minutes,
            provider=provider,
            api_key=api_key,
            topics=topics,
        )

        # Persist the chosen settings for next launch.
        config.save_config({"last_settings": {
            "mode": mode,
            "category": category,
            "difficulty": difficulty,
            "topics": topics,
            "num_questions": num_questions,
            "duration_minutes": duration_minutes,
        }})

        with self._lock:
            self._answer_keys[quiz["quiz_id"]] = quiz["answer_key"]
            self._quiz_meta[quiz["quiz_id"]] = {
                "mode": mode,
                "subject": category,
                "topics": topics,
                "difficulty": difficulty,
                "num_questions": num_questions,
                "duration_minutes": duration_minutes,
            }

        log.info(
            "quiz %s built: %d questions, warnings=%s",
            quiz["quiz_id"], len(quiz["questions"]), quiz["warnings"],
        )

        # Freshly generated questions are never wasted. If auto-save is enabled,
        # persist them (deduped) in the background while the user takes the test.
        # Otherwise stash them so the analysis screen can offer a manual save.
        generated = quiz.get("generated_questions") or []
        auto_save = bool(cfg.get("auto_save_ai", False))
        if generated and auto_save:
            with self._lock:
                self._auto_saved[quiz["quiz_id"]] = len(generated)
            threading.Thread(
                target=self._save_generated_questions,
                args=(generated, category),
                daemon=True,
            ).start()
        elif generated:
            with self._lock:
                self._pending_saves[quiz["quiz_id"]] = {
                    "questions": generated,
                    "subject": category,
                }

        return {
            "ok": True,
            "quiz_id": quiz["quiz_id"],
            "duration_minutes": quiz["duration_minutes"],
            "questions": quiz["questions"],
            "warnings": quiz["warnings"],
        }

    @staticmethod
    def _ai_source(subject: str) -> str:
        """Source label for AI-generated questions saved to the bank.

        All AI-generated questions share a single source tag regardless of
        subject/session — the per-question subject field still allows filtering,
        and individual questions can be removed one by one.
        """
        return "AI generated"

    def _save_generated_questions(self, records: List[Dict[str, Any]], subject: str) -> None:
        """Background worker: dedupe + store AI-generated questions."""
        try:
            result = question_store.add_questions(records, source=self._ai_source(subject))
            log.info(
                "saved AI questions: %d added, %d skipped (duplicates)",
                result.get("added", 0), result.get("skipped", 0),
            )
        except Exception as exc:  # pragma: no cover - best-effort persistence
            log.warning("failed to save generated questions: %s", exc)

    def save_ai_questions(self, quiz_id: str) -> Dict[str, Any]:
        """Manually persist a quiz's AI-generated questions to the bank.

        Used by the "Add questions to database" button on the analysis screen
        when auto-save is off. Duplicates are skipped.
        """
        with self._lock:
            pend = self._pending_saves.pop(quiz_id, None)
        if not pend or not pend.get("questions"):
            return {"ok": False, "error": "No AI questions to add for this quiz."}
        result = question_store.add_questions(
            pend["questions"], source=self._ai_source(pend.get("subject", "All"))
        )
        log.info(
            "manual save AI questions: %d added, %d skipped",
            result.get("added", 0), result.get("skipped", 0),
        )
        return {"ok": True, **result}

    def submit_quiz(self, quiz_id: str, responses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Score a quiz and return summary + charts + review."""
        log.info("submit_quiz %s with %d responses", quiz_id, len(responses))
        with self._lock:
            answer_key = self._answer_keys.pop(quiz_id, None)
            meta = self._quiz_meta.pop(quiz_id, {})
        if answer_key is None:
            log.warning("submit_quiz: unknown/already-submitted quiz %s", quiz_id)
            return {"ok": False, "error": "Unknown or already-submitted quiz."}

        scored = quiz_engine.score_quiz(answer_key, responses)

        # Optionally enrich missing explanations using the active provider.
        cfg = config.load_config()
        provider = cfg.get("active_provider", "groq")
        api_key = config.get_api_key(provider)
        if api_key:
            scored["review"] = analysis.enrich_explanations(scored["review"], provider, api_key)

        # Persist this attempt to the session history.
        try:
            review = scored.get("review", [])
            # Store a compact, self-contained snapshot of every question so the
            # history screen can render exactly what was attempted later, even
            # if the underlying bank questions change.
            attempted_questions = [
                {
                    "question": r.get("question", ""),
                    "options": r.get("options", []),
                    "correct_index": r.get("correct_index"),
                    "selected_index": r.get("selected_index"),
                    "is_correct": r.get("is_correct", False),
                    "attempted": r.get("attempted", False),
                    "subject": r.get("category", ""),
                    "topic": r.get("topic", ""),
                    "difficulty": r.get("difficulty", "medium"),
                    "explanation": r.get("explanation", ""),
                    "time_spent_seconds": r.get("time_spent_seconds", 0),
                }
                for r in review
            ]
            sessions.save_session({
                "mode": meta.get("mode", "bank"),
                "subject": meta.get("subject", "All"),
                "topics": meta.get("topics", []),
                "difficulty": meta.get("difficulty", "All"),
                "duration_minutes": meta.get("duration_minutes"),
                "score": scored.get("score", 0),
                "total": scored.get("total", 0),
                "accuracy": scored.get("accuracy", 0.0),
                "attempted": scored.get("attempted", 0),
                "skipped": scored.get("skipped", 0),
                "time_taken_seconds": scored.get("total_time_seconds", 0.0),
                "avg_time_seconds": scored.get("avg_time_seconds", 0.0),
                "category_accuracy": scored.get("category_accuracy", {}),
                "difficulty_accuracy": scored.get("difficulty_accuracy", {}),
                "topic_accuracy": scored.get("topic_accuracy", {}),
                "questions": attempted_questions,
            })
        except Exception as exc:  # pragma: no cover - history is best-effort
            log.warning("failed to save session: %s", exc)

        # Tell the UI whether this quiz has AI questions still awaiting a manual
        # save (auto-save off), so it can show the "Add to database" button.
        with self._lock:
            pend = self._pending_saves.get(quiz_id)
            auto_saved = self._auto_saved.pop(quiz_id, 0)
        pending_ai = len(pend["questions"]) if pend and pend.get("questions") else 0

        return {
            "ok": True,
            "summary": analysis.summarize(scored),
            "charts": analysis.build_charts(scored),
            "review": scored["review"],
            "pending_ai_count": pending_ai,
            "auto_saved_count": auto_saved,
        }

    # --- Session history ----------------------------------------------------

    def list_sessions(self) -> Dict[str, Any]:
        """All past quiz sessions, newest first."""
        return {"ok": True, "sessions": sessions.list_sessions()}

    def clear_sessions(self) -> Dict[str, Any]:
        """Erase all saved session history."""
        sessions.clear_sessions()
        log.info("cleared session history")
        return {"ok": True, "sessions": []}

    # --- Scanned / image question import (Gemini vision) --------------------

    _PDF_SOURCE = mcq_bank.PDF_IMPORT_SOURCE
    _IMAGE_SOURCE = mcq_bank.IMAGE_IMPORT_SOURCE

    def import_questions(self, file_path: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Add MCQs from a file to the writable bank (deduped), tagged with a
        dedicated source.

        - **Digital PDFs** are parsed straight from their text — no LLM, no API
          key, no quota. Scanned/image-only PDFs yield nothing and are rejected
          with a hint to import them as images instead.
        - **Images** (png/jpg/webp/…) are read via Gemini vision OCR, which
          needs a Gemini API key.
        """
        path = Path(file_path)
        options = options or {}
        if not path.exists():
            return {"ok": False, "error": "File not found."}
        ext = path.suffix.lower()

        # --- PDF: free, offline text parsing -------------------------------
        if ext == ".pdf":
            subject = options.get("subject") or ""
            if not syllabus.is_subject(subject):
                return {"ok": False, "error": "Choose the subject for this PDF before importing."}
            try:
                records = pdf_processor.parse_mcqs_from_pdf(path)
            except pdf_processor.ImportTooLarge as exc:
                return {"ok": False, "error": str(exc)}
            except Exception as exc:  # noqa: BLE001 - corrupt/unreadable file
                log.warning("import_questions parse failed for %s: %s", path.name, exc)
                return {"ok": False, "error": "Could not read that PDF — it may be corrupt."}
            if not records:
                return {
                    "ok": False,
                    "error": (
                        "No complete questions could be read from that PDF. Make sure it's a "
                        "digital PDF with selectable text and each question has four options "
                        "plus a marked answer (e.g. \"Ans. (b)\"). If it's a scan, import each "
                        "page as an image instead."
                    ),
                }
            for rec in records:
                rec["subject"] = subject
                rec["category"] = subject
                rec["topic"] = ""
                rec["difficulty"] = rec.get("difficulty") or "medium"
            result = question_store.add_questions(records, source=self._PDF_SOURCE)
            log.info(
                "import_questions(pdf) %s: found %d, added %d, skipped %d",
                path.name, len(records), result["added"], result["skipped"],
            )
            return {
                "ok": True,
                "found": len(records),
                "added": result["added"],
                "skipped": result["skipped"],
                "pages_failed": 0,
                "quota_exhausted": False,
                "source": path.name,
            }

        # --- Image: Gemini vision OCR --------------------------------------
        if ext not in pdf_processor.IMPORT_IMAGE_EXTS:
            return {"ok": False, "error": "Please choose a PDF or image (png, jpg, webp)."}

        key = config.get_api_key("gemini")
        if not key:
            return {
                "ok": False,
                "error": "Add a Gemini API key in Settings to import questions from images.",
            }
        try:
            png = pdf_processor.render_image_png(path)
        except pdf_processor.ImportTooLarge as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - corrupt/unreadable file
            log.warning("import_questions render failed for %s: %s", path.name, exc)
            return {"ok": False, "error": "Could not read that image — it may be corrupt or unsupported."}

        records: List[Dict[str, Any]] = []
        quota_hit = False
        part = {"mime_type": "image/png", "data": png}
        try:
            records = llm_client.extract_mcqs_from_images([part], None, key)
        except llm_client.LLMError as exc:
            err = str(exc).lower()
            if "429" in err or "quota" in err or "rate limit" in err or "rate-limit" in err:
                quota_hit = True
            log.warning("import_questions image failed: %s", exc)

        if not records:
            if quota_hit:
                msg = (
                    "Gemini's free-tier daily limit (20 requests/day) is exhausted, "
                    "so the image couldn't be read. Try again after the quota resets, "
                    "or enable billing on your Gemini API key."
                )
            else:
                msg = "No complete questions could be read from that image."
            return {"ok": False, "error": msg, "quota_exhausted": quota_hit}

        result = question_store.add_questions(records, source=self._IMAGE_SOURCE)
        log.info(
            "import_questions(image) %s: found %d, added %d, skipped %d",
            path.name, len(records), result["added"], result["skipped"],
        )
        return {
            "ok": True,
            "found": len(records),
            "added": result["added"],
            "skipped": result["skipped"],
            "pages_failed": 0,
            "quota_exhausted": quota_hit,
            "source": path.name,
        }

    def pick_database_import_file(self) -> Optional[str]:
        """Open a native dialog to pick a CGL Buddy database JSON file."""
        import webview

        windows = webview.windows
        if not windows:
            return None
        result = windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=(
                "CGL Buddy database (*.json)",
                "JSON files (*.json)",
                "All files (*.*)",
            ),
        )
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else result

    def import_database(self, file_path: str) -> Dict[str, Any]:
        """Append questions from a database JSON file, skipping duplicates."""
        path = Path(file_path)
        if not path.exists():
            return {"ok": False, "error": "File not found."}
        if path.suffix.lower() != ".json":
            return {"ok": False, "error": "Please choose a JSON database file."}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = question_store.records_from_payload(payload)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            log.warning("import_database failed for %s: %s", path.name, exc)
            return {"ok": False, "error": "Could not read that database JSON."}

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        preserve_sources = {
            self._PDF_SOURCE,
            self._IMAGE_SOURCE,
            mcq_bank.LEGACY_IMPORT_SOURCE,
        }
        for rec in records:
            source = rec.get("source") if rec.get("source") in preserve_sources else mcq_bank.DATABASE_IMPORT_SOURCE
            grouped.setdefault(source, []).append(rec)

        added = 0
        skipped = 0
        for source, items in grouped.items():
            result = question_store.add_questions(items, source=source)
            added += result.get("added", 0)
            skipped += result.get("skipped", 0)
        log.info(
            "import_database %s: found %d, added %d, skipped %d",
            path.name, len(records), added, skipped,
        )
        return {
            "ok": True,
            "found": len(records),
            "added": added,
            "skipped": skipped,
            "source": path.name,
        }

    def export_database(self) -> Dict[str, Any]:
        """Save the user's writable question database as portable JSON."""
        import webview

        windows = webview.windows
        if not windows:
            return {"ok": False, "error": "No app window is available."}
        default_name = f"cgl-buddy-database-{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
        result = windows[0].create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=default_name,
            file_types=(
                "CGL Buddy database (*.json)",
                "JSON files (*.json)",
                "All files (*.*)",
            ),
        )
        if not result:
            return {"ok": True, "cancelled": True}
        selected = result[0] if isinstance(result, (list, tuple)) else result
        path = Path(selected)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        payload = question_store.export_payload()
        try:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("export_database failed for %s: %s", path, exc)
            return {"ok": False, "error": "Could not save the database file."}
        log.info("export_database %s: %d questions", path.name, payload["question_count"])
        return {
            "ok": True,
            "path": str(path),
            "exported": payload["question_count"],
        }

    def pick_import_file(self) -> Optional[str]:
        """Open a native dialog to pick an image for vision question import."""
        import webview

        windows = webview.windows
        if not windows:
            return None
        result = windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=(
                "Images (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif)",
                "All files (*.*)",
            ),
        )
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else result

    # --- Database management ------------------------------------------------

    _BUNDLED_SOURCE = "Built-in bank"

    def db_overview(self) -> Dict[str, Any]:
        """Counts + sources for the database-management screen.

        Returns MCQ question sources (the read-only built-in bank plus any
        writable AI/imported sources), each with counts.
        """
        bundled = mcq_bank.bundled_questions()
        mcq_sources: List[Dict[str, Any]] = [{
            "source": self._BUNDLED_SOURCE,
            "count": len(bundled),
            "deletable": False,
        }]
        for s in question_store.sources():
            mcq_sources.append({
                "source": s["source"],
                "count": s["count"],
                "deletable": True,
            })
        total_mcq = len(bundled) + sum(s["count"] for s in question_store.sources())
        return {
            "ok": True,
            "mcq_sources": mcq_sources,
            "total_mcq": total_mcq,
            "subjects": ["All"] + syllabus.subjects(),
        }

    def list_db_questions(
        self,
        subject: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 300,
    ) -> Dict[str, Any]:
        """Browse stored MCQs (built-in bank + writable store), with filters."""
        subject = subject or "All"
        source = source or "All"
        items: List[Dict[str, Any]] = []

        def _matches_subject(q: Dict[str, Any]) -> bool:
            if subject == "All":
                return True
            return (q.get("subject") or q.get("category") or "General") == subject

        if source in ("All", self._BUNDLED_SOURCE):
            for q in mcq_bank.bundled_questions():
                if _matches_subject(q):
                    items.append(self._shape_db_question(q, self._BUNDLED_SOURCE, deletable=False))
        if source != self._BUNDLED_SOURCE:
            store_src = None if source == "All" else source
            for q in question_store.list_questions(subject=subject, source=store_src):
                items.append(self._shape_db_question(
                    q, q.get("source", "AI generated"), deletable=True
                ))

        total = len(items)
        return {"ok": True, "questions": items[: max(0, int(limit))], "total": total}

    @staticmethod
    def _shape_db_question(q: Dict[str, Any], source: str, deletable: bool = False) -> Dict[str, Any]:
        return {
            "id": q.get("id", ""),
            "question": q.get("question", ""),
            "options": q.get("options", []),
            "correct_index": q.get("correct_index"),
            "subject": q.get("subject") or q.get("category") or "General",
            "topic": q.get("topic", ""),
            "difficulty": q.get("difficulty", "medium"),
            "explanation": q.get("explanation", ""),
            "source": source,
            "deletable": deletable,
        }

    def delete_db_source(self, source: str) -> Dict[str, Any]:
        """Delete all writable-store MCQs from a given source (with the UI's
        confirmation). The built-in bank is read-only and cannot be deleted."""
        if not source or source == self._BUNDLED_SOURCE:
            return {"ok": False, "error": "The built-in bank is read-only and cannot be deleted."}
        removed = question_store.delete_by_source(source)
        log.info("delete_db_source %r: removed %d questions", source, removed)
        return {"ok": True, "removed": removed}

    def delete_db_question(self, question_id: str) -> Dict[str, Any]:
        """Delete a single user-stored question by id (built-in bank excluded).

        Bundled questions have no id, so only writable-store questions match.
        """
        if not question_id:
            return {"ok": False, "error": "No question specified."}
        removed = question_store.delete_question(question_id)
        if not removed:
            return {"ok": False, "error": "That question can't be deleted (built-in or already removed)."}
        log.info("delete_db_question %s: removed", question_id)
        return {"ok": True, "removed": removed}

    def pick_pdf(self) -> Optional[str]:
        """Open a native file dialog and return the chosen PDF path (or None)."""
        import webview

        windows = webview.windows
        if not windows:
            return None
        result = windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("PDF files (*.pdf)",),
        )
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else result
