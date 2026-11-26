# Champion vs Challenger portfolio impact report

The historical replay comparison is designed to help underwriting analysts and CRO reviewers understand what changes when a DEV candidate (challenger) is compared with the current production champion.

The two runtimes receive the **same immutable application, bureau, alternative-data and outcome snapshots**. Kestra runs the baseline and candidate replay branches in parallel, then runs the comparison task only after both replay artifacts have completed successfully. The report is therefore a paired policy-path comparison, not two independently generated portfolios.

## Where to find the report

1. Execute the candidate-specific historical replay flow in namespace `com.ai.credit.dev`.
2. For the infrastructure smoke test, use `max_cases=100`. This confirms orchestration and report generation only; it is not a basis for risk conclusions.
3. For the analyst/CRO assessment, execute the same flow against the same dataset with `max_cases=0` so all 5,000 cases are replayed.
4. In the Kestra execution, open the successful `compare_replays` task and download its output files.

The primary deliverables are `champion_challenger_report.pdf` and `champion_challenger_report.html`. The HTML is self-contained. The task also emits CSV and JSON data for independent analysis.

## Executive metrics

| Metric | Definition | Interpretation |
|---|---|---|
| Strict approval rate | `APPROVED / all applications` | Only straight-through approvals. Counteroffers are excluded. |
| Offer rate | `(APPROVED + COUNTEROFFER) / all applications` | The broader commercial offer funnel. |
| FSTPD30 among approved | Matured FSTPD30 events among `APPROVED` cases divided by matured FSTPD30 labels among those approved cases | Primary strict-approval risk indicator. |
| FSTPD30 among offers | Matured FSTPD30 events among `APPROVED + COUNTEROFFER` divided by matured labels among those offered cases | Separate sensitivity metric for the broader offer population. |
| FSTPD30 label coverage | Matured labels divided by the relevant approved/offer population | Shows how much of the decision population contributes to the risk denominator. |

The report shows counts, rates and challenger-minus-champion movement. Risk percentages are not presented without their matured-label denominator and coverage. An immature label is never treated as a zero.

**Strict approval and offer are different measures.** An applicant receiving a counteroffer is part of the offer rate but is not counted as an `APPROVED` case. This keeps the headline approval metric unambiguous while retaining counteroffers in the commercial funnel.

## Stage-by-stage scorecard

The report covers the six underwriting decision stages. Stage 7 in the production flow renders the decision report; it is a presentation task rather than an additional applicant decision gate, so it is not counted as a population stage.

For every underwriting stage, the report shows:

- Every defined stage outcome, including zero-count outcomes, with applicant counts.
- Each outcome as a share of the original cohort and as a share of applicants who entered that stage.
- The stage progression/clearance rate, using the stage entrants as its denominator.
- The **eventual final approval rate among applicants who entered that stage**, counting `APPROVED` only.
- The FSTPD30 incidence among the stage's positive/progressed population, using matured labels only.
- Label counts and maturity coverage so the risk denominator is visible.

The positive outcome used for the stage progression/risk view differs by stage:

| Stage | Positive/progressed population | Stage outcomes displayed |
|---|---|---|
| 1. Input validation and hard gates | `PASSED` | `PASSED`, `REJECTED`, `REFERRED`, `CANCELLED`, `NOT_REACHED` |
| 2. Credit bureau policy | `PASSED` | `PASSED`, `REJECTED`, `REFERRED`, `CANCELLED`, `NOT_REACHED` |
| 3. Consent and source plan | `ROUTED_TO_COLLECTION` | `ROUTED_TO_COLLECTION`, `SKIPPED_NO_CONSENT`, `CANCELLED`, `NOT_REACHED` |
| 4. Big-data source collection | `COMPLETE` | `COMPLETE`, `PARTIAL`, `FAILED`, `SKIPPED_NO_CONSENT`, `CANCELLED`, `NOT_REACHED` |
| 5. AIDflow profile inference | `SCORED` | `SCORED`, `INCOMPLETE`, `CANCELLED`, `NOT_REACHED` |
| 6. UWflow decision, affordability and pricing | `APPROVED` for FSTPD30 risk; `APPROVED + COUNTEROFFER` for offer/progression | `APPROVED`, `COUNTEROFFER`, `REFERRED`, `REJECTED`, `CANCELLED`, `NOT_REACHED` |

`NOT_REACHED` matters: a case rejected at the bureau stage must not be counted as a Stage 6 rejection as well. The replay records the stage where the business decision path actually stopped. Kestra may still execute a downstream no-op task to render a consistent response, but the population report does not attribute the case to a business stage it never reached.

## FSTPD30 playground target

The standard synthetic dataset is named `synthetic-eur-v4-fstpd30-...` and uses generator version `0.4.0`.

`FSTPD30` is a binary target:

- `1` if any of the first, second or third scheduled instalments reaches **30 or more days past due**.
- `0` if none of those three instalments reaches 30 DPD.
- `null` until the third instalment plus its 30-day observation window has matured.

