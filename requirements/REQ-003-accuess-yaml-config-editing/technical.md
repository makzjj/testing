# REQ-003 Technical Design

> Status: Completed
> Requirement: requirement.md
> Created: 2026-04-16
> Updated: 2026-04-20

## 1. Technology Stack

| Module | Technology | Rationale |
|:---|:---|:---|
| Project config parsing and writing | Python + PyYAML | Reuses the current config stack and keeps YAML handling inside the existing desktop codebase |
| Desktop config editor UI | Python + PyQt6 | Matches the current workspace-shell implementation |
| Runtime live-value overlay | Existing runtime packet/event flow + bridge adapters | Reuses live MCU/node information that already exists in the runtime path |
| File reveal/open action | Windows shell invocation through Python subprocess / `os.startfile` style integration | Fits the desktop app environment and the user's requested reveal behavior |
| Validation and save orchestration | Dedicated backend config service modules | Keeps version/save/schema logic out of the page widget layer |

## 2. Design Principles

- Source-of-truth first: the new ACCuESS YAML file becomes the canonical config source for ACCuESS metadata and editable page content.
- YAML-only persistence: YAML field values remain the only editable and persisted config values; live hardware values are read-only comparison overlays only.
- Preserve round-trip structure: unknown sections and unknown fields should survive load/edit/save whenever feasible.
- Startup compatibility first: selector and workspace startup continue working even while ACCuESS moves to the richer schema.
- High cohesion, low coupling: YAML parsing, editable model building, save/versioning, live hardware overlay, and UI rendering stay in separate modules.
- Reuse first: extend `project_loader`, workspace bridges, and current runtime data hooks rather than inventing a parallel config stack.
- Safe save flow: version confirmation and save target naming must be explicit and user-safe.
- UI predictability: the Project Config page should behave like a structured developer tool, not a free-form document editor.

## 3. Architecture Overview

REQ-003 extends the current selector + workspace shell architecture with a dedicated config-editing pipeline.

Current simplified flow:

1. `ProgramSelectorWindow` loads `ProjectDefinition` objects through `myconfig.project_loader`
2. `ProjectWorkspaceWindow` receives the selected `ProjectDefinition`
3. `WorkspaceRuntimeBridge` reads raw YAML summaries through `RawProjectConfigReader`
4. `Project Config` page still renders summary cards rather than editable YAML sections

Target flow for REQ-003:

1. Selector startup continues to load valid project definitions from YAML
2. A new pre-parse repair/diagnostic step checks malformed YAML before the main config flow continues
3. A new config-schema layer normalizes the new ACCuESS structure for startup metadata and workspace use
4. A new config-edit service exposes:
   - current raw YAML content
   - editable presentation model
   - validation results
   - version-aware save flow
   - current active config file path
   - open/reveal action
5. The `Project Config` page requests config sections from the bridge and renders editable section widgets dynamically
6. The bridge also exposes live hardware overlay values from available runtime/device state
7. Save writes a new `<project_name>_<version>.yaml` file and updates the active project config path in the workspace context

Required source organization for this phase:

- `myconfig/`
  - `project_loader.py` (startup compatibility + new schema metadata extraction)
  - `project_models.py` (expanded config/project model support)
  - `yaml_repair_service.py` (new)
  - `config_schema_adapter.py` (new)
  - `config_editor_service.py` (new)
  - `config_save_service.py` (new)
- `gui/workspace/bridges/`
  - `raw_project_config_reader.py` (extended cache invalidation / active path support)
  - `workspace_runtime_bridge.py` (new config APIs + live overlay APIs)
- `gui/workspace/pages/`
  - `overview_page.py` (refactored `Project Config` editing experience)
- `gui/workspace/sections/overview/`
  - new editable section widgets replacing summary-only cards for this page
- `services/`
  - reuse runtime event/state access where live hardware values already exist

## 4. Module Design

### 4.1 `YamlRepairService`
- Responsibility:
  - perform an explicit malformed-YAML pre-parse diagnostic step before normal config loading
  - attempt safe syntax repair for known recoverable issues
  - return repair diagnostics when repair is needed or impossible
- Public interface:
  - `diagnose(path: Path) -> YamlRepairDiagnostic`
  - `repair_if_needed(path: Path) -> YamlRepairResult`
- Internal structure:
  - raw text read
  - YAML parser try/fail
  - conservative repair helpers
  - diagnostic message builder
