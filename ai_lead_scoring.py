"""Utility for calculating AI assisted lead scores."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, MutableMapping, Optional


@dataclass
class LeadFeatures:
    """Container for normalised lead features."""

    email_engagement_rate: float
    meetings_completed: int
    deal_stage: str
    industry_fit: float
    annual_revenue: float
    intent_score: float
    custom_attributes: MutableMapping[str, float] = field(default_factory=dict)

    def to_vector(self, weights: Mapping[str, float]) -> Dict[str, float]:
        """Convert features to numeric vector using provided weights."""

        vector = {
            "email_engagement_rate": self.email_engagement_rate,
            "meetings_completed": float(self.meetings_completed),
            "industry_fit": self.industry_fit,
            "annual_revenue": self.annual_revenue,
            "intent_score": self.intent_score,
        }
        stage_weight = weights.get(f"deal_stage::{self.deal_stage}", 0.0)
        vector["deal_stage"] = stage_weight
        for key, value in self.custom_attributes.items():
            vector[f"custom::{key}"] = value
        return vector


@dataclass
class LeadScoreResult:
    lead_id: str
    probability_to_close: float
    contributing_factors: Dict[str, float]


class LeadScorer:
    """Logistic scoring model based on weighted features."""

    def __init__(self, weights: Mapping[str, float], bias: float = -1.0) -> None:
        self._weights = dict(weights)
        self._bias = bias

    @classmethod
    def from_json(cls, payload: str) -> "LeadScorer":
        data = json.loads(payload)
        return cls(weights=data["weights"], bias=data.get("bias", -1.0))

    def score(self, lead_id: str, features: LeadFeatures) -> LeadScoreResult:
        vector = features.to_vector(self._weights)
        linear_sum = self._bias
        contributions: Dict[str, float] = {}
        for key, value in vector.items():
            weight = self._weights.get(key, 0.0)
            contribution = weight * value
            linear_sum += contribution
            if abs(contribution) > 0.001:
                contributions[key] = contribution
        probability = 1 / (1 + math.exp(-linear_sum))
        return LeadScoreResult(lead_id=lead_id, probability_to_close=probability, contributing_factors=contributions)

    def batch_score(self, batch: Iterable[Dict[str, object]]) -> Iterable[LeadScoreResult]:
        for record in batch:
            features = LeadFeatures(
                email_engagement_rate=float(record.get("email_engagement_rate", 0.0)),
                meetings_completed=int(record.get("meetings_completed", 0)),
                deal_stage=str(record.get("deal_stage", "lead")),
                industry_fit=float(record.get("industry_fit", 0.0)),
                annual_revenue=float(record.get("annual_revenue", 0.0)),
                intent_score=float(record.get("intent_score", 0.0)),
                custom_attributes={
                    key: float(value)
                    for key, value in record.get("custom_attributes", {}).items()
                },
            )
            yield self.score(str(record.get("lead_id", "unknown")), features)


DEFAULT_WEIGHTS = {
    "email_engagement_rate": 1.2,
    "meetings_completed": 0.8,
    "industry_fit": 1.5,
    "annual_revenue": 0.000001,
    "intent_score": 1.0,
    "deal_stage::appointmentscheduled": 0.6,
    "deal_stage::presentationscheduled": 0.9,
    "deal_stage::decisionmakerboughtin": 1.2,
    "deal_stage::contractsent": 1.4,
    "deal_stage::closedwon": 2.0,
    "custom::inbound_velocity": 0.7,
    "custom::product_interest": 0.5,
}

DEFAULT_SCORER = LeadScorer(DEFAULT_WEIGHTS, bias=-2.0)


def score_lead(lead_id: str, features: LeadFeatures, scorer: Optional[LeadScorer] = None) -> LeadScoreResult:
    scorer = scorer or DEFAULT_SCORER
    return scorer.score(lead_id, features)


__all__ = [
    "LeadFeatures",
    "LeadScoreResult",
    "LeadScorer",
    "DEFAULT_SCORER",
    "DEFAULT_WEIGHTS",
    "score_lead",
]
