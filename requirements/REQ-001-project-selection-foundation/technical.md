# REQ-001 Technical Design

> Status: Completed
> Requirement: requirement.md
> Created: 2026-04-01
> Updated: 2026-04-06

## 1. Technology Stack

| Module | Technology | Rationale |
|:---|:---|:---|
| Desktop UI | Python + PyQt6 | Existing application stack, current selector and main window already use PyQt6 |
| Project config parsing | Python + YAML parser (`PyYAML`) | Simple and readable project configuration format, easy for future editing |
| Project discovery | `pathlib` + local filesystem scanning | Matches the existing `project_configs/` folder approach |
| Shared data models | Python `dataclass` + typing | Lightweight typed models suited for Phase 1 scope |
| Validation layer | Pure Python validator functions/classes | Keeps validation logic independent from UI code |
| Logging / user-visible errors | Existing UI messaging + structured loader result objects | Minimizes immediate refactor cost while keeping future reuse possible |
| Legacy config reference | Existing ACCuESS XML (`OFC-04-00.xml`) | Shapes future YAML sections without forcing Phase 1 to consume full legacy detail |


## 2. Design Principles

- High cohesion, low coupling: project discovery, YAML parsing, validation, selector presentation, and runtime handoff should be separate responsibilities
- Reuse first: all project-loading logic should live in shared loader/model modules rather than in selector UI code
- Testability: loader, schema parsing, and validation should be executable without instantiating the full GUI
- Config first: project identity and capability metadata should come from YAML where possible
- Transition-safe: Phase 1 may still open the current `MainWindow`, but project context must already be modeled cleanly
- Extension-safe: richer YAML sections may exist to mirror legacy XML structure even if Phase 1 consumes only a minimal subset


## 3. Architecture Overview

Phase 1 should introduce a proper project-loading path before the future workspace shell is built.

Current high-level flow:

1. Application starts
2. Selector window opens
3. Selector scans `project_configs/`
4. User selects a project
5. Existing `MainWindow` opens with project context attached

Target Phase 1 flow:

1. Application starts
2. Selector requests project list from a project-loading service/module
3. Loader scans YAML files and parses minimal project metadata
4. Validator classifies each config as valid or invalid
5. Selector displays valid projects and blocks invalid/no-project cases
6. User selects a project
7. Selector passes a typed project definition into the next runtime layer
8. Existing `MainWindow` opens temporarily with that project definition or derived context

Target source organization for this phase:

- `gui/`
  - `program_selector_window.py`
- `myconfig/`
  - `project_loader.py`
  - future schema helpers / validation helpers
- `models/` or `myconfig/`
  - future `ProjectDefinition` and related dataclasses
- `project_configs/`
  - YAML project files

Planned architecture diagram files:

- `tech-architecture.puml`
- `tech-sequence.puml`
- `tech-class.puml`


## 4. Module Design

### 4.1 Project Config Discovery Module

- Responsibility:
  - scan the `project_configs/` directory
  - collect candidate `.yaml` / `.yml` files
  - normalize discovery order
- Public interface:
  - `ensure_project_config_dir() -> Path`
  - `discover_projects() -> list[...]`
- Internal structure:
  - folder existence check
  - file filtering
  - path normalization
- Reuse notes:
  - this module should be reusable by selector, future diagnostics, and config validation tools

### 4.2 YAML Parsing Module

- Responsibility:
  - read YAML file content
  - convert raw YAML data into a structured Python object or intermediate dict
- Public interface:
  - `load_project_config(path: Path) -> RawProjectConfig | ValidationIssue`
- Internal structure:
  - safe file open
  - YAML parse
  - top-level structure verification
- Reuse notes:
  - parsing must stay outside the selector so future CLI tools, tests, or config editors can reuse it

### 4.3 Project Validation Module

- Responsibility:
  - enforce the minimal schema
  - detect missing required fields
  - classify config errors cleanly
- Public interface:
  - `validate_project_config(raw_config) -> ValidationResult`
- Internal structure:
  - required field validation
  - optional field defaults
  - duplicate/empty display-name handling
- Reuse notes:
  - validation should be reusable by selector, future config editor pages, and automated tests

### 4.4 Project Definition Model

- Responsibility:
  - represent one parsed and validated project in typed form
- Public interface:
  - dataclass-style field access
- Internal structure:
  - identity metadata
  - system metadata
  - feature placeholders
  - UI metadata
- Reuse notes:
  - this becomes the bridge between selector, workspace shell, and future feature enablement

### 4.5 Selector Integration Layer

- Responsibility:
  - ask the loader for available projects
  - show only valid selectable entries
  - manage placeholder state and button enablement
- Public interface:
  - internal methods in `ProgramSelectorWindow`
- Internal structure:
  - placeholder entry
  - dropdown population
  - selected-project retrieval
  - open-button state transitions
- Reuse notes:
  - UI should remain thin and should not own parsing or validation rules

### 4.6 Project Context Handoff Layer

- Responsibility:
  - pass selected project context into the next runtime window
- Public interface:
  - selector-to-window handoff method or runtime context object
- Internal structure:
  - selected project name
  - config path
  - future full `ProjectDefinition`
