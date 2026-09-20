"""MCP server exposing the jev ticket-quality gate to agents.

Run with:  uv run typesafe-tpm-mcp
Transport: stdio (the default for local MCP clients).
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from .schema import (
    TICKET_REVIEW_QUESTIONS,
    TicketDraft,
    build_feedback,
    load_thresholds,
    review_ticket,
    route_ticket_review,
)

mcp = MCPServer("ticket-quality")


TICKET_TEMPLATE = {
    "title": "",
    "goal": "Why this ticket exists — the concrete outcome and why it matters now.",
    "description": "What to build or change, in enough detail that an agent "
                   "can implement it without asking a clarifying question.",
    "acceptance_criteria": ["Checkable pass/fail condition"],
    "not_in_scope": ["Adjacent work an agent might assume is included but isn't"],
    "files_to_create": ["Path or location the ticket should produce"],
    "do_not_touch": ["Files, systems, or pipelines that must not be modified"],
    "context_references": ["Dependencies, related tickets, prior art"],
}


@mcp.tool()
def get_ticket_template() -> dict[str, Any]:
    """Return the blank ticket template with guidance for each section.

    Use this before drafting a ticket so the draft already has every section
    the quality gate checks for.
    """
    return TICKET_TEMPLATE


@mcp.tool()
def review_ticket_quality(
    title: str,
    goal: str,
    description: str,
    acceptance_criteria: list[str] | None = None,
    not_in_scope: list[str] | None = None,
    files_to_create: list[str] | None = None,
    do_not_touch: list[str] | None = None,
    context_references: list[str] | None = None,
) -> dict[str, Any]:
    """Review a drafted ticket for quality before an agent executes it.

    Returns a routing verdict (`ready_for_execution`, `needs_revision`,
    `needs_human_scoping`, or `blocked_on_dependency`), a list of
    section-keyed fixes, and the underlying diagnostic signals.

    Do NOT begin implementing a ticket whose route is anything other than
    `ready_for_execution`.
    """
    ticket = TicketDraft(
        title=title,
        goal=goal,
        description=description,
        acceptance_criteria=acceptance_criteria or [],
        not_in_scope=not_in_scope or [],
        files_to_create=files_to_create or [],
        do_not_touch=do_not_touch or [],
        context_references=context_references or [],
    )

    if not os.environ.get("TYPESAFE_API_KEY"):
        return {
            "error": "TYPESAFE_API_KEY is not set in the server environment. "
                     "See the README quickstart.",
        }

    thresholds = load_thresholds()

    try:
        answers = review_ticket(ticket)
    except Exception as exc:  # surface the failure rather than silently passing the ticket
        return {
            "error": f"TypeSafe review call failed: {exc}",
            "route": "needs_human_scoping",
            "reason": "review_unavailable",
        }

    decision = route_ticket_review(answers, thresholds)
    feedback = build_feedback(answers, thresholds)

    return {
        "route": decision["route"],
        "reason": decision["reason"],
        "confidence": decision.get("confidence"),
        "gated": decision.get("gated"),
        "verify": decision.get("verify"),
        "fixes": feedback,
        "signals": {
            "ambiguity_level": answers["ambiguity_level"].score,
            "blast_radius": answers["blast_radius"].score,
            "scope_creep_risk": answers["scope_creep_risk"].noul,
            "internal_contradiction": answers["internal_contradiction"].noul,
            "protected_paths_coverage": answers["protected_paths_coverage"].choice,
            "dependencies_declared": answers["dependencies_declared"].noul,
            "goal_actionable": answers["goal_actionable"].noul,
            "description_sufficient": answers["description_sufficient"].noul,
            "acceptance_criteria_verifiable": answers["acceptance_criteria_verifiable"].noul,
            "scope_exclusions_adequate": answers["scope_exclusions_adequate"].noul,
        },
        "readiness_probabilities": answers["ticket_readiness"].probabilities,
    }


@mcp.tool()
def explain_primitives() -> dict[str, Any]:
    """List the questions this gate asks and what each one checks.

    Useful when you want to understand *why* a ticket was routed the way it
    was, or to pre-empt a failure while drafting.
    """
    return {
        question_id: question.instructions
        for question_id, question in TICKET_REVIEW_QUESTIONS.items()
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
