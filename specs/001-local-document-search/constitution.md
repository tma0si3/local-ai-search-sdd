<!--
SYNC IMPACT REPORT (temporary scratch material — remove before committing)

Version change: 1.0.0 → 2.0.0
Bump rationale: MAJOR. The five placeholder-derived principles drafted in 1.0.0 were
inferred from the project name without author input. They are replaced wholesale by
eight author-supplied principles. Two 1.0.0 principles (Pluggable Model and Index
Backends; Reproducible Indexing) are removed outright as unjustified complexity under
the new simplicity mandate, which is a backward-incompatible governance change.

Modified principles:
  I. Local-First and Private by Default   → IV. User Documents Stay on the Local Machine (narrowed)
  III. Test-First (NON-NEGOTIABLE)        → V. Automated Tests for Important Backend Behavior (relaxed from strict TDD)
  V. Observable and Debuggable Retrieval  → VIII. Easy to Understand and Run Locally (reframed)

Added principles:
  I. Simple, Understandable Architecture
  II. Python and Open-Source Local Components
  III. No Cloud Services Required for the MVP
  VI. Small, Independently Testable Components
  VII. No Unnecessary Frameworks or Infrastructure

Removed principles:
  II. Pluggable Model and Index Backends (1.0.0) — abstraction not yet earned
  IV. Reproducible Indexing (1.0.0)              — presumed a search architecture not yet chosen

Modified sections:
  Security and Data Handling Constraints → Technology and Dependency Constraints
  Development Workflow and Quality Gates → retained, rewritten to match relaxed testing stance

Follow-up TODOs (deferred placeholders):
  - TODO(PROJECT_SCOPE): The repository still contains no README or source. The
    application's actual purpose is undefined here; principles are domain-neutral by
    necessity. Confirm scope on first amendment.
  - TODO(GUIDANCE_FILE): No runtime agent guidance file exists yet. Create one and
    reference it from Governance when the first feature lands.
  - TODO(IMPORTANT_BEHAVIOR): Principle V governs "important" backend behavior. The
    project MUST record its working definition once the first module exists.
-->

# Local AI Search Constitution

## Core Principles

### I. Simple, Understandable Architecture

The architecture MUST be explainable to a new developer in a single sitting without
a diagram tool. Indirection MUST be introduced only in response to a problem that
has already occurred, never in anticipation of one. Where two designs satisfy the
requirement, the one with fewer moving parts MUST be chosen.

Rationale: This is a small application. Architectural sophistication it does not need
is pure carrying cost, paid on every future change.

### II. Python and Open-Source Local Components

The implementation language is Python. Components MUST be open-source and MUST be
able to run on the developer's machine. A dependency that requires a paid license,
a hosted account, or a proprietary runtime MUST NOT be introduced.

Rationale: A single language and a locally runnable stack keep the project
inspectable, forkable, and free of access barriers for anyone who clones it.

### III. No Cloud Services Required for the MVP

The MVP MUST be fully functional with no network access. No cloud service may be a
required dependency for installing, running, or testing the application. Optional
remote integrations MAY exist, but MUST degrade cleanly to a working local-only
mode when absent or unreachable, and MUST NOT be enabled by default.

Rationale: A hard cloud dependency makes the application unusable offline, couples
its lifetime to a vendor's, and introduces account management into a tool that
should just run.

### IV. User Documents Stay on the Local Machine

User documents, their contents, and anything derived from them MUST remain on the
local machine. Transmitting them off-device MUST NOT occur. Where a future feature
genuinely requires egress, it MUST be opt-in, disabled by default, disclosed at the
point of enablement, and scoped to the minimum data required. Telemetry and usage
analytics MUST NOT be collected.

Rationale: Users entrust the application with personal documents. Silent egress of
that material is a defect of the highest severity, not a configuration choice.

### V. Automated Tests for Important Backend Behavior

Important backend behavior MUST be covered by automated tests. "Important" means
logic that is hard to verify by inspection, that has failed before, or whose failure
would be silent. Bug fixes MUST include a test that fails before the fix. Exhaustive
coverage of trivial code is NOT required and SHOULD be avoided.

Rationale: Tests exist to catch regressions in logic that is genuinely difficult to
reason about. Blanket coverage targets produce ceremony, not confidence.

### VI. Small, Independently Testable Components

Components MUST be small enough to test in isolation. A component MUST NOT require
the full application to be running in order to be exercised. I/O, configuration
access, and external calls MUST be kept at the edges so core logic can be tested
without them.

Rationale: Independently testable units are the mechanism that makes Principle V
cheap enough to actually follow.

### VII. No Unnecessary Frameworks or Infrastructure

Frameworks, service layers, container orchestration, message queues, and background
infrastructure MUST NOT be introduced unless a concrete, present requirement cannot
be met without them. The standard library and a small number of focused libraries
are the default. Every dependency MUST be justified at the point it is added.

Rationale: Infrastructure added speculatively must still be configured, debugged,
upgraded, and understood by everyone who follows.

### VIII. Easy to Understand and Run Locally

A developer MUST be able to clone the repository and run both the application and
its tests using documented commands, without manual environment surgery. Setup
steps MUST be documented and MUST be kept current. Errors MUST state what failed
and what to do about it.

Rationale: The time between cloning and a working local run is the clearest signal
of whether the preceding seven principles are actually being honoured.

## Technology and Dependency Constraints

- Python is the implementation language. Introducing a second runtime requires an
  amendment to this constitution.
- Dependencies MUST be open-source, locally runnable, and declared in a single
  dependency manifest.
- Credentials and tokens, if any optional integration requires them, MUST be read
  from the environment and MUST NOT appear in source, committed configuration,
  or logs.
- Application data, caches, and generated artifacts MUST be written only to paths
  the user has configured or to a documented application data directory.
- Any outbound network call MUST be attributable to a named, documented, optional
  feature.

## Development Workflow and Quality Gates

- Every change MUST originate from a specification produced by the Spec Kit
  workflow before implementation begins.
- A change MUST NOT merge while any test is failing.
- A bug fix MUST include a regression test.
- Dependency additions MUST be justified in the pull request, including why the
  functionality cannot reasonably be implemented with the standard library.
- Setup and run instructions MUST be updated in the same change that invalidates
  them.

## Governance

This constitution supersedes all other development practices for this project.
Where guidance conflicts, this document controls.

**Amendment procedure.** Amendments MUST be proposed as a change to this file, MUST
state the rationale, and MUST identify any in-flight work requiring migration. An
amendment takes effect when merged.

**Versioning policy.** This document follows semantic versioning. MAJOR for the
removal or backward-incompatible redefinition of a principle; MINOR for a new
principle or materially expanded guidance; PATCH for clarifications and wording
that do not change meaning.

**Compliance review.** Every pull request MUST verify compliance with these
principles. Deviations MUST be justified in writing in the pull request and either
accepted as a scoped exception with a stated expiry or rejected. Unjustified
complexity is grounds for rejection on its own.

**Version**: 2.0.0 | **Ratified**: 2026-10-03 | **Last Amended**: 2026-10-03