- Reuse notes:
  - keeps syntax repair/diagnostics separate from schema normalization and editor/save logic

### 4.2 `ConfigSchemaAdapter`
- Responsibility:
  - understand the new ACCuESS YAML schema
  - map rich top-level YAML sections to startup-friendly metadata and editor-friendly section models
  - preserve raw structure for round-trip save
- Public interface:
  - `build_project_identity(raw: dict, path: Path) -> ProjectDefinition`
  - `build_editor_sections(raw: dict) -> list[ConfigSectionModel]`
  - `extract_version(raw: dict) -> str | None`
  - `extract_project_name(raw: dict) -> str`
- Internal structure:
  - top-level section readers
  - field coercion helpers
  - non-destructive fallback handling for missing or unknown fields
- Reuse notes:
  - centralizes schema knowledge so `project_loader` and UI code do not each hardcode YAML traversal differently

### 4.3 `ConfigEditorService`
- Responsibility:
  - read current YAML
  - validate YAML content
  - expose editable section/field models to the bridge/UI
  - rebuild YAML from edited field payloads while preserving unknown structure
- Public interface:
  - `load_current_config(path: Path) -> ConfigDocument`
  - `build_editor_model(path: Path) -> ConfigEditorModel`
  - `apply_edit_payload(document: ConfigDocument, payload: dict) -> ConfigDocument`
  - `validate_document(document: ConfigDocument) -> list[ConfigValidationIssue]`
- Internal structure:
  - file read
  - raw YAML cache
  - section model builder
  - typed validation helpers
- Reuse notes:
  - keeps page widgets free from direct YAML mutation logic

### 4.4 `ConfigSaveService`
- Responsibility:
  - handle version-aware confirmation rules
  - generate versioned output filename
  - write YAML safely to disk
  - return the new active config path
- Public interface:
  - `prepare_save(document, requested_version, confirmed_new_version) -> SavePlan`
  - `save_document(document, save_plan) -> SaveResult`
- Internal structure:
  - current-version extraction
  - filename builder `<project_name>_<version>.yaml`
  - collision checks
  - atomic or staged write strategy
- Reuse notes:
  - isolates user-safety logic from the rest of the bridge and UI

### 4.5 `ProjectLoader` extension
- Responsibility:
  - preserve selector startup behavior while understanding the new ACCuESS schema
- Public interface:
  - existing APIs remain:
    - `load_available_projects()`
    - `load_project_yaml(path)`
    - `build_project_definition(raw, path)`
- Internal structure:
  - invoke malformed-YAML diagnostic/repair before normal YAML load
  - delegate metadata extraction to `ConfigSchemaAdapter`
  - support both current minimal schemas and the richer ACCuESS schema
- Reuse notes:
  - avoids breaking the selector and existing project discovery flow

### 4.6 `RawProjectConfigReader` extension
- Responsibility:
  - read and cache the active project YAML path
  - allow cache invalidation after save
  - support config-path replacement after versioned save
- Public interface:
  - `load() -> dict`
  - `invalidate() -> None`
  - `set_active_path(path: Path) -> None`
  - `current_path() -> Path`
- Internal structure:
  - cached raw document
  - active config path tracking
- Reuse notes:
  - keeps bridge code simple when save changes the underlying filename

### 4.7 `WorkspaceRuntimeBridge` extension
- Responsibility:
  - expose Project Config page data and actions without embedding business logic in the page
- Public interface:
  - `get_config_editor_model()`
  - `save_config_changes(...)`
  - `get_live_hardware_overlays()`
  - `open_project_config_file()`
  - `reveal_project_config_file()`
- Internal structure:
  - compose config editor service
  - compose config save service
  - compose raw config reader
  - adapt live runtime values into page-friendly mismatch-only overlay models
- Reuse notes:
  - keeps the page declarative and aligns with current workspace bridge patterns

### 4.8 `Project Config Page` refactor
- Responsibility:
  - replace summary-only `Project Config` content with editable YAML-driven sections
- Public interface:
  - `refresh(...)`
  - section-level save / reveal / reload interactions through the bridge
- Internal structure:
  - top action row
  - top-level YAML section panels
  - nested field editors
  - save/version confirmation dialog flow
  - mismatch-only live hardware badges/highlight rows
- Reuse notes:
  - section containers and field rows should become reusable widgets for future config-related pages

