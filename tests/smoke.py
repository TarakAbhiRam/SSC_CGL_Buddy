"""Quick smoke tests for the pure-logic backend modules.

Run with:  python -m tests.smoke   (after `pip install -r requirements.txt`)
Exercises JSON parsing/validation, scoring, and bank sampling without needing
any network, API key, or the embedding model.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import llm_client, mcq_bank, quiz_engine  # noqa: E402
from backend import question_store  # noqa: E402

def test_parse_clean_json():
    raw = (
        '[{"question":"2+2?","options":["1","2","3","4"],"correct_index":3,'
        '"topic":"Number System",'
        '"category":"Math","difficulty":"easy","explanation":"4."}]'
    )
    mcqs = llm_client.parse_mcqs(raw)
    assert len(mcqs) == 1, mcqs
    assert mcqs[0]["correct_index"] == 3
    assert mcqs[0]["topic"] == "Number System"


def test_parse_fenced_and_malformed_mixed():
    raw = (
        "```json\n"
        '[{"question":"ok?","options":["a","b","c","d"],"correct_index":0,'
        '"topic":"Reading Comprehension",'
        '"category":"X","difficulty":"weird","explanation":"e"},'
        '{"question":"bad","options":["only","two"],"correct_index":0}]'
        "\n```"
    )
    mcqs = llm_client.parse_mcqs(raw)
    # Malformed (2 options) dropped; difficulty normalised to "medium".
    assert len(mcqs) == 1, mcqs
    assert mcqs[0]["difficulty"] == "medium"


def test_parse_enforces_selected_topics():
    raw = (
        '[{"question":"rc?","options":["a","b","c","d"],"correct_index":1,'
        '"topic":"Reading Comprehension","category":"English Comprehension",'
        '"difficulty":"medium","explanation":"x"},'
        '{"question":"pj?","options":["a","b","c","d"],"correct_index":2,'
        '"topic":"Para Jumbles (Sentence Rearrangement)","category":"English Comprehension",'
        '"difficulty":"medium","explanation":"y"}]'
    )
    mcqs = llm_client.parse_mcqs(raw, allowed_topics=["Reading Comprehension"])
    assert len(mcqs) == 1, mcqs
    assert mcqs[0]["topic"] == "Reading Comprehension"


def test_validate_rejects_bad_index():
    assert llm_client.validate_mcq(
        {"question": "q", "options": ["a", "b", "c", "d"], "correct_index": 9}
    ) is None


def test_scoring():
    answer_key = {
        "q1": {"correct_index": 0, "category": "A", "difficulty": "easy",
               "explanation": "", "question": "q1", "options": ["a", "b", "c", "d"]},
        "q2": {"correct_index": 1, "category": "A", "difficulty": "easy",
               "explanation": "", "question": "q2", "options": ["a", "b", "c", "d"]},
        "q3": {"correct_index": 2, "category": "B", "difficulty": "hard",
               "explanation": "", "question": "q3", "options": ["a", "b", "c", "d"]},
    }
    responses = [
        {"id": "q1", "selected_index": 0, "time_spent_seconds": 5},   # correct
        {"id": "q2", "selected_index": 3, "time_spent_seconds": 8},   # wrong
        {"id": "q3", "selected_index": None, "time_spent_seconds": 2},  # skipped
    ]
    scored = quiz_engine.score_quiz(answer_key, responses)
    assert scored["score"] == 1, scored
    assert scored["total"] == 3
    assert scored["attempted"] == 2
    assert scored["skipped"] == 1
    assert scored["category_accuracy"]["A"]["total"] == 2
    assert scored["category_accuracy"]["A"]["correct"] == 1
    # Difficulty buckets are always reported (easy/medium/hard).
    da = scored["difficulty_accuracy"]
    assert set(da.keys()) == {"easy", "medium", "hard"}, da
    assert da["easy"]["total"] == 2 and da["easy"]["correct"] == 1, da
    assert da["hard"]["total"] == 1 and da["hard"]["correct"] == 0, da


def test_bank_sampling():
    subjects = mcq_bank.list_categories()
    assert subjects, "sample bank should ship with subjects"
    sample = mcq_bank.sample_questions(3, subject="All", difficulty="All", seed=42)
    assert len(sample) == 3
    # Filtering by a real subject returns only that subject.
    one = subjects[0]
    filtered = mcq_bank.sample_questions(50, subject=one, seed=1)
    assert all((q.get("subject") or q.get("category")) == one for q in filtered)


def test_bank_topic_filter():
    subjects = mcq_bank.list_categories()
    one = next((s for s in subjects if mcq_bank.list_topics(s)), None)
    assert one, "at least one subject should expose subtopics"
    topics = mcq_bank.list_topics(one)
    target = topics[0]
    filtered = mcq_bank.sample_questions(50, subject=one, topics=[target], seed=7)
    assert filtered, "topic filter should return at least one question"
    assert all(q.get("topic") == target for q in filtered)


def test_question_store_dedup():
    """The writable store skips duplicates (within itself and the bundled bank)."""
    src = "smoke test source"
    try:
        # A question identical to a bundled one must be skipped.
        bundled = mcq_bank.bundled_questions()[0]
        r1 = question_store.add_questions([bundled], source=src)
        assert r1["added"] == 0 and r1["skipped"] == 1, r1

        # A brand-new question is added once, then deduped on re-add.
        novel = {
            "question": "__smoke__ unique question 7x9 = ?",
            "options": ["61", "63", "65", "67"],
            "correct_index": 1,
            "subject": "Quantitative Aptitude",
            "topic": "Multiplication",
            "difficulty": "easy",
            "explanation": "63.",
        }
        r2 = question_store.add_questions([novel], source=src)
        assert r2["added"] == 1, r2
        r3 = question_store.add_questions([novel], source=src)
        assert r3["added"] == 0 and r3["skipped"] == 1, r3

        # Stored question is now visible to the merged bank.
        assert any(q.get("source") == src for q in question_store.list_questions(source=src))

        # Single-question delete by id removes exactly one.
        stored = question_store.list_questions(source=src)
        assert stored, "should have a stored question to delete"
        removed_one = question_store.delete_question(stored[0]["id"])
        assert removed_one == 1, removed_one
    finally:
        removed = question_store.delete_by_source(src)
        # After the single delete there may be 0 left; cleanup must not error.
        assert removed >= 0


def test_database_payload_import_dedup():
    """Portable database JSON can be imported while skipping duplicates."""
    src = mcq_bank.DATABASE_IMPORT_SOURCE
    original_store_path = question_store._store_path  # noqa: SLF001
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_store = Path(tmpdir) / "user_mcq.json"
        try:
            question_store._store_path = lambda: temp_store  # noqa: SLF001
            record = {
                "question": "__smoke__ portable db question?",
                "options": ["a", "b", "c", "d"],
                "correct_index": 2,
                "subject": "General Awareness",
                "topic": "Static GK",
                "difficulty": "medium",
                "explanation": "Because c.",
            }
            payload = {"format": question_store.EXPORT_FORMAT, "questions": [record, record]}
            records = question_store.records_from_payload(payload)
            result = question_store.add_questions(records, source=src)
            assert result == {"added": 1, "skipped": 1}, result
            exported = question_store.export_payload()
            assert exported["format"] == question_store.EXPORT_FORMAT
            assert exported["question_count"] == 1

            sample = mcq_bank.sample_questions(10, subject="General Awareness", source="bank", seed=3)
            assert any(q.get("source") == src for q in sample)
        finally:
            question_store._store_path = original_store_path  # noqa: SLF001


def test_pdf_imports_are_separate_from_bank_images():
    """Bank + images includes tagged image imports, while PDF imports stay separate."""
    subject = "__smoke__ source split"
    pdf_q = {
        "question": "__smoke__ pdf-only question?",
        "options": ["a", "b", "c", "d"],
        "correct_index": 0,
        "subject": subject,
        "difficulty": "medium",
        "explanation": "",
    }
    image_q = {
        "question": "__smoke__ image-bank question?",
        "options": ["a", "b", "c", "d"],
        "correct_index": 1,
        "subject": subject,
        "topic": "Tagged topic",
        "difficulty": "easy",
        "explanation": "",
    }
    original_store_path = question_store._store_path  # noqa: SLF001
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_store = Path(tmpdir) / "user_mcq.json"
        try:
            question_store._store_path = lambda: temp_store  # noqa: SLF001
            question_store.add_questions([pdf_q], source=mcq_bank.PDF_IMPORT_SOURCE)
            question_store.add_questions([image_q], source=mcq_bank.IMAGE_IMPORT_SOURCE)

            bank_questions = mcq_bank.sample_questions(10, subject=subject, source="bank", seed=1)
            pdf_questions = mcq_bank.sample_questions(10, subject=subject, source="pdf", seed=1)
            assert [q["question"] for q in bank_questions] == [image_q["question"]]
            assert [q["question"] for q in pdf_questions] == [pdf_q["question"]]
        finally:
            question_store._store_path = original_store_path  # noqa: SLF001


def test_ai_generated_questions_are_in_full_bank():
    """Full question bank must include AI-generated questions saved to the store."""
    subject = "__smoke__ ai in full bank"
    ai_q = {
        "question": "__smoke__ AI generated should appear in full bank?",
        "options": ["a", "b", "c", "d"],
        "correct_index": 2,
        "subject": subject,
        "difficulty": "medium",
        "explanation": "",
    }
    original_store_path = question_store._store_path  # noqa: SLF001
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_store = Path(tmpdir) / "user_mcq.json"
        try:
            question_store._store_path = lambda: temp_store  # noqa: SLF001
            question_store.add_questions([ai_q], source="AI generated")

            bank_questions = mcq_bank.sample_questions(10, subject=subject, source="bank", seed=11)
            assert any(q.get("question") == ai_q["question"] for q in bank_questions), bank_questions
        finally:
            question_store._store_path = original_store_path  # noqa: SLF001


def test_ai_retag_backfills_subject_and_topic():
    """Legacy AI rows should be retagged to canonical subject/topic when possible."""
    original_store_path = question_store._store_path  # noqa: SLF001
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_store = Path(tmpdir) / "user_mcq.json"
        try:
            question_store._store_path = lambda: temp_store  # noqa: SLF001
            question_store.add_questions([
                {
                    "question": "Arrange the following sentences to form a meaningful paragraph.",
                    "options": ["A", "B", "C", "D"],
                    "correct_index": 0,
                    "category": "English",
                    "difficulty": "medium",
                    "explanation": "",
                }
            ], source="AI generated")
            changed = question_store.retag_ai_questions()
            assert changed >= 1
            rows = question_store.list_questions(source="AI generated")
            assert rows and rows[0].get("subject") == "English Comprehension", rows
            assert rows[0].get("topic") == "Para Jumbles (Sentence Rearrangement)", rows
        finally:
            question_store._store_path = original_store_path  # noqa: SLF001


def test_pdf_text_mcq_parser():
    """Digital PDF text is parsed into bank-ready MCQs without network calls."""
    from backend import pdf_processor

    text = """Q1. What is the capital of India?
