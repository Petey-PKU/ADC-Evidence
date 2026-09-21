# Reproducibility record: independent holdout preparation (2026-09-21)

An independent holdout draft was constructed outside the public repository at
the current public code version `bcd27ab3802329b7caf1f62a33ee660dfa0c1963`.
The private question file is not tracked, copied, or published in this
repository. It contains 20 questions with structured facts, comparisons, and
refusal cases; every row includes a standard answer, evidence-source metadata,
partial-answer policy, refusal rule, and scoring fields.

The content-free manifest records an owner-controlled private ACL. This is an
operator attestation, not an automatic proof of access permissions. Before a
paper evaluation, a project owner must independently confirm the ACL, source
answers, question independence, and the evaluation window.

| Artifact | Public record |
|---|---|
| Question count | `20` |
| Question-file and question-set hashes | retained in the private manifest |
| Database/index/question-set binding | retained in the private evaluation record |
| Evaluation window and ACL details | retained outside the public repository |

The paper-readiness audit validated the private manifest, file hashes, schema,
and exact-text disjointness against the 120 exposed questions. With this private
holdout supplied, the `independent_holdout` check is `pass`; the overall audit
remains `not_ready_for_submission` because real `human_independent` or
`human_adjudicated` labels are still absent. The draft is therefore a
preparation artifact, not a publication result.

The frozen draft was also smoke-tested against the verified offline release
launcher without a model API: 20/20 questions completed without runtime errors;
14 structured questions and 3 comparison questions used the structured backend
with claim validation reported as valid, and 3 refusal questions used the
refusal route. These are routing and execution diagnostics only; they do not
measure semantic correctness or replace human review.

A private two-arm review packet has now been generated from the same offline
run. It contains 20 questions, 40 blinded candidate outputs, and 80 blank
review slots for two independent reviewers per candidate. The arm identity map
is stored separately and remains undisclosed until both ratings are saved and
any disagreements are adjudicated. The packet contains no standard answers;
automatic system-versus-baseline diagnostics remain private and are not a
publication result. Review status is still `awaiting_independent_human_review`.

Reproduce the content-free manifest in a private directory with:

```powershell
$env:PYTHONPATH="<public-repo>\src"
python <public-repo>\scripts\build_independent_holdout_manifest.py `
  --questions <private-review>\holdout_questions.jsonl `
  --question-set-version <private-version> `
  --evaluation-window-id <private-window> `
  --access-control-method "owner-controlled private ACL; file stored outside public repository" `
  --database-data-version <private-data-version> `
  --code-commit <public-code-commit> `
  --output <private-review>\holdout_manifest.json
```

No question content, reviewer identity, local path, or private manifest was
added to the public repository.
