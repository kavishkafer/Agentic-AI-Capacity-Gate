# Capacity Gate — Analysis Log

A running record of what has been built, what it computes, and what it found.
Updated as work proceeds. Read top to bottom the first time; after that, the
**Status** and **Change log** sections tell you what moved.

**Status as of 31 Aug 2026** — Gates A, B and C implemented; Gate C tested
(10/10 passing). Four measurement results from ATT&CK v19.2, plus an acquisition
curve and a worked demonstration on a converged incident. No testbed required for
any of it. CSVs in `out/`.

---

## 1. What this is for

The CRCI 2026 paper needs one measured result. The result we are producing is:

> Given a realistic instrumentation profile, what fraction of ICS attack
> techniques can be **evidenced at all**?

This is the Gate C formula from the architecture, run exhaustively over MITRE's
own data instead of over claims from a live system. Same code, different input —
which is why it needs no testbed, no agents, and no ICSSIM.

**Why nobody has done this before.** The link from a detection method to the
specific telemetry it requires only became machine-readable in ATT&CK v18
(October 2025). Before that, detections were free-text prose. The computation
below was not possible eleven months ago.

---

## 2. The data

ATT&CK STIX bundles, pulled from `mitre-attack/attack-stix-data` on GitHub.

| | version | file | size |
|---|---|---|---|
| ICS | **19.2** (current) | `data/ics-19.2.json` | 4.1 MB |
| Enterprise | **19.2** (current) | `data/ent-19.2.json` | 53.8 MB |

v18.1 bundles are also on disk from an earlier pass; **v19.2 is what the analysis
uses.** All counts below exclude deprecated and revoked objects.

---

## 3. How the detection chain actually resolves

This was the first real finding, and it is not what the architecture document
originally assumed. The chain is **not** a set of STIX `relationship` objects
throughout. It mixes relationships with embedded reference lists:

```
Technique  <--[relationship: "detects"]--  DetectionStrategy
                                                 |
                                                 |  x_mitre_analytic_refs   (embedded list)
                                                 v
                                             Analytic
                                                 |
                                                 |  x_mitre_log_source_references[]   (embedded list)
                                                 |     each entry: { x_mitre_data_component_ref, name, channel }
                                                 v
                                           DataComponent
```

So an analytic does **not** point at data components directly. It points at *log
sources*, and each log source names the data component it yields plus a channel.
`src/attack.py` walks this and flattens it to a set of data-component names per
analytic.

**Worth writing into the paper's method section**, because a reviewer checking
the bundle will see the intermediate hop and expect it to be described.

---

## 4. The gate

`src/gate.py`. The formula, unchanged from the architecture:

```
C(c) = OR  over DET in Strategies(T)
       OR  over AN  in Analytics(DET)
       AND over dc  in DataComponents(AN) :  dc in coverage(c)
```

Read: **technique T is evidenceable iff at least one of ATT&CK's own analytics
has all of its required data components available.** Any route works; each route
is all-or-nothing.

`coverage` is a set of data-component names. It can come from either:

- a **real claim** — union of `κ(s)` over the sources of every cited observation
- a **hypothetical profile** — what a given deployment can observe

Identical function, both uses. That equivalence is worth a sentence in the paper.

### The three-valued verdict

Originally the gate returned pass/fail. That was **wrong**, and the bug is
described in §6. It now returns:

| Outcome | Meaning |
|---|---|
| `PASS` | at least one analytic fully covered |
| `FAIL` | analytics exist, none fully covered — the evidence cannot support the claim |
| `UNDEFINED` | ATT&CK declares **no required data components** — no capacity check is possible at all |

`UNDEFINED` is a statement about the *ontology*, not about the evidence.

---

## 5. What is authored by us, and what is not

This division is the paper's defence against the circularity objection, so it is
enforced in the file layout:

| File | Authored? |
|---|---|
| `src/attack.py` | **No** — reads the published bundle |
| `src/gate.py` | **No** — the formula, nothing domain-specific |
| `src/profiles.py` | **Yes** — the instrumentation tiers. The only place our judgement enters |