The maturity rule is four months on book for this synthetic fixture. Immature cases are excluded from the risk-rate numerator and denominator and are shown in label coverage.

### How the synthetic correlation is designed

The generator creates one shared latent credit-risk propensity from affordability/application characteristics. It is not part of the application payload supplied to UWflow or AIDflow. That latent propensity shapes the synthetic bureau snapshot and the ten alternative-data source snapshots; the payment-level FSTPD30 outcomes are generated separately from the same latent propensity plus bureau history and affordability.

The ten source fixtures are:

1. Telecom payment history (`telco_stability`)
2. Utility payment history (`utility_reliability`)
3. Open-banking cash flow (`open_banking_cashflow`)
4. Device integrity (`device_fingerprint`)
5. Session continuity (`geo_mobility`)
6. Transaction integrity (`ecommerce_behavior`)
7. Digital identity verification (`digital_identity_age`)
8. Income consistency (`income_velocity`)
9. Small-ticket repayment history (`microloan_history`)
10. Merchant concentration context (`merchant_affinity`)

The bureau snapshot includes bureau score, active and historical delinquencies, historical defaults, utilization, inquiries, accounts and open-loan counts. More adverse synthetic bureau profiles are intentionally associated with higher FSTPD30 incidence. The identity/fraud features use a related but separate synthetic propensity so fraud-control outcomes are not simply copies of credit history.

The outcome label and `fstpd30_probability_for_simulation` are generator-only. They are stored in the separate historical outcome snapshot; they are **not sent into AIDflow or UWflow as inference/decision inputs**. The same target snapshot is reused by champion and challenger.

## Cutoff sensitivity and the approval-risk relationship

AIDflow produces one customer-profile score from the ten normalized source scores. A threshold applied to that score to decide whether an application is automatically approved, referred or declined belongs to UWflow decision policy; it does not change AIDflow's score inference itself.

### Policy editing boundary

The Policy Studio currently exposes Stage 1 and Stage 3 policy editing. Stage 6 profile-score cutoffs remain part of the UWflow runtime decision policy and are not editable in the Studio. The 620-to-840 regression sensitivity test changes only the cutoff in a disposable candidate-runtime copy and replays the same 10,000 synthetic cases through both runtimes. It validates the reporting path and the expected direction of the approval/risk trade-off; it is not an analyst-facing control or a credit-risk performance claim. A candidate with the same runtime module hashes as the champion is a no-op and should produce no strategy-driven migrations. To assess a changed strategy, build a candidate with an explicit policy/runtime difference and run the paired Kestra flow.

On a fixed cohort, a more permissive threshold can admit more applicants but may also admit a riskier marginal population. A stricter threshold can reduce the approval/offer rate while lowering FSTPD30 incidence in the approved population. The report measures the direction and size of that trade-off; it does not assume that one direction is always better.

A regression sensitivity test replays 10,000 deterministic applications with the current 620 score threshold and a stricter 840 candidate threshold. On that test seed, the stricter threshold reduces both approval and FSTPD30 among approved cases, while reversing the two policies produces the corresponding higher-approval/higher-FSTPD30 trade-off. These are regression-fixture results, not forecasts or performance claims.

## Supporting artifacts

| Artifact | Contents |
|---|---|
| `comparison.json` | Complete report metrics, assessment, dataset and runtime provenance. |
| `stage_comparison.csv` | All stage outcomes, counts, cohort/entrant shares and conditional final approval metrics. |
| `score_deciles.csv` | Champion and challenger AIDflow score deciles, approval/offer rates and separate approved-only and offer-population FSTPD30 rates. |
| `segment_impact.csv` | Approval, offer and FSTPD30 by bureau score band, historical defaults/delinquencies, open-loan band, income band, employment and age. |
| `source_coverage.csv` | Successful, failed, missing and not-attempted counts for every one of the ten sources. |
| `case_comparison.csv` | Per-application decision, score, amount, target and stage-outcome changes. |
| `decision_migrations.csv` | Champion-to-challenger decision migration matrix. |
| `champion_challenger_report.pdf` | CRO-oriented printable report. |
| `champion_challenger_report.html` | Self-contained browser report. |

## What this report does not establish

This is a synthetic, counterfactual playground. The generator creates labels for every applicant, including applications that a policy would not actually approve or book. That construction is intentional: it allows the same simulated applicant evidence and outcome target to be reused when a policy cutoff changes. It is not observed performance of booked loans.

FSTPD30 is an early-payment delinquency indicator (30+ DPD on one of the first three instalments), not a conventional default-rate definition and not expected credit loss. It does not contain loss given default, exposure at default, recoveries, timing of loss or funding/operating costs. A lower FSTPD30 rate is not by itself proof of improved profitability, fairness, calibration or production suitability.

A real CRO decision requires observed booked-loan outcomes, loan take-up and exposure, mature vintages, censoring/selection controls, a governed target definition, LGD/EAD if loss cost is being assessed, and independent validation. The synthetic report is for software-path, policy-sensitivity and analyst-workflow testing only.
