"""LLM abstraction: a single ``generate_mcqs`` entry point over Gemini & Groq.

Both providers are instructed to return ONLY a JSON array of MCQs. Responses are
defensively parsed (markdown fences stripped, first JSON array extracted),
validated against a strict schema, and malformed items are skipped. Provider
calls are retried with exponential backoff.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from . import syllabus

log = logging.getLogger("CGL_Buddy.llm")

VALID_PROVIDERS = ("gemini", "groq")
GEMINI_MODEL = "gemini-2.5-flash"
GROQ_MODEL = "llama-3.1-8b-instant"


class LLMError(RuntimeError):
    """Provider call failed (auth, network, rate limit, etc.)."""


# --- Prompt -----------------------------------------------------------------

def build_prompt(
    context_chunks: List[str],
    num_questions: int,
    category: Optional[str],
    difficulty: Optional[str],
    topics: Optional[List[str]] = None,
) -> str:
    context = "\n\n---\n\n".join(context_chunks) if context_chunks else "(no extra context)"
    subject = category if category and category != "All" else "any of the four SSC CGL subjects"
    diff = difficulty if difficulty and difficulty != "All" else "a mix of easy, medium and hard"
    topic_choices = list(topics or [])
    if (not topic_choices) and category and category != "All":
        topic_choices = syllabus.topics(category)
    topic_line = ""
    if topic_choices:
        topic_line = (
            "\nUse only these valid subtopics for the topic field (pick the best one per question): "
            + ", ".join(topic_choices) + "."
        )
    return f"""You are a question setter for the Staff Selection Commission Combined Graduate
Level (SSC CGL) Tier-1 examination in India. Write {num_questions} multiple-choice
questions on "{subject}" at {diff} difficulty.{topic_line}

These MUST match the real SSC CGL exam style:
- Exam-grade, India-centric content. Reasoning = analogies/series/coding-decoding/
  classification/syllogism/figures; Quantitative Aptitude = arithmetic, algebra,
  geometry, mensuration, trigonometry, data interpretation; English = grammar,
  vocabulary, comprehension as tested by SSC; General Awareness = Indian history,
  polity, geography, economy, static GK, general science, and current affairs.
- Each question must be self-contained, exam-appropriate, and unambiguous — NOT
  generic trivia. Quant/reasoning questions should require actual calculation or
  logic, like a real SSC paper.