### 4.9 `LiveHardwareOverlayProvider`
- Responsibility:
  - gather currently available live hardware values from runtime state
  - map them to YAML field locations when meaningful
  - compare live values against the corresponding YAML field values
  - emit overlays only when the live value differs from the YAML value
- Public interface:
  - `collect_live_values() -> list[LiveHardwareFieldValue]`
- Internal structure:
  - MCU version source
  - node version source
  - hardware info source
  - path-to-field matching logic
  - mismatch comparison logic
- Reuse notes:
  - future pages can reuse the same live-value source instead of directly reading runtime internals

## 5. Data Model

### 5.1 `ConfigDocument`
- Fields:
  - `raw_data: dict`
  - `source_path: Path`
  - `project_name: str`
  - `version: str | None`
- Purpose:
  - canonical in-memory representation for load/edit/save

### 5.2 `ConfigEditorModel`
- Fields:
  - `sections: list[ConfigSectionModel]`
  - `source_path: Path`
  - `project_name: str`
  - `version: str | None`
  - `validation_issues: list[ConfigValidationIssue]`
- Purpose:
  - bridge-friendly editable model for the Project Config page

### 5.3 `ConfigSectionModel`
- Fields:
  - `section_key: str`
  - `title: str`
  - `fields: list[ConfigFieldModel]`
  - `raw_value_type: str`
- Purpose:
  - represents one top-level YAML section

### 5.4 `ConfigFieldModel`
- Fields:
  - `path: str`
  - `label: str`
  - `value: object`
  - `value_type: str`
  - `editable: bool`
  - `children: list[ConfigFieldModel]`
  - `live_overlay: LiveHardwareFieldValue | None`
- Purpose:
  - recursive editable field model for nested YAML content where `value` is always the YAML-backed editable value

### 5.5 `LiveHardwareFieldValue`
- Fields:
  - `path: str`
  - `label: str`
  - `yaml_value: object`
  - `live_value: object`
  - `display_text: str`
  - `highlight_tone: str`
- Purpose:
  - marks a field as having a mismatch-only read-only live hardware overlay and tells the UI how to present it

### 5.6 `SavePlan`
- Fields:
  - `target_version: str`
  - `target_path: Path`
  - `requires_confirmation: bool`
  - `warning_text: str`
- Purpose:
  - explicit intermediate object for the user-safe save flow

### 5.7 `SaveResult`
- Fields:
  - `saved_path: Path`
  - `saved_version: str`
  - `message: str`
- Purpose:
  - bridge/UI response after save succeeds

### 5.8 `YamlRepairDiagnostic`
- Fields:
  - `is_valid: bool`
  - `was_repaired: bool`
  - `message: str`
  - `repaired_text: str | None`
- Purpose:
  - communicates the explicit malformed-YAML pre-parse diagnostic outcome to loader/editor flows

## 6. API Design

This feature adds internal Python APIs rather than external HTTP endpoints.

### 6.1 Loader / schema APIs
- `diagnose(path: Path) -> YamlRepairDiagnostic`
- `repair_if_needed(path: Path) -> YamlRepairResult`
- `load_project_yaml(path: Path) -> dict`
- `build_project_definition(raw: dict, path: Path) -> ProjectDefinition`
- `build_project_identity(raw: dict, path: Path) -> ProjectDefinition`

### 6.2 Config editor APIs
- `load_current_config(path: Path) -> ConfigDocument`
- `build_editor_model(path: Path) -> ConfigEditorModel`
- `validate_document(document: ConfigDocument) -> list[ConfigValidationIssue]`

### 6.3 Save APIs
- `prepare_save(document, requested_version, confirmed_new_version) -> SavePlan`
- `save_document(document, save_plan) -> SaveResult`

### 6.4 Bridge APIs
- `get_config_editor_model() -> ConfigEditorModel`
- `save_config_changes(edit_payload: dict, requested_version: str | None, confirmed_new_version: bool) -> SaveResult | SavePlan`
- `open_project_config_file() -> str`
- `reveal_project_config_file() -> str`
- `get_live_hardware_overlays() -> list[LiveHardwareFieldValue]`

## 7. Key Flows

### 7.1 Startup metadata flow

1. Selector discovers project YAML files
2. `YamlRepairService` performs an explicit malformed-YAML diagnostic step
3. If repair is needed and safe, repaired YAML text is produced before normal parsing continues
4. `project_loader` reads raw YAML
5. `ConfigSchemaAdapter` extracts project name, display name, version, features, UI metadata, and axis count from the new ACCuESS schema
6. Selector continues to open the workspace as before

