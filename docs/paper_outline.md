# Paper outline: Evidence-Constrained Retrieval for Auditable ADC R&D QA

This is a manuscript scaffold. Bracketed fields are intentionally incomplete;
they must be filled only after the independent holdout and human review gates
pass. No number in this file is a result.

## Working title

**Evidence-Constrained, Temporal Retrieval for Auditable Antibody–Drug Conjugate R&D Question Answering**

## Abstract template

Researchers querying antibody–drug conjugate (ADC) development data need answers
that identify the entity, preserve source and time, and expose uncertainty when
evidence is missing or conflicting. We present ADC-Evidence, a structured
evidence workbench that routes fact, comparison, literature, trial, change, and
refusal questions; binds atomic claims to source records; and fails closed when
the requested conclusion is not supported. We evaluate the system against a
fixed offline retrieval baseline on an access-controlled, independently reviewed
holdout of **[N]** questions. Primary outcomes are human-judged answer correctness,
evidence support, citation correspondence, completeness, and refusal correctness.
The paired difference is **[VALUE/CI/P-VALUE]** under a predeclared rubric.
Component ablations test **[COMPONENTS]** while holding corpus, budget, and
generator constant. Results **[SUPPORT/DO NOT SUPPORT]** the hypotheses that
structured routing and evidence validation improve **[OUTCOME]**. We release the
public code, smoke checks, schemas, and analysis scripts; private source records
and reviewer identities remain protected.

## 1. Research questions and hypotheses

- **RQ1:** Does structured routing improve human-judged correctness and
  completeness on multi-field ADC questions?
- **RQ2:** Does claim-level evidence validation reduce unsupported conclusions
  and incorrect citations?
- **RQ3:** How does the system behave under missing, conflicting, and
  time-dependent evidence?

The preregistered hypotheses are H1 (routing), H2 (evidence validation), and H3
(temporal/conflict handling). They remain hypotheses until the independent
holdout analysis is complete.

## 2. System and task definition

Describe the data model, temporal fact representation, source snapshots,
retrieval modes, exact PMID/NCT routing, structured field answering, refusal
guards, citation validation, and audit trail. Define the task as research
information retrieval and synthesis; exclude patient-specific diagnosis,
prescribing, dose selection, and treatment recommendations.

## 3. Evaluation protocol

### 3.1 Data and splits

Report database data version, source snapshot hashes, question-set hash, cutoff
time, entity/category counts, and licensing. The 120-question development set
and public 20-question smoke holdout are exploratory. The primary test set must
be constructed and frozen outside the development workflow, with an
access-control record and `eligible_for_unseen_test_claim: true`.

### 3.2 Systems and baselines

Compare the full system with a same-corpus offline extractive RAG baseline.
Lock the corpus, top-k, retrieval budget, generator, prompt, and code commit
before unblinding. Use `ADC_OFFLINE_ONLY=true` for the reproducible no-API
condition. Any remote-model arm is a separate experiment with its exact model,
prompt, cost, and network configuration reported.

### 3.3 Human review

Use a blinded packet with primary and secondary independent ratings for all
high-risk questions and the predeclared ordinary subset. Resolve disagreements
with an adjudicator after both independent ratings are saved. Store
`review_origin` and reviewer-slot metadata; report coverage, disagreement count,
observed agreement, and Cohen's κ. AI-assisted review can triage cases but is
not an independent human label.

### 3.4 Outcomes and statistics

Define binary success before looking at results (for example, all required
answer, evidence, citation, completeness, and refusal fields meet the rubric).
Use paired question-level labels, bootstrap confidence intervals, and the exact
two-sided McNemar test. Report the full contingency table, sample size, missing
labels, sensitivity analyses for partial answers, and all failed runs.

## 4. Results tables (fill only from verified artifacts)

| Outcome | Full system | Offline baseline | Paired difference (95% CI) | McNemar p |
|---|---:|---:|---:|---:|
| Human correctness | `[PENDING]` | `[PENDING]` | `[PENDING]` | `[PENDING]` |
| Evidence support | `[PENDING]` | `[PENDING]` | `[PENDING]` | `[PENDING]` |
| Citation correspondence | `[PENDING]` | `[PENDING]` | `[PENDING]` | `[PENDING]` |
| Completeness | `[PENDING]` | `[PENDING]` | `[PENDING]` | `[PENDING]` |
| Refusal correctness | `[PENDING]` | `[PENDING]` | `[PENDING]` | `[PENDING]` |

Every table row must link to a report hash, review-origin audit, database
version, and the exact analysis command.

The readiness report also records warnings separately from blockers; a warning
such as a runtime-generated demo database must not be presented as confirmation
evidence.

## 5. Ablation and error analysis

For each component, report a matched ablation with the same questions, corpus,
budget, and generator. Separate exact identifier routing, structured field
validation, evidence-topic validation, and refusal policy where the design
permits. Group human-confirmed errors by missing fact, wrong source, unsupported
claim, conflict handling, and over-refusal. Do not infer component causality
from the combined full-system versus baseline comparison.

## 6. Limitations and ethics

State that public seed data are not a clinical gold standard, that source
freshness and licensing constrain generalization, and that the system is not a
clinical decision tool. Discuss single-domain coverage, question construction
bias, reviewer expertise, residual semantic-support errors, and the difference
between smoke diagnostics and confirmation results.

## 7. Reproducibility checklist

- [ ] Independent holdout manifest and access-control record.
- [ ] Independent holdout manifest bound to the frozen JSONL file hash and count.
- [ ] Human review JSONL with accepted provenance values only.
- [ ] Independent reviewers followed the blinded packet and submitted before identity reveal.
- [ ] Double-review agreement and adjudication report.
- [ ] Database, corpus, question, code, and prompt hashes.
- [ ] Public artifact manifest with commit, tracked-file hashes, and hygiene result.
- [ ] Paired statistics JSON and analysis command.
- [ ] Ablation reports with matched budgets.
- [ ] CI log and uploaded paper-readiness audit.
- [ ] Dependency freeze captured for each supported Python version.
- [ ] Public artifact excludes private source records, reviewer identities, and keys.

Until every unchecked item is complete, describe the work as an engineering
evaluation or methods report rather than a confirmed superiority study.
