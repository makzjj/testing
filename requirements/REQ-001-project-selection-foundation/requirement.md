# REQ-001 Project Selection Foundation

> Status: Completed
> Created: 2026-04-01
> Updated: 2026-04-06

## 1. Background

The current BioBot Robot Arm Tester already has a top-level selector and a `project_configs/` folder, but the project-loading flow is still shallow.

At the moment:

- project discovery is based mainly on YAML file presence and file name
- project metadata is not fully parsed from YAML
- invalid YAML handling is not implemented
- the selected project does not yet create a true project workspace shell
- the runtime still falls back to the existing large `MainWindow`

This creates a gap between the intended platform architecture and the current implementation.

The purpose of this requirement is to complete the first real foundation of multi-project selection so the application can evolve from:

- one tool with a selector UI

into:

- one platform with config-driven project loading

This requirement is also intended to protect the architecture from slipping back into hardcoded project branching inside shared UI code.


## 2. Target Users & Scenarios

### Target users

- internal developers extending the BioBot test platform
- firmware engineers using project-specific tool entry points
- mechanical engineers using project-specific test tools
- application / production engineers launching project-specific workflows

### Primary scenarios

1. A developer adds a new project YAML file and expects the selector to show a new project entry.
2. A user launches the application, selects a project, and expects the correct project context to be loaded.
3. A malformed or incomplete YAML file exists in `project_configs/`, and the application should fail gracefully rather than crash.
4. The selected project must carry enough metadata to support future workspace-shell and feature-enablement logic.
5. The selector should remain clean and easy to use while being the true first step of project loading.


## 3. Functional Requirements

### F-01 Project config discovery

- Main flow:
  - The application shall scan the `project_configs/` directory at startup.
  - Each valid `.yaml` or `.yml` file shall be treated as one candidate project.
  - The selector shall populate its project dropdown from discovered project definitions.
- Error handling:
  - If the folder does not exist, the application shall create it or fail gracefully with a clear message.
  - If no valid project config exists, the selector shall remain usable but block project opening.
- Edge cases:
  - Non-YAML files in the folder shall be ignored.
  - Hidden or nested files shall not be treated as project definitions unless explicitly supported later.

### F-02 Minimal YAML schema definition

- Main flow:
  - The application shall define a minimal supported schema for project YAML files.
  - The first schema version shall include at least:
    - project identity
    - display name
    - basic system metadata
    - feature/capability placeholders
    - UI/workspace metadata placeholders
- Error handling:
  - Missing required top-level fields shall be reported as config errors.
  - Unknown optional fields shall not crash the application.
- Edge cases:
  - The schema shall allow future extension without breaking existing configs.
  - Early placeholder values shall be tolerated during the transition phase.

### F-03 YAML metadata parsing

- Main flow:
  - The loader shall parse project metadata from YAML content rather than relying only on file names.
  - The selector shall display the configured project display name.
  - The selected project object shall retain the parsed config path and metadata for downstream use.
- Error handling:
  - YAML parsing errors shall be captured and surfaced in a non-crashing way.
  - Invalid project files shall not block valid projects from appearing.
- Edge cases:
  - If display name is absent but project name exists, fallback rules may be applied.
  - Duplicate display names should be handled consistently and flagged for cleanup later.

### F-04 Selector behavior and interaction

- Main flow:
  - The selector shall show a default placeholder option such as `Please select project`.
  - The `Open` action shall stay disabled until a valid project is selected.
  - The selector shall pass the selected project context into the next application window.
- Error handling:
  - Attempting to open without a valid project shall show a clear blocking message or keep the action disabled.
- Edge cases:
  - If the list is empty, the selector shall explain that no valid project config is available.
  - Future refresh behavior shall be designed but may remain simple in the first iteration.

### F-05 Project context handoff

- Main flow:
  - After a project is selected, the application shall pass the selected project identity and config path to the next runtime layer.
  - The runtime shall be able to read this project context for future workspace-shell and feature-enablement work.
- Error handling:
  - If project context cannot be resolved, the application shall not silently continue with an incorrect project.
- Edge cases:
  - The current implementation may still open the existing `MainWindow`, but the project context shall be preserved for the next architecture phase.

### F-06 Graceful validation and error visibility

- Main flow:
  - The project loader shall classify project files as valid or invalid.
  - Invalid project definitions shall be excluded from selection or clearly marked, depending on the chosen UX.
