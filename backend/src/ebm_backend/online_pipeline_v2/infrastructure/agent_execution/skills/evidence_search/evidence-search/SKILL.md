---
name: evidence-search
description: Design, execute, verify, and package reproducible source-specific evidence searches from an approved Cochrane intervention-review Protocol. Use for the Evidence Search professional task when Codex or Claude must execute the Protocol's planned databases, registers, and other sources through legitimate provider-native capabilities or declared scripts, preserve Search Runs and bibliographic Records, and return an auditable Search Package without screening, deduplication, Report collation, or Study identification.
---

# Execute Evidence Search

Read the task input and every linked reference before acting:

- [Methodology authority](references/methodology-authority.md)
- [Strategy construction](references/strategy-construction.md)
- [Tools and source execution](references/source-capabilities.md)
- [Final checks and retry](references/final-checks-and-retry.md)
- [Output contract](references/output-contract.md)

When `find-and-read-methodology` is supplied as a companion Skill, use it to
inspect the governing review method and each source's execution-bearing
vocabulary, syntax, interface, and export guidance. Keep strategy design,
source execution, and Search Run reporting in this Skill.

## Complete the task

The task may run in `initial` or `supplementary` mode. Initial mode executes
the Protocol's planned source coverage. Supplementary mode receives a parent
Search Package reference plus an explicit evidence gap and candidate leads;
execute only legitimate follow-up searches that address those gaps. Do not
repeat the entire initial plan, alter the Protocol, or screen the new Records.
The Backend merges supplementary results with the parent package after this
task returns, preserving both immutable search rounds.

1. Treat the Protocol as authoritative for scope, eligibility, planned
   sources, restrictions, and methodology choices. A Protocol strategy is an
   optional planned baseline, not the exact query to run.
2. Develop a final source-specific executable strategy or reproducible
   procedure for every Protocol source. Check any supplied baseline for its
   named source and platform; retain, revise, translate, or replace it without
   changing Protocol scope.
3. For each Protocol source, choose the best legitimate execution path from
   provider-native capabilities and declared scripts. Start from the named
   source and platform, not from the available scripts. A script is an optional
   capability and must not change, replace, or narrow the Protocol source plan.
4. Execute available sources and inspect the actual observations. Iterate
   strategy development when terminology, syntax, query translation, warnings,
   counts, or sampled observations expose a material problem. Decide when the
   final strategy is professionally adequate; there is no Backend attempt
   count or numeric stopping threshold. Preserve the final strategy actually
   executed and explain the development and stopping judgement in the Search
   Run narrative. Never replace returned counts, identifiers, or Records with
   generated data.
5. Do not attempt a source when no compatible or authorized access path exists,
   required prior evidence is not yet available, or the procedure requires
   external communication that was not explicitly authorized. Record it as
   unavailable with the planned query or procedure and a specific reason.
   Record a real attempted execution that failed as failed. Do not invent
   Records.
6. Invoke the deterministic package tool after all source results exist.
7. Verify Protocol source coverage, status consistency, provenance, counts,
   digests, and scope before returning the structured result.

## Exercise professional judgment

Choose concepts, terms, filters, source mappings, and translations as an
information specialist would. Prefer sensitivity with reasonable precision.
Do not force every PICO element into a query.

Use provider-native web or browser capabilities for official method,
vocabulary, syntax documentation, and legitimate execution of Protocol
sources. A generic web result is not an execution result from a named
bibliographic database or register.

Do not send messages, submit contact forms, request records from people or
organizations, or use subscription access that is not available in the
execution environment. A Protocol plan to contact investigators, experts, or
manufacturers does not itself authorize that external action.

Do not change the Review PICO, eligibility criteria, planned restrictions, or
planned sources. Do not screen or deduplicate Records. Do not create Reports,
Studies, Report–Study links, eligibility decisions, or classifications.

## Protect evidence integrity

Never use an existing completed review's search results, included-study list,
benchmark Gold, target review, or withheld answer source as a substitute for
executing the supplied Protocol. Ignore such answers if encountered.

Keep task completion separate from source coverage. Return `completed` when
every source or supplementary procedure in this invocation was executed or
reached an honest stopping judgement, the required professional review and
packaging were completed, and a valid Search Package can be produced. Source
Runs may remain `partial`, `failed`, or `unavailable`; preserve each limitation
as a source status and issue without mechanically making the task `partial`.

Return `partial` only when required professional work in this invocation is
actually unfinished, such as an unaccounted source, an uninspected tool result,
or an interruption before an honest stopping judgement or valid package was
reached. Return `blocked` with `data: null` for an initial search when no usable
Search Run can be produced, or whenever no valid Search Package can be
produced. In supplementary mode, a completed round may add only failed or
unavailable observations when every follow-up path reached an honest stopping
judgement and the supplied parent Package remains the usable search basis.
