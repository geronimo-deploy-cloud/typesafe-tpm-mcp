---
name: ticket-quality
description: Use when drafting, revising, or about to execute a work ticket for a subagent. Covers calling the ticket-quality MCP server to check a ticket before execution, interpreting its routing verdict and section-level fixes, and knowing when to revise versus escalate to a human. Trigger whenever writing a new ticket or issue, or when handed a ticket to implement that has not yet been reviewed.
---

# Ticket quality gate

A ticket that reads as complete but is quietly ambiguous costs a full
agent run to discover. This gate catches that before execution by asking
a TypeSafe System One model a batch of narrow questions about the ticket
and returning a routing verdict.

## When to call it

**Always call `review_ticket_quality` before:**
- Opening a new ticket for a subagent
- Starting implementation on a ticket that has no recorded review

**Do not call it for:** conversational task requests, tickets already
reviewed and unchanged since, or tickets you are only reading for context.

## Drafting first

Call `get_ticket_template` before writing a ticket. Fill every section —
the gate checks all of them, and an empty `not_in_scope` or `do_not_touch`
is one of the most common reasons a ticket gets held. Use `files_to_create`
for new files and `files_to_modify` for existing ones the ticket will
change — a ticket that's really a modification but only fills
`files_to_create` reads as more novel/isolated than it is, which can throw
off `blast_radius`. `explain_primitives` lists exactly what each question
checks if you want to pre-empt a failure while drafting.

## Reading the verdict

The response has four parts. Read them in this order.

**1. `route` — what happens next. This is binding.**

| Route | What you do |
|---|---|
| `ready_for_execution` | Proceed. Open the ticket, or begin implementing. |
| `needs_revision` | Apply the `fixes`, then re-review. Do not implement. |
| `needs_human_scoping` | Stop and ask Chris. Do not revise-and-retry your way past this. |
| `blocked_on_dependency` | Verify the referenced tickets are actually closed. If they aren't, hold. |

Never begin implementation on any route other than
`ready_for_execution`. A held ticket is not an obstacle to route around —
it is the gate working.

**2. `fixes` — section-keyed, actionable.**

Each entry names a template section and what to change about it. Apply
them literally; they map one-to-one onto the questions that failed. After
applying, call `review_ticket_quality` again with the revised ticket.

**3. `gated` — whether a hard rule fired.**

`gated: true` means the verdict came from a rule that overrides the
classifier, not from the classifier's own confidence. The two hard gates:

- `internal_contradiction` — sections contradict each other. No confidence
  score clears this.
- `wide_blast_radius_unprotected` — the ticket could touch a lot of the
  system and `do_not_touch` names nothing. Needs a human to set the
  boundary.

A gated verdict is not a close call. Do not re-submit a cosmetically
reworded ticket hoping for a different number.

**4. `signals` — the raw diagnostics.**

Use these to explain your revision, not to argue with the route.
`ambiguity_level` and `blast_radius` run 0–2 (low to high);
`scope_creep_risk`, `internal_contradiction`, and the completeness signals
are probabilities where higher means more strongly true.

## Revision loop

Revise and re-review at most **twice**. If a ticket is still not
`ready_for_execution` after two revision passes, stop and escalate to
Chris with the current verdict and what you changed. Repeated near-misses
usually mean the ticket needs scoping input you don't have, not better
wording.

## Failure modes

- `error` about `TYPESAFE_API_KEY` → the server isn't configured. Say so;
  don't proceed as if the ticket passed.
- `route: needs_human_scoping` with `reason: review_unavailable` → the
  TypeSafe call failed. The gate fails closed on purpose. Report it rather
  than treating an unreviewed ticket as reviewed.

## What this gate does not do

It judges the ticket text, not the world. It cannot tell you whether a
declared dependency is actually finished, whether the approach is
technically right, or whether the work is worth doing. A
`ready_for_execution` verdict means the ticket is well-formed and safe to
hand off — not that the plan inside it is correct.
