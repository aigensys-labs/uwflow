# UWflow Core Python runtime

This directory contains both ways of executing the original UWflow Python engine:

- `runtime/` holds the canonical nine-file implementation used by the Kestra task flow and the local runner.
- `runner.py` invokes Stages 1–6 in process, using the same hard-gate, bureau, source-plan, alternative-data, AIDflow and UWflow decision functions as the Kestra tasks.
- `cli.py` adds Stage 7 by rendering the applicant JSON, HTML and PDF reports.

Run from the repository root:

```bash
python -m core.python.cli
```

Use an application JSON file and output directory:

```bash
python -m core.python.cli --input core/underwriting/examples/applications/application_default.json --output-dir var/reports
```

The Kestra flow imports the same nine runtime modules from a verified immutable Namespace Files bundle. Its task execution remains isolated; the local CLI does not start Kestra or Docker.

The `uwflow-demo` and `uwflow-report` console commands are Core-owned convenience entry points to this seven-stage CLI; they do not depend on the platform Modules.
