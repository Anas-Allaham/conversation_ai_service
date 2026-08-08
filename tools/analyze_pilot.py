from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEVEL_INDEX = {"Pre-A1": 0, "A1": 1, "A2": 2, "B1": 3, "B2": 4}
DIMENSIONS = [
    "task_achievement",
    "interactive_communication",
    "fluency",
    "coherence",
    "lexical_adequacy",
    "intelligibility",
]


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    first = Counter(a for a, _ in pairs)
    second = Counter(b for _, b in pairs)
    observed = sum(a == b for a, b in pairs) / len(pairs)
    expected = sum(first[level] * second[level] for level in LEVEL_INDEX) / (len(pairs) ** 2)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def main() -> None:
    manifest = rows(ROOT / "pilot" / "pilot_dataset_manifest.csv")
    ratings = rows(ROOT / "pilot" / "human_ratings.csv")
    if not manifest or not ratings:
        raise SystemExit("Fill both pilot CSV files before running agreement analysis.")
    by_assessment: dict[str, list[dict[str, str]]] = defaultdict(list)
    for rating in ratings:
        by_assessment[rating["assessment_id"]].append(rating)

    rater_pairs: list[tuple[str, str]] = []
    system_pairs: list[tuple[str, str]] = []
    dimension_disagreement = Counter()
    missing: list[str] = []
    for trial in manifest:
        assessment_id = trial["assessment_id"]
        human = by_assessment.get(assessment_id, [])
        if len(human) < 2:
            missing.append(assessment_id)
            continue
        rater_pairs.append((human[0]["final_conversational_level"], human[1]["final_conversational_level"]))
        agreed = human[0].get("adjudicated_level") or human[1].get("adjudicated_level")
        if not agreed and human[0]["final_conversational_level"] == human[1]["final_conversational_level"]:
            agreed = human[0]["final_conversational_level"]
        if agreed and trial.get("system_level"):
            system_pairs.append((trial["system_level"], agreed))
        for dimension in DIMENSIONS:
            if human[0].get(dimension) and human[1].get(dimension):
                difference = abs(float(human[0][dimension]) - float(human[1][dimension]))
                if difference >= 1:
                    dimension_disagreement[dimension] += 1

    exact = sum(a == b for a, b in system_pairs) / len(system_pairs) if system_pairs else 0
    adjacent = (
        sum(abs(LEVEL_INDEX[a] - LEVEL_INDEX[b]) <= 1 for a, b in system_pairs) / len(system_pairs)
        if system_pairs
        else 0
    )
    fluent_grammar_rows = [row for row in manifest if row.get("fluent_grammar_inaccurate", "").lower() == "true"]
    result = {
        "assessments_in_manifest": len(manifest),
        "assessments_with_two_raters": len(rater_pairs),
        "missing_two_rater_records": missing,
        "human_exact_agreement": round(sum(a == b for a, b in rater_pairs) / len(rater_pairs), 4) if rater_pairs else None,
        "human_cohen_kappa": None if cohen_kappa(rater_pairs) is None else round(cohen_kappa(rater_pairs), 4),
        "system_exact_agreement": round(exact, 4),
        "system_within_one_level": round(adjacent, 4),
        "target_exact_met": exact >= 0.70,
        "target_adjacent_met": adjacent >= 0.90,
        "dimension_disagreements": dict(dimension_disagreement),
        "fluent_grammar_inaccurate_cases": len(fluent_grammar_rows),
        "average_test_duration_seconds": round(
            sum(float(row["test_duration_seconds"]) for row in manifest if row.get("test_duration_seconds"))
            / max(1, sum(bool(row.get("test_duration_seconds")) for row in manifest)),
            2,
        ),
    }
    output = ROOT / "pilot" / "agreement_results.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

