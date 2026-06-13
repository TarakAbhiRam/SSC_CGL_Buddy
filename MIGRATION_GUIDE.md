# CGL Buddy Migration Guide

This guide explains how the app works today and how to adapt it from SSC CGL to another exam such as GATE, banking, UPSC, school subjects, or any custom MCQ course.

## How The App Works

CGL Buddy is a local desktop quiz app built with PyWebView.

```text
main.py
  -> opens frontend/index.html in a desktop window
  -> exposes backend/api_routes.Api to JavaScript

frontend/
  -> setup screen, quiz screen, analysis, history, question bank, settings

backend/
  -> builds quizzes, imports questions, stores settings, scores attempts

data/mcq_bank.json
  -> bundled read-only question bank shipped with the app

user app data/user_mcq.json
  -> user-imported, AI-generated, and shared database questions
```

The user chooses a subject, question source, difficulty, question count, and timer. The backend builds a quiz, keeps the answer key server-side, sends only safe question data to the frontend, then scores the attempt after submission.

## Question Sources

The app currently has three quiz sources:

- **Bank + images**: bundled questions from `data/mcq_bank.json`, plus image/shared-database imports saved in the user database.
- **Imported PDFs**: questions parsed from digital PDFs. They are subject-tagged only and kept separate from the normal bank.
- **AI generation**: fresh questions generated through Groq or Gemini using the user's API key.

User-added questions are stored separately from the built-in bank so they can be deleted, exported, imported, and deduplicated.

## Portable JSON Database Format

Database import/export uses this shape:

```json
{
  "format": "cgl-buddy-mcq-db",
  "version": 1,
  "question_count": 1,
  "questions": [
    {
      "question": "What is 2 + 2?",
      "options": ["1", "2", "3", "4"],
      "correct_index": 3,
      "subject": "Quantitative Aptitude",
      "topic": "Simplification",
      "difficulty": "easy",
      "explanation": "2 + 2 = 4.",
      "source": "Imported database"
    }
  ]
}
```

Required fields:

- `question`: non-empty string
- `options`: exactly four options
- `correct_index`: 0-based answer index, from `0` to `3`
- `subject`: top-level subject name

Recommended fields:

- `topic`: subtopic name
- `difficulty`: `easy`, `medium`, or `hard`
- `explanation`: short solution
- `source`: source label, usually `Imported database`

Duplicate handling is automatic. `backend/question_store.py` normalizes question text and skips repeated questions already present in the bundled bank or user database.

## What Is Exam-Specific

These parts currently contain SSC CGL-specific names, subjects, topics, or wording:

- `backend/syllabus.py`: canonical subjects and topics.
- `data/mcq_bank.json`: bundled built-in MCQs.
- `backend/llm_client.py`: AI prompts and parsing instructions may mention SSC CGL style.
- `frontend/index.html`: visible UI text such as CGL/SSC wording.
- `README.md`: project description and user documentation.
- `main.py`: window title is `CGL Buddy`.
- `backend/paths.py`: app data directory is `CGL_Buddy`.
- Build scripts/workflows: packaged app name and artifact names.

Most behavior is already generic MCQ behavior. The main migration job is replacing the taxonomy, built-in bank, prompts, and branding.

## Migration Steps

### 1. Pick The New Exam Identity

Decide the new app name and app data folder.

Example for GATE:

```text
App name: GATE Buddy
App data folder: GATE_Buddy
Repo/product wording: GATE practice companion
```

Files to update:

- `main.py`: `WINDOW_TITLE`
- `backend/paths.py`: user data directory and optional old-dir migration
- `README.md`: title and product wording
- `frontend/index.html`: visible app name and helper text
- Build scripts under `build/` and `.github/workflows/`

### 2. Replace The Syllabus Taxonomy

Edit `backend/syllabus.py`. This file is the single source of truth for subjects and topics.

For example, a simple GATE CSE taxonomy could look like:

```python
ENGINEERING_MATH = "Engineering Mathematics"
DIGITAL_LOGIC = "Digital Logic"
COMPUTER_ORG = "Computer Organization and Architecture"
PROGRAMMING = "Programming and Data Structures"
ALGORITHMS = "Algorithms"
THEORY = "Theory of Computation"
COMPILERS = "Compiler Design"
OS = "Operating System"
DATABASES = "Databases"
NETWORKS = "Computer Networks"

SYLLABUS = {
    ENGINEERING_MATH: [
        "Linear Algebra",
        "Calculus",
        "Probability",
        "Discrete Mathematics",
    ],
    ALGORITHMS: [
        "Asymptotic Analysis",
        "Sorting",
        "Graphs",
        "Dynamic Programming",
    ],
    DATABASES: [
        "ER Model",
        "Relational Algebra",
        "SQL",
        "Transactions",
        "Normalization",
    ],
}

SUBJECTS = [
    ENGINEERING_MATH,
    DIGITAL_LOGIC,
    COMPUTER_ORG,
    PROGRAMMING,
    ALGORITHMS,
    THEORY,
    COMPILERS,
    OS,
    DATABASES,
    NETWORKS,
]
```