- Reuse notes:
  - the handoff logic should later be reused when introducing the project workspace shell

### 4.7 Legacy XML Reference Mapping

The supplied ACCuESS XML config (`OFC-04-00.xml`) should be treated as a migration reference, not as a runtime dependency.

Recommended Phase 1 mapping approach:

| Legacy XML area | YAML area | Phase 1 handling |
|:---|:---|:---|
| `<system-settings>` | `system` | only minimal selector-facing metadata is consumed now |
| `<mcu-control><serial-port>` | `mcu.serial_port` | stored for future use, ignored by the current selector model |
| `<robot-control><axis-*>` | `robot.axes.*` | stored for future use, ignored by the current selector model |
| `<robot-geometry>` | `geometry` | allowed as extension data |
| `<calibration>` | `calibration` | allowed as extension data |

This keeps Phase 1 intentionally small while allowing sample YAML files to resemble real project data.


## 5. Data Model

Planned Phase 1 core models:

### 5.1 ProjectDefinition

- Fields:
  - `name: str`
  - `display_name: str`
  - `config_path: Path`
  - `system_axes: int | None`
  - `features: ProjectFeatures`
  - `ui: ProjectUiConfig`

### 5.2 ProjectFeatures

- Fields:
  - `firmware_tools: bool`
  - `mechanical_tools: bool`
  - `application_tools: bool`
  - `stress_test: bool`
  - `integration_test: bool`

### 5.3 ProjectUiConfig

- Fields:
  - `workspace: str | None`
  - `notes: str | None`

### 5.4 ValidationIssue

- Fields:
  - `path: Path`
  - `severity: str`
  - `message: str`
  - `field: str | None`

### 5.5 ProjectLoadResult

- Fields:
  - `valid_projects: list[ProjectDefinition]`
  - `invalid_projects: list[ValidationIssue]`

Planned class diagram file:

- `tech-class.puml`


## 6. API Design

This phase does not introduce external HTTP APIs. The relevant APIs are internal Python interfaces.

### 6.1 Discovery API

- `ensure_project_config_dir() -> Path`
- `discover_project_files() -> list[Path]`

### 6.2 Parse API

- `load_project_yaml(path: Path) -> dict`

### 6.3 Validation API

- `validate_project_yaml(raw: dict, path: Path) -> ValidationResult`

### 6.4 Build API

- `build_project_definition(raw: dict, path: Path) -> ProjectDefinition`

### 6.5 Selector API

- `load_available_projects() -> ProjectLoadResult`
- `open_selected_project(project: ProjectDefinition) -> None`


## 7. Key Flows

### 7.1 Startup selector flow

1. `main.py` creates `ProgramSelectorWindow`
2. selector calls project-loading entry point
3. loader scans `project_configs/`
4. loader parses and validates each YAML file
5. valid projects are returned to selector
6. selector renders placeholder + project options

### 7.2 Invalid YAML flow

1. loader opens a YAML file
2. parse or validation fails
3. issue is recorded
4. invalid project is excluded or marked invalid
5. valid projects still return normally
6. selector remains functional

### 7.3 Project open flow

1. user selects a valid project
2. `Open` becomes enabled
3. selector retrieves selected project definition
4. selector opens the next runtime window
5. selected project context is attached to the next runtime layer

Planned sequence diagram file:

- `tech-sequence.puml`


## 8. Shared Modules & Reuse Strategy

Shared reusable parts introduced or clarified by this phase:

- project discovery logic
- YAML parsing logic
- validation logic
- typed project-definition model
- selector-to-runtime context handoff pattern

Reuse strategy:

- selector UI should consume shared project-loading logic, not duplicate it
- future workspace shell should reuse `ProjectDefinition`
- future config editor or diagnostics should reuse validation and parsing logic
- future tests should target loader/model modules directly without GUI dependency


## 9. Risks & Notes

- Risk 1:
  - If YAML parsing is implemented inside `ProgramSelectorWindow`, the selector will become architecture-heavy too early
- Risk 2:
  - If project data remains file-name-derived only, the platform will not really become config-driven
- Risk 3:
  - If validation is weak, malformed configs will create fragile startup behavior
- Risk 4:
  - If project context handoff uses loose attributes only, future workspace-shell refactor may require extra cleanup
- Risk 5:
  - Temporary hardcoded compatibility is acceptable now, but should not delay the next workspace-shell phase for too long

Implementation notes for this stage:

- Hardcoded behavior is still acceptable where the real workspace shell does not yet exist
- Placeholder YAML files can continue to exist during transition
- This technical design intentionally stops short of full workspace-shell implementation


## 10. Change Log

| Version | Date | Changes | Affected Scope | Reason |
|:---|:---|:---|:---|:---|
| v1 | 2026-04-01 | Initial technical design draft for project selection foundation | ALL | Derived from REQ-001 and Phase 1 architecture plan |
| v2 | 2026-04-01 | Added legacy XML mapping guidance and activated PlantUML artifact references | Sections 1, 2, 3, 4, 5, 7 | Incorporated ACCuESS config reference and local PlantUML availability |
| v3 | 2026-04-06 | Marked technical design as completed after implementation and verification passed | Status metadata | Final archive step for REQ-001 |
