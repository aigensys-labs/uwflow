# UWflow Modules — source map

The directories below contain the source code for the UWflow platform Modules. For operating instructions, open the module's README: each one is the user-facing entry point and links to the relevant task guides.

| Source directory | Operator entry point |
|---|---|
| [policy-studio/](policy-studio/README.md) | Policy authoring and analyst workspaces |
| [lifecycle/](lifecycle/README.md) | Workspace forking and immutable DEV candidates |
| [history/](history/README.md) | Historical datasets, storage and source evidence |
| [evaluation/](evaluation/README.md) | Paired historical replay |
| [reporting/](reporting/README.md) | Comparative underwriting impact reports |
| [production/](production/README.md) | Approval, release assembly and deployment |
| [platform-runtime/](platform-runtime/README.md) | Optional module task-image dependencies |

Modules operate around the independently runnable Core. They do not own the seven-stage underwriting runtime and are not deployed into the live production execution path.