(A) Mumbai
(B) New Delhi
(C) Kolkata
(D) Chennai
Ans. (B)

2. Largest planet? (1) Earth (2) Jupiter (3) Mars (4) Venus
Correct answer: 2"""
    records = pdf_processor.parse_mcqs_from_text(text)
    assert len(records) == 2, records
    assert records[0]["question"] == "What is the capital of India?"
    assert records[0]["options"] == ["Mumbai", "New Delhi", "Kolkata", "Chennai"]
    assert records[0]["correct_index"] == 1
    assert records[1]["question"] == "Largest planet?"
    assert records[1]["options"] == ["Earth", "Jupiter", "Mars", "Venus"]
    assert records[1]["correct_index"] == 1


def test_vision_import_helpers():
    """Render helpers + guards + empty-image short-circuit (no network)."""
    import tempfile
    import fitz  # PyMuPDF
    from backend import pdf_processor

    # Empty image list returns no MCQs and never touches the network.
    assert llm_client.extract_mcqs_from_images([], None, "fake-key") == []

    # Extract prompt advertises the required schema keys.
    prompt = llm_client.build_extract_prompt("Quantitative Aptitude")
    for key in ("question", "options", "correct_index", "difficulty"):
        assert key in prompt, key

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # Single image -> normalised PNG bytes.
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30))
        pix.clear_with(255)
        img_path = tmp / "snippet.png"
        pix.save(str(img_path))
        png = pdf_processor.render_image_png(img_path)
        assert png[:8] == b"\x89PNG\r\n\x1a\n", "expected PNG signature"

        # Small PDF -> one PNG per page.
        doc = fitz.open()
        doc.new_page()
        pdf_path = tmp / "one.pdf"
        doc.save(str(pdf_path))
        doc.close()
        pages = pdf_processor.render_pdf_pages_png(pdf_path)
        assert len(pages) == 1 and pages[0]["png"][:4] == b"\x89PNG", pages

        # Too many pages -> ImportTooLarge.
        doc = fitz.open()
        for _ in range(pdf_processor.MAX_OCR_PAGES + 1):
            doc.new_page()
        big_path = tmp / "big.pdf"
        doc.save(str(big_path))
        doc.close()
        try:
            pdf_processor.render_pdf_pages_png(big_path)
            raise AssertionError("expected ImportTooLarge for over-cap PDF")
        except pdf_processor.ImportTooLarge:
            pass


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR {t.__name__}: {exc!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