The requirement side (what a technique needs) is entirely MITRE's. We supply only
the availability side (what a deployment has), and we sweep it.

---

## 6. The bug that became a finding

**Symptom.** With *zero* instrumentation, 12 ICS techniques reported as
evidenceable.

**Cause.** Twelve ICS analytics declare no required data components. The formula
ends in `DataComponents(AN) ⊆ coverage`, and **the empty set is a subset of
everything** — so those analytics were trivially satisfied by any coverage,
including none.

**Why it matters.** Those 12 techniques are not obscure:

| | | |
|---|---|---|
| T0813 Denial of Control | T0815 Denial of View | T0826 Loss of Availability |
| T0827 Loss of Control | T0828 Loss of Productivity and Revenue | T0829 Loss of View |
| T0831 Manipulation of Control | T0832 Manipulation of View | T0837 Loss of Protection |
| T0879 Damage to Property | **T0880 Loss of Safety** | T0882 Theft of Operational Information |

**All twelve are the ICS Impact tactic — and that is the entire Impact tactic.**
MITRE's analytic for T0880 Loss of Safety states, verbatim:

> *"No standard detection method currently exists for this technique."*

So the naive gate was passing the **most consequential claims in any converged
incident** with no evidence whatsoever. The fix — the `UNDEFINED` outcome — turns
a silent failure into an explicit one.

**This is a contribution, not just a bug fix.** Anyone building a capacity check
over ATT&CK hits the same trap. The distinction between *"the evidence does not
support this"* and *"nothing could tell us whether it does"* demands different
responses in a safety context, and a two-valued gate collapses them.

---

## 7. Results

### 7.1 Detection-chain structure

| | ICS | Enterprise |
|---|---|---|
| techniques | 97 | 697 |
| data components | 36 | 106 |
| **analytics per technique** | **1.00** | **2.50** |
| max analytics (alternative routes) | **1** | 9 |
| `UNDEFINED` techniques | 12 (12.4%) | 45 (6.5%) |

**Every ICS technique has exactly one analytic.** Not "about one" — one, with a
maximum of one. There is never an alternative route. Enterprise averages 2.5 and
reaches 9, so an Enterprise technique can often be evidenced a different way when
one telemetry source is missing. **ICS cannot.**

### 7.2 Evidenceable ICS techniques by instrumentation profile

Percentages are of the 85 *checkable* techniques (excluding the 12 `UNDEFINED`).

| Profile | PASS | FAIL | % of checkable |
|---|---|---|---|
| Network flow only | 1 | 84 | **1.2%** |
| + deep packet inspection | 8 | 77 | 9.4% |
| **+ historian / process data** | **10** | 75 | **11.8%** |
| + host logging (EWS / HMI) | 43 | 42 | 50.6% |
| + controller-side logging | 85 | 0 | 100% |

The third row is the one to quote: **a typical OT security deployment — network
monitoring plus a historian, no endpoint logging on engineering workstations, no
controller-side logs — can evidence about 12% of ICS techniques.** Flow-only
monitoring evidences one.

The last tier is the one rarely present in real facilities, and it alone accounts
for the jump from 50.6% to 100%.

### 7.3 Criticality — techniques lost if a single component is absent

ICS, top five of 34 load-bearing components:

| Techniques lost | Share | Data component |
|---|---|---|
| 44 | 45.4% | Network Traffic Content |
| 41 | 42.3% | Application Log Content |
| 31 | 32.0% | Network Traffic Flow |
| 21 | 21.6% | Process Creation |
| 17 | 17.5% | Device Alarm |

Enterprise's most load-bearing component is Process Creation at 34.3% — but
Enterprise has 2.5 fallback routes on average. **The ICS numbers are worse *and*
have no fallback.**

### 7.4 The Impact gap

All 12 ICS Impact-tactic techniques are `UNDEFINED`. ATT&CK specifies what
evidence supports *how an attacker got in and what they did*, and specifies
nothing for *what physically happened as a result*.

