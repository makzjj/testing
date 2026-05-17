# REQ-002 Technical Design

> Status: Completed
> Requirement: requirement.md
> Created: 2026-04-08
> Updated: 2026-04-15

## 1. Technology Stack

| Module | Technology | Rationale |
|:---|:---|:---|
| Desktop workspace shell | Python + PyQt6 | Matches the existing application stack and keeps Phase 2 inside the current desktop framework |
| Project context reuse | Existing `ProjectDefinition` dataclass | Reuses Phase 1 project-loading output without blocking on Phase 3 model expansion |
| Page routing | `QStackedWidget` + page registry metadata | Simple, reliable page switching inside one workspace shell |
| Shared shell widgets | PyQt6 custom `QWidget` components | Keeps navigation, session, console, cards, and page sections reusable |
| Summary and settings presentation | Qt layouts, `QGroupBox`, `QLabel`, `QTableWidget`, `QListWidget` | Supports the mockup's card and summary-driven presentation without adding unnecessary dependencies |
| Console rendering | `QPlainTextEdit` or `QTextEdit` with append-only helpers | Provides a fixed right-side console panel that can bridge current logging behavior |
| Transition hooks | Thin Python adapter methods around legacy runtime behavior | Enables staged migration without requiring immediate full service extraction |


## 2. Design Principles

- Shell first: the project workspace shell becomes the default runtime landing layer after selector handoff.
- High cohesion, low coupling: navigation, session summary, console, pages, and runtime bridge logic remain separate responsibilities.
- Mockup fidelity first: Phase 2 follows the approved mockup for structure and module grouping rather than inventing a new top-level layout.
- Transition-safe: the design allows selective reuse of legacy runtime behavior without making `MainWindow` the top-level information architecture again.
- Reuse first: shared widgets and page sections should be generic enough to support later page growth.
- Layered file ownership: shell, pages, widgets, bridges, and lightweight workspace models must be split into dedicated modules instead of being collapsed into one file.
- Future feature placement stays flexible: Phase 2 must not encode a permanent ownership rule for future stress-test workflows or similar specialized tools.
- No silent scope creep: Phase 2 establishes the shell and page homes first; full state/service/protocol refactors remain future work.


## 3. Architecture Overview

Phase 2 introduces a new top-level workspace window between the selector and the old runtime logic.

Current flow:

1. `main.py` creates `ProgramSelectorWindow`
2. selector loads valid `ProjectDefinition` objects
3. selector opens `MainWindow` directly

Target Phase 2 flow:

1. `main.py` creates `ProgramSelectorWindow`
2. selector loads valid `ProjectDefinition` objects
3. selector opens `ProjectWorkspaceWindow(project_definition)`
4. workspace shell builds:
   - left navigation
   - left-bottom live session panel
   - central stacked page area
   - fixed right-side console panel
5. workspace shell activates `Overview` by default
6. page modules host real content, transitional content, or bridge content in clearly owned areas

Required source organization for this phase:

- `gui/`
  - `program_selector_window.py`
  - `project_workspace_window.py`
  - `workspace_models.py`
  - `pages/`
    - `overview_page.py`
    - `firmware_page.py`
    - `mechanical_page.py`
    - `application_production_page.py`
    - `settings_page.py`
  - `widgets/`
    - `workspace_navigation.py`
    - `live_session_panel.py`
    - `console_panel.py`
    - `summary_card.py`
    - `module_section.py`
  - `bridges/`
    - `workspace_runtime_bridge.py`

This design keeps the new shell visible and stable while allowing selected legacy capabilities to be migrated behind page boundaries rather than through another round of `MainWindow` growth.
The layered split above is part of the implementation constraint for this REQ, not an optional cleanup step.


## 4. Module Design

### 4.1 `ProjectWorkspaceWindow`
- Responsibility:
  - own the top-level Phase 2 workspace shell
  - receive `ProjectDefinition`
  - compose navigation, live session, page stack, and console
  - coordinate default page routing and selector return behavior
- Public interface:
  - constructor `ProjectWorkspaceWindow(project_definition: ProjectDefinition)`
  - `set_active_page(route_id: str) -> None`
  - `append_console(message: str) -> None`
  - `update_session_state(state: WorkspaceSessionState) -> None`
- Internal structure:
  - shell layout builder
  - page registry initialization
  - route switching
  - workspace close / selector restore hooks
- Reuse notes:
  - becomes the shared shell for all future projects, not an ACCuESS-specific window

### 4.2 `WorkspaceNavigationWidget`
- Responsibility:
  - render first-level navigation items
  - emit page-switch requests
  - display active-route state
- Public interface:
  - `set_items(items: list[WorkspacePageDefinition]) -> None`
  - `set_active(route_id: str) -> None`
  - signal or callback `page_selected(route_id: str)`
- Internal structure:
  - route metadata list
  - button/list-item state updates
- Reuse notes:
  - future capability-driven page enablement can reuse the same widget with different page definitions

### 4.3 `LiveSessionPanel`
- Responsibility:
  - show persistent session information in the lower-left shell area
  - summarize project identity, connection/session state, and current runtime mode
