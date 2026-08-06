# Quality and Recovery

Before returning, verify:

- the binding exactly echoes the supplied complete-Protocol, Protocol-projection,
  Selection Package, and Study Data Collection identifiers and digests without
  comparing the two distinct Protocol representations for byte equality;
- the Protocol-planned method is preserved and every applied version, variant,
  authority, applicability decision, and conflict is recorded;
- every Included Study is represented by an applicable target or explicit
  unassessed coverage; targets are Protocol-relevant, linked to real Study
  Result ids, analytically defined, and not selected by expected judgement;
- the assessment preserves every required native section, domain, signalling
  question, algorithm/proposed judgement, override rule, and overall rule;
- every response and judgement has support, scientific evidence provenance,
  and no favourable inference from missing reporting;
- unavailable or incomplete evidence is expressed through the method's
  uncertainty handling and limitations rather than an engineering rejection;
- each target has exactly one assessment, coverage is explicit, and all
  upstream identifiers are valid;
- the artifact contains no full text, runtime diagnostics, or hidden evaluation
  material.

`completed` means every Included Study is accounted for and all applicable
selected targets have method-valid assessments. It may legitimately contain no
targets when explicit coverage establishes that no applicable Result exists. It
does not mean every Report was fully accessible, every signalling answer was
favourable, or all information was reported. `partial` means required target or
method work materially remains unfinished. `blocked` means no valid bound
document can be created and requires an error issue.

The task is one complete Agent execution. If interrupted, return a truthful
non-completed outcome; do not claim a checkpoint or human independence. A later
run starts again from the immutable upstream artifacts and may reuse only
persisted, validated scientific evidence available in those artifacts.
