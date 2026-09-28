from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Literal, cast
from urllib.parse import urlparse


class ModelError(ValueError):
    pass


TriState = Literal["yes", "no", "unknown"]
AccessKind = Literal["public", "members", "university", "conditions", "unknown"]
CoverStatus = Literal["indoor", "outdoor", "partially_covered", "seasonal", "unknown"]
VerificationStatus = Literal["confirmed", "probable", "to_verify", "not_confirmed", "closed"]
EvidenceRelation = Literal["supports", "contradicts", "discovery"]
Confidence = Literal["confirmed", "probable", "to_verify"]
MatchStatus = Literal["matched", "duplicate", "not_confirmed", "unresolved"]

_TRI_STATES = {"yes", "no", "unknown"}
_ACCESS_KINDS = {"public", "members", "university", "conditions", "unknown"}
_COVER_STATUSES = {"indoor", "outdoor", "partially_covered", "seasonal", "unknown"}
_VERIFICATION_STATUSES = {"confirmed", "probable", "to_verify", "not_confirmed", "closed"}
_EVIDENCE_RELATIONS = {"supports", "contradicts", "discovery"}
_CONFIDENCES = {"confirmed", "probable", "to_verify"}
_MATCH_STATUSES = {"matched", "duplicate", "not_confirmed", "unresolved"}


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ModelError(f"{field} must be a non-empty string")
    return value