### 7.2 Project Config page load flow

1. User opens `Project Config`
2. Page requests editor model from `WorkspaceRuntimeBridge`
3. Bridge triggers the malformed-YAML diagnostic/repair step
4. Bridge loads raw YAML through `RawProjectConfigReader`
5. `ConfigEditorService` builds section and field models
6. Page renders top-level sections and nested editable rows

### 7.3 Live hardware overlay flow

1. Page requests live overlay values from bridge
2. Bridge reads current runtime/device values from available runtime state
3. `LiveHardwareOverlayProvider` maps live values to YAML field paths and compares them against the YAML field values
4. Only mismatched values are returned as overlays
5. Page renders a read-only highlighted indicator such as `Actual: MCU Version = xxx`
6. Matching live values produce no extra indicator

### 7.4 Version-aware save flow

1. User edits YAML fields and clicks save
2. Page submits edited payload and visible version state
3. Bridge applies edits to a `ConfigDocument`
4. `ConfigSaveService` compares old vs new version
5. If version is unchanged:
   - return a confirmation requirement to UI
   - UI prompts for explicit version update
   - save remains blocked until a new version is entered and confirmed
6. When confirmed, service writes `<project_name>_<version>.yaml`
7. Reader/bridge update the active config path and invalidate cache
8. Page refreshes from the newly saved file
9. Live hardware overlay data is ignored by persistence logic; only YAML-backed edited values are saved

### 7.5 Open / reveal file flow

1. User clicks open/reveal action
2. Page asks bridge for file action
3. Bridge resolves current active config path
4. OS shell opens or reveals the file

## 8. Shared Modules & Reuse Strategy

Shared modules introduced or extended by this requirement:

- `project_loader.py`
- `raw_project_config_reader.py`
- `workspace_runtime_bridge.py`
- new config schema adapter
- new config editor/save services
- reusable recursive config field widgets
- live hardware overlay provider

Reuse strategy:

- keep selector startup on the current loader API so REQ-001 behavior does not regress
- reuse the workspace bridge as the Project Config page's backend-facing integration point
- reuse current runtime sources for MCU/node/live data instead of creating a second hardware polling path
- build reusable config field widgets so future config pages or dialogs can share them

## 9. Risks & Notes

- Risk 1:
  - If save reconstructs YAML too aggressively, unknown fields or formatting intent may be lost.
- Risk 2:
  - If startup metadata extraction hardcodes only ACCuESS-specific paths without fallback behavior, other projects may break.
- Risk 3:
  - Mapping live runtime values to YAML fields may be partial in the first version because current runtime state is uneven.
- Risk 4:
  - If mismatch comparison logic is too broad, the UI may show noisy overlays; it must emit indicators only when live and YAML values actually differ.
- Risk 5:
  - File reveal/open behavior is OS-specific and should be implemented carefully for Windows-first behavior.
- Risk 6:
  - If the Project Config page tries to be a generic text editor instead of a structured config tool, UX will become noisy and hard to validate.

Implementation notes:

- Keep the first version of the editor schema-driven but section-ordered by a fixed top-level template for readability.
- Preserve old workspace and selector behavior unless a schema-driven config-path update is intentional.
- Use concise comments only around version/save confirmation and non-obvious schema normalization logic.

## 10. Change Log

| Version | Date | Changes | Affected Scope | Reason |
|:---|:---|:---|:---|:---|
| v1 | 2026-04-16 | Initial technical design for new ACCuESS schema support, YAML editor service, versioned save flow, live hardware overlay, and file reveal action | ALL | Derived from approved REQ-003 requirement analysis |
| v2 | 2026-04-16 | Clarified mismatch-only live hardware comparison behavior so YAML remains the only editable/persisted value and live overlays are read-only | Sections 2, 4.6, 4.7, 4.8, 5.4, 5.5, 7.3, 7.4, 9 | Incorporated user clarification before implementation |
| v3 | 2026-04-16 | Added explicit malformed-YAML pre-parse repair/diagnostic step and renamed the save confirmation API to make version-change requirement explicit | Sections 3, 4.1-4.9, 5.8, 6.1/6.3/6.4, 7.1/7.2/7.4 | Incorporated final pre-implementation cleanup before coding |
