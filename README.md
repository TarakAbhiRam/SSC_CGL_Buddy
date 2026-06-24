# CGL Buddy

CGL Buddy is your SSC CGL practice companion: a lightweight app for
macOS, Windows, and Android that helps aspirants practise from the built-in bank, import
subject-wise PDF questions, generate fresh AI MCQs, take timed quizzes, and
track performance.

It ships with a built-in question bank, can import ready-made MCQs from digital
PDFs into a separate PDF practice source, includes tagged image imports with the
normal bank, and can optionally generate fresh SSC CGL-style questions through
Groq or Gemini when the user adds an API key.

The app is intentionally kept light: the normal runtime does **not** load a local
embedding model, PyTorch, or ChromaDB. PDFs are parsed directly into bank questions
instead of being indexed as reference material.

This README is the single source of truth for the project: product scope,
architecture, build instructions, and distribution notes live here.

---

## For Users

1. Unzip the file you received.
2. Open the app:
  - **macOS**: double-click **`CGL Buddy.app`**.
  - **Windows**: double-click **`CGL Buddy.exe`**.
   - If Windows shows a blue "Windows protected your PC" box: click **More info → Run anyway**
     (the app is safe; it just isn't code-signed).
3. Pick a subject, source, difficulty, number of questions, and a time limit. Start the quiz.
4. **API key is optional.** Without one you can use Bank + images mode or PDF mode.
   With one, the app can generate brand-new questions or read MCQs from images.

### Importing Your Own Questions

- **Digital PDF with selectable text**: use **Add questions from PDF**. The app parses
  question text, four options, and the marked answer. Choose the PDF's subject first;
  those questions stay in the separate **Imported PDFs** exam source. No API key is needed.
- **Image / screenshot of MCQs**: use **Import questions from image**. This uses Gemini
  vision OCR, so it needs a Gemini API key and is subject to Gemini quota limits. Image
  imports are tagged by Gemini and included in **Bank + images** mode.
- **Shared JSON database**: open **Question bank** and use **Export database** to save
  your current user-added questions as a portable JSON file. Use **Import database** to
  append another CGL Buddy JSON database; repeated questions are skipped automatically.

PDF import expects each question to include four options and a detectable answer such as
`Ans. (b)`, `Answer: B`, or `Correct answer: 2`. Questions without an answer are skipped
because the app cannot grade them safely.

### (Optional) Getting a free API key
- **Groq** (recommended, fast & free): https://console.groq.com → sign in → *API Keys* → create key.
- **Gemini**: https://aistudio.google.com/app/apikey → create key.

Paste the key into the app's **Settings** screen and click **Test key**. That's it.

---

## For Developers

### Architecture in one line
PyWebView desktop window → vanilla HTML/CSS/JS frontend → Python backend → JSON-backed
question bank → PyMuPDF PDF parser → optional Groq/Gemini calls → timed quiz → analysis.

Android uses the same frontend and backend contract: Android WebView → shared
frontend transport adapter → local HTTP bridge → Python backend. Platform-specific
code stays in thin host adapters so Windows development remains unchanged.

### Current lightweight runtime

Included in the normal app runtime:
- PyWebView native desktop shell
- PyMuPDF for digital PDF text extraction and image normalization
- Local JSON question stores
- Groq/Gemini clients for optional cloud AI features

Not included in the normal lightweight runtime:
- `sentence-transformers`
- PyTorch
- ChromaDB
- local embedding model / PDF-reference RAG

Those were part of the older “upload PDF as reference text for the LLM” design. The current
product direction is “parse PDF questions into the bank,” which does not need that stack.

### Run locally (macOS / Windows / Linux)
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Optional shared-backend modes:
```bash
python run.py --desktop          # same desktop behavior as python main.py
python run.py --http             # local HTTP API bridge for testing
python run.py --both             # desktop app plus HTTP bridge
python scripts/verify_platform_contract.py
```

### Project layout
```
main.py            PyWebView entry point + bundled-path resolution
backend/           config, PDF parsing, LLM client, quiz engine, analysis, API bridge
scripts/           OFFLINE prep helpers / legacy prep scripts
frontend/          index/setup/quiz/analysis HTML + style.css + script.js
data/              mcq_bank.json (shipped built-in bank) + optional dev data
.github/workflows/ build-windows.yml, build-macos.yml, build-android.yml
android/           Android WebView + Chaquopy host (API 28+)
build/             build_mac.sh, build_win.bat, build_android.sh/.bat
```

### Product scope

Core app goals:
- Desktop app for SSC CGL MCQ practice on macOS and Windows.
- Bank + images mode works without any API key after image imports are saved.
- Users can import subject-wise digital PDFs into a separate PDF practice source.
- Users can import tagged questions from images through the active provider's vision OCR (Gemini or Groq).
- Users can optionally generate fresh SSC CGL-style questions through Groq/Gemini.
- Timed quiz, per-question answer tracking, session history, charts, and review screen.

Intentionally out of the lightweight runtime:
- Local PDF-reference RAG.
- Runtime embeddings/vector search.
- PyTorch-backed local language/embedding models.

### Offline prep / legacy notes

The shipped app no longer needs runtime embeddings or ChromaDB. Some old prep scripts remain
for experimentation, but they are not part of the lightweight app build.

To refresh the bundled question bank, use the bank-generation scripts that write
`data/mcq_bank.json`. Keep any RAG/vector-store scripts out of the packaged runtime unless the
PDF-reference feature is intentionally brought back.

Legacy RAG flow, disabled for the current product direction:
```bash
python scripts/ingest_pdfs.py        # extract text from data/pdfs/ (OCR stub for scans)
python scripts/chunk_and_embed.py    # chunk + embed -> data/chroma_db/
python scripts/tag_topics.py         # LLM pass: assign topic + difficulty (needs your key)
python scripts/build_mcq_bank.py     # pre-generate MCQ pool -> data/mcq_bank.json (needs your key)
```

### Implementation notes

- `backend/llm_client.py` abstracts Gemini/Groq behind the same JSON MCQ schema.
- LLM calls use retries/backoff and validate MCQ shape before questions reach the quiz.
- `backend/question_store.py` stores imported/generated questions in the user data dir.
- Built-in questions are read-only; user/imported/generated questions are deletable.
- Quiz sources are intentionally separate: Bank + images, Imported PDFs, and AI generation.
- API keys and user settings are stored locally, not sent anywhere except to the selected provider.
- Use `pathlib`/bundled path helpers so the same code works under PyInstaller on macOS/Windows.

---

## Building Desktop Apps

PyInstaller **cannot cross-compile**, so build each platform on its native OS or use the
included GitHub Actions workflows.

### GitHub Actions

- `.github/workflows/build-windows.yml` builds `CGL_Buddy_Windows.zip` on `windows-latest`.
- `.github/workflows/build-macos.yml` builds `CGL_Buddy_macOS.zip` on `macos-latest`.
- `.github/workflows/build-android.yml` builds `app-debug.apk` on `ubuntu-latest`.

The desktop workflows install the lightweight runtime requirements and package the app with
PyInstaller. The Android workflow builds the WebView/Chaquopy APK path.

### Manual Windows Build
```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt pyinstaller
build\build_win.bat
```
Output: `dist\CGL Buddy\CGL Buddy.exe`.

### Optional Windows Installer With Inno Setup

If you want an installer, build the PyInstaller app first on a Windows PC, then
compile `build\CGL_Buddy_Inno_Setup.iss` with Inno Setup.

Important: CGL Buddy is built as a PyInstaller **onedir** app. The installer must
include the whole `dist\CGL Buddy\` folder, not only `CGL Buddy.exe`, because the
exe depends on files inside that folder.

The provided Inno script creates a 64-bit-compatible installer:

```bat
build\build_win.bat
iscc build\CGL_Buddy_Inno_Setup.iss
```

Output: `installer\CGL_Buddy_Setup_x64.exe`.

If a user sees **"This app can't run on your PC"**, check these first:

- The Windows build/installer was created on Windows, not macOS.
- The installer includes all files from `dist\CGL Buddy\`, not just the exe.
- The target PC is 64-bit Windows 10/11. The normal GitHub Actions/Python build is x64.
- If you must support old 32-bit Windows PCs, build a separate installer using 32-bit Python on 32-bit Windows and label it separately.
- Re-download the installer if the file may be incomplete or corrupted.

### Manual macOS Build
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller
bash build/build_mac.sh
```
Output: `dist/CGL Buddy/CGL Buddy.app`.

---

## Building Android APK

Android support is layered on top of the shared frontend/backend. It does not
replace the Windows/macOS workflow.

SDK policy:
- Minimum SDK: Android 9 / API 28.
- Target SDK: latest configured release SDK (`cglBuddyTargetSdk=36`).
- Compile SDK: aligned with target SDK (`cglBuddyCompileSdk=36`).
- Autorotate: allowed; the Android activity handles orientation and screen-size
  changes without recreating the WebView, so quiz state/timer are preserved.

Manual Android build on macOS/Linux:
```bash
bash build/build_android.sh
```

Manual Android build on Windows:
```bat
build\build_android.bat
```

Output: `android/app/build/outputs/apk/debug/app-debug.apk`.

Android implementation notes:
- `android/app/src/main/java/com/cglbuddy/app/MainActivity.kt` hosts the shared
  frontend in Android WebView.
- `android/app/src/main/python/android_entry.py` starts the Python HTTP backend
  inside the app process.
- `requirements-android.txt` keeps desktop-only packages out of the APK while
  including the runtime dependencies needed for bank, PDF, image, AI, history,
  database import/export, and analysis flows.
- Selected PDFs/images/database files are copied into Android app storage before
  being passed to the shared Python importer.

The local machine needs Android Studio or Gradle plus the Android SDK installed
to produce an APK. GitHub Actions installs those tools automatically.

### Lightweight packaging rule

Do not add `--collect-all chromadb`, `--collect-all sentence_transformers`, or PyTorch to the
default build unless the old PDF-reference RAG feature is intentionally restored. That stack is
the main source of high RAM and large package size.

### Distribution notes

- Ship builds as `.zip` files: `CGL_Buddy_macOS.zip` and `CGL_Buddy_Windows.zip`.
- If shipping an installer, use `CGL_Buddy_Setup_x64.exe` built from `build\CGL_Buddy_Inno_Setup.iss`.
- Unsigned Windows builds may show SmartScreen. Users can choose **More info → Run anyway**.
- Unsigned macOS builds may need the usual Gatekeeper approval for locally distributed apps.
- PyInstaller cannot cross-compile; build Windows on Windows and macOS on macOS, or use the workflows.

### Verification checklist

- `python scripts/verify_platform_contract.py` passes.
- `python -m tests.smoke` passes.
- App launches locally with `python main.py`.
- Android debug APK builds with `bash build/build_android.sh` or GitHub Actions.
- Bank + images quiz works with no API key.
- PDF import adds subject-tagged questions to Database → Browse questions and PDF mode.
- Image import shows a clear Gemini quota/API-key message when needed.
- Groq/Gemini key testing works from Settings.
- macOS and Windows build artifacts include `frontend/` and `data/`.

---

## Config & privacy
- API keys and last-used settings are stored locally in the app data directory.
- Bank/imported questions are stored locally in `user_mcq.json`.
- Digital PDFs are parsed locally with PyMuPDF.
- Image OCR is sent to Gemini only when the user chooses image import.
- Fresh AI generation is sent only to the selected provider (Groq or Gemini), using the user's
   own key.