def _optional_text(value: object, field: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ModelError(f"{field} must be a string or null")
    return value


def _literal(value: object, field: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ModelError(f"{field} has invalid value: {value!r}")
    return value


def _url(value: object, field: str) -> str:
    value = _text(value, field)
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as error:
        raise ModelError(f"{field} must be an absolute HTTP(S) URL") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or any(char.isspace() for char in value)
        or port is not None
        and parsed.hostname is None
    ):
        raise ModelError(f"{field} must be an absolute HTTP(S) URL")
    return value


def _optional_url(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _url(value, field)


def _strings(values: object, field: str, *, allow_list: bool = False) -> tuple[str, ...]:
    if not isinstance(values, tuple) and not (allow_list and isinstance(values, list)):
        raise ModelError(f"{field} must be a tuple")
    result = tuple(cast(tuple[object, ...] | list[object], values))
    if not all(isinstance(value, str) and value.strip() for value in result):
        raise ModelError(f"{field} must contain non-empty strings")
    result = cast(tuple[str, ...], result)
    if len(set(result)) != len(result):
        raise ModelError(f"{field} must not contain duplicate values")
    return result


def _utc_timestamp(value: object, field: str) -> str:
    value = _text(value, field)
    if not value.endswith("Z"):
        raise ModelError(f"{field} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise ModelError(f"{field} must be an ISO-8601 UTC timestamp ending in Z") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
        raise ModelError(f"{field} must be an ISO-8601 UTC timestamp ending in Z")
    return value


# Public entry points for validators shared with connector modules.
validate_text = _text
validate_optional_text = _optional_text
validate_literal = _literal
validate_url = _url
validate_utc_timestamp = _utc_timestamp


@dataclass(frozen=True, slots=True)
class CandidateEntry:
    candidate_id: str
    raw_name: str
    municipality: str
    courts_text: str | None
    type_text: str | None
    access_text: str | None

    def __post_init__(self) -> None:
        _text(self.candidate_id, "candidate_id")
        _text(self.raw_name, "raw_name")
        _text(self.municipality, "municipality")
        _optional_text(self.courts_text, "courts_text")
        _optional_text(self.type_text, "type_text")
        _optional_text(self.access_text, "access_text")


@dataclass(frozen=True, slots=True)
class CourtGroup:
    label: str
    count: int
    format: str | None
    cover_status: CoverStatus

    def __post_init__(self) -> None:
        _text(self.label, "label")
        if not isinstance(cast(object, self.count), int) or self.count <= 0:
            raise ModelError("count must be a positive integer")
        _optional_text(self.format, "format")
        _literal(self.cover_status, "cover_status", _COVER_STATUSES)

    def to_mapping(self) -> dict[str, object]:
        return {
            "label": self.label,
            "count": self.count,
            "format": self.format,
            "cover_status": self.cover_status,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, object]) -> "CourtGroup":
        try:
            return cls(
                label=cast(str, mapping["label"]),
                count=cast(int, mapping["count"]),
                format=cast(str | None, mapping["format"]),
                cover_status=cast(CoverStatus, mapping["cover_status"]),
            )
        except KeyError as error:
            raise ModelError(f"missing court group key: {error.args[0]}") from error


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    url: str
    source_type: str
    title: str
    checked_at: str
    fact_key: str
    relation: EvidenceRelation
    evidence: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _url(self.url, "url")
        for field in ("source_type", "title", "checked_at", "fact_key", "evidence"):
            _text(getattr(self, field), field)
        _utc_timestamp(self.checked_at, "checked_at")
        _literal(self.relation, "relation", _EVIDENCE_RELATIONS)
        _literal(self.confidence, "confidence", _CONFIDENCES)

    def to_mapping(self) -> dict[str, object]:
        return {
            "url": self.url,
            "source_type": self.source_type,
            "title": self.title,
            "checked_at": self.checked_at,
            "fact_key": self.fact_key,
            "relation": self.relation,
            "evidence": self.evidence,
            "confidence": self.confidence,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, object]) -> "SourceEvidence":
        try:
            return cls(
                url=cast(str, mapping["url"]),
                source_type=cast(str, mapping["source_type"]),
                title=cast(str, mapping["title"]),
                checked_at=cast(str, mapping["checked_at"]),
                fact_key=cast(str, mapping["fact_key"]),
                relation=cast(EvidenceRelation, mapping["relation"]),
                evidence=cast(str, mapping["evidence"]),
                confidence=cast(Confidence, mapping["confidence"]),
            )
        except KeyError as error:
            raise ModelError(f"missing evidence key: {error.args[0]}") from error


@dataclass(frozen=True, slots=True)
class LocationRecord:
    location_id: str
    canonical_name: str
    municipality: str
    candidate_ids: tuple[str, ...]
    access_kind: AccessKind
    membership_required: TriState
    public_booking: TriState
    racket_rental: TriState
    locker_rooms: TriState
    booking_account_required: TriState
    verification_status: VerificationStatus
    court_groups: tuple[CourtGroup, ...]
    aliases: tuple[str, ...]
    evidence: tuple[SourceEvidence, ...]
    notes: str
    brand: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    overall_cover_status: CoverStatus = "unknown"
    official_url: str | None = None
    booking_url: str | None = None
    booking_platform: str | None = None

    def __post_init__(self) -> None:
        for field in ("location_id", "canonical_name", "municipality"):
            _text(getattr(self, field), field)
        _strings(self.candidate_ids, "candidate_ids")
        _literal(self.access_kind, "access_kind", _ACCESS_KINDS)
        for field in (
            "membership_required",
            "public_booking",
            "racket_rental",
            "locker_rooms",
            "booking_account_required",
        ):
            _literal(getattr(self, field), field, _TRI_STATES)
        _literal(self.verification_status, "verification_status", _VERIFICATION_STATUSES)
        if not isinstance(cast(object, self.court_groups), tuple) or not all(
            isinstance(group, CourtGroup) for group in cast(tuple[object, ...], self.court_groups)
        ):
            raise ModelError("court_groups must contain CourtGroup values")
        _strings(self.aliases, "aliases")
        if not isinstance(cast(object, self.evidence), tuple) or not all(
            isinstance(item, SourceEvidence) for item in cast(tuple[object, ...], self.evidence)
        ):
            raise ModelError("evidence must contain SourceEvidence values")
        _text(self.notes, "notes", allow_empty=True)
        for field in ("brand", "address", "booking_platform"):
            _optional_text(getattr(self, field), field)
        for field in ("latitude", "longitude"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, (int, float)) or not isfinite(value)):
                raise ModelError(f"{field} must be a finite number or null")
        _literal(self.overall_cover_status, "overall_cover_status", _COVER_STATUSES)
        _optional_url(self.official_url, "official_url")
        _optional_url(self.booking_url, "booking_url")
        if self.verification_status in {"confirmed", "probable"} and not self.evidence:
            raise ModelError("confirmed and probable locations require evidence")

    def to_mapping(self) -> dict[str, object]:
        return {
            "location_id": self.location_id,
            "canonical_name": self.canonical_name,
            "municipality": self.municipality,
            "candidate_ids": list(self.candidate_ids),
            "access_kind": self.access_kind,
            "membership_required": self.membership_required,
            "public_booking": self.public_booking,
            "racket_rental": self.racket_rental,
            "locker_rooms": self.locker_rooms,
            "booking_account_required": self.booking_account_required,
            "verification_status": self.verification_status,
            "court_groups": [group.to_mapping() for group in self.court_groups],
            "aliases": list(self.aliases),
            "evidence": [item.to_mapping() for item in self.evidence],
            "notes": self.notes,
            "brand": self.brand,
            "address": self.address,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "overall_cover_status": self.overall_cover_status,
            "official_url": self.official_url,
            "booking_url": self.booking_url,
            "booking_platform": self.booking_platform,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, object]) -> "LocationRecord":
        required = {
            "location_id",
            "canonical_name",
            "municipality",
            "candidate_ids",
            "access_kind",
            "membership_required",
            "public_booking",
            "racket_rental",
            "locker_rooms",
            "booking_account_required",
            "verification_status",
            "court_groups",
            "aliases",
            "evidence",
            "notes",
        }
        allowed = required | {
            "brand",
            "address",
            "latitude",
            "longitude",
            "overall_cover_status",
            "official_url",
            "booking_url",
            "booking_platform",
        }
        missing = sorted(required - mapping.keys())
        if missing:
            raise ModelError(f"missing location keys: {', '.join(missing)}")
        unknown = mapping.keys() - allowed
        if unknown:
            raise ModelError(f"unknown location keys: {', '.join(sorted(unknown))}")
        try:
            groups = mapping["court_groups"]
            evidence = mapping["evidence"]
            if not isinstance(groups, (list, tuple)) or not isinstance(evidence, (list, tuple)):
                raise ModelError("court_groups and evidence must be lists")
            raw_groups = cast(Sequence[object], groups)
            raw_evidence = cast(Sequence[object], evidence)
            return cls(
                location_id=cast(str, mapping["location_id"]),
                canonical_name=cast(str, mapping["canonical_name"]),
                municipality=cast(str, mapping["municipality"]),
                candidate_ids=_strings(mapping["candidate_ids"], "candidate_ids", allow_list=True),
                access_kind=cast(AccessKind, mapping["access_kind"]),
                membership_required=cast(TriState, mapping["membership_required"]),
                public_booking=cast(TriState, mapping["public_booking"]),
                racket_rental=cast(TriState, mapping["racket_rental"]),
                locker_rooms=cast(TriState, mapping["locker_rooms"]),
                booking_account_required=cast(TriState, mapping["booking_account_required"]),
                verification_status=cast(VerificationStatus, mapping["verification_status"]),
                court_groups=tuple(
                    CourtGroup.from_mapping(cast(Mapping[str, object], item)) for item in raw_groups
                ),
                aliases=_strings(mapping["aliases"], "aliases", allow_list=True),
                evidence=tuple(
                    SourceEvidence.from_mapping(cast(Mapping[str, object], item))
                    for item in raw_evidence
                ),
                notes=cast(str, mapping["notes"]),
                brand=cast(str | None, mapping.get("brand")),
                address=cast(str | None, mapping.get("address")),
                latitude=cast(float | None, mapping.get("latitude")),
                longitude=cast(float | None, mapping.get("longitude")),
                overall_cover_status=cast(
                    CoverStatus, mapping.get("overall_cover_status", "unknown")
                ),
                official_url=cast(str | None, mapping.get("official_url")),
                booking_url=cast(str | None, mapping.get("booking_url")),
                booking_platform=cast(str | None, mapping.get("booking_platform")),
            )
        except (TypeError, AttributeError) as error:
            raise ModelError("invalid location mapping") from error


@dataclass(frozen=True, slots=True)
class CandidateMatch:
    candidate_id: str
    location_id: str | None
    status: MatchStatus
    note: str

    def __post_init__(self) -> None:
        _text(self.candidate_id, "candidate_id")
        _optional_text(self.location_id, "location_id")
        _literal(self.status, "status", _MATCH_STATUSES)
        _text(self.note, "note", allow_empty=True)


@dataclass(frozen=True, slots=True)
class VerificationRun:
    run_id: str
    started_at: str
    ended_at: str
    candidate_count: int
    error_count: int
    summary: str

    def __post_init__(self) -> None:
        for field in ("run_id", "started_at", "ended_at"):
            _text(getattr(self, field), field)
        _utc_timestamp(self.started_at, "started_at")
        _utc_timestamp(self.ended_at, "ended_at")
        for field in ("candidate_count", "error_count"):
            value = getattr(self, field)
            if not isinstance(value, int) or value < 0:
                raise ModelError(f"{field} must be a non-negative integer")
        _text(self.summary, "summary", allow_empty=True)