- Public interface:
  - `update_state(state: WorkspaceSessionState) -> None`
- Internal structure:
  - project label
  - connection status row
  - session summary fields
- Reuse notes:
  - later service/state work can feed this panel without changing shell layout

### 4.4 `ConsolePanel`
- Responsibility:
  - render the fixed right-side console visible across all first-level pages
  - centralize append-only console behavior for the workspace
- Public interface:
  - `append_line(message: str) -> None`
  - `clear() -> None`
  - optional `attach_log_source(...)`
- Internal structure:
  - read-only text area
  - optional action row
- Reuse notes:
  - can later become the presentation layer over a real logging service

### 4.5 `WorkspacePageStack`
- Responsibility:
  - own first-level page widgets and switch between them inside the same workspace shell
- Public interface:
  - `register_page(route_id: str, widget: QWidget) -> None`
  - `show_page(route_id: str) -> None`
- Internal structure:
  - route-to-index mapping
  - `QStackedWidget`
- Reuse notes:
  - centralizes page routing so the selector and page widgets stay unaware of each other

### 4.6 `OverviewPage`
- Responsibility:
  - present summary information and quick actions for the selected project workspace
- Public interface:
  - `refresh(project_definition, session_state) -> None`
- Internal structure:
  - connection and bench session card
  - KPI summary cards
  - transport summary section
  - node summary section
  - runtime alerts section
  - quick actions section
  - project capabilities section
- Reuse notes:
  - summary-card and section widgets used here should also be reusable on other pages

### 4.7 `FirmwarePage`
- Responsibility:
  - host firmware-oriented modules without turning the page into another all-purpose main window
- Public interface:
  - `refresh(...) -> None`
  - optional callbacks for actions such as opening the serial monitor or forwarding command actions
- Internal structure:
  - command debug section
  - UART protocol monitor section
  - frame loss summary section
  - motion command section
  - sensor snapshot section
- Reuse notes:
  - sections may initially bridge to legacy dialogs or current logic, but the page owns their layout placement

### 4.8 `MechanicalPage`
- Responsibility:
  - host mechanical workflow modules and observation-oriented summaries
- Public interface:
  - `refresh(...) -> None`
- Internal structure:
  - motor behaviour observation section
  - axis motion control section
  - repeatability section
  - sensor limits and offsets section
  - selected axis snapshot section
- Reuse notes:
  - snapshot cards and table sections should be reusable patterns rather than one-off page code

### 4.9 `ApplicationProductionPage`
- Responsibility:
  - host the current application and production workflow modules defined for Phase 2 without becoming the mandatory home for every future specialized test flow
- Public interface:
  - `refresh(...) -> None`
- Internal structure:
  - integration checklist section
  - controller profile section
  - test run setup section
- Reuse notes:
  - this page remains one focused first-level area, but future stress-test workflows may later be attached from other pages or action buttons when requirements become clearer

### 4.10 `SettingsPage`
- Responsibility:
  - present project metadata, enabled tool areas, bench defaults, and configuration actions
- Public interface:
  - `refresh(project_definition) -> None`
- Internal structure:
  - project metadata section
  - enabled tool areas section
  - bench defaults section
  - configuration actions section
- Reuse notes:
  - future project editing and config diagnostics can grow from this page without changing the shell

### 4.11 `WorkspaceRuntimeBridge`
- Responsibility:
  - provide controlled adapters from the new shell/pages to legacy runtime behavior that cannot yet be fully extracted in Phase 2
- Public interface:
  - focused helper methods such as:
    - `open_serial_monitor()`
    - `open_zposs_plot()`
    - `get_session_snapshot()`
    - `get_node_summary()`
    - `append_log(...)`
- Internal structure:
  - no page layout ownership
  - no top-level window ownership
  - no re-creation of the legacy all-in-one shell
- Reuse notes:
  - this bridge exists to reduce migration risk and should remain thin enough to be replaced later by real services/state models

### 4.12 Selector integration update
- Responsibility:
  - change selector handoff from legacy `MainWindow` launch to `ProjectWorkspaceWindow` launch
- Public interface:
  - internal selector method update in `ProgramSelectorWindow`
- Internal structure:
  - window creation
  - selector hide/show coordination
- Reuse notes:
  - keeps Phase 1 selection logic intact while changing only the runtime destination


## 5. Data Model

Phase 2 should keep the data model intentionally light and focused on workspace structure.

### 5.1 Reused `ProjectDefinition`
- Fields already available from Phase 1:
  - `name`
  - `display_name`
  - `config_path`
  - `system_axes`
  - `features`
  - `ui`
- Use in Phase 2:
  - workspace title
  - settings page metadata
  - project capabilities summary
  - future route enablement decisions

### 5.2 `WorkspacePageDefinition`
- Fields:
  - `route_id: str`
  - `label: str`
  - `enabled: bool`
  - `order: int`
- Purpose:
  - define first-level navigation items independent from concrete widgets

### 5.3 `WorkspaceSessionState`
- Fields:
  - `project_name: str`
  - `connection_text: str`
  - `session_text: str`
  - `active_page: str`
  - `alerts_text: str | None`
