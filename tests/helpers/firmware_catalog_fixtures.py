from __future__ import annotations

import json
from pathlib import Path


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "firmware_catalogs"
LEGACY_BINARY_CATALOG_PATH = FIXTURE_ROOT / "legacy_binary_catalog.json"
LEGACY_TEXT_CATALOG_PATH = FIXTURE_ROOT / "legacy_text_catalog.json"


def load_legacy_binary_catalog() -> dict[str, object]:
    return _load_catalog(
        LEGACY_BINARY_CATALOG_PATH,
        mode="binary",
        required_fields=(
            "legacy_index",
            "name",
            "opcode",
            "form",
            "parameter_type",
            "default_value",
            "expected_response",
            "manual_verification_prompt",
        ),
    )


def load_legacy_text_catalog() -> dict[str, object]:
    return _load_catalog(
        LEGACY_TEXT_CATALOG_PATH,
        mode="text",
        required_fields=(
            "legacy_index",
            "command",
            "type",
            "default_value",
            "expected_prefix",
            "expected_response",
        ),
    )


def _load_catalog(path: Path, *, mode: str, required_fields: tuple[str, ...]) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Catalog fixture {path} must contain an object payload.")

    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, int) or schema_version <= 0:
        raise ValueError(f"Catalog fixture {path} has invalid schema_version {schema_version!r}.")

    fixture_mode = payload.get("mode")
    if fixture_mode != mode:
        raise ValueError(f"Catalog fixture {path} has mode {fixture_mode!r}, expected {mode!r}.")

    source = payload.get("source")
    if not isinstance(source, str) or not source:
        raise ValueError(f"Catalog fixture {path} is missing a non-empty source.")

    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"Catalog fixture {path} must contain a list of entries.")

    validated_entries: list[dict[str, object]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Catalog fixture {path} entry {index} must be an object.")
        missing = [field for field in required_fields if field not in entry]
        if missing:
            raise ValueError(f"Catalog fixture {path} entry {index} is missing fields: {', '.join(missing)}.")

        legacy_index = entry.get("legacy_index")
        if not isinstance(legacy_index, int) or legacy_index < 0:
            raise ValueError(f"Catalog fixture {path} entry {index} has invalid legacy_index {legacy_index!r}.")

        if mode == "binary":
            opcode = entry.get("opcode")
            if not isinstance(opcode, int) or opcode < 0 or opcode > 0xFF:
                raise ValueError(f"Catalog fixture {path} entry {index} has invalid opcode {opcode!r}.")
        validated_entries.append(dict(entry))

    return {
        "schema_version": schema_version,
        "source": source,
        "mode": mode,
        "entries": tuple(validated_entries),
    }
