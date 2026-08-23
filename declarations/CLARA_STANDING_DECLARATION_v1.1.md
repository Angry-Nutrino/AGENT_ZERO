# Standing Declaration: CLARA's Admissibility Gate and Receipt Layer

**System:** CLARA (Contextual Locally Aware Robust Agent)
**Author and operator:** Alkama Eqbal
**Declaration version:** 1.1
**Issued:** 2026-08-23
**Supersedes:** v1.0 (2026-08-17), which remains a valid description of the system at its issue date
**Implementation status at issue:** gate enabled, running in SHADOW mode, external adapter live
**Canonical artifact:** this document, at https://github.com/Angry-Nutrino/C.L.A.R.A.-Contextual-Locally-Aware-Robust-Agent-/blob/main/declarations/CLARA_STANDING_DECLARATION_v1.1.md. Any copy that differs
from the authored version is not this declaration.

**What changed from v1.0.** Three corrections. All of them narrow a claim rather than widen one, and none
of them adds a capability. Two came from reviewers who read the document properly: an external reviewer found that
Section 5 asserted more about `policy_version` than the implementation supports, and a second reviewer had
earlier executed the verifier and established that the signature does not cover the decision block. The
third is a disclosure about the ledger that v1.0 simply did not make. Each is marked **[v1.1]** at the
point where it appears, rather than collected in a changelog, so that a reader who encounters the claim
encounters the correction with it.

---

## 0. What this document is, and what it is not

This is an owner-authored description of one layer of one system. I wrote it, it stays in my format, and
nobody else speaks for it. It describes what CLARA's admissibility gate does today, in the version
running on the date above. It is not a specification of what the layer will become, not a claim of
compliance with any external standard, and not a security assurance.

The parts that matter most are Section 7, what the receipt does not establish, and Section 8, the known
coverage gaps. I have put them in the same document as the capability claims on purpose. A governance
artifact that lists only what works is marketing, and it fails at exactly the moment someone relies on it.

---

## 1. Creation point

The receipt is created by the **admissibility gate**, in the tool dispatch path, **before the proposed
action executes**.

The sequence is: the agent selects a tool and arguments, the dispatcher calls the gate, the gate builds an
abstract envelope from those arguments, an adapter returns a verdict, a receipt is written, and only then
does control return to the dispatcher.

Two consequences follow, and both are deliberate.

**The evidence exists ahead of the act.** It is not derived from an execution log after the fact, so it
does not depend on the action having succeeded, or having run at all.

**A receipt is written whether the verdict is allow, review, or deny.** A denied action is still an event
that happened and is still attestable. An audit trail that records only what was permitted proves nothing
about what was stopped.

The gate fires for **instrumented mutating tools**. **[v1.1 - this read "mutating tools" in v1.0. a reviewer's
intake document used "instrumented mutating tools", which is more accurate in a single phrase,
because it carries the Section 8 coverage limit at the point of the claim instead of four sections later.
His wording, adopted.]** Non-mutating tools and a disabled gate return an immediate allow
with no envelope and no ledger entry, and the receipt says so rather than pretending an adjudication
occurred.

---

## 2. Verdicts

Three verdicts: **ALLOW**, **REVIEW**, **DENY**.

Each decision record carries:

| Field | Meaning |
|---|---|
| `receipt_id` | Identifier for this decision |
| `verdict` | ALLOW, REVIEW or DENY |
| `reason` | Why, as returned by the deciding adapter |
| `adapter` | Which adapter decided |
| `mode` | `shadow` or `enforce` |
| `enforced` | Whether this verdict actually blocked anything |
| `envelope` | The abstract action description that was adjudicated (Section 3) |

`enforced` is true only when the mode is `enforce` **and** the verdict was REVIEW or DENY. In shadow mode
it is always false. This field exists so a reader can never mistake a logged denial for a prevented action.