For converged IT/OT reconstruction that is the half of the attack that matters
most, and it is the half the ontology is silent on.

---

## 8. Worked example — the two claims from the scenario

The running scenario: attacker moves `WS-14` → `JUMP-01` → writes to `PLC-07`.
The agent makes two claims. Site coverage is *network + DPI + historian*
(7 data components).

**Claim 1 — "the attacker performed a Program Download" (T0843)**

MITRE's single analytic requires four things:

| Required | Available? |
|---|---|
| Network Traffic Content | yes |
| Device Alarm | yes |
| Asset Inventory | yes |
| **Application Log Content** | **no** — controller-side logging not deployed |

Three of four. No alternative route exists. → **FAIL**, reason: *missing
Application Log Content*. The claim may well be true; it is not provable from what
this site collects, and the gate names exactly what would fix that.

**Claim 2 — "this caused a Loss of Safety" (T0880)**

Required data components: none declared. → **UNDEFINED**. No capacity check is
possible. Under the original two-valued gate this returned **PASS** — the most
consequential claim in the incident, accepted on no evidence at all.

---

---

## 8a. Acquisition order — what to instrument first

`gate.acquisition_order()`. Greedy: at each step, add the data component that
makes the most additional techniques evidenceable. Answers the operational
question *"what should this site buy next?"* rather than *"what is the minimum
set?"*

**ICS**, 85 checkable techniques, first five steps:

| # | data component | cumulative | marginal |
|---|---|---|---|
| 1 | Application Log Content | 2 | +2 |
| 2 | Network Traffic Content | 7 | +5 |
| 3 | Network Traffic Flow | 16 | +9 |
| 4 | Device Alarm | 20 | +4 |
| 5 | Asset Inventory | 26 | +6 |

**The curve is remarkably flat.** The best single step buys 9 techniques out of
85; most buy 1–2. Reaching 98.8% takes 31 of the 36 components, and greedy then
stalls — the final technique needs two more components simultaneously, which a
greedy step cannot see.

**There is no cheap win in ICS instrumentation.** Because each technique requires
~3 specific components and there is never an alternative route, coverage is a long
grind rather than a few high-value sensors.

### A hypothesis that did not survive

We expected ICS acquisition to be *less efficient* than Enterprise. It is not:

| | 1 component | 3 | 5 | 10 |
|---|---|---|---|---|
| ICS | 2.4% | 18.8% | 30.6% | 50.6% |
| Enterprise | 3.7% | 13.7% | 25.6% | 49.4% |

Near-identical. **The ICS disadvantage is not acquisition efficiency** — it is the
absence of alternative routes (1.00 vs 2.50 analytics) and the Impact gap. Worth
reporting as a tested-and-rejected hypothesis; it makes the surviving claims
sharper.

---

## 8b. Worked demonstration — the full gate stack

`src/demo.py`. Seven claims from the valve incident, run through Gates A, B and C
against a partially-instrumented site (15 data components: endpoint logging,
firewall flow, Modbus DPI, historian, MoC records — **no controller-side logging**).

| Claim | Type | Result |
|---|---|---|
| c1 | Actor | passes — IT evidence for an IT claim |
| c2 | Join | passes — cites both IT and OT |
| c3 | Impact | passes — OT evidence for a physical claim |
| **c4** | MaliciousChange | **Gate B rejects** — cites only OT; needs IT *and* ET |
| **c5** | Technique T0843 | **Gate C rejects** — has 3 of 4 required components, missing `Application Log Content` |
| **c6** | Technique T0880 | **Gate C UNDEFINED** — no capacity check possible |
| c7 | Actor (padded) | **Gate A rejects** — cites an observation about a different asset |

The three rejections are the paper's worked examples, and each fails for a
different reason at a different gate:

- **c4** — the evidence is real and about the right asset, but OT telemetry cannot establish intent. A legitimate and a malicious logic download look identical.
- **c5** — the right *kind* of evidence, three-quarters of what is required, and no fallback route. The rejection names exactly what to instrument.
- **c6** — the most consequential claim in the incident, and ATT&CK does not say what would prove it.

### A structural gap this surfaced

**ET evidence has no representation in ATT&CK's data-component vocabulary.** There
is no component for change authorisation or management-of-change. So an ET source
contributes to `domains(c)` — which Gate B checks — but contributes *nothing* to
`coverage(c)`, which Gate C checks.

The two gates therefore operate over different vocabularies, which is precisely
why both are needed rather than one subsuming the other. Worth stating in the
paper: authorisation evidence is invisible to ATT&CK by construction.

---

## 8c. A flaw found in the specification

The architecture document defines Gate A's minimality conjunct as:

> `minimal(cites(c))` — no strict subset of `cites(c)` satisfies the other three conjuncts of A

**This is degenerate.** Gate A's other conjuncts are all *per-observation*
predicates (resolves, consistent, in-window). If every citation satisfies them,
so does every proper subset — so nothing is ever minimal and the check never fires.

Worse, a naive reading (test against the *domain* requirement instead) wrongly
rejects legitimate claims: claim c5 cites two OT observations that supply
*different* data components, both needed for T0843. Testing against domains alone
sees the second as redundant.

**Replaced with:** a citation is load-bearing if removing it either shrinks
`coverage(c)` or breaks the domain requirement.

**And an honest limitation.** That catches genuine *redundancy*, not adversarial
*padding* — a citation that widens coverage is load-bearing by construction. The
real defence against padding is the asset/reachability conjunct, which requires
every citation to concern the claim's subject (this is what rejects c7). Citation
cardinality is reported as a diagnostic alongside.

**Action:** `ARCHITECTURE-v4.md` §3 Gate A needs correcting. The current wording
does not survive implementation.


---

## 8d. Figures

`src/figures.py` — writes PDF (vector, for the manuscript) and PNG (for viewing)
to `out/`. Colours are the dataviz reference palette, slots 1 and 2 in documented
adjacent order, so CVD and contrast validation is inherited rather than re-derived.
Single-series figures carry no legend; the title names the series.

| File | Shows |
|---|---|
| `fig1_instrumentation_ladder` | the headline measurement — 1% → 12% → 51% → 100% across the five tiers |
| `fig2_routes_per_technique` | the mechanism — ICS is a single bar at 1 route; Enterprise spreads across 1–6 |
| `fig3_criticality` | single points of failure — Network Traffic Content removes 45% of ICS coverage |

**Caption note for fig3.** Three components (Device Alarm, Process History/Live
Data, Process/Event Alarm) show no Enterprise bar because they are **ICS-only
components**, not because Enterprise scores zero. Say so in the caption or a
reader will misread it.

**Figure 2 is the one that carries the argument.** The ladder shows *what* the
problem is; the routes distribution shows *why* — a single bar at 100% against a
spread. Everything else in the analysis follows from that one structural fact.


---

## 8e. Novelty sweep (31 Aug 2026)

Five arXiv query angles plus a web sweep. **The core claim survives**: no
published academic analysis computes coverage over the ATT&CK v18+
Technique→Strategy→Analytic→DataComponent graph. Everything written about the v18
detection model is vendor explainers and practitioner blogs (MITRE's own
announcement, Picus, Cymulate, Industrial Cyber). The most direct query returned
**zero results**.

Two papers surfaced that must be cited.

**SecRespond** (arXiv 2607.26791) — *"the first benchmark for evaluating LLM
agents on the post-compromise incident-response workflow."* Disk snapshot plus
alerts in, forensic report plus remediation plan out; 10 cyber ranges, 21 ATT&CK
techniques, 23 frontier LLMs. **Same scope framing we adopted** — independent
validation that post-compromise is an underexplored gap. Cloud/enterprise hosts,
no ICS/OT, no capacity reasoning. It is evaluation infrastructure rather than a
competing architecture, and it is a likely comparison point for the *system*
paper later.

