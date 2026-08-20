from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from adc_evidence.config import DEFAULT_SEED_PATH, PROJECT_ROOT


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


@dataclass(frozen=True)
class AliasMatch:
    entity_type: str
    entity_id: str
    canonical_name: str
    matched_alias: str


class EntityNormalizer:
    def __init__(
        self,
        seed_path: Path = DEFAULT_SEED_PATH,
        entities_path: Path = PROJECT_ROOT / "configs" / "entities.json",
    ) -> None:
        self.aliases: dict[str, list[tuple[str, str, str]]] = {
            "adc": [],
            "target": [],
            "payload": [],
        }
        self.adc_names: dict[str, str] = {}
        self.adc_ids: dict[str, str] = {}
        self._load_adc_aliases(seed_path)
        self._load_reference_aliases(entities_path)

    def _load_adc_aliases(self, seed_path: Path) -> None:
        with seed_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                adc_id = row["adc_id"]
                canonical = row["adc_name"]
                values = [canonical]
                values.extend(alias for alias in row.get("aliases", "").split("|") if alias)
                self.adc_names[normalize_text(canonical)] = canonical
                self.adc_ids[normalize_text(canonical)] = adc_id
                for alias in values:
                    self.aliases["adc"].append((normalize_text(alias), adc_id, canonical))

    def _load_reference_aliases(self, entities_path: Path) -> None:
        config = json.loads(entities_path.read_text(encoding="utf-8"))
        for config_key, entity_type in (("targets", "target"), ("payloads", "payload")):
            for canonical, aliases in config[config_key].items():
                for alias in {canonical, *aliases}:
                    self.aliases[entity_type].append(
                        (normalize_text(alias), canonical, canonical)
                    )

    def canonical_adc(self, value: str) -> tuple[str, str] | None:
        normalized = normalize_text(value)
        for alias, entity_id, canonical in self.aliases["adc"]:
            if normalized == alias:
                return entity_id, canonical
        return None

    def canonical_target(self, value: str) -> str | None:
        matches = self.find_matches(value, entity_types=("target",))
        return matches[0].canonical_name if matches else None

    def find_matches(
        self,
        text: str,
        entity_types: tuple[str, ...] = ("adc", "target", "payload"),
    ) -> list[AliasMatch]:
        normalized_text = f" {normalize_text(text)} "
        matches: dict[tuple[str, str], AliasMatch] = {}
        for entity_type in entity_types:
            for normalized_alias, entity_id, canonical in self.aliases[entity_type]:
                if not normalized_alias:
                    continue
                if f" {normalized_alias} " in normalized_text:
                    key = (entity_type, entity_id)
                    current = matches.get(key)
                    if current is None or len(normalized_alias) > len(
                        normalize_text(current.matched_alias)
                    ):
                        matches[key] = AliasMatch(
                            entity_type=entity_type,
                            entity_id=entity_id,
                            canonical_name=canonical,
                            matched_alias=normalized_alias,
                        )
        return sorted(
            matches.values(),
            key=lambda item: (item.entity_type, item.canonical_name),
        )

    def aliases_for_adc(self, adc_id: str) -> list[str]:
        return [
            alias
            for alias, candidate_id, _ in self.aliases["adc"]
            if candidate_id == adc_id
        ]

