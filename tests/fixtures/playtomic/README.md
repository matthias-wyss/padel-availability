# Playtomic Fixture Boundary

The five JSON files in this directory are synthetic, deterministic offline
parser-contract data. They are not redacted copies of live Playtomic JSON
responses and do not assert live Playtomic payload provenance.

The live source manifest records all five locations as explicitly unavailable:
no unauthenticated public JSON availability feed was established from the
booking pages, so no endpoint is invented for these fixtures or the manifest.

The fixtures exist only to exercise slot parsing, state preservation, UTC
normalization, date-window filtering, and deterministic deduplication without
network access.