**Banking-sector NIDS coverage** (arXiv 2608.00895) — the **nearest
methodological neighbour**. Maps ATT&CK techniques onto NIDS benchmark datasets
under the sensor limitations of NIST SP 800-94, using a four-model LLM consensus
to derive 68 "network-observable behaviours" from 210 techniques.

> **The contrast is worth drawing explicitly in related work.** They ask a
> structurally similar question — *what is observable under real sensor limits?* —
> and answer it by having LLMs *judge* observability from technique prose. We read
> it directly from ATT&CK's own machine-readable analytic requirements. Their
> method is what you must do **before** v18; ours is what v18 makes possible. That
> comparison strengthens the novelty claim rather than threatening it.

**Caveat.** One sweep is a signal, not proof. A DBLP and Google Scholar pass
should still be run before the paper asserts firstness.

---

## 8f. Longitudinal check — the Impact gap is not a backlog artefact

The strongest hostile review of the Impact finding is *"that is MITRE's backlog,
not a property of evidenceability."* Tested by re-running the gate against v18.1:

| | techniques | UNDEFINED | Impact tactic fully UNDEFINED |
|---|---|---|---|
| ICS v18.1 | 83 | 12 | yes, no extras |
| ICS v19.2 | 97 | 12 | yes, no extras |

**MITRE grew ICS from 83 to 97 techniques between these releases and authored
analytics for every one of the 14 new techniques — while leaving the entire
Impact tactic marked "no standard detection method currently exists."** That is a
position maintained across releases, not a queue not yet reached.

**Still separate the two claims in the paper.** The measurement establishes what
can be checked against the shared detection ontology *today*; the deeper claim —
that physical-consequence techniques are intrinsically hard to evidence from
telemetry — is *supported* by MITRE's own wording but not proven by it. Blur them
and the objection lands; separate them and it does not.

**v20 is due around late October** — after submission, before the conference.
Pin every claim to v19.2 in text, tables and captions. If the gap persists, it is
a strong slide; if it closes, "as of v19.2" holds and a longitudinal angle opens
for the journal version.

---

## 8g. Denominator decision — near-moot

Typical deployment (network + DPI + historian):

| Reading | Result |
|---|---|
| A — of *checkable* techniques (UNDEFINED excluded) | 10/85 = **11.8%** |
| B — of *all* techniques (UNDEFINED counted unprovable) | 10/97 = **10.3%** |

The story does not move. **Report A, footnote B.** Take this to supervisors as a
resolved choice with both numbers shown, not as an open question.

---

## 8h. Profiles grounded in DeTT&CT format

`src/export_dettect.py` emits each cumulative tier as a **DeTT&CT data-source
administration YAML** file (`out/dettect/`). All five validate against the schema.

This converts the analysis's only authored assumption from an ad-hoc invention
into an instance of a schema practitioners already maintain for their own
estates. Consequences:

- a reviewer can **diff** our assumed instrumentation against a real one
- an operator can substitute their own administration file and re-run every result
- the assumption becomes **falsifiable** rather than merely declared

DeTT&CT (Rabobank CDC) has no peer-reviewed write-up — cite as practitioner
practice, not literature. Quality scores are uniform placeholders: the gate is a
binary availability test and does not consume them.

**Reproducibility also pinned:** `data/MANIFEST.md` records retrieval date, sizes
and SHA-256 hashes for all four bundles.


## 9. Repository

```
capacity-gate/
  data/     ATT&CK STIX bundles (v19.2 used; v18.1 retained)
  src/
    attack.py        bundle loading, chain resolution      [not authored]
    gate.py          the capacity formula, 3-valued        [not authored]
    profiles.py      instrumentation tiers                 [AUTHORED]
    claims.py        claim model, Gates A and B             [rho AUTHORED]
    demo.py          worked incident through the gate stack
    figures.py       paper figures (PDF + PNG)
    export_dettect.py  profiles -> DeTT&CT administration YAML
    run_analysis.py  produces all tables + CSVs
  tests/
    test_gate.py     10 tests, all passing
  out/
    profiles_ics.csv       per-profile counts
    criticality_ics.csv    per-component criticality
    criticality_enterprise.csv
    techniques_ics.csv     per-technique detail incl. missing components
```

