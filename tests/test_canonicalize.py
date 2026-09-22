from pathlib import Path

from padel_availability.canonicalize import (
    candidate_signature,
    normalize_text,
    suggest_duplicate_pairs,
)
from padel_availability.inventory import load_candidates
from padel_availability.models import CandidateEntry


def test_normalize_text_handles_case_accents_and_punctuation() -> None:
    assert normalize_text("Vaudoise aréna") == "vaudoise arena"
    assert normalize_text("  Padel-Station / Chêne-Bourg  ") == "padel station chene bourg"


def test_normalize_text_turns_unicode_punctuation_into_separators() -> None:
    assert normalize_text("Padel—Station⁄Court") == "padel station court"


def test_normalize_text_preserves_non_latin_letters() -> None:
    assert normalize_text("Падел клуб") == "падел клуб"


def test_candidate_signature_normalizes_name_and_municipality() -> None:
    assert candidate_signature("Padel-Station", "Chêne-Bourg") == (
        "padel station",
        "chene bourg",
    )


def test_duplicate_suggestions_include_close_variants_in_same_municipality() -> None:
    entries = (
        CandidateEntry("site-b", "Padel Station", "Chêne-Bourg", None, None, None),
        CandidateEntry("site-a", "Padel-Station", "Chene Bourg", None, None, None),
    )

    assert suggest_duplicate_pairs(entries) == (("site-a", "site-b"),)
    assert entries[0].raw_name == "Padel Station"


def test_duplicate_suggestions_reject_below_threshold() -> None:
    entries = (
        CandidateEntry("site-a", "Padel Alpha", "Geneva", None, None, None),
        CandidateEntry("site-b", "Tennis Omega", "Geneva", None, None, None),
    )

    assert suggest_duplicate_pairs(entries) == ()


def test_duplicate_suggestions_require_matching_normalized_municipality() -> None:
    entries = (
        CandidateEntry("site-a", "Padel Station", "Genève", None, None, None),
        CandidateEntry("site-b", "Padel Station", "Lausanne", None, None, None),
    )

    assert suggest_duplicate_pairs(entries) == ()


def test_duplicate_suggestions_do_not_merge_distinct_airpad_sites() -> None:
    entries = load_candidates(Path("data/candidates.json"))
    suggestions = suggest_duplicate_pairs(entries)

    assert ("airpad-les-acacias", "airpad-la-praille") not in suggestions
