"""Champion-selection rule (section F, ADR 0006): compare baseline vs.
secondary model on the *same* validation metric — `config.champion_metric`,
default WAPE, the scale-aware business metric section F asks for — and pick
whichever has the lower measured value on the overall validation set. A tie
(secondary not strictly better) keeps the baseline: a secondary model that
doesn't measurably beat the baseline hasn't earned the added complexity, and
the spec explicitly forbids reporting a worse model as the winner.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChampionResult:
    champion_name: str
    metric_name: str
    baseline_value: float
    secondary_value: float
    reason: str


def select_champion(
    *,
    baseline_name: str,
    baseline_metrics: dict[str, float],
    secondary_name: str,
    secondary_metrics: dict[str, float],
    metric_name: str,
) -> ChampionResult:
    baseline_value = baseline_metrics[metric_name]
    secondary_value = secondary_metrics[metric_name]

    if secondary_value < baseline_value:
        champion = secondary_name
        reason = (
            f"{secondary_name} {metric_name}={secondary_value:.4f} < "
            f"{baseline_name} {metric_name}={baseline_value:.4f}"
        )
    else:
        champion = baseline_name
        reason = (
            f"{secondary_name} {metric_name}={secondary_value:.4f} did not beat "
            f"{baseline_name} {metric_name}={baseline_value:.4f}; keeping baseline"
        )

    return ChampionResult(
        champion_name=champion,
        metric_name=metric_name,
        baseline_value=baseline_value,
        secondary_value=secondary_value,
        reason=reason,
    )
