import json
from collections.abc import Sequence

from .models import CandidateMatch, LocationRecord, VerificationRun

_TRI_STATE_LABELS = {"yes": "Oui", "no": "Non", "unknown": "Inconnu"}
_TRI_STATE_FIELDS = (
    ("membership_required", "Adhésion requise"),
    ("public_booking", "Réservation publique"),
    ("racket_rental", "Location de raquettes"),
    ("locker_rooms", "Vestiaires"),
    ("booking_account_required", "Compte requis"),
)
_MARKDOWN_SPECIAL = frozenset("\\`*_{}[]()<>#!|~")


def _sorted_locations(locations: Sequence[LocationRecord]) -> tuple[LocationRecord, ...]:
    return tuple(
        sorted(
            locations,
            key=lambda item: (item.municipality, item.canonical_name, item.location_id),
        )
    )


def _sorted_matches(matches: Sequence[CandidateMatch]) -> tuple[CandidateMatch, ...]:
    return tuple(sorted(matches, key=lambda item: item.candidate_id))


def _location_title(location: LocationRecord) -> str:
    return f"{location.canonical_name} ({location.municipality})"


def _escape(value: object) -> str:
    text = str(value).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return "".join(f"\\{char}" if char in _MARKDOWN_SPECIAL else char for char in text)


def _link(label: str, url: str) -> str:
    destination = url.replace("\\", "\\\\").replace("<", "\\<").replace(">", "\\>")
    return f"[{_escape(label)}](<{destination}>)"


def _location_facts(location: LocationRecord) -> list[str]:
    access = "Inconnu" if location.access_kind == "unknown" else _escape(location.access_kind)
    facts = [
        f"- Location ID: {_escape(location.location_id)}",
        f"- Candidate IDs: {', '.join(_escape(item) for item in location.candidate_ids)}",
        f"- Statut: {_escape(location.verification_status)}",
        f"- Accès: {access}",
    ]
    for field, label in _TRI_STATE_FIELDS:
        facts.append(f"- {label}: {_TRI_STATE_LABELS[getattr(location, field)]}")
    cover = (
        "Inconnu"
        if location.overall_cover_status == "unknown"
        else _escape(location.overall_cover_status)
    )
    facts.append(f"- Couverture: {cover}")
    if location.court_groups:
        courts = ", ".join(
            f"{_escape(group.label)} ({group.count})"
            for group in sorted(location.court_groups, key=lambda item: item.label)
        )
        facts.append(f"- Courts: {courts}")
    else:
        facts.append("- Courts: Inconnu")
    if location.address:
        facts.append(f"- Adresse: {_escape(location.address)}")
    if location.official_url:
        facts.append(f"- Site officiel: {_link(location.official_url, location.official_url)}")
    if location.booking_url:
        facts.append(f"- Réservation: {_link(location.booking_url, location.booking_url)}")
    if location.booking_platform:
        facts.append(f"- Plateforme: {_escape(location.booking_platform)}")
    if location.notes:
        facts.append(f"- Notes: {_escape(location.notes)}")
    return facts


def _unknown_facts(location: LocationRecord) -> list[str]:
    facts: list[str] = []
    if location.access_kind == "unknown":
        facts.append("access_kind")
    facts.extend(field for field, _ in _TRI_STATE_FIELDS if getattr(location, field) == "unknown")
    if location.overall_cover_status == "unknown":
        facts.append("overall_cover_status")
    if not location.court_groups:
        facts.append("court_groups")
    for field in ("brand", "address", "official_url", "booking_url", "booking_platform"):
        if getattr(location, field) is None:
            facts.append(field)
    return sorted(facts)


def _markdown_location_group(locations: Sequence[LocationRecord], heading: str) -> list[str]:
    lines = [heading]
    if not locations:
        return lines + ["Aucune.", ""]
    for location in locations:
        lines.extend([f"### {_escape(_location_title(location))}", *_location_facts(location), ""])
    return lines


