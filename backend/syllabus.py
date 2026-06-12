"""SSC CGL syllabus taxonomy: 4 main subjects and their subtopics.

This is the single source of truth for the subject/subtopic structure used
throughout the app (bank tagging, quiz building, live-generation prompts and
the setup UI). Subtopics are deliberately granular so a learner can practise a
single question type (e.g. "Time & Work" or "Percentage") instead of a whole
subject.

Topics are based on the SSC CGL Tier-I and Tier-II syllabus.
"""

from __future__ import annotations

from typing import Dict, List

# Canonical subject keys. Keep these stable: they are persisted in the MCQ bank,
# saved sessions and the config file.
REASONING = "General Intelligence & Reasoning"
QUANT = "Quantitative Aptitude"
ENGLISH = "English Comprehension"
GA = "General Awareness"

# subject -> ordered list of subtopics
SYLLABUS: Dict[str, List[str]] = {
    REASONING: [
        "Analogies",
        "Classification (Odd One Out)",
        "Series (Number & Alphabet)",
        "Coding-Decoding",
        "Blood Relations",
        "Direction Sense",
        "Ranking & Order",
        "Syllogism",
        "Venn Diagrams",
        "Seating Arrangement & Puzzles",
        "Statement & Conclusions",
        "Mathematical Operations",
        "Word Formation & Dictionary",
        "Non-Verbal (Mirror, Paper, Embedded)",
        "Cubes & Dice",
    ],
    QUANT: [
        "Number System",
        "Simplification (BODMAS, Surds & Indices)",
        "HCF & LCM",
        "Ratio & Proportion",
        "Percentage",
        "Average",
        "Profit, Loss & Discount",
        "Simple & Compound Interest",
        "Time & Work",
        "Pipes & Cisterns",
        "Time, Speed & Distance",
        "Trains, Boats & Streams",
        "Mixture & Alligation",
        "Partnership",
        "Problems on Ages",
        "Mensuration (2D & 3D)",
        "Geometry",
        "Trigonometry",
        "Height & Distance",
        "Algebra",
        "Data Interpretation",
    ],
    ENGLISH: [
        "Reading Comprehension",
        "Cloze Test",
        "Spotting Errors",
        "Sentence Improvement",
        "Fill in the Blanks",
        "Synonyms",
        "Antonyms",
        "Idioms & Phrases",
        "One Word Substitution",
        "Spelling Correction",
        "Active & Passive Voice",
        "Direct & Indirect Speech",
        "Para Jumbles (Sentence Rearrangement)",
    ],
    GA: [
        "History",
        "Geography",
        "Indian Polity",
        "Economics",
        "Physics",
        "Chemistry",
        "Biology",
        "Static GK",
        "Current Affairs",
        "Books & Authors",
        "Important Days",
        "Awards & Honours",
        "Sports",
        "Art & Culture",
        "Computer Knowledge",
    ],
}

# Subjects in the order they should appear in the UI.
SUBJECTS: List[str] = [REASONING, QUANT, ENGLISH, GA]


def subjects() -> List[str]:
    """All four SSC CGL subjects in display order."""
    return list(SUBJECTS)


def topics(subject: str) -> List[str]:
    """Subtopics for a subject, or [] if the subject is unknown/"All"."""
    return list(SYLLABUS.get(subject, []))


def is_subject(name: str) -> bool:
    return name in SYLLABUS


def is_topic(subject: str, topic: str) -> bool:
    return topic in SYLLABUS.get(subject, [])


def as_dict() -> Dict[str, List[str]]:
    """Serialisable taxonomy for the frontend: ``{subject: [topics...]}``."""
    return {s: list(ts) for s, ts in SYLLABUS.items()}
