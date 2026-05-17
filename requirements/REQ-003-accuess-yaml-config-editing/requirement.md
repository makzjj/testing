# REQ-003 ACCuESS YAML-Driven Config Editing And Live Hardware Overlay

> Status: Completed
> Created: 2026-04-16
> Updated: 2026-04-20

## 1. Background

The ACCuESS project configuration has moved to a richer YAML schema in [project_configs/ACCuESS.yaml](/d:/testingTool/Biobot_Robot_Arm_Tester/project_configs/ACCuESS.yaml).

The current application only consumes a small normalized subset of project YAML:

- selector startup reads minimal project metadata
- workspace bridge reads a few summary fields
- the current `Project Config` page is still a summary/dashboard view rather than a real config editor

This creates a mismatch between the new ACCuESS YAML file and the actual runtime/UI behavior:

- much of the new ACCuESS YAML structure is ignored
- the frontend cannot inspect or edit the full YAML
- users cannot save versioned YAML updates safely from the UI
- live hardware values that already exist in the runtime path are not surfaced in the config page as a clear overlay

The purpose of this requirement is to make the new ACCuESS YAML schema the active source of truth for project/config metadata and to introduce a safe YAML load/edit/save workflow in the `Project Config` page without breaking the current selector/startup flow.

## 2. Target Users & Scenarios

### Target users

- firmware engineers checking MCU and node configuration against real hardware
- mechanical engineers reviewing axis and sensor configuration before bench work
- application / production engineers updating project configuration for current benches
- internal developers maintaining the YAML/config flow

### Primary scenarios

1. A user selects ACCuESS in the selector and expects startup/project metadata to come from the new YAML structure.
2. A user opens `Project Config` and expects to view all YAML sections and nested fields.
3. A user edits configuration values in the UI and saves them back to disk safely.
4. A user saves a new config version and expects explicit confirmation if the version was not updated.
5. A user compares YAML-defined values with live hardware values wherever real device data is available.
6. A user clicks one button to open or reveal the corresponding YAML file.

## 3. Functional Requirements

### F-01 New ACCuESS YAML schema support
- Main flow:
  - The backend shall support the new ACCuESS YAML structure as the primary config format for ACCuESS.
  - Project startup shall derive project/config metadata dynamically from the new YAML structure.
  - The new YAML shall become the source of truth for ACCuESS project/config metadata.
- Error handling:
  - Missing or malformed optional fields shall not crash startup.
  - Validation errors shall be reported safely and clearly.
- Edge cases:
  - Top-level keys containing spaces shall be supported.
  - Empty values and nullable values shall be preserved.

### F-02 YAML syntax pre-processing
- Main flow:
  - Before continuing with config-driven startup or editing flows, the system shall detect whether the YAML file is syntactically invalid.
  - If the YAML file has syntax errors, the system shall repair YAML syntax first while preserving intended structure and content as much as possible.
- Error handling:
  - If syntax cannot be repaired safely, the user shall receive a blocking error instead of loading corrupted content silently.
- Edge cases:
  - Schema mismatch alone shall not be treated as YAML syntax failure.

### F-03 YAML read API / service
- Main flow:
  - The backend shall expose a reusable API/service that returns the current full YAML content for the selected project.
  - The returned structure shall preserve all top-level sections, nested mappings, nested lists, scalar values, and unknown fields.
- Error handling:
  - Read and parse failures shall return structured errors rather than crashing the workspace.
- Edge cases:
  - Unknown sections shall be preserved and returned unchanged.

### F-04 YAML edit and submit flow
- Main flow:
  - The `Project Config` page shall load current YAML content from the backend.
  - Top-level YAML sections may be mapped to fixed section containers for now.
  - Within each section, nested content shall render dynamically so users can inspect and edit all YAML fields.
  - The UI shall submit edited YAML content back to the backend in a structured save payload.
- Error handling:
  - Invalid edits shall be blocked with clear error messaging.
- Edge cases:
  - Null values, booleans, integers, floats, and strings shall round-trip safely.

### F-05 YAML save flow and version confirmation
- Main flow:
  - Saving shall be explicit and user-confirmed.
  - The system shall check whether the version number has changed before saving.
  - If the version number was not updated, the user shall be required to confirm and enter/update a new version before save completes.
  - The saved filename shall use the format `<project_name>_<version>.yaml`.
- Error handling:
  - Invalid or missing version data shall block save.
  - Save failures shall not corrupt the current source file.
- Edge cases:
  - Filename collisions shall be handled safely.
  - The save target path shall become the new active config path after save succeeds.

### F-06 YAML file open / reveal action
- Main flow:
  - The UI shall provide one-click open or reveal for the current YAML file.
  - The backend shall resolve the correct current config file path, including newly versioned save targets.
- Error handling:
  - Missing-file or OS-shell failures shall surface as clear user feedback.
- Edge cases:
  - The action shall target the most recently saved filename when save-as-versioned output is used.

### F-07 Project Config page refactor
- Main flow:
  - The current `Project Config` page shall become a real configuration editor rather than a summary-only page.
  - Each top-level YAML property shall map to one visible UI section or component.
  - Section content shall render dynamically from YAML so all nested fields can be viewed and edited.
- Error handling:
  - A single bad section shall not blank the whole page.
- Edge cases:
  - Larger nested sections shall remain readable and predictable to edit.

