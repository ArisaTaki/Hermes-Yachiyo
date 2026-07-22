"""Application-independent contracts for deciding whether a user goal is done.

Tool outcomes describe one attempt.  A goal contract keeps the original user
goal and its completion criteria stable across planning and recovery, while a
goal assessment records only runtime-correlated evidence.  Model prose and
uncorrelated observations cannot satisfy an effectful criterion.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

from apps.shell.agent.runtime.action_targets import action_target_matches

from apps.shell.agent.runtime.tool_outcomes import (
    OutcomeStatus,
    ToolOutcome,
    VerificationStatus,
)
from apps.shell.agent.runtime.verification_receipts import (
    EXACT_FILE_CONTENT_PRESENT_PREDICATE,
    SEMANTIC_ARTIFACT_ADEQUACY_PREDICATE,
)


def _clean_text(value: Any, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError("required text value is empty")
    return text


def _canonical_names(values: Sequence[Any] | set[Any] | frozenset[Any]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            text
            for value in values
            if (text := str(value or "").strip())
        )
    )


def _freeze_json(value: Any, *, depth: int = 0) -> Any:
    if depth > 12:
        raise ValueError("goal contract JSON nesting is too deep")
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("goal contract JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            clean_key = str(key or "").strip()
            if not clean_key:
                raise ValueError("goal contract JSON keys must be non-empty")
            frozen[clean_key] = _freeze_json(item, depth=depth + 1)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, depth=depth + 1) for item in value)
    raise TypeError(f"unsupported goal contract JSON value: {type(value).__name__}")


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    frozen = _freeze_json(value)
    if not isinstance(frozen, Mapping):
        raise TypeError("goal contract value must be a mapping")
    return frozen


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def _stable_id(prefix: str, *parts: Any) -> str:
    encoded = "\0".join(str(part or "") for part in parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class GoalCriterion:
    """One immutable completion condition from the original user goal."""

    criterion_id: str
    description: str
    effectful: bool = False
    required: bool = True
    response_satisfiable: bool = False
    required_capabilities: tuple[str, ...] = ()
    required_effects: tuple[str, ...] = ()
    required_verification_predicates: tuple[str, ...] = ()
    expected: Mapping[str, Any] = field(default_factory=dict)
    source_step_ids: tuple[str, ...] = ()
    verifier_step_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "criterion_id", _clean_text(self.criterion_id, required=True))
        object.__setattr__(self, "description", _clean_text(self.description, required=True))
        object.__setattr__(
            self,
            "required_capabilities",
            _canonical_names(self.required_capabilities),
        )
        object.__setattr__(self, "required_effects", _canonical_names(self.required_effects))
        object.__setattr__(
            self,
            "required_verification_predicates",
            _canonical_names(self.required_verification_predicates),
        )
        object.__setattr__(self, "source_step_ids", _canonical_names(self.source_step_ids))
        object.__setattr__(self, "verifier_step_ids", _canonical_names(self.verifier_step_ids))
        object.__setattr__(self, "expected", _freeze_mapping(self.expected))
        if self.effectful and self.response_satisfiable:
            raise ValueError("effectful criteria cannot be satisfied by model response text")

    def to_payload(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "description": self.description,
            "effectful": self.effectful,
            "required": self.required,
            "response_satisfiable": self.response_satisfiable,
            "required_capabilities": list(self.required_capabilities),
            "required_effects": list(self.required_effects),
            "required_verification_predicates": list(
                self.required_verification_predicates
            ),
            "expected": _json_value(self.expected),
            "source_step_ids": list(self.source_step_ids),
            "verifier_step_ids": list(self.verifier_step_ids),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "GoalCriterion":
        return cls(
            criterion_id=payload.get("criterion_id", ""),
            description=payload.get("description", ""),
            effectful=payload.get("effectful") is True,
            required=payload.get("required") is not False,
            response_satisfiable=payload.get("response_satisfiable") is True,
            required_capabilities=tuple(payload.get("required_capabilities") or ()),
            required_effects=tuple(payload.get("required_effects") or ()),
            required_verification_predicates=tuple(
                payload.get("required_verification_predicates") or ()
            ),
            expected=(
                payload.get("expected")
                if isinstance(payload.get("expected"), Mapping)
                else {}
            ),
            source_step_ids=tuple(payload.get("source_step_ids") or ()),
            verifier_step_ids=tuple(payload.get("verifier_step_ids") or ()),
        )


@dataclass(frozen=True, slots=True)
class GoalContract:
    """Stable root goal and evidence rules for one Runtime run."""

    contract_id: str
    original_goal: str
    criteria: tuple[GoalCriterion, ...]
    run_id: str = ""
    intent_kind: str = "general"
    max_total_attempts: int = 12
    max_subgoal_attempts: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_id", _clean_text(self.contract_id, required=True))
        object.__setattr__(self, "run_id", _clean_text(self.run_id))
        object.__setattr__(self, "original_goal", _clean_text(self.original_goal, required=True))
        object.__setattr__(self, "intent_kind", _clean_text(self.intent_kind) or "general")
        criteria = tuple(self.criteria)
        if not criteria or any(not isinstance(item, GoalCriterion) for item in criteria):
            raise ValueError("GoalContract requires GoalCriterion values")
        criterion_ids = [item.criterion_id for item in criteria]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("GoalContract criterion ids must be unique")
        object.__setattr__(self, "criteria", criteria)
        if not 1 <= int(self.max_total_attempts) <= 100:
            raise ValueError("GoalContract.max_total_attempts must be from 1 to 100")
        if not 1 <= int(self.max_subgoal_attempts) <= int(self.max_total_attempts):
            raise ValueError("GoalContract.max_subgoal_attempts is outside the total budget")
        object.__setattr__(self, "max_total_attempts", int(self.max_total_attempts))
        object.__setattr__(self, "max_subgoal_attempts", int(self.max_subgoal_attempts))

    def criterion(self, criterion_id: str) -> GoalCriterion | None:
        clean_id = str(criterion_id or "").strip()
        return next((item for item in self.criteria if item.criterion_id == clean_id), None)

    def bind_run(self, run_id: str) -> "GoalContract":
        clean_run_id = _clean_text(run_id, required=True)
        if self.run_id and self.run_id != clean_run_id:
            raise ValueError("GoalContract is already bound to another run")
        return self if self.run_id == clean_run_id else replace(self, run_id=clean_run_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "run_id": self.run_id,
            "original_goal": self.original_goal,
            "intent_kind": self.intent_kind,
            "criteria": [criterion.to_payload() for criterion in self.criteria],
            "max_total_attempts": self.max_total_attempts,
            "max_subgoal_attempts": self.max_subgoal_attempts,
            "source": "goal_contract",
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "GoalContract":
        raw_criteria = payload.get("criteria")
        criteria = tuple(
            GoalCriterion.from_payload(item)
            for item in (raw_criteria if isinstance(raw_criteria, (list, tuple)) else ())
            if isinstance(item, Mapping)
        )
        return cls(
            contract_id=payload.get("contract_id", ""),
            run_id=payload.get("run_id", ""),
            original_goal=payload.get("original_goal", ""),
            intent_kind=payload.get("intent_kind", "general"),
            criteria=criteria,
            max_total_attempts=payload.get("max_total_attempts", 12),
            max_subgoal_attempts=payload.get("max_subgoal_attempts", 2),
        )


@dataclass(frozen=True, slots=True)
class GoalEvidence:
    """One immutable, correlation-bound fact considered by GoalCoordinator."""

    evidence_id: str
    contract_id: str
    criterion_id: str
    run_id: str
    kind: str
    verification_predicate: str = ""
    source_tool_call_id: str = ""
    verifier_tool_call_id: str = ""
    source_step_id: str = ""
    verifier_step_id: str = ""
    plan_id: str = ""
    capabilities: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    observed: Mapping[str, Any] = field(default_factory=dict)
    verified: bool = False
    status: str = ""

    def __post_init__(self) -> None:
        for name in ("evidence_id", "contract_id", "criterion_id", "run_id", "kind"):
            object.__setattr__(self, name, _clean_text(getattr(self, name), required=True))
        object.__setattr__(
            self,
            "verification_predicate",
            _clean_text(self.verification_predicate),
        )
        object.__setattr__(
            self,
            "source_tool_call_id",
            _clean_text(self.source_tool_call_id),
        )
        object.__setattr__(
            self,
            "verifier_tool_call_id",
            _clean_text(self.verifier_tool_call_id),
        )
        object.__setattr__(self, "source_step_id", _clean_text(self.source_step_id))
        object.__setattr__(self, "verifier_step_id", _clean_text(self.verifier_step_id))
        object.__setattr__(self, "plan_id", _clean_text(self.plan_id))
        object.__setattr__(self, "capabilities", _canonical_names(self.capabilities))
        object.__setattr__(self, "effects", _canonical_names(self.effects))
        object.__setattr__(self, "observed", _freeze_mapping(self.observed))
        object.__setattr__(self, "status", _clean_text(self.status))

    def to_payload(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "contract_id": self.contract_id,
            "criterion_id": self.criterion_id,
            "run_id": self.run_id,
            "kind": self.kind,
            "verification_predicate": self.verification_predicate,
            "source_tool_call_id": self.source_tool_call_id,
            "verifier_tool_call_id": self.verifier_tool_call_id,
            "source_step_id": self.source_step_id,
            "verifier_step_id": self.verifier_step_id,
            "plan_id": self.plan_id,
            "capabilities": list(self.capabilities),
            "effects": list(self.effects),
            "observed": _json_value(self.observed),
            "verified": self.verified,
            "status": self.status,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "GoalEvidence":
        return cls(
            evidence_id=payload.get("evidence_id", ""),
            contract_id=payload.get("contract_id", ""),
            criterion_id=payload.get("criterion_id", ""),
            run_id=payload.get("run_id", ""),
            kind=payload.get("kind", ""),
            verification_predicate=payload.get("verification_predicate", ""),
            source_tool_call_id=payload.get("source_tool_call_id", ""),
            verifier_tool_call_id=payload.get("verifier_tool_call_id", ""),
            source_step_id=payload.get("source_step_id", ""),
            verifier_step_id=payload.get("verifier_step_id", ""),
            plan_id=payload.get("plan_id", ""),
            capabilities=tuple(payload.get("capabilities") or ()),
            effects=tuple(payload.get("effects") or ()),
            observed=(
                payload.get("observed")
                if isinstance(payload.get("observed"), Mapping)
                else {}
            ),
            verified=payload.get("verified") is True,
            status=payload.get("status", ""),
        )


@dataclass(frozen=True, slots=True)
class BoundedSubgoal:
    """A recovery objective that cannot escape or weaken its parent criterion."""

    subgoal_id: str
    contract_id: str
    criterion_id: str
    action: str
    description: str
    source_tool_call_id: str
    attempt: int
    max_attempts: int

    def __post_init__(self) -> None:
        for name in (
            "subgoal_id",
            "contract_id",
            "criterion_id",
            "action",
            "description",
            "source_tool_call_id",
        ):
            object.__setattr__(self, name, _clean_text(getattr(self, name), required=True))
        if not 1 <= int(self.attempt) <= int(self.max_attempts):
            raise ValueError("BoundedSubgoal attempt is outside its budget")
        object.__setattr__(self, "attempt", int(self.attempt))
        object.__setattr__(self, "max_attempts", int(self.max_attempts))

    def to_payload(self) -> dict[str, Any]:
        return {
            "subgoal_id": self.subgoal_id,
            "contract_id": self.contract_id,
            "criterion_id": self.criterion_id,
            "action": self.action,
            "description": self.description,
            "source_tool_call_id": self.source_tool_call_id,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "BoundedSubgoal":
        return cls(
            subgoal_id=payload.get("subgoal_id", ""),
            contract_id=payload.get("contract_id", ""),
            criterion_id=payload.get("criterion_id", ""),
            action=payload.get("action", ""),
            description=payload.get("description", ""),
            source_tool_call_id=payload.get("source_tool_call_id", ""),
            attempt=payload.get("attempt", 0),
            max_attempts=payload.get("max_attempts", 0),
        )


@dataclass(frozen=True, slots=True)
class GoalAssessment:
    """Dynamic evidence ledger for an immutable GoalContract."""

    contract_id: str
    run_id: str
    evidence: tuple[GoalEvidence, ...] = ()
    subgoals: tuple[BoundedSubgoal, ...] = ()
    satisfied_criterion_ids: tuple[str, ...] = ()
    unsatisfied_criterion_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_id", _clean_text(self.contract_id, required=True))
        object.__setattr__(self, "run_id", _clean_text(self.run_id, required=True))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "subgoals", tuple(self.subgoals))
        object.__setattr__(
            self,
            "satisfied_criterion_ids",
            _canonical_names(self.satisfied_criterion_ids),
        )
        object.__setattr__(
            self,
            "unsatisfied_criterion_ids",
            _canonical_names(self.unsatisfied_criterion_ids),
        )

    @property
    def completed(self) -> bool:
        return not self.unsatisfied_criterion_ids

    def to_payload(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "run_id": self.run_id,
            "evidence": [item.to_payload() for item in self.evidence],
            "subgoals": [item.to_payload() for item in self.subgoals],
            "satisfied_criterion_ids": list(self.satisfied_criterion_ids),
            "unsatisfied_criterion_ids": list(self.unsatisfied_criterion_ids),
            "completed": self.completed,
            "source": "goal_coordinator",
        }

    def to_persisted_payload(self) -> dict[str, Any]:
        """Project the ledger for durable events without artifact bodies."""

        payload = self.to_payload()
        payload["evidence"] = [
            _persisted_goal_evidence_payload(item) for item in self.evidence
        ]
        return payload


def _persisted_goal_evidence_payload(evidence: GoalEvidence) -> dict[str, Any]:
    """Serialize evidence without persisting exact artifact bodies."""

    payload = evidence.to_payload()
    if evidence.verification_predicate not in {
        EXACT_FILE_CONTENT_PRESENT_PREDICATE,
        SEMANTIC_ARTIFACT_ADEQUACY_PREDICATE,
    }:
        return payload
    observed = payload.get("observed")
    if not isinstance(observed, dict) or "content" not in observed:
        return payload
    observed.pop("content", None)
    observed["content_redacted"] = True
    return payload


class GoalCoordinator:
    """Evaluate a root goal only from contract-bound runtime evidence."""

    def initial(self, contract: GoalContract) -> GoalAssessment:
        run_id = _clean_text(contract.run_id, required=True)
        return self._reassess(
            contract,
            GoalAssessment(contract_id=contract.contract_id, run_id=run_id),
        )

    def restore_assessment(
        self,
        contract: GoalContract,
        payload: Mapping[str, Any],
    ) -> GoalAssessment:
        self._require_contract_identity(
            contract,
            contract_id=payload.get("contract_id", ""),
            run_id=payload.get("run_id", ""),
        )
        raw_evidence = payload.get("evidence")
        evidence = tuple(
            GoalEvidence.from_payload(item)
            for item in (raw_evidence if isinstance(raw_evidence, (list, tuple)) else ())
            if isinstance(item, Mapping)
        )
        raw_subgoals = payload.get("subgoals")
        subgoals = tuple(
            BoundedSubgoal.from_payload(item)
            for item in (raw_subgoals if isinstance(raw_subgoals, (list, tuple)) else ())
            if isinstance(item, Mapping)
        )
        for item in evidence:
            self._require_contract_identity(
                contract,
                contract_id=item.contract_id,
                run_id=item.run_id,
            )
            if contract.criterion(item.criterion_id) is None:
                raise ValueError("assessment evidence references an unknown criterion")
        for item in subgoals:
            if item.contract_id != contract.contract_id or contract.criterion(item.criterion_id) is None:
                raise ValueError("assessment subgoal is outside the goal contract")
        assessment = GoalAssessment(
            contract_id=contract.contract_id,
            run_id=contract.run_id,
            evidence=evidence,
            subgoals=subgoals,
        )
        # Never trust serialized satisfied/completed flags; recompute them.
        return self._reassess(contract, assessment)

    def record_tool_outcome(
        self,
        contract: GoalContract,
        assessment: GoalAssessment,
        outcome: ToolOutcome,
        *,
        run_id: str,
        source_tool_call_id: str,
        source_step_id: str = "",
        plan_id: str = "",
        observed: Mapping[str, Any] | None = None,
        eligible_criterion_ids: Sequence[str] | None = None,
    ) -> GoalAssessment:
        self._require_assessment(contract, assessment, run_id)
        if not isinstance(outcome, ToolOutcome):
            raise TypeError("record_tool_outcome requires a ToolOutcome")
        source_id = _clean_text(source_tool_call_id, required=True)
        clean_source_step_id = _clean_text(source_step_id)
        clean_plan_id = _clean_text(plan_id)
        observed_payload = (
            _freeze_mapping(observed)
            if observed is not None
            else _outcome_observed_mapping(outcome.raw)
        )
        eligible_ids = (
            None
            if eligible_criterion_ids is None
            else set(_canonical_names(tuple(eligible_criterion_ids)))
        )
        additions: list[GoalEvidence] = []
        for criterion in contract.criteria:
            if eligible_ids is not None and criterion.criterion_id not in eligible_ids:
                continue
            if not _criterion_matches_outcome(criterion, outcome):
                continue
            expected_matches = _expected_matches(
                criterion.expected,
                observed_payload,
                capability_ids=criterion.required_capabilities,
                source_step_id=clean_source_step_id,
            )
            verified = bool(
                outcome.status is OutcomeStatus.SUCCESS
                and expected_matches
                and not criterion.verifier_step_ids
                and (
                    outcome.verification is VerificationStatus.VERIFIED
                    if criterion.effectful
                    else outcome.verification
                    in {VerificationStatus.VERIFIED, VerificationStatus.NOT_REQUIRED}
                )
            )
            evidence_id = _stable_id(
                "goal-evidence",
                contract.contract_id,
                criterion.criterion_id,
                run_id,
                "tool_outcome",
                source_id,
                outcome.status.value,
            )
            additions.append(
                GoalEvidence(
                    evidence_id=evidence_id,
                    contract_id=contract.contract_id,
                    criterion_id=criterion.criterion_id,
                    run_id=run_id,
                    kind="tool_outcome",
                    source_tool_call_id=source_id,
                    source_step_id=clean_source_step_id,
                    plan_id=clean_plan_id,
                    capabilities=outcome.capabilities,
                    effects=outcome.effects,
                    observed=observed_payload,
                    verified=verified,
                    status=outcome.status.value,
                )
            )
        return self._with_evidence(contract, assessment, additions)

    def record_verifier_evidence(
        self,
        contract: GoalContract,
        assessment: GoalAssessment,
        *,
        criterion_id: str,
        run_id: str,
        source_tool_call_id: str,
        verifier_tool_call_id: str,
        source_step_id: str = "",
        verifier_step_id: str = "",
        plan_id: str = "",
        verification_predicate: str = "",
        predicate_fulfilled: bool | None = None,
        status: str = "",
        observed: Mapping[str, Any],
    ) -> GoalAssessment:
        self._require_assessment(contract, assessment, run_id)
        criterion = contract.criterion(criterion_id)
        if criterion is None:
            raise ValueError("verifier evidence references an unknown criterion")
        source_id = _clean_text(source_tool_call_id, required=True)
        verifier_id = _clean_text(verifier_tool_call_id, required=True)
        clean_source_step_id = _clean_text(source_step_id)
        clean_verifier_step_id = _clean_text(verifier_step_id)
        clean_plan_id = _clean_text(plan_id)
        clean_predicate = _clean_text(verification_predicate)
        source_evidence = next(
            (
                item
                for item in reversed(assessment.evidence)
                if item.kind == "tool_outcome"
                and item.criterion_id == criterion.criterion_id
                and item.source_tool_call_id == source_id
                and item.contract_id == contract.contract_id
                and item.run_id == run_id
                and (
                    not clean_source_step_id
                    or item.source_step_id == clean_source_step_id
                )
                and (not clean_plan_id or item.plan_id == clean_plan_id)
            ),
            None,
        )
        source_correlated = source_evidence is not None or not criterion.effectful
        verifier_allowed = bool(
            not criterion.verifier_step_ids
            or clean_verifier_step_id in criterion.verifier_step_ids
        )
        clean_observed = _freeze_mapping(observed)
        verified = bool(
            source_correlated
            and verifier_allowed
            and predicate_fulfilled is not False
            and _expected_matches(
                criterion.expected,
                clean_observed,
                capability_ids=criterion.required_capabilities,
                source_step_id=(
                    source_evidence.source_step_id
                    if source_evidence is not None
                    else clean_source_step_id
                ),
            )
        )
        evidence_identity = (
            contract.contract_id,
            criterion.criterion_id,
            run_id,
            "verifier",
            source_id,
            verifier_id,
        )
        if clean_predicate:
            evidence_identity = (*evidence_identity, clean_predicate)
        evidence = GoalEvidence(
            evidence_id=_stable_id("goal-evidence", *evidence_identity),
            contract_id=contract.contract_id,
            criterion_id=criterion.criterion_id,
            run_id=run_id,
            kind="verifier",
            verification_predicate=clean_predicate,
            source_tool_call_id=source_id,
            verifier_tool_call_id=verifier_id,
            source_step_id=(
                source_evidence.source_step_id
                if source_evidence is not None
                else clean_source_step_id
            ),
            verifier_step_id=clean_verifier_step_id,
            plan_id=(source_evidence.plan_id if source_evidence is not None else clean_plan_id),
            capabilities=(source_evidence.capabilities if source_evidence else ()),
            effects=(source_evidence.effects if source_evidence else ()),
            observed=clean_observed,
            verified=verified,
            status=_clean_text(status) or ("verified" if verified else "uncorrelated"),
        )
        return self._with_evidence(contract, assessment, (evidence,))

    def record_final_response(
        self,
        contract: GoalContract,
        assessment: GoalAssessment,
        *,
        run_id: str,
        response_text: str,
    ) -> GoalAssessment:
        self._require_assessment(contract, assessment, run_id)
        text = _clean_text(response_text, required=True)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        additions = [
            GoalEvidence(
                evidence_id=_stable_id(
                    "goal-evidence",
                    contract.contract_id,
                    criterion.criterion_id,
                    run_id,
                    "response",
                    digest,
                ),
                contract_id=contract.contract_id,
                criterion_id=criterion.criterion_id,
                run_id=run_id,
                kind="response",
                observed={"response_present": True, "response_sha256": digest},
                verified=True,
                status="present",
            )
            for criterion in contract.criteria
            if criterion.response_satisfiable and not criterion.effectful
        ]
        return self._with_evidence(contract, assessment, additions)

    def open_subgoal(
        self,
        contract: GoalContract,
        assessment: GoalAssessment,
        *,
        criterion_id: str,
        action: str,
        description: str,
        source_tool_call_id: str,
    ) -> tuple[GoalAssessment, BoundedSubgoal | None]:
        self._require_assessment(contract, assessment, assessment.run_id)
        criterion = contract.criterion(criterion_id)
        if criterion is None or criterion.criterion_id not in assessment.unsatisfied_criterion_ids:
            return assessment, None
        clean_action = _clean_text(action, required=True)
        clean_description = _clean_text(description, required=True)
        clean_source = _clean_text(source_tool_call_id, required=True)
        attempts = sum(
            1
            for item in assessment.subgoals
            if item.criterion_id == criterion.criterion_id and item.action == clean_action
        )
        if (
            attempts >= contract.max_subgoal_attempts
            or len(assessment.subgoals) >= contract.max_total_attempts
        ):
            return assessment, None
        attempt = attempts + 1
        subgoal = BoundedSubgoal(
            subgoal_id=_stable_id(
                "subgoal",
                contract.contract_id,
                criterion.criterion_id,
                clean_action,
                clean_source,
                attempt,
            ),
            contract_id=contract.contract_id,
            criterion_id=criterion.criterion_id,
            action=clean_action,
            description=clean_description,
            source_tool_call_id=clean_source,
            attempt=attempt,
            max_attempts=contract.max_subgoal_attempts,
        )
        return replace(assessment, subgoals=(*assessment.subgoals, subgoal)), subgoal

    def _with_evidence(
        self,
        contract: GoalContract,
        assessment: GoalAssessment,
        additions: Sequence[GoalEvidence],
    ) -> GoalAssessment:
        if not additions:
            return assessment
        by_id = {item.evidence_id: item for item in assessment.evidence}
        for item in additions:
            by_id[item.evidence_id] = item
        return self._reassess(
            contract,
            replace(assessment, evidence=tuple(by_id.values())),
        )

    @staticmethod
    def _reassess(
        contract: GoalContract,
        assessment: GoalAssessment,
    ) -> GoalAssessment:
        satisfied = tuple(
            criterion.criterion_id
            for criterion in contract.criteria
            if _evidence_set_satisfies_criterion(criterion, assessment.evidence)
        )
        unsatisfied = tuple(
            criterion.criterion_id
            for criterion in contract.criteria
            if criterion.required and criterion.criterion_id not in satisfied
        )
        return replace(
            assessment,
            satisfied_criterion_ids=satisfied,
            unsatisfied_criterion_ids=unsatisfied,
        )

    @staticmethod
    def _require_contract_identity(
        contract: GoalContract,
        *,
        contract_id: Any,
        run_id: Any,
    ) -> None:
        if str(contract_id or "").strip() != contract.contract_id:
            raise ValueError("goal evidence belongs to another contract")
        if not contract.run_id or str(run_id or "").strip() != contract.run_id:
            raise ValueError("goal evidence belongs to another run")

    def _require_assessment(
        self,
        contract: GoalContract,
        assessment: GoalAssessment,
        run_id: Any,
    ) -> None:
        if not isinstance(assessment, GoalAssessment):
            raise TypeError("GoalCoordinator requires a GoalAssessment")
        self._require_contract_identity(
            contract,
            contract_id=assessment.contract_id,
            run_id=assessment.run_id,
        )
        if str(run_id or "").strip() != assessment.run_id:
            raise ValueError("goal evidence run_id does not match the assessment")


def _criterion_matches_outcome(
    criterion: GoalCriterion,
    outcome: ToolOutcome,
) -> bool:
    if not criterion.required_capabilities and not criterion.required_effects:
        return False
    capabilities = set(outcome.capabilities)
    effects = set(outcome.effects)
    return set(criterion.required_capabilities).issubset(capabilities) and set(
        criterion.required_effects
    ).issubset(effects)


def _evidence_satisfies_criterion(
    criterion: GoalCriterion,
    evidence: GoalEvidence,
) -> bool:
    """Require the exact planner-declared source/verifier lineage.

    A tool result can remain useful source evidence without being allowed to
    finish a criterion that names a dedicated verifier step.  Rechecking the
    step ids here also keeps restored assessment payloads from weakening the
    immutable contract.
    """

    if evidence.criterion_id != criterion.criterion_id or not evidence.verified:
        return False
    if (
        criterion.source_step_ids
        and evidence.kind in {"tool_outcome", "verifier"}
        and evidence.source_step_id not in criterion.source_step_ids
    ):
        return False
    if not criterion.verifier_step_ids:
        return True
    return bool(
        evidence.kind == "verifier"
        and evidence.verifier_step_id in criterion.verifier_step_ids
        and evidence.source_tool_call_id
        and evidence.verifier_tool_call_id
    )


def _evidence_set_satisfies_criterion(
    criterion: GoalCriterion,
    evidence: Sequence[GoalEvidence],
) -> bool:
    eligible = tuple(
        item for item in evidence if _evidence_satisfies_criterion(criterion, item)
    )
    required_predicates = frozenset(criterion.required_verification_predicates)
    if not required_predicates:
        return bool(eligible)
    grouped_predicates: dict[tuple[Any, ...], set[str]] = {}
    for item in eligible:
        predicate = item.verification_predicate
        if predicate not in required_predicates:
            continue
        lineage = _verification_predicate_lineage(criterion, item)
        if lineage is None:
            continue
        grouped_predicates.setdefault(lineage, set()).add(predicate)
    return any(
        required_predicates.issubset(observed_predicates)
        for observed_predicates in grouped_predicates.values()
    )


def _verification_predicate_lineage(
    criterion: GoalCriterion,
    evidence: GoalEvidence,
) -> tuple[Any, ...] | None:
    """Return the immutable lineage shared by predicates for one artifact."""

    base = (
        evidence.source_tool_call_id,
        evidence.source_step_id,
        evidence.verifier_tool_call_id,
        evidence.verifier_step_id,
        evidence.plan_id,
    )
    if any(not value for value in base):
        return None
    artifact_predicates = {
        EXACT_FILE_CONTENT_PRESENT_PREDICATE,
        SEMANTIC_ARTIFACT_ADEQUACY_PREDICATE,
    }
    if not artifact_predicates.intersection(
        criterion.required_verification_predicates
    ):
        return base
    observed_path = _clean_text(evidence.observed.get("observed_path"))
    content_sha256 = _clean_text(
        evidence.observed.get("content_sha256")
    ).casefold()
    content_length = evidence.observed.get("content_length")
    if (
        not observed_path
        or len(content_sha256) != 64
        or any(character not in "0123456789abcdef" for character in content_sha256)
        or isinstance(content_length, bool)
        or not isinstance(content_length, int)
        or content_length <= 0
    ):
        return None
    return (*base, observed_path, content_sha256, content_length)


def _outcome_observed_mapping(raw: Any) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        return MappingProxyType({})
    observed = dict(raw)
    data = raw.get("data")
    if isinstance(data, Mapping):
        observed.update(data)
    return _freeze_mapping(observed)


def _expected_matches(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    capability_ids: Iterable[str] = (),
    source_step_id: str = "",
) -> bool:
    if not expected:
        return True
    for key, value in expected.items():
        if key not in observed:
            return False
        observed_value = observed[key]
        if key == "target" and isinstance(value, Mapping):
            if not isinstance(observed_value, Mapping) or not action_target_matches(
                value,
                observed_value,
                capability_ids=capability_ids,
                source_step_id=source_step_id,
            ):
                return False
            continue
        if not _expected_value_matches(value, observed_value):
            return False
    return True


def _expected_value_matches(expected: Any, observed: Any) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(observed, Mapping) and all(
            key in observed and _expected_value_matches(value, observed[key])
            for key, value in expected.items()
        )
    if isinstance(expected, tuple):
        if not isinstance(observed, (list, tuple)) or len(expected) != len(observed):
            return False
        return all(
            _expected_value_matches(expected_item, observed_item)
            for expected_item, observed_item in zip(expected, observed)
        )
    if isinstance(expected, str) and isinstance(observed, str):
        return " ".join(expected.split()).casefold() == " ".join(observed.split()).casefold()
    return expected == observed


__all__ = [
    "BoundedSubgoal",
    "GoalAssessment",
    "GoalContract",
    "GoalCoordinator",
    "GoalCriterion",
    "GoalEvidence",
]