Keep subject names stable once users start saving data. The app persists subject strings in user questions, quiz history, and settings.

### 3. Replace The Built-In Bank

Update `data/mcq_bank.json` with the new exam's built-in questions.

Each record should follow this schema:

```json
{
  "question": "Which normal form removes partial dependency?",
  "options": ["1NF", "2NF", "3NF", "BCNF"],
  "correct_index": 1,
  "subject": "Databases",
  "topic": "Normalization",
  "difficulty": "medium",
  "explanation": "2NF removes partial dependency from a relation that is already in 1NF."
}
```

Rules:

- Use the exact subject strings from `backend/syllabus.py`.
- Use topic strings from that subject's topic list when possible.
- Use `correct_index` as 0-based: A = `0`, B = `1`, C = `2`, D = `3`.
- Keep options as exactly four strings.
- Keep `difficulty` as `easy`, `medium`, or `hard`.

### 4. Update AI Prompts

Search in `backend/llm_client.py` for SSC CGL-specific wording. Replace it with the target exam style.

For GATE, prompts should say things like:

```text
Generate GATE-style multiple-choice questions for the selected subject/topic.
Prefer conceptual and numerical questions where appropriate.
Return strict JSON with question, options, correct_index, subject, topic,
difficulty, and explanation.
```

Avoid asking the model to generate anything outside the app schema. The parser validates shape, but better prompts reduce bad output.

### 5. Decide PDF Behavior

Current PDF import is subject-only:

- user chooses a subject
- parser extracts questions/options/answers
- imported records get `topic: ""`
- imported PDFs stay in the **Imported PDFs** source

This works for any exam as long as PDFs have selectable text and answer markers. If the new exam needs topic-level PDF tagging, add a topic dropdown or an AI tagging pass, but subject-only is simpler and safer for large PDFs.

### 6. Keep Shared Database Import Generic

The import/export feature is already generic. A shared JSON database for GATE, banking, or any other exam works if the subjects match the new `backend/syllabus.py` values.

When importing a friend's database:

- existing duplicate questions are skipped
- new questions are appended
- imported shared database questions use `Imported database`
- they appear in Bank + images mode
- they are deletable from Question bank

### 7. Update UI Text

Search the frontend for old exam names:

```bash
rg "SSC|CGL|CGL Buddy|SSC CGL" frontend backend README.md main.py build .github
```

Update visible text in:

- `frontend/index.html`
- `frontend/script.js`
- `frontend/style.css` only if class names or labels mention the old exam
- `README.md`

Keep generic labels like `Subject`, `Topic`, `Question source`, `Question bank`, and `Imported PDFs` because they work across exams.

### 8. Update App Data Migration Carefully

`backend/paths.py` controls where user data is stored. For a hard rebrand, use a new app directory, such as `GATE_Buddy`.

If you want existing users to keep old data, add migration from the old folder to the new folder. If the new exam is unrelated, do not migrate old SSC data automatically because subjects will not match.

Recommended rule:

- Same app, renamed: migrate old data.
- New exam/product: start with a fresh app data folder.

### 9. Validate The Migration

Run:

```bash
source venv/bin/activate
python -m tests.smoke
python main.py
```

Manual checks:

- App opens with the new name.
- Subject dropdown shows the new taxonomy.
- Bank + images quiz works without API keys.
- Built-in bank questions match the selected subject.
- Shared JSON import appends new questions and skips duplicates.
- Imported database source is deletable.
- PDF import uses the new subject list.
- AI generation prompt produces questions for the new exam.
- Exported database can be imported again without duplicating questions.

## Generating A New Bank With AI

You can generate questions outside the app and save them as JSON. Use the portable schema above, then import the file through Question bank.

Suggested workflow:

1. Generate or collect MCQs for one subject/topic at a time.
2. Normalize them into the CGL Buddy JSON schema.
3. Validate the JSON with:

```bash
python -m json.tool your_database.json >/dev/null
```

4. Import through **Question bank → Import database**.
5. Browse the source and delete bad questions if needed.
6. Export a clean database to share.

For a built-in bank, copy vetted questions into `data/mcq_bank.json`. For a user-shareable bank, keep them in portable export JSON format.

## Reusing The App For Any Subject

The app is already close to exam-agnostic because it only assumes:

- questions are MCQs with four options
- answers are represented by `correct_index`
- questions belong to a subject
- topics are optional but useful
- difficulty is easy/medium/hard

To reuse it for any subject, define a new taxonomy, provide a matching question bank, update prompts/branding, and keep the same import/export and quiz engine.

## Quick Checklist

- [ ] Rename product/app title.
- [ ] Decide whether to use a new app data folder.
- [ ] Replace `backend/syllabus.py` subjects/topics.
- [ ] Replace `data/mcq_bank.json` with new exam questions.
- [ ] Update AI prompts in `backend/llm_client.py`.
- [ ] Update README and visible UI text.
- [ ] Build and smoke test locally.
- [ ] Test JSON database import/export and duplicate skipping.
- [ ] Test PDF import with the new subject list.
- [ ] Test packaged app on macOS/Windows.