def render_markdown_report(
    locations: Sequence[LocationRecord],
    candidate_matches: Sequence[CandidateMatch],
    run: VerificationRun,
) -> str:
    ordered_locations = _sorted_locations(locations)
    ordered_matches = _sorted_matches(candidate_matches)
    lines = ["# Padel Availability Inventory", "", "## Summary"]
    lines.extend(
        [
            f"- Verification run: {_escape(run.run_id)}",
            f"- Started (UTC): {_escape(run.started_at)}",
            f"- Ended (UTC): {_escape(run.ended_at)}",
            f"- Candidates: {run.candidate_count}",
            f"- Locations: {len(ordered_locations)}",
            f"- Errors: {run.error_count}",
            f"- Summary: {_escape(run.summary or 'Unknown')}",
            "",
        ]
    )

    confirmed = tuple(
        location
        for location in ordered_locations
        if location.verification_status in {"confirmed", "probable"}
    )
    lines.append("## Locations")
    lines.extend(_markdown_location_group(confirmed, "### Confirmed and probable locations"))
    lines.extend(
        _markdown_location_group(
            tuple(
                location
                for location in ordered_locations
                if location.verification_status in {"to_verify", "not_confirmed", "closed"}
            ),
            "## Locations to verify or closed",
        )
    )

    lines.append("## Duplicate and alias decisions")
    lines.append("### Candidate decisions")
    decisions: list[str] = []
    for match in ordered_matches:
        target = match.location_id or "none"
        decisions.append(
            f"- Candidate {_escape(match.candidate_id)}: {_escape(match.status)} -> "
            f"{_escape(target)} ({_escape(match.note)})"
        )
    lines.extend(decisions or ["Aucune."])
    lines.append("### Aliases")
    aliases: list[str] = []
    for location in ordered_locations:
        if location.aliases:
            aliases.append(
                f"- {_escape(_location_title(location))} aliases: "
                f"{', '.join(_escape(alias) for alias in sorted(location.aliases))}"
            )
    lines.extend(aliases or ["Aucune."])
    lines.append("")

    lines.append("## Missing or unknown facts")
    lines.append("Unknown values are rendered as `Inconnu`.")
    unknown_lines = [
        f"- {_escape(_location_title(location))}: {', '.join(_unknown_facts(location))}"
        for location in ordered_locations
        if _unknown_facts(location)
    ]
    lines.extend(unknown_lines or ["Aucun."])
    lines.append("")

    lines.append("## Source evidence and contradictions")
    lines.append("### Unresolved candidates")
    unresolved = [
        f"- {_escape(match.candidate_id)}: {_escape(match.note)}"
        for match in ordered_matches
        if match.status in {"not_confirmed", "unresolved"}
    ]
    lines.extend(unresolved or ["Aucun."])
    lines.append("### Sources")
    evidence = sorted(
        ((location, item) for location in ordered_locations for item in location.evidence),
        key=lambda pair: (
            pair[1].url,
            pair[1].fact_key,
            pair[1].checked_at,
            pair[1].evidence,
            pair[1].title,
            pair[1].source_type,
            pair[1].relation,
            pair[1].confidence,
            pair[0].location_id,
        ),
    )
    for location, item in evidence:
        lines.append(
            f"- {_escape(_location_title(location))}: {_link(item.title, item.url)} — "
            f"{_escape(item.fact_key)} — "
            f"{_escape(item.relation)}; {_escape(item.evidence)} "
            f"(vérifié: {_escape(item.checked_at)})"
        )
    if not evidence:
        lines.append("Aucune.")
    lines.append("### Warnings and contradictions")
    contradictions = sorted(
        ((location, item) for location, item in evidence if item.relation == "contradicts"),
        key=lambda pair: (
            pair[1].url,
            pair[1].fact_key,
            pair[1].checked_at,
            pair[1].evidence,
            pair[1].title,
            pair[1].source_type,
            pair[1].relation,
            pair[1].confidence,
            pair[0].location_id,
        ),
    )
    for location, item in contradictions:
        lines.append(
            f"- {_escape(_location_title(location))}: {_escape(item.fact_key)} via "
            f"{_link(item.title, item.url)}: "
            f"{_escape(item.evidence)}"
        )
    if not contradictions:
        lines.append("Aucune.")
    lines.append("")
    return "\n".join(lines)


def _location_mapping(location: LocationRecord) -> dict[str, object]:
    mapping = location.to_mapping()
    mapping["candidate_ids"] = sorted(location.candidate_ids)
    mapping["aliases"] = sorted(location.aliases)
    mapping["court_groups"] = [
        group.to_mapping() for group in sorted(location.court_groups, key=lambda item: item.label)
    ]
    mapping["evidence"] = [
        item.to_mapping()
        for item in sorted(
            location.evidence,
            key=lambda item: (
                item.url,
                item.fact_key,
                item.checked_at,
                item.evidence,
                item.title,
                item.source_type,
                item.relation,
                item.confidence,
            ),
        )
    ]
    return mapping


def render_json_report(
    locations: Sequence[LocationRecord],
    candidate_matches: Sequence[CandidateMatch],
    run: VerificationRun,
) -> str:
    payload = {
        "candidate_matches": [
            {
                "candidate_id": match.candidate_id,
                "location_id": match.location_id,
                "status": match.status,
                "note": match.note,
            }
            for match in _sorted_matches(candidate_matches)
        ],
        "locations": [_location_mapping(location) for location in _sorted_locations(locations)],
        "verification_run": {
            "run_id": run.run_id,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "candidate_count": run.candidate_count,
            "location_count": len(locations),
            "error_count": run.error_count,
            "summary": run.summary,
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