- Error handling:
  - The application shall not crash because of malformed YAML or missing required fields.
  - User-facing messaging shall explain the issue at a useful level.
- Edge cases:
  - One broken YAML file shall not prevent all other valid projects from loading.
  - Validation messages should stay concise and not overload the selector UI.

### F-07 Transition compatibility

- Main flow:
  - During the early platform phase, the implementation may continue to open the current `MainWindow` after selection.
  - Temporary hardcoded behavior is acceptable where the real workspace shell does not exist yet.
- Error handling:
  - Temporary compatibility behavior shall not hide incorrect config-loading outcomes.
- Edge cases:
  - Placeholder YAML files may continue to exist temporarily for selector testing.
  - This compatibility mode shall not redefine the long-term config-first architecture.


## 4. Non-functional Requirements

- NFR-01 Maintainability
  - Project-loading logic shall live outside `MainWindow`.
  - The implementation shall avoid spreading project-selection rules across multiple UI files.

- NFR-02 Extensibility
  - Adding a new project should mainly require adding a new YAML file, plus future project-specific modules if needed.

- NFR-03 Stability
  - Invalid or incomplete YAML files shall not crash application startup.

- NFR-04 Clarity
  - Selector behavior shall remain simple and understandable for internal users.

- NFR-05 Traceability
  - Parsed project metadata shall map cleanly to later `ProjectDefinition` and feature models.

- NFR-06 UI sustainability
  - The selector shall stay lightweight and should not become a dumping ground for advanced runtime controls.


## 5. Out of Scope

- Building the full project workspace shell
- Refactoring `MainWindow` into pages and panels
- Role-based navigation implementation
- Full feature enablement by YAML
- Typed `ProjectDefinition` and state-model rollout across the full application
- Protocol-layer refactor
- Service-layer extraction beyond what is needed for project loading
- Final selector UX polish for all future product needs


## 6. Acceptance Criteria

| ID | Feature | Condition | Expected Result |
|:---|:---|:---|:---|
| AC-01 | F-01 Project config discovery | Valid `.yaml` files exist in `project_configs/` | Each valid file appears as one selectable project entry |
| AC-02 | F-01 Project config discovery | No valid project config exists | Selector shows no valid project choice and blocks `Open` |
| AC-03 | F-02 Minimal YAML schema definition | A new project file follows the minimal schema | Loader accepts the file without requiring code changes in selector UI |
| AC-04 | F-03 YAML metadata parsing | YAML contains display metadata | Selector shows configured project display name rather than only a file-derived label |
| AC-05 | F-03 YAML metadata parsing | One YAML file is malformed | Valid projects still load and the application does not crash |
| AC-06 | F-04 Selector behavior and interaction | Application starts | Dropdown defaults to a placeholder option and `Open` is disabled |
| AC-07 | F-04 Selector behavior and interaction | A valid project is selected | `Open` becomes enabled |
| AC-08 | F-05 Project context handoff | User opens a valid project | Selected project name and config path are passed into the next runtime window |
| AC-09 | F-06 Graceful validation and error visibility | Required YAML fields are missing | The config is rejected or marked invalid without crashing the application |
| AC-10 | F-07 Transition compatibility | Workspace shell is not implemented yet | Application may still open the current `MainWindow`, but selected project context remains available |


## 7. Open Questions

1. Which fields must be required in the first real schema version versus allowed as placeholders?
2. Should invalid project configs be hidden from the selector or shown with an error state?
3. Should selector refresh be automatic, manual, or deferred?
4. What is the first minimum metadata set needed by the future project workspace shell?


## 8. Diagram Status

PlantUML artifacts for this requirement are stored in this requirement folder:

- `tech-architecture.puml` / `tech-architecture.svg`
- `tech-sequence.puml` / `tech-sequence.svg`
- `tech-class.puml` / `tech-class.svg`


## 9. Change Log

| Version | Date | Changes | Affected Scope | Reason |
|:---|:---|:---|:---|:---|
| v1 | 2026-04-01 | Initial requirement draft for Phase 1 project selection foundation | ALL | Derived from `docs/architecture/ARCHITECTURE_TODO.md` Phase 1 and current platform blueprint |
| v2 | 2026-04-01 | Updated diagram status after adding PlantUML artifacts | Section 8 | Local PlantUML tooling is now available |
| v3 | 2026-04-06 | Marked requirement as completed after implementation, review, and verification passed | Status metadata | Final archive step for REQ-001 |
