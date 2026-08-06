---
name: find-and-read-methodology
description: Locate, verify, and inspect the current directly applicable official or primary methodology needed by an active evidence-based-medicine task. Use as a companion when a parent Skill must interpret a Protocol-selected standard, resolve an open method choice, or apply a method whose executable guidance, instrument, template, algorithm, syntax, or update details are not fully present in task input.
---

# Find And Read Methodology

Obtain the execution-bearing methodology needed by the active professional
task. Find and read authority; leave method selection within Protocol
constraints, professional application, judgements, and task output to the
parent Skill.

Read [authority discovery and sufficiency](references/authority-discovery-and-sufficiency.md)
when source roles, version identity, access, or stopping judgement are unclear.

## Workflow

1. Determine the exact execution need from the Protocol and parent task:
   method, version or revision, variant, applicable study or review design,
   decision left open, and the part of the method that must be applied or
   checked. Do not broaden the search into unrelated methodology.
2. Identify the current directly applicable official or primary authority. If
   the Protocol binds a historical version, retrieve that version and inspect
   current official update information only to identify a material conflict or
   interpretation issue; do not silently replace the Protocol.
3. Follow the authority chain beyond catalog, search, citation, product, and
   version landing pages. Inspect the execution-bearing content needed for the
   task, which may be an online chapter, full guidance document, instrument,
   template, algorithm, technical supplement, platform documentation, or a
   combination. A page that merely names or links a method is not evidence that
   its operational content was read.
4. Read enough to establish applicability and execute the relevant method:
   required sections or steps, conditional paths, permitted responses or
   choices, decision or calculation rules, output obligations, exceptions, and
   update notices that can materially affect this task. Adapt depth to the
   execution need rather than mechanically reading every document on a site.
5. Reconcile the source identity, version, variant, and scope across the
   materials actually inspected. Preserve conflicts and ambiguous
   applicability. If official or primary guidance is inaccessible after
   reasonable legitimate attempts, the parent task may use the model's
   existing methodology knowledge as an explicitly marked `llm_fallback`;
   never present that knowledge as a read authority or invent its URL,
   version, sections, or access date. Record the model identifier and the
   unverified limitation in the parent's existing methodology fields.
6. Hand the parent Skill the exact title, direct locator, version or revision,
   sections or material actually read, applicable principles, decisions they
   informed, and remaining limitations. Record them through the parent's
   existing methodology, authority, decision, provenance, narrative, or issue
   fields. Do not create a separate methodology artifact or access log.
7. Stop when the inspected authority is sufficient for the parent to apply and
   self-check the method, or when materially different official or primary
   paths are unlikely to resolve the remaining gap. An authority access gap is
   a methodology-sufficiency limitation, not unfinished task work: if the
   parent can still form a coherent, executable professional output (including
   an explicitly marked `llm_fallback`), return `completed` with a warning.
   Use `partial` only when a required professional step or target remains
   undone, and `blocked` only when no valid output can be formed. Never turn an
   access limitation into an engineering crash.

## Autonomy And Boundaries

Choose lawful native search, browsing, PDF, document, image, or file-reading
paths suited to the source. No fixed site list, locator order, file format,
request count, or tool route is prescribed. Prefer the governing organization
and original method authors over secondary summaries; use search results and
aggregators only as discovery leads.

Do not reproduce an external standard inside this Skill, treat repository
history as methodological authority, or present remembered rules as a read
authority. A clearly marked model fallback may guide a provisional method, but
it is not verified execution truth. Do not retrieve Studies, Reports, completed-review answers,
benchmark Gold, or other scientific evidence unless the parent Skill
independently permits that evidence activity. Do not make the parent's
eligibility, extraction, Risk-of-Bias, synthesis, certainty, or reporting
decision.