**[v1.1] None of the fields in this table are covered by the signature.** The signature is applied to the
envelope (Section 3), which is one field inside this record. `verdict`, `reason`, `adapter`, `mode` and
`enforced` are assembled after signing and are not bound by it. There is no receipt-level signature.
Altering a verdict in a stored ledger row does not break verification of that row's envelope.

I am stating this here, beside the fields themselves, because I have twice told a third party the opposite
in correspondence while this document said the correct thing. A claim that lives in only one section is a
claim I can misremember. One reviewer established this by executing the verifier in a container on
2026-08-18. A second independently caught the same contradiction between my correspondence and this
document on 2026-08-23.

---

## 3. The envelope, and the privacy floor

The gate never adjudicates on raw arguments. It builds an **abstract envelope** containing metadata only.

| Field | Content |
|---|---|
| `agent_id` | Static agent identifier |
| `timestamp` | UTC, ISO 8601, explicit offset, second precision |
| `nonce` | Per-decision unique value |
| `policy_version` | Identifier of the ruleset that produced the verdict (Section 5) |
| `signature`, `signature_alg` | Ed25519 signature over all other fields (Section 5) |
| `tool` | Tool name |
| `intent` | Declared intent for that tool |
| `target_type` | `local_file` or `process` |
| `target_path_hash` | SHA-256 of the target **basename**, truncated to 16 hex characters |
| `arg_summary` | Argument keys with each value's **type and character length only**, never the value |
| `target_class` | Coarse class of what is being touched (below) |
| `operation_class` | `read`, `write`, `modify`, `delete` or `execute` |
| `risk_class` | `low`, `medium`, `high` or `critical` |
| `irreversible` | Boolean, derived from operation semantics |
| `data_classification`, `execution_mode`, `task_id` | Context labels |

**The privacy floor:** no raw path, no file content, no command string, no conversation text ever enters
the envelope. Classification happens locally, on the raw values, and only the resulting labels leave the
machine. That is what lets an external engine distinguish a sandbox note-write from a system write without
ever seeing a path.

**Target classes.** File targets resolve to one of nine: `credentials`, `vcs_internal`, `host_config`,
`system_binary`, `dependency_manifest`, `build_config`, `sandbox`, `user_space`, `project`. Process
targets resolve to one of four: `dev_tool`, `project_script`, `shell`, `system_service`.

Precedence is evaluated most-dangerous-first and is load-bearing, because a single path routinely matches
several classes and the highest must win. A credential is classified as a credential wherever it lives.

**Irreversibility is orthogonal to target class by design.** It is derived from what is being done, never
from what is being touched. Reading a version-control internal file is not irreversible; a hard history
reset is, and the operation says so. Coupling the two would make it impossible to tell whether a REVIEW
came from what was touched or from what was done to it.

**The privacy floor has a cost, and it is a real one.** Because the ledger stores only a truncated hash of
a basename, a past decision cannot be re-classified later from the ledger alone. Any re-analysis of
historical decisions has to replay raw arguments from a separate source. I state this because it is the
kind of limitation that is easy to discover only when someone actually tries the re-analysis.

---

## 4. Local and external decision paths

Two paths exist and the receipt always records which one decided.

**Local adapters** evaluate against a local policy file. They are synchronous and take microseconds.

**External adapters** send the envelope to a third-party governance engine, which returns a verdict, a
reason, and its own evidence references. Those references are carried into the receipt, so a decision made
externally is independently verifiable against that engine rather than resting on my word.

The two modes behave differently on the external path, and the difference is worth stating precisely.

In **shadow**, an external call runs fire-and-forget on a background thread. The caller receives an
immediate allow marked `enforced: false`, and the real verdict lands in the ledger out of band. This is
honest because in shadow no verdict is enforced anyway, so blocking the dispatch path on a network round
trip would buy nothing.

In **enforce**, the external call is synchronous. The verdict must be known before the action may proceed.

**Failure behaviour is currently fail-open**, and it is configurable. If an adapter errors or times out,
the action is allowed and the failure is recorded. This is the correct setting for shadow mode and the
wrong one for enforcement. Changing it is part of the enforcement decision, not a detail of it.

