# CGL Buddy API Contract

This document defines the complete API contract used by the frontend. All platform transports (PyWebView desktop bridge, HTTP bridge for Android) must implement these methods with identical request/response shapes.

**Platform Transports**
- Desktop (Windows/macOS): `PyWebView Bridge` → `window.pywebview.api.*`
- Android/Capacitor: `HTTP Bridge` → `POST http://localhost:8000/api/*`

**Method List & Schemas**

## Settings
- `get_settings()` → `{active_provider, has_gemini_key, has_groq_key, auto_save_ai, last_settings}`
- `save_settings(payload)` → `{ok, active_provider, has_gemini_key, has_groq_key, auto_save_ai, last_settings}`
- `test_api_key(provider, api_key?)` → `{ok, message?}`
- `delete_api_key(provider)` → `{ok, active_provider, has_gemini_key, has_groq_key, auto_save_ai, last_settings}`

## Catalog
- `get_syllabus()` → `{subjects, topics}`
- `list_categories()` → `[str]`
- `list_topics(subject?)` → `[str]`
- `bank_count(category?, difficulty?, topics?)` → `int`

## Quiz
- `start_quiz(options)` → `{ok, quiz_id?, error?, duration_minutes, questions, warnings}`
  - options: `{mode, category, difficulty, topics, num_questions, duration_minutes, provider}`
- `submit_quiz(quiz_id, responses)` → `{ok, error?, summary, charts, review, pending_ai_count, auto_saved_count}`
  - responses: `[{id, selected_index, time_spent_seconds}]`
- `save_ai_questions(quiz_id)` → `{ok, error?, saved_count}`

## History & Sessions
- `list_sessions()` → `{ok, sessions}`
- `clear_sessions()` → `{ok}`

## Database (Questions)
- `db_overview()` → `{subjects, sources}` where each source has `{name, count, locked, tag}`
- `list_db_questions(subject, source)` → `{questions: [{id, subject, source, question, options, answer_index, difficulty, tags}]}`
- `delete_db_question(question_id)` → `{ok, error?}`
- `delete_db_source(source)` → `{ok, error?}`

## Import/Export
- `pick_pdf()` → `file_path?` (desktop: triggers native picker; Android: delegates to FileProvider/UI)
- `pick_import_file()` → `file_path?` (desktop: triggers native picker; Android: delegates to FileProvider/UI)
- `pick_database_import_file()` → `file_path?` (desktop: triggers native picker; Android: delegates to FileProvider/UI)
- `import_questions(file_path, options?)` → `{ok, error?, imported_count, source}`
- `import_database(file_path)` → `{ok, error?, imported_count, skipped_count}`
- `export_database()` → `{ok, error?, file_path}` (desktop: saves to user-chosen location; Android: exports to Downloads)

## Constraints & Platform-Specific Notes
1. **File operations**: Desktop uses PyWebView native dialogs; Android uses Capacitor File plugin + intent-based pickers. Response contract is identical (file path string).
2. **Transactionality**: `submit_quiz` is the only state-mutating operation that requires immediate persistence guarantee.
3. **Async contract**: All methods are async (Promise-based in JS).
4. **Error handling**: All errors are returned as `{ok: false, error: "message"}` in the response dict; never thrown.
5. **Serialization**: All request/response payloads are JSON-serializable (no binary data in core API).

## Changes Not in This Phase
- File upload/download will remain desktop-specific in Phase 1 (PyWebView file dialogs stay); HTTP/Android file bridge is Phase 2.
- Local storage paths are abstracted in backend but not yet unified for Android; Phase 2 will add persistent storage adapter.
