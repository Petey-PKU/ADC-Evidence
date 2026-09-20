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

### 2.1 Implementation-to-manuscript map

The implementation claims in this section should be tied to the following
public artifacts rather than reconstructed from screenshots or ad-hoc runs:

| Manuscript element | Public implementation or record | Current interpretation |
|---|---|---|
| Entity and temporal evidence model | `src/adc_evidence/database.py`, `src/adc_evidence/workbench.py`, `docs/data_sources.md` | Source snapshots and data versions are explicit; freshness and completeness remain source-specific. |
| Question routing and structured facts | `src/adc_evidence/generation/service.py`, `src/adc_evidence/generation/structured.py` | Exact fact, comparison, trial, literature, change, and refusal routes are deterministic code paths. |
| Retrieval and citation controls | `src/adc_evidence/rag/retriever.py`, `src/adc_evidence/generation/citations.py`, `src/adc_evidence/generation/guards.py` | Retrieval, claim support, citation validity, and refusal are separately recorded; passing a programmatic guard is not semantic correctness. |
| Public data boundary | `data/public/catalog_scope_policy.json`, `data/public/marketed_adc_catalog.audit.json`, `docs/public_dataset_and_benchmark.md` | The snapshot has 23 catalog records, 3,503 trials, 1,410 documents, and 6,754 entity links; source coverage is partial or unknown and catalog fields remain pending independent review. |
| Development benchmark | `data/annotations/public_benchmark_v1.manifest.json`, `src/adc_evidence/evaluation/public_benchmark.py` | The 98-question public set is `development_exposed`; its automatic scores are smoke diagnostics and cannot support an unseen-test claim. |
| Same-corpus comparison | `src/adc_evidence/evaluation/benchmark.py`, `src/adc_evidence/evaluation/offline_comparison.py`, `scripts/compare_public_benchmark.py` | Reports bind question, database, prompt, network, generator, and retrieval-budget metadata before paired diagnostics are produced. |
| Human and holdout gates | `src/adc_evidence/evaluation/paper_readiness.py`, `docs/independent_review_packet.md` | Human labels must use independent/adjudicated provenance; the holdout must be separately frozen and access controlled. Both are currently missing. |
| Reproducible distribution | `scripts/package_public_release.py`, `scripts/verify_public_release.py`, `docs/release_gate_2026-09-20.md` | The current package is research-only; a public release still requires a valid redistribution attestation. |

This map separates what the code currently guarantees from what must be
established by independent review. In particular, the public catalog and
benchmark are inputs for reproducibility, not gold-standard labels.

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
- [ ] Public artifact manifest with package version, release reference, commit, tracked-file hashes, and hygiene result.
- [ ] Paired statistics JSON and analysis command.
- [ ] Ablation reports with matched budgets.
- [ ] CI log and uploaded paper-readiness audit.
- [ ] AI-assisted pre-review risks addressed; independent human review remains required.
- [ ] CI offline smoke holdout report archived (diagnostic only, not an unseen-test result).
- [ ] Dependency freeze captured for each supported Python version.
- [ ] Public artifact excludes private source records, reviewer identities, and keys.

Until every unchecked item is complete, describe the work as an engineering
evaluation or methods report rather than a confirmed superiority study.
