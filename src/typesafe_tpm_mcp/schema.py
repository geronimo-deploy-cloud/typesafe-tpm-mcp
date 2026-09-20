"""Ticket schema, jev primitives, and the confidence-gated router.

This is the reviewed logic from ticket_quality_schema.py, packaged so the
MCP server in server.py can expose it as a tool. The routing thresholds
live here as module constants so they can be tuned in one place — or
overridden by environment variable, see `load_thresholds()`.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient


# --------------------------------------------------------------------------
# Ticket schema — mirrors the project's GitHub issue template
# --------------------------------------------------------------------------

class TicketDraft(BaseModel):
    title: str = Field(description="Short imperative title for the ticket.")
    goal: str = Field(description="Why this ticket exists, concretely.")
    description: str = Field(description="What to build/change, in enough detail to implement.")
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Checkable pass/fail conditions for calling this done.",
    )
    not_in_scope: list[str] = Field(
        default_factory=list,
        description="Adjacent work explicitly excluded from this ticket.",
    )
    files_to_create: list[str] = Field(
        default_factory=list,
        description="Files or locations the ticket is expected to produce.",
    )
    files_to_modify: list[str] = Field(
        default_factory=list,
        description="Existing files the ticket is expected to change.",
    )
    do_not_touch: list[str] = Field(
        default_factory=list,
        description="Files, systems, or pipelines that must not be modified.",
    )
    context_references: list[str] = Field(
        default_factory=list,
        description="Dependencies, related tickets, prior art, links.",
    )

    def to_jev_state(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# --------------------------------------------------------------------------
# Jev primitives
# --------------------------------------------------------------------------

TICKET_REVIEW_QUESTIONS = {
    # Group A: section-level completeness
    "goal_actionable": Noul(
        instructions="Does `goal` state a specific, concrete reason this "
        "ticket exists, rather than a vague aspiration?",
    ),
    "description_sufficient": Noul(
        instructions="Does `description`, together with `goal`, give an "
        "agent enough detail to implement this without needing to ask a "
        "clarifying question first?",
    ),
    "acceptance_criteria_verifiable": Noul(
        instructions="Are the items in `acceptance_criteria` concrete and "
        "checkable (pass/fail), rather than subjective or vague?",
    ),
    "scope_exclusions_adequate": Noul(
        instructions="Given `description`, does `not_in_scope` explicitly "
        "exclude the adjacent work an agent could plausibly assume is included?",
    ),
    "protected_paths_coverage": Choice(
        instructions="Given `description`, `files_to_create`, and "
        "`files_to_modify`, does `do_not_touch` need to name protected "
        "files/systems, and if so, does it?",
        criteria={
            "specified_and_relevant": "Protection is needed and is named.",
            "not_applicable": "No protected files/systems are implicated by this ticket.",
            "missing_but_needed": "Protection appears needed but nothing is named.",
        },
    ),
    "dependencies_declared": Noul(
        instructions="Does `context_references` name any other tickets or "
        "systems this one assumes are already complete, if `description` "
        "implies such a dependency?",
    ),
    # Group B: risk diagnostics
    "ambiguity_level": Score(
        instructions="How much room for differing interpretation exists "
        "across `description` and `acceptance_criteria` together?",
        criteria=[
            "clear and unambiguous",
            "some room for interpretation",
            "highly ambiguous",
        ],
    ),
    "scope_creep_risk": Noul(
        instructions="Given `description` and `not_in_scope`, is there a "
        "plausible path for an agent to expand this ticket well beyond its "
        "stated `goal`?",
    ),
    "blast_radius": Score(
        instructions="Given `files_to_modify`, `files_to_create`, "
        "`do_not_touch`, and `description`, how much of the existing "
        "system could plausibly be touched while executing this ticket?",
        criteria=["isolated", "moderate", "wide"],
    ),
    "internal_contradiction": Noul(
        instructions="Do any statements across `goal`, `description`, and "
        "`acceptance_criteria` contradict each other?",
    ),
    # Group C: routing intent
    "ticket_readiness": Choice(
        instructions="Given the completeness and risk signals above, what "
        "should happen to this ticket before execution?",
        criteria={
            "ready_for_execution": "The ticket is complete, unambiguous, and safe to hand to an agent.",
            "needs_revision": "The ticket has gaps or contradictions the author should fix.",
            "needs_human_scoping": "The ticket needs specificity or safeguards only a human can add.",
            "blocked_on_dependency": "The ticket depends on something not yet done.",
        },
    ),
}


# --------------------------------------------------------------------------
# Thresholds — tunable without touching logic
# --------------------------------------------------------------------------

DEFAULT_THRESHOLDS = {
    "readiness_confidence_floor": 0.60,
    "contradiction_noul_gate": 0.70,
    "near_tie_margin": 0.15,
    # per-route: cost of being wrong sets the bar
    "route_needs_revision": 0.50,
    "route_needs_human_scoping": 0.50,
    "route_ready_for_execution": 0.80,
    # completeness noul floors used for generating remediation feedback
    "weak_section_noul": 0.50,
}


def load_thresholds() -> dict[str, float]:
    """Defaults, overridable per-key via TQ_<KEY_UPPERCASE> env vars."""
    thresholds = dict(DEFAULT_THRESHOLDS)
    for key in thresholds:
        env_value = os.environ.get(f"TQ_{key.upper()}")
        if env_value:
            thresholds[key] = float(env_value)
    return thresholds


# --------------------------------------------------------------------------
# Review + routing
# --------------------------------------------------------------------------

def review_ticket(ticket: TicketDraft) -> dict[str, Any]:
    """One batched jev call. Returns raw typed answers keyed by question ID."""
    with TypeSafeClient() as client:
        response = client.system_one(
            state=ticket.to_jev_state(),
            questions=TICKET_REVIEW_QUESTIONS,
        )
    return response.answers


# Which section each completeness primitive points at, and what to do when it fails.
REMEDIATION = {
    "goal_actionable": (
        "goal",
        "Rewrite Goal to name the concrete outcome and why it matters now, "
        "not a general aspiration.",
    ),
    "description_sufficient": (
        "description",
        "Add the detail an agent would otherwise have to ask for: inputs, "
        "expected behavior, and what the output looks like.",
    ),
    "acceptance_criteria_verifiable": (
        "acceptance_criteria",
        "Restate each criterion so it can be checked pass/fail without "
        "judgment calls.",
    ),
    "scope_exclusions_adequate": (
        "not_in_scope",
        "Name the adjacent work an agent could reasonably assume is included "
        "but shouldn't be.",
    ),
}


def build_feedback(answers: dict[str, Any], thresholds: dict[str, float]) -> list[dict[str, str]]:
    """Turn failing primitives into specific, section-keyed fix instructions.

    This is what makes the tool useful to an authoring agent: not "score 0.4"
    but "Acceptance Criteria — restate each criterion so it's pass/fail."
    """
    feedback: list[dict[str, str]] = []
    floor = thresholds["weak_section_noul"]

    for question_id, (section, instruction) in REMEDIATION.items():
        if answers[question_id].noul < floor:
            feedback.append({"section": section, "fix": instruction})

    if answers["internal_contradiction"].noul > thresholds["contradiction_noul_gate"]:
        feedback.append({
            "section": "goal/description/acceptance_criteria",
            "fix": "These sections contradict each other — reconcile them before execution.",
        })

    if answers["protected_paths_coverage"].choice == "missing_but_needed":
        feedback.append({
            "section": "do_not_touch",
            "fix": "This ticket implicates files or systems that should be protected; "
                   "name them explicitly in Do Not Touch.",
        })

    if answers["scope_creep_risk"].noul > 0.5:
        feedback.append({
            "section": "not_in_scope",
            "fix": "There's a plausible path to expanding well past the stated Goal — "
                   "tighten the scope boundary.",
        })

    if answers["ambiguity_level"].score > 1.5:
        feedback.append({
            "section": "description",
            "fix": "Description and Acceptance Criteria leave significant room for "
                   "differing interpretation — make the intended reading explicit.",
        })

    return feedback


def route_ticket_review(answers: dict[str, Any], thresholds: dict[str, float]) -> dict[str, Any]:
    """Hard gates, then confidence floor, then near-tie, then per-route threshold."""
    readiness = answers["ticket_readiness"]

    # Step 1: hard gates — override ticket_readiness at any confidence.
    if answers["internal_contradiction"].noul > thresholds["contradiction_noul_gate"]:
        return {"route": "needs_revision", "reason": "internal_contradiction", "gated": True}

    if (
        answers["blast_radius"].score > 1.5
        and answers["protected_paths_coverage"].choice == "missing_but_needed"
    ):
        return {
            "route": "needs_human_scoping",
            "reason": "wide_blast_radius_unprotected",
            "gated": True,
        }

    # Step 2: confidence floor on the classification itself.
    if readiness.confidence < thresholds["readiness_confidence_floor"]:
        return {
            "route": "needs_human_scoping",
            "reason": "low_confidence_readiness",
            "confidence": readiness.confidence,
            "gated": True,
        }

    # blocked_on_dependency is never cleared by confidence alone — jev only
    # knows a dependency was *claimed*. The caller must verify it.
    if readiness.choice == "blocked_on_dependency":
        if answers["dependencies_declared"].noul < 0.5:
            return {"route": "needs_revision", "reason": "undeclared_dependency", "gated": True}
        return {
            "route": "blocked_on_dependency",
            "reason": "declared_dependency_needs_verification",
            "verify": "Confirm the referenced ticket(s) in context_references are actually closed "
                      "before executing.",
            "gated": True,
        }

    # Step 3: near-tie on the full distribution.
    ranked = sorted(readiness.probabilities.values(), reverse=True)[:2]
    if len(ranked) == 2 and (ranked[0] - ranked[1]) < thresholds["near_tie_margin"]:
        return {
            "route": "needs_human_scoping",
            "reason": "ambiguous_readiness",
            "probabilities": readiness.probabilities,
            "gated": True,
        }

    # Step 4: per-route threshold.
    threshold = thresholds[f"route_{readiness.choice}"]
    if readiness.confidence < threshold:
        return {
            "route": "needs_human_scoping",
            "reason": f"below_threshold_for_{readiness.choice}",
            "confidence": readiness.confidence,
            "gated": True,
        }

    return {
        "route": readiness.choice,
        "reason": "cleared_threshold",
        "confidence": readiness.confidence,
        "gated": False,
    }