- Purpose:
  - lightweight shell-facing state for `LiveSessionPanel` and overview/session summaries

### 5.4 `ConsoleMessage`
- Fields:
  - `level: str`
  - `text: str`
  - `timestamp: str | None`
- Purpose:
  - optional typed message shape if the console panel should stop accepting raw strings later

Planned class diagram files:

- `tech-class.puml`


## 6. API Design

This phase does not introduce external HTTP APIs. The relevant APIs are internal Python interfaces.

### 6.1 Selector to workspace handoff
- `ProjectWorkspaceWindow(project_definition: ProjectDefinition)`

### 6.2 Navigation API
- `set_active_page(route_id: str) -> None`
- `page_selected(route_id: str)` signal or callback

### 6.3 Session API
- `update_session_state(state: WorkspaceSessionState) -> None`

### 6.4 Console API
- `append_console(message: str) -> None`
- `append_line(message: str) -> None`
- `clear() -> None`

### 6.5 Page construction API
- `build_page_registry(project_definition: ProjectDefinition) -> list[WorkspacePageDefinition]`
- `build_workspace_pages(project_definition: ProjectDefinition) -> dict[str, QWidget]`

### 6.6 Bridge API
- `open_serial_monitor() -> None`
- `open_zposs_plot() -> None`
- `get_session_snapshot() -> WorkspaceSessionState`
- `get_node_summary() -> dict | list`


## 7. Key Flows

### 7.1 Project open flow

1. User selects a valid project in `ProgramSelectorWindow`
2. Selector creates `ProjectWorkspaceWindow(project_definition)`
3. Workspace shell builds navigation, session panel, console panel, and stacked pages
4. Workspace sets `Overview` as the active route
5. Selector hides while the workspace is active

### 7.2 First-level navigation flow

1. User clicks a navigation item such as `Mechanical`
2. Navigation widget emits the selected route id
3. Workspace shell activates the matching page in the stack
4. Live session panel and console panel remain unchanged as shell-level components

### 7.3 Transitional runtime data flow

1. Workspace shell or a page requests session, summary, or action data
2. A thin runtime bridge retrieves data from legacy runtime sources or placeholder providers
3. The page updates its cards/sections without taking ownership of legacy top-level layout
4. Future service extraction can replace the bridge without changing the shell/page hierarchy

Planned sequence diagram files:

- `tech-sequence.puml`


## 8. Shared Modules & Reuse Strategy

Shared reusable parts introduced or clarified by this phase:

- project workspace shell
- page registry metadata
- navigation widget
- live session panel
- console panel
- summary-card / section-container widgets
- lightweight workspace models
- thin runtime bridge helpers

Reuse strategy:

- all first-level pages consume shared shell widgets rather than building their own sidebars or console areas
- summary cards and section containers are shared building blocks, not page-specific implementations
- `ProjectDefinition` is reused directly instead of introducing a separate Phase 2 project context type
- bridge helpers remain narrow so they can later be replaced by services without changing page ownership
- future specialized tools should be addable through page-local sections, buttons, or focused entry widgets without changing the shell contract


## 9. Risks & Notes

- Risk 1:
  - If the selector still opens `MainWindow` directly, Phase 2 will not actually establish the intended workspace layer.
- Risk 2:
  - If the shell layout is added directly into `gui/main_window.py`, the refactor will preserve the main architecture problem it is supposed to solve.
- Risk 3:
  - If the console or live session area is implemented inside each page, layout consistency and persistent context will break.
- Risk 4:
  - If the bridge grows too large, Phase 2 may accidentally recreate a hidden version of the old all-in-one runtime architecture.
- Risk 5:
  - If pages try to achieve full legacy feature parity immediately, or if future specialized tools are prematurely hardcoded to one page during Phase 2, later feature placement will become expensive to change.

Implementation notes for this stage:

- prefer shipping a stable shell with clearly owned module areas over forcing every legacy feature into its final form immediately
- do not implement `Stress testing` in this round, and do not encode a permanent ownership rule for where future stress-test workflows must live
- do not let `IPQC-SW` override the approved mockup structure
- plan the code layout so Phase 5 can continue decomposing old `MainWindow` responsibilities into dedicated page-owned widgets and services


## 10. Change Log

| Version | Date | Changes | Affected Scope | Reason |
|:---|:---|:---|:---|:---|
| v1 | 2026-04-08 | Initial technical design draft for the Phase 2 workspace shell, first-level page structure, and controlled legacy transition strategy | ALL | Derived from REQ-002 and the approved Phase 2 mockup structure |
| v2 | 2026-04-09 | Made layered multi-file organization mandatory and deferred `Stress testing` implementation while keeping its future ownership under `Application / Production` | Sections 2, 3, 4.9, 9 | Incorporated user review feedback before coding |
| v3 | 2026-04-09 | Removed the fixed future ownership rule for `Stress testing` and clarified that future specialized tools must remain easy to place from different pages or entry points | Sections 2, 4.9, 8, 9 | Incorporated follow-up user review feedback before coding |
