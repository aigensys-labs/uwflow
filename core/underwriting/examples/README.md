# Synthetic examples

All data in this directory is illustrative software-fixture data. It is not real applicant
information, calibrated credit-risk evidence or a basis for lending decisions.

| Directory / file | Contents | Use it when… |
|---|---|---|
| [applications/](applications/) | Individual synthetic application payloads and the expected default decision | You want to run or inspect one underwriting case |
| [History sample cohort](../../../modules/history/examples/cohorts/dev_cohort.sample.jsonl) | Sample multi-application DEV replay input owned by the History module | You want to exercise paired historical replay |
| [SCENARIOS.md](SCENARIOS.md) | Summary of the demonstration scenarios and expected outcomes | You want a quick overview of the included cases |

Core generates applicant JSON, HTML and PDF reports when a scenario is run. The History module owns the separate sample cohort at `modules/history/examples/cohorts/dev_cohort.sample.jsonl`; Core does not own or require historical replay data. Do not replace synthetic data with production applicant records in this demonstration package.
