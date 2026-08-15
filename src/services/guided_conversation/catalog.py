from __future__ import annotations

import json
from pathlib import Path

from .models import (
    LEVEL_RANK,
    CEFRLevel,
    GuidedDomainDefinition,
    GuidedDomainSummary,
    GuidedScenario,
    ScenarioCatalog,
    ScenarioSummary,
)


class ScenarioCatalogError(RuntimeError):
    pass


class ScenarioNotFound(ScenarioCatalogError):
    pass


class ScenarioLocked(ScenarioCatalogError):
    pass


class ScenarioCatalogRepository:
    """Loads immutable, version-controlled scenario JSON from the repository."""

    def __init__(self, content_root: Path) -> None:
        self.content_root = content_root.resolve()
        metadata_path = self.content_root / "_catalog.json"
        if not metadata_path.exists():
            raise ScenarioCatalogError(f"Scenario catalog metadata not found: {metadata_path}")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            scenarios = [
                GuidedScenario.model_validate_json(path.read_text(encoding="utf-8"))
                for path in sorted(self.content_root.glob("*.json"))
                if not path.name.startswith("_")
            ]
            self.catalog = ScenarioCatalog(
                content_version=str(metadata["content_version"]),
                domains=[
                    GuidedDomainDefinition.model_validate(domain) for domain in metadata["domains"]
                ],
                scenarios=scenarios,
            )
        except (OSError, KeyError, json.JSONDecodeError, ValueError) as exc:
            raise ScenarioCatalogError("The guided scenario catalog is invalid") from exc

    @property
    def content_version(self) -> str:
        return self.catalog.content_version

    def get(self, scenario_id: str, version: int | None = None) -> GuidedScenario:
        candidates = [
            scenario
            for scenario in self.catalog.scenarios
            if scenario.id == scenario_id
            and scenario.status == "published"
            and (version is None or scenario.version == version)
        ]
        if not candidates:
            raise ScenarioNotFound(f"Scenario {scenario_id!r} was not found")
        return max(candidates, key=lambda scenario: scenario.version)

    def get_domain(self, domain_id: str) -> GuidedDomainDefinition:
        for domain in self.catalog.domains:
            if domain.id == domain_id:
                return domain
        raise ScenarioCatalogError(f"Guided domain {domain_id!r} was not found")

    @staticmethod
    def is_unlocked(
        scenario: GuidedScenario,
        placement_completed: bool,
        placement_level: CEFRLevel | None,
    ) -> bool:
        return bool(
            placement_completed
            and placement_level is not None
            and LEVEL_RANK[placement_level] >= LEVEL_RANK[scenario.required_level]
        )

    def authorize(
        self,
        scenario: GuidedScenario,
        placement_completed: bool,
        placement_level: CEFRLevel | None,
    ) -> None:
        if not placement_completed or placement_level is None:
            raise ScenarioLocked("Complete the placement assessment before starting this scenario")
        if not self.is_unlocked(scenario, placement_completed, placement_level):
            raise ScenarioLocked(f"This scenario requires {scenario.required_level.value}")

    def list_summaries(
        self,
        placement_completed: bool,
        placement_level: CEFRLevel | None,
    ) -> list[ScenarioSummary]:
        published = [
            scenario for scenario in self.catalog.scenarios if scenario.status == "published"
        ]
        latest: dict[str, GuidedScenario] = {}
        for scenario in published:
            current = latest.get(scenario.id)
            if current is None or scenario.version > current.version:
                latest[scenario.id] = scenario

        summaries: list[ScenarioSummary] = []
        for scenario in sorted(
            latest.values(),
            key=lambda item: (
                self.get_domain(item.domain_id).order,
                LEVEL_RANK[item.required_level],
                item.title,
            ),
        ):
            domain = self.get_domain(scenario.domain_id)
            unlocked = self.is_unlocked(scenario, placement_completed, placement_level)
            reason = None
            if not unlocked:
                reason = (
                    "Complete your placement assessment"
                    if not placement_completed or placement_level is None
                    else f"Requires {scenario.required_level.value}"
                )
            summaries.append(
                ScenarioSummary(
                    scenario_id=scenario.id,
                    scenario_version=scenario.version,
                    domain_id=domain.id,
                    domain_title=domain.title,
                    theme=scenario.theme,
                    title=scenario.title,
                    required_level=scenario.required_level,
                    estimated_minutes=scenario.estimated_minutes,
                    learner_role=scenario.learner_role,
                    system_role=scenario.system_role,
                    objective=scenario.objective,
                    turn_count=len(scenario.turns),
                    is_locked=not unlocked,
                    lock_reason=reason,
                )
            )
        return summaries

    def list_domains(
        self,
        placement_completed: bool,
        placement_level: CEFRLevel | None,
    ) -> list[GuidedDomainSummary]:
        summaries = self.list_summaries(placement_completed, placement_level)
        by_domain: dict[str, list[ScenarioSummary]] = {}
        for scenario in summaries:
            by_domain.setdefault(scenario.domain_id, []).append(scenario)
        result: list[GuidedDomainSummary] = []
        for domain in sorted(self.catalog.domains, key=lambda item: (item.order, item.title)):
            scenarios = by_domain.get(domain.id, [])
            if not scenarios:
                continue
            result.append(
                GuidedDomainSummary(
                    domain_id=domain.id,
                    title=domain.title,
                    description=domain.description,
                    scenario_count=len(scenarios),
                    available_scenario_count=sum(not item.is_locked for item in scenarios),
                    scenarios=scenarios,
                )
            )
        return result