**Reproduce:**

```
python src/run_analysis.py     # all tables + CSVs
python src/demo.py             # worked incident through Gates A/B/C
python src/figures.py          # figures -> out/*.pdf, *.png
python src/export_dettect.py   # profiles -> out/dettect/*.yaml
python tests/test_gate.py      # test suite
```

Standard library only, except `figures.py` which needs `matplotlib`
(`pip install matplotlib`). Everything else runs on a clean Python 3.12.

---

## 10. Open questions

- **How to report the 12 `UNDEFINED` techniques.** Currently excluded from the denominator, and both readings are reported. The alternative (counting them as unevidenceable) gives a harsher headline. Needs a stated decision in the paper.
- **Profile validity.** The five tiers in `profiles.py` are author-defined and are the paper's main assumption. Worth grounding against a published ICS monitoring reference or DeTT&CT-style administration data.
- ~~Greedy minimum-coverage~~ — **done**, see §8a. Curve is flat; no cheap win exists.
- ~~Gate A minimality in `ARCHITECTURE-v4.md`~~ — **fixed 31 Aug**, with the degeneracy and the honest limitation both recorded in the spec.
- ~~Figures~~ — **done**, three of them (§8d).
- ~~Instrumentation profiles need grounding~~ — **done 31 Aug**, exported as DeTT&CT administration YAML (§8h). The tier *contents* remain a judgement call; the *format* is now established practice.
- ~~UNDEFINED denominator~~ — **near-moot** (§8g): 11.8% vs 10.3%. Report A, footnote B.
- **DBLP / Google Scholar sweep** still outstanding — arXiv is clean (§8e) but that is one source.
- **Pin every claim to v19.2** in text, tables and figure captions before writing. v20 lands late October.
- **Supervisor ratification** needed on three things that are theirs to own: the measurement-paper framing, the denominator choice, and the profile tier contents.
- **Enterprise profiles.** Table 2 is ICS-only. The Enterprise column from an early run used ICS-shaped tiers and was not meaningful; separate Enterprise profiles would be needed for a fair cross-domain comparison.

---

## 11. Change log

**31 Aug 2026**
- Project created under `Architecture/capacity-gate/`, separate from the docs
- Downloaded ATT&CK bundles; corrected v18.1 → **v19.2** after the current version was flagged
- Resolved the detection chain; found the log-source intermediate hop
- Implemented `attack.py`, `gate.py`, `profiles.py`
- Found the empty-requirement bug; added the `UNDEFINED` outcome
- Established that all 12 ICS Impact-tactic techniques are `UNDEFINED`
- Wrote 10 tests, all passing
- Produced Tables 1–4 and four CSVs
- Added `acquisition_order()`; ran ICS and Enterprise curves (§8a)
- Tested and **rejected** the hypothesis that ICS instrumentation is less efficient than Enterprise
- Built `claims.py` (claim model, Gates A and B) and `demo.py` (worked incident)
- Found and fixed a **degenerate minimality definition** in the architecture spec (§8c)
- Found that **ET evidence has no ATT&CK data-component representation** (§8b)
- Corrected the Gate A minimality definition in `ARCHITECTURE-v4.md`
- Produced three paper figures as PDF + PNG (§8d)
- Ran the **novelty sweep** — core claim survives; two papers added to the reading list (§8e)
- **Longitudinal check**: the Impact gap holds identically in v18.1 and v19.2 (§8f)
- Settled the **denominator question** — 11.8% vs 10.3%, story unchanged (§8g)
- **Grounded the profiles** in DeTT&CT administration format (§8h)
- Pinned reproducibility with `data/MANIFEST.md` (hashes + retrieval date)