- Do NOT cross-reference questions (no "as in question 3", "from previous
    passage", "refer above", "Q1-Q5" style linkage).
- Every question must be independent. If a question uses a passage/case/data
    block, include the full passage/case inside that same question text.
- For passage-style sets, repeat the full passage for each affected question
    instead of sharing one common passage across multiple questions.
- Plausible distractors (common mistakes), with exactly one correct option.
- Vary the position of the correct option across questions.

Output rules:
- Return ONLY a JSON array. No prose, no markdown, no code fences.

Each element must be an object with EXACTLY these keys:
  "question":      string
  "options":       array of exactly 4 strings
  "correct_index": integer 0-3 (index of the correct option)
  "category":      string (the SSC CGL subject)
    "topic":         string (subtopic tag)
  "difficulty":    one of "easy", "medium", "hard"
  "explanation":   string (1-2 sentences on why the answer is correct)

Topic tagging rules:
- "topic" is mandatory for every question.
- If subtopics were provided, "topic" must be one of: {", ".join(topic_choices) if topic_choices else "(infer the best SSC subtopic for the question)"}.
- Do not leave "topic" empty.

Reference material (use as inspiration for style/topics; do not copy verbatim):
{context}
"""


def build_extract_prompt(category: Optional[str] = None) -> str:
    """Prompt for reading MCQs out of scanned page / image snippets (vision)."""
    cat = category if category and category != "All" else "the appropriate SSC subject"
    return f"""You are an expert SSC exam assistant. The attached image(s) are scanned
exam pages or snippets from a question paper / question bank. Read them and extract
EVERY complete multiple-choice question you can find — there may be just one, or many.

Rules:
- Only include questions that have a clear stem and exactly 4 options.
- If the correct answer is marked or indicated, use it; otherwise choose the option
  you are confident is correct.
- Transcribe text faithfully and fix obvious OCR glitches.
- Skip page headers/footers, ads, watermarks, page numbers, and incomplete questions.
- Return ONLY a JSON array. No prose, no markdown, no code fences.

Each element must be an object with EXACTLY these keys:
  "question":      string
  "options":       array of exactly 4 strings
  "correct_index": integer 0-3 (index of the correct option)
  "category":      string (the subject, e.g. "{cat}")
  "difficulty":    one of "easy", "medium", "hard"
  "explanation":   string (1-2 sentences on why the answer is correct)

If you cannot read any complete question, return an empty array [].
"""


# --- Provider calls ---------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
def _call_gemini(prompt: str, api_key: str) -> str:
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = model.generate_content(
            prompt,
            generation_config={"temperature": 0.4, "response_mime_type": "application/json"},
        )
        return resp.text or ""
    except Exception as exc:  # noqa: BLE001 - normalise provider-specific errors
        raise LLMError(f"Gemini request failed: {exc}") from exc


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
def _call_gemini_vision(image_parts: List[Dict[str, Any]], prompt: str, api_key: str) -> str:
    """Send image(s) + a prompt to the (multimodal) Gemini model.

    ``image_parts`` is a list of ``{"mime_type": str, "data": bytes}`` blobs.
    """
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = model.generate_content(
            [prompt, *image_parts],
            generation_config={"temperature": 0.2, "response_mime_type": "application/json"},
        )
        return resp.text or ""
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"Gemini vision request failed: {exc}") from exc


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
def _call_groq(prompt: str, api_key: str) -> str:
    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert question setter for India's SSC CGL Tier-1 exam. "
                        "You produce authentic, exam-grade, India-centric MCQs that match the "
                        "real SSC CGL pattern and difficulty — never generic trivia. You always "
                        "reply with ONLY a JSON array of question objects."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"Groq request failed: {exc}") from exc


def _call_provider(prompt: str, provider: str, api_key: str) -> str:
    provider = (provider or "").lower()
    if provider not in VALID_PROVIDERS:
        raise LLMError(f"Unknown provider: {provider!r}")
    if not api_key:
        raise LLMError(f"No API key configured for {provider}.")
    log.debug("calling %s (prompt %d chars)", provider, len(prompt))
    raw = _call_gemini(prompt, api_key) if provider == "gemini" else _call_groq(prompt, api_key)
    log.debug("%s raw response (%d chars): %s", provider, len(raw), raw[:500])
    return raw


# --- Parsing & validation ---------------------------------------------------

def _extract_json_array(raw: str) -> Any:
    """Best-effort: strip fences and pull out the first JSON array/object."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError("No JSON array found in model response.")


def _coerce_list(parsed: Any) -> List[Dict[str, Any]]:
    """Accept a bare array, or an object wrapping the array under a common key."""
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("questions", "mcqs", "items", "data"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
        # Single question object
        if "question" in parsed and "options" in parsed:
            return [parsed]
    return []


def _canon_topic(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _match_allowed_topic(topic: str, allowed_topics: List[str]) -> Optional[str]:
    if not topic:
        return None
    want = _canon_topic(topic)
    for candidate in allowed_topics:
        if _canon_topic(candidate) == want:
            return candidate
    # Accept close variants such as "para jumble" vs canonical long label.
    want_tokens = set(re.findall(r"[a-z0-9]+", want))
    for candidate in allowed_topics:
        cand = _canon_topic(candidate)
        cand_tokens = set(re.findall(r"[a-z0-9]+", cand))
        if want in cand or cand in want:
            return candidate
        if want_tokens and len(want_tokens & cand_tokens) >= max(1, min(2, len(want_tokens))):
            return candidate
    return None


def _canonical_subject(raw: str, requested_category: Optional[str]) -> str:
    if requested_category and requested_category != "All":
        return requested_category
    text = (raw or "").strip().lower()
    if not text:
        return "General"
    aliases = {
        "general intelligence & reasoning": syllabus.REASONING,
        "reasoning": syllabus.REASONING,
        "general intelligence": syllabus.REASONING,
        "quantitative aptitude": syllabus.QUANT,
        "quant": syllabus.QUANT,
        "math": syllabus.QUANT,
        "mathematics": syllabus.QUANT,
        "english comprehension": syllabus.ENGLISH,
        "english": syllabus.ENGLISH,
        "general awareness": syllabus.GA,
        "gk": syllabus.GA,
        "ga": syllabus.GA,
    }
    return aliases.get(text, raw.strip() or "General")


def validate_mcq(
    item: Any,
    allowed_topics: Optional[List[str]] = None,
    requested_category: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return a normalised MCQ dict, or None if invalid."""
    if not isinstance(item, dict):
        return None
    question = item.get("question")
    options = item.get("options")
    correct_index = item.get("correct_index")
    if not isinstance(question, str) or not question.strip():
        return None
    if not isinstance(options, list) or len(options) != 4:
        return None
    if not all(isinstance(o, str) and o.strip() for o in options):
        return None
    if not isinstance(correct_index, int) or not (0 <= correct_index <= 3):
        return None
    difficulty = item.get("difficulty")
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "medium"

    topic = str(item.get("topic") or "").strip()
    if not topic:
        return None
    if allowed_topics:
        matched = _match_allowed_topic(topic, allowed_topics)
        if not matched:
            return None
        topic = matched

    category = _canonical_subject(str(item.get("category") or "General"), requested_category)

    return {
        "question": question.strip(),
        "options": [o.strip() for o in options],
        "correct_index": correct_index,
        "category": category,
        "topic": topic,
        "difficulty": difficulty,
        "explanation": str(item.get("explanation") or "").strip(),
    }


def parse_mcqs(
    raw: str,
    allowed_topics: Optional[List[str]] = None,
    requested_category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Parse + validate a raw model response into clean MCQs (malformed skipped)."""
    parsed = _extract_json_array(raw)
    items = _coerce_list(parsed)
    valid: List[Dict[str, Any]] = []
    for item in items:
        mcq = validate_mcq(
            item,
            allowed_topics=allowed_topics,
            requested_category=requested_category,
        )
        if mcq:
            valid.append(mcq)
    return valid


# --- Public entry point ------------------------------------------------------

def generate_mcqs(
    context_chunks: List[str],
    num_questions: int,
    category: Optional[str],
    difficulty: Optional[str],
    provider: str,
    api_key: str,
    topics: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Generate validated MCQs via the selected provider.

    Raises ``LLMError`` if the provider call fails after retries.
    Returns only schema-valid MCQs (malformed ones are dropped).
    """
    allowed_topics = list(topics or [])
    if (not allowed_topics) and category and category != "All":
        allowed_topics = syllabus.topics(category)

    prompt = build_prompt(context_chunks, num_questions, category, difficulty, topics)
    raw = _call_provider(prompt, provider, api_key)
    try:
        return parse_mcqs(raw, allowed_topics=allowed_topics, requested_category=category)
    except (ValueError, json.JSONDecodeError):
        # One corrective retry: re-ask via the same provider before giving up.
        raw_retry = _call_provider(
            prompt + "\n\nReturn ONLY a valid JSON array and include a valid topic field on every item.",
            provider,
            api_key,
        )
        return parse_mcqs(raw_retry, allowed_topics=allowed_topics, requested_category=category)


def extract_mcqs_from_images(
    image_parts: List[Dict[str, Any]],
    category: Optional[str],
    api_key: str,
) -> List[Dict[str, Any]]:
    """Read MCQs out of scanned page/image blobs via Gemini vision.

    ``image_parts`` is a list of ``{"mime_type": str, "data": bytes}``. Returns
    validated MCQs (malformed ones dropped); ``[]`` if nothing readable.
    Raises ``LLMError`` if the provider call fails after retries.
    """
    if not image_parts:
        return []
    if not api_key:
        raise LLMError("No Gemini API key configured for image extraction.")
    prompt = build_extract_prompt(category)
    raw = _call_gemini_vision(image_parts, prompt, api_key)
    try:
        return parse_mcqs(raw)
    except (ValueError, json.JSONDecodeError):
        return []


def test_api_key(provider: str, api_key: str) -> Dict[str, Any]:
    """Lightweight validation of a provider key. Returns ``{ok, message}``."""
    try:
        raw = _call_provider(
            'Return ONLY this JSON array: [{"question":"2+2?","options":["1","2","3","4"],'
            '"correct_index":3,"category":"Math","difficulty":"easy","explanation":"2+2=4."}]',
            provider,
            api_key,
        )
        mcqs = parse_mcqs(raw)
        if mcqs:
            return {"ok": True, "message": f"{provider} key works."}
        return {"ok": False, "message": f"{provider} responded but output was unparseable."}
    except LLMError as exc:
        return {"ok": False, "message": str(exc)}