### F-08 Live hardware overlay and highlighting
- Main flow:
  - The YAML value shall remain the only editable and persisted configuration value.
  - Wherever actual hardware information can be read from the real device, the system shall compare the detected live hardware value against the corresponding YAML field value.
  - The UI shall show a highlighted read-only mismatch indicator only when the live hardware value is different from the YAML field value.
  - The mismatch indicator shall use clear text such as `Actual: MCU Version = xxx`.
- Error handling:
  - If live hardware data is unavailable, the page shall fall back to YAML-defined values without crashing.
- Edge cases:
  - Some fields may have live values while others do not.
  - If the detected hardware value matches the YAML field value, no extra live indicator shall be shown.
  - Live hardware values are read-only comparison values and must never be written back into YAML automatically unless the user manually edits the YAML field.

### F-09 Safe validation and schema handling
- Main flow:
  - Backend validation shall cover required sections and safe read/write behavior for the new schema.
  - Save logic shall preserve unknown fields and existing structure whenever possible.
- Error handling:
  - Malformed or missing fields shall be handled safely with validation feedback.
- Edge cases:
  - Future new sections added to ACCuESS YAML shall survive round-trip editing without destructive rewriting.

### F-10 Startup and runtime compatibility preservation
- Main flow:
  - Existing selector startup behavior shall continue to work.
  - Existing runtime behavior shall remain working unless a schema change requires an intentional update.
- Error handling:
  - Schema-driven compatibility problems shall degrade gracefully instead of silently opening with broken state.
- Edge cases:
  - Other project configs such as ML2.0 shall continue to load safely.

## 4. Non-functional Requirements

- NFR-01 Maintainability
  - New YAML parsing, normalization, save/version logic, and file actions shall be implemented as modular services or bridge helpers rather than being embedded directly into one page class.

- NFR-02 Reuse first
  - Existing loader, project model, workspace bridge, and widget patterns shall be reused where practical.

- NFR-03 Safe YAML handling
  - YAML parsing and writing shall use safe mechanisms and avoid unsafe object construction.

- NFR-04 Round-trip preservation
  - Unknown or currently unused YAML fields should be preserved during read/edit/save whenever feasible.

- NFR-05 Compact professional UI
  - The updated `Project Config` page shall remain structured, readable, and developer-tool-like rather than decorative.

- NFR-06 Minimal breakage
  - Changes outside the YAML/config flow shall be minimized.

- NFR-07 Explicit save safety
  - The save flow shall make filename/version consequences clear before the file is written.

## 5. Out of Scope

- redesign of the selector window
- full refactor of all runtime services unrelated to YAML/config flow
- full migration of every legacy runtime UI area into the new shell
- protocol redesign for hardware communication
- advanced schema migration tooling for every historical config format
- multi-user concurrent YAML editing

## 6. Acceptance Criteria

| ID | Feature | Condition | Expected Result |
|:---|:---|:---|:---|
| AC-01 | F-01 New ACCuESS YAML schema support | ACCuESS is selected at startup | Project metadata loads from the new YAML structure without breaking startup |
| AC-02 | F-02 YAML syntax pre-processing | YAML contains syntax errors | Syntax is repaired first or a clear blocking error is shown |
| AC-03 | F-03 YAML read API / service | `Project Config` page opens | Full current YAML content is loaded from the backend |
| AC-04 | F-04 YAML edit and submit flow | User edits nested config fields | Edited values are reflected in the backend save payload |
| AC-05 | F-05 YAML save flow and version confirmation | User saves without updating version | User must confirm and update version before save completes |
| AC-06 | F-05 YAML save flow and version confirmation | Save succeeds | File is saved as `<project_name>_<version>.yaml` |
| AC-07 | F-06 YAML file open / reveal action | User clicks open/reveal action | Corresponding YAML file is opened or revealed |
| AC-08 | F-07 Project Config page refactor | YAML contains multiple top-level sections | Each section is rendered in a structured editable UI |
| AC-09 | F-08 Live hardware overlay and highlighting | Live hardware value differs from the YAML field value | UI shows a highlighted read-only mismatch indicator such as `Actual: ...` |
| AC-10 | F-08 Live hardware overlay and highlighting | Live hardware value matches the YAML field value | UI shows no extra live mismatch indicator |
| AC-11 | F-08 Live hardware overlay and highlighting | User saves while a live mismatch indicator is present | Only the user-edited YAML value is persisted; live value is not auto-written |
| AC-12 | F-09 Safe validation and schema handling | YAML contains unknown fields | Unknown fields survive read/edit/save without unintended loss |
| AC-13 | F-10 Startup and runtime compatibility preservation | Existing startup flow is exercised | Selector and workspace still launch successfully |

## 7. Change Log

| Version | Date | Changes | Affected Scope | Reason |
|:---|:---|:---|:---|:---|
| v1 | 2026-04-16 | Initial requirement document for ACCuESS YAML-driven config editing, versioned save flow, file reveal action, and live hardware overlay | ALL | Approved Stage 1 requirement analysis |
| v2 | 2026-04-16 | Clarified that YAML remains the only editable/persisted value and live hardware indicators appear only for mismatches as read-only comparison data | Section 3 F-08, Section 6 AC-09/AC-10/AC-11 | Incorporated user clarification before implementation |
