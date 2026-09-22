import unicodedata
from collections.abc import Sequence
from difflib import SequenceMatcher
from itertools import combinations

from .models import CandidateEntry


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    casefolded = without_marks.casefold()
    separated = "".join(
        " " if unicodedata.category(character).startswith(("P", "S")) else character
        for character in casefolded
    )
    return " ".join(separated.split())


def candidate_signature(name: str, municipality: str) -> tuple[str, str]:
    return normalize_text(name), normalize_text(municipality)


def suggest_duplicate_pairs(
    entries: Sequence[CandidateEntry],
) -> tuple[tuple[str, str], ...]:
    signatures = [
        (entry.candidate_id, *candidate_signature(entry.raw_name, entry.municipality))
        for entry in entries
    ]
    suggestions: list[tuple[str, str]] = []
    for left, right in combinations(signatures, 2):
        if left[2] != right[2]:
            continue
        if SequenceMatcher(None, left[1], right[1]).ratio() >= 0.88:
            suggestions.append((min(left[0], right[0]), max(left[0], right[0])))
    return tuple(sorted(suggestions))