---

## 5. Binding: policy version and signature

Two mechanisms bind a verdict to the thing it decided on.

**Policy version.** Every envelope carries a `policy_version` derived as a **content hash of the local policy
file**, not a hand-maintained string. A hand-maintained version number goes stale the moment someone edits
the policy and forgets to bump it, and from then on the receipt is confidently wrong about which rules
were in force. An explicit override exists for cases where an external convention requires a specific
label.

**[v1.1 - CORRECTION. v1.0 described this field as the "identifier of the ruleset that produced the
verdict". That is true on the local path and false on the external one.]** The field is computed the same
way regardless of which adapter decided. On the **external** path the verdict comes from the third-party
engine and the local policy file is never consulted, so `policy_version` there identifies a ruleset that
had no part in the decision. **Read it as local policy identity only.** A verifier cannot determine, from
the receipt alone, which external ruleset produced an external verdict. The external engine's own evidence
references (Section 4) are the only handle on that. Found by an external reviewer on 2026-08-23, in answer
to a question I had not anticipated.

**Signature.** Each envelope is signed with **Ed25519** over the canonical JSON of every field except the
two signature fields themselves. Canonical means sorted keys and no whitespace, so verification does not
depend on formatting. The signature is applied **last**, after the risk metadata and the irreversibility
flag are populated, so it covers the governance-relevant fields rather than leaving exactly those unbound.

**Verification is available to third parties without my code.** The rule is fully specified: reconstruct
the canonical JSON of the envelope minus `signature` and `signature_alg`, then verify the base64 signature
against the published public key using standard Ed25519. Any Ed25519 implementation will do.

**The signing key is never generated.** If no key is configured the signature field stays empty and the
gate keeps working. This is deliberate. A per-process ephemeral key produces signatures that look valid
and can never be verified again after a restart, which is worse than no signature at all, because it
converts an honest absence of evidence into a false presence of it.

---

## 6. Retention and inspection

**Retention.** Receipts are appended to a local, append-only ledger file on the operator's machine.
Writes are atomic, using a write-to-temp, fsync, atomic-rename sequence, and are serialised by a lock so
concurrent decisions cannot clobber each other. The ledger is a **ring buffer capped at 2000 decisions**.
It is local telemetry. Nothing is shipped anywhere by default.

**The cap is a real limit, not a formality.** Once 2000 decisions have accumulated, the oldest age out and
are gone. This is not an archival record and should not be relied on as one.

**[v1.1] The ledger has no completeness, deletion, reordering or omission protection of any kind.** There
is no hash chain, no sequence numbers, no per-entry signature. Atomicity protects against a torn file
during a write. It does nothing against a file edited afterwards. Delete a row, reorder two, or remove the
last fifty, and nothing in the ledger detects it. Each surviving row's envelope still verifies
individually, which makes an absence easier to miss rather than harder.

**So the ledger is honest about each decision it contains, and silent about whether it contains all of
them.** v1.0 said "append-only" and described the atomic write, which reads as a stronger integrity claim
than the implementation makes. Asked directly by an external reviewer on 2026-08-23, and the honest answer is no.

**Inspection.** The operator can inspect the full ledger. That is me. Where an external engine decided,
that engine independently holds its own evidence for that decision, which means the external path is the
only one today where a decision is inspectable by someone who is not me.

**No inspection rights are granted by this document.** If a counterparty needs access to specific
receipts, that is a separate agreement and this declaration is not it.

---

## 7. What the receipt does and does not establish

**Establishes:**

- What was decided: allow, review or deny
- Which adapter decided it, and in which mode
- Whether the verdict was enforced
- The abstract shape of the action adjudicated: tool, intent, operation class, target class, risk class, irreversibility
- Which ruleset version produced the verdict
- When, to the second, in UTC
- That the envelope was not altered after the gate saw it, where a signing key is configured

**Does not establish:**

**It is a decision receipt, not an outcome receipt.** It records what was authorised. It does not record
that the action ran, or that its real-world effect matched the decision. Proving the effect requires
reading back the resulting state, which is a separate layer and I do not have it.

**It does not close time-of-check-to-time-of-use.** The signature proves the envelope was not altered
after the gate saw it. It does not prove that the action which executed is the action that was
adjudicated. The binding between verdict and execution is **structural**: nothing in the dispatch path
mutates arguments between the check and the call, so in practice the evaluated action is the executed one.
But nothing verifies that, and the executor does not know a gate exists. Closing this requires
re-checking the verdict against the actual arguments at execution time, which is a design change and not
a field.

**[v1.1] It does not bind the verdict.** The signature covers the envelope, which is the description of
the action that was adjudicated. It does not cover the verdict, the reason, the adapter, the mode or the
enforced flag. Those are recorded, not attested.

**[v1.1] It does not establish that the ledger is complete.** A receipt says one decision happened. The
set of receipts does not say that no decision is missing.

**It does not carry identity or authority provenance.** `agent_id` is a static string, not a per-run
principal, and there is no delegation chain behind it.

**It does not snapshot runtime configuration.** A decision can be reconstructed as to policy version and
action shape, but not as to the full runtime state that produced it.

**It does not currently prevent anything.** The system runs in shadow. Every verdict is advisory. A
recorded DENY in shadow mode means the action proceeded and the objection was logged.

---

## 8. Known coverage gaps

**The most important limitation in this document.** The gate adjudicates actions that reach it. It cannot
adjudicate a code path that does not.

I found one such path in my own system: a general-purpose code-execution tool that was never on the
checked list, which meant anything performed through it happened with no envelope, no verdict and no
receipt. It was not an attack. It is simply where the agent went by itself when the checked path was
unavailable. A denied file write and the identical write performed through that tool produce completely
different evidence, and only one of them produces any.

That gap is open as of this version. Instrumentation to measure how often it is taken is running; the
restriction is not yet built. **I regard closing it as a hard prerequisite to enforcement**, because
enforcing on one path while an equivalent unmonitored path exists produces a control that is easier to
believe in than it deserves.

**Classification is pattern matching, not semantic.** Target and risk classes are derived from string
patterns over paths and commands. An obfuscated or unusually-constructed command can land in a lower risk
class than it warrants. The taxonomy catches the ordinary cases well and does not claim to be adversarial.

**Fail-open, as noted in Section 4.**

---

## 9. Version and status

| | |
|---|---|
| Declaration version | 1.1 |
| Supersedes | 1.0 (2026-08-17) |
| Issued | 2026-08-23 |
| Gate | Enabled |
| Mode | **Shadow.** No verdict is enforced. |
| Adapter in use | External third-party governance engine |
| Adapter failure behaviour | Fail-open |
| Envelope signing | Ed25519, key configured |
| Policy versioning | Content hash of the LOCAL ruleset |
| Ledger | Local, append-only, atomic, ring buffer capped at 2000. **No completeness, deletion, reordering or omission protection** |
| Signature scope | **Envelope only.** Verdict, reason, adapter, mode and enforced are NOT signed |
| Policy version scope | **Local ruleset only.** Does not identify the deciding ruleset on the external path |
| Coverage | Instrumented mutating tools on the dispatch path. One known uninstrumented execution path remains open (Section 8). |

**Enforcement has published criteria and no date.** Five conditions must hold before the mode changes:
evidence that the shadow period actually contained dangerous cases rather than only safe ones; a measured
false-deny rate, weighted above false-allow; determinism, meaning the same action in the same context
produces the same verdict every time; a fail-closed path that has been exercised rather than designed; and
an escalation route a human actually answers. The coverage gap in Section 8 is a hard prerequisite
independent of all five.

This declaration will be reissued with a new version number if any of the above changes. Prior versions
remain valid descriptions of the system at their issue date.

---

*Authored by Alkama Eqbal. This document may be reproduced in full and unaltered. It may not be edited,
excerpted in a way that changes its meaning, or presented as speaking for any party other than its author.*
