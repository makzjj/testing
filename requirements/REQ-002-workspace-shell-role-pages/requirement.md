# REQ-002 Workspace Shell And Role Pages

> Status: Completed
> Created: 2026-04-08
> Updated: 2026-04-15

## 1. Background

The BioBot Robot Arm Tester has already completed the first project-selection milestone:

- the application starts with a selector window
- projects are discovered from `project_configs/`
- YAML metadata is parsed into a typed project object
- the selected project context can be handed to the next runtime layer

However, after project selection the runtime still falls back to the existing large `MainWindow`.

This creates a mismatch between the intended platform architecture and the actual user experience:

- the selector already behaves like the entry point of a multi-project platform
- the approved Phase 2 mockup already defines a clearer workspace hierarchy
- the runtime still opens a legacy all-in-one window
- new UI features still risk being added into `gui/main_window.py`

The purpose of this requirement is to build the first real project workspace shell for Phase 2, based on the approved mockup in `docs/ui_mockups/PHASE2_UI_DESIGN_GUIDE_ZH.md`.

This requirement is intended to move the product from:

- selector plus one oversized shared runtime window

to:

- selector plus a structured workspace shell with role-oriented top-level pages

This requirement also protects the architecture from continued `MainWindow` growth by establishing a real home for new pages and modules before larger service and state refactors begin.


## 2. Target Users & Scenarios

### Target users

- firmware engineers using protocol, command, and sensor-debug tools
- mechanical engineers using motion, repeatability, and limit-observation tools
- application / production engineers using integration, controller setup, and other workflow-specific tools
- internal developers continuing the platform refactor

### Primary scenarios

1. A user selects a project in the selector and expects to enter a real project workspace rather than the legacy all-purpose runtime window.
2. A user needs clear first-level navigation between `Overview`, `Firmware`, `Mechanical`, `Application / Production`, and `Settings`.
3. A user expects a persistent `Live session` summary and a persistent right-side `Console` while moving between pages.
4. A user expects high-frequency summary information on `Overview` and more focused tools on deeper pages.
5. A user expects future specialized test features, including possible stress-test entry points, to be addable later without forcing a workspace restructure or a one-page-only ownership rule.


## 3. Functional Requirements

### F-01 Workspace entry and project context handoff
- Main flow:
  - After a user selects a valid project in the selector, the application shall open a shared project workspace shell.
  - The workspace shell shall receive the selected `ProjectDefinition` or an equivalent typed project context.
  - The selector shall hide while the workspace is open and reappear when the workspace is closed.
- Error handling:
  - If project context cannot be resolved, the application shall not silently open an incorrect workspace.
  - The user shall receive a clear blocking message instead of entering a broken workspace.
- Edge cases:
  - Phase 2 may continue using the current minimal project model from Phase 1.
  - Phase 2 shall not wait for the full long-term project model before introducing the shell.

### F-02 Shared workspace shell layout
- Main flow:
  - The workspace shall implement the approved four-area layout:
    - left navigation
    - left-bottom live session block
    - main content area
    - fixed right-side console
  - The workspace shall prioritize useful content area over decorative page headers or large branding blocks.
- Error handling:
  - If a page module is not yet fully wired to runtime logic, the workspace shall show a clear transitional state instead of blank content or crashes.
- Edge cases:
  - Window resizing shall preserve the presence of the console area.
  - Layout decisions shall follow the current mockup first, with `IPQC-SW` used only as a secondary structure reference when needed.

### F-03 First-level navigation and page routing
- Main flow:
  - The workspace shall provide first-level navigation for:
    - `Overview`
    - `Firmware`
    - `Mechanical`
    - `Application / Production`
    - `Settings`
  - The default landing page after workspace creation shall be `Overview`.
  - Page switching shall happen within the same workspace shell.
- Error handling:
  - A navigation item shall not route to an empty or broken page without a visible fallback state.
- Edge cases:
  - Phase 2 may keep the first-level page set fixed.
  - Capability-driven page enablement may be refined in later phases.

### F-04 Overview page composition
- Main flow:
  - The `Overview` page shall present summary-oriented workspace information rather than detailed specialist tools.
  - The page shall include the following modules or equivalent content regions:
    - `Connection and bench session`
    - KPI summary
    - `Transport summary`
    - `Node summary`
    - `Runtime alerts`
    - `Quick actions`
    - `Project capabilities`
- Error handling:
  - If live runtime data is not yet available, the page shall show recognizable empty or pending states.
- Edge cases:
  - Detailed protocol panels, motion panels, and future specialized test controls shall not be moved back into `Overview`.

### F-05 Firmware page composition
- Main flow:
  - The `Firmware` page shall provide structured regions for firmware-oriented tools.
  - The page shall include at least the following modules or module homes:
    - `Command debug`
    - `UART protocol monitor`
    - `Frame loss summary`
    - `Motion command panel`
    - `Sensor snapshot`
- Error handling:
  - Modules that are not fully migrated in Phase 2 shall still appear as clear, bounded areas instead of disappearing from the new information architecture.
- Edge cases:
  - Phase 2 does not require a full transport/service refactor before the firmware page can exist.

### F-06 Mechanical page composition
- Main flow:
  - The `Mechanical` page shall provide structured regions for mechanical workflow tools.
  - The page shall include at least the following modules or module homes:
    - `Motor behaviour observation`
    - `Axis motion control`
    - `Repeatability check`
    - `Sensor limits and offsets`
    - `Selected axis snapshot`
- Error handling:
  - Transitional modules shall render safe placeholder or partially wired states when full runtime wiring is not yet available.
- Edge cases:
  - Trend-line visualization is not required in this phase.
  - Table, summary-card, and status-block presentations are acceptable and preferred for Phase 2.

### F-07 Application / Production page composition
- Main flow:
  - The `Application / Production` page shall host application-side and production-side workflow modules.
  - The page shall include at least the following modules or module homes:
    - `Integration checklist`
    - `Controller profile`
    - `Test run setup`
- Error handling:
  - Transitional integration with legacy logic shall not hardcode future specialized test workflows into this page if they belong elsewhere later.
- Edge cases:
  - The current iteration shall not ship working stress-testing behavior as part of Phase 2.
  - Future stress-test workflows may later be introduced from different pages, buttons, or module areas, so Phase 2 shall keep extension points flexible.

### F-08 Settings page composition
- Main flow:
  - The `Settings` page shall display project and workspace configuration information relevant to the selected project.
  - The page shall include at least:
    - `Project metadata`
    - `Enabled tool areas`
    - `Bench defaults`
    - `Configuration actions`
- Error handling:
  - Missing optional metadata shall result in empty-state rendering rather than exceptions.
- Edge cases:
  - Phase 2 may keep this page primarily informational.
  - Full configuration editing flows can be introduced later.

### F-09 Persistent live session and console regions
- Main flow:
  - The left-bottom `Live session` block shall remain visible while the user navigates between first-level pages.
  - The right-side `Console` shall remain visible while the user navigates between first-level pages.
  - Page switching shall not recreate or discard the console region.
- Error handling:
  - If there is no active runtime session, the shell shall display a clear idle or disconnected state.
- Edge cases:
  - Phase 2 may reuse current runtime-derived information before a future logging service and session state model are fully introduced.

### F-10 Phase boundary and legacy transition control
- Main flow:
  - New Phase 2 UI structure shall be implemented as a workspace shell plus pages and reusable widgets.
  - The shell shall become the default landing structure after selector handoff.
- Error handling:
  - Any temporary bridge to legacy runtime logic shall be explicit and limited in scope.
  - Transitional compatibility shall not mask broken page ownership or route unclear new features back into `MainWindow`.
- Edge cases:
  - Phase 2 may preserve portions of existing runtime logic behind the shell.
  - Phase 2 shall not be blocked on full service extraction, state modeling, or protocol formalization.


## 4. Non-functional Requirements

- NFR-01 Maintainability
  - Phase 2 shall create a real shell/page hierarchy so new top-level UI does not continue to grow inside `gui/main_window.py`.

- NFR-02 Consistency
  - All first-level pages shall follow the same shell structure and visual density rules.

- NFR-03 Usable density
  - Pages shall maximize useful area and avoid large decorative headers.

- NFR-04 Transition safety
  - The new shell shall allow staged migration from legacy runtime behavior without destabilizing startup or project selection.

- NFR-05 Extensibility
  - The shell shall provide a stable landing layer for later page enablement, typed project modeling, services, and state work.

- NFR-06 Mockup fidelity
  - The approved Phase 2 mockup shall be the primary reference for layout, module grouping, and top-level navigation.

- NFR-07 Reuse readiness
  - Shared UI elements such as navigation, session blocks, console panels, cards, and module containers shall be designed for reuse across pages.

- NFR-08 Layered file structure
  - Phase 2 implementation shall be split by responsibility into dedicated shell, page, widget, bridge, and model modules where appropriate.
  - The new workspace shall not be implemented as one new monolithic file.

- NFR-09 Future feature placement flexibility
  - Phase 2 shall not encode a permanent ownership rule for future stress-test workflows or similar specialized tools.
  - The workspace structure shall allow later features to be introduced through page-local modules, buttons, or other focused entry points without rewriting the shell.


## 5. Out of Scope

- full `ProjectDefinition` expansion for every future capability field
- complete capability-driven page enablement rules
- full decomposition of `gui/main_window.py`
- full extraction of serial, command, packet, and scan services
- complete rollout of typed node state and app state models
- full logging service refactor
- implementation of future stress-testing workflows or their final page/button entry strategy
- final visual polish for every future workflow module
- complete feature parity migration of every existing dialog and panel


## 6. Acceptance Criteria

| ID | Feature | Condition | Expected Result |
|:---|:---|:---|:---|
| AC-01 | F-01 Workspace entry and project context handoff | User selects a valid project and clicks `Open` | The selector opens a shared workspace shell using the selected project context |
| AC-02 | F-01 Workspace entry and project context handoff | Workspace is closed | The selector becomes visible again |
| AC-03 | F-02 Shared workspace shell layout | Workspace opens | Left navigation, left-bottom live session, central content, and fixed right-side console are visible |
| AC-04 | F-03 First-level navigation and page routing | Workspace opens for the first time | `Overview` is the active default page |
| AC-05 | F-03 First-level navigation and page routing | User switches between first-level pages | Navigation occurs inside the same workspace window |
| AC-06 | F-04 Overview page composition | User opens `Overview` | Summary-oriented modules are shown and detailed specialist tools are not dumped back onto the page |
| AC-07 | F-05 Firmware page composition | User opens `Firmware` | Firmware-oriented module regions are visible |
| AC-08 | F-06 Mechanical page composition | User opens `Mechanical` | Mechanical workflow module regions are visible |
| AC-09 | F-07 Application / Production page composition | User opens `Application / Production` | The page contains its current application / production sections and remains a focused first-level page inside the workspace |
| AC-10 | F-08 Settings page composition | User opens `Settings` | Project metadata and configuration-related sections are visible |
| AC-11 | F-09 Persistent live session and console regions | User navigates across first-level pages | `Live session` and `Console` remain visible and do not reset on each page switch |
| AC-12 | F-10 Phase boundary and legacy transition control | Code structure is reviewed after implementation | Phase 2 shell and top-level pages are implemented as dedicated shell/page/widget modules rather than being added directly as a new top-level layout inside `gui/main_window.py` |
| AC-13 | NFR-09 Future feature placement flexibility | Code structure is reviewed after implementation | Future specialized tools can be added as dedicated page modules or button-driven entries without rewriting the shell or forcing ownership into one fixed page |


## 7. Diagram Status

Requirement-level PlantUML artifacts for this requirement are stored in this folder:

- `req-usecase.puml`
- `req-flow.puml`
- `req-sequence.puml`

Rendered SVG artifacts:

- `req-usecase.svg`
- `req-flow.svg`
- `req-sequence.svg`


## 8. Change Log

| Version | Date | Changes | Affected Scope | Reason |
|:---|:---|:---|:---|:---|
| v1 | 2026-04-08 | Initial requirement document for Phase 2 workspace shell and role-oriented top-level pages | ALL | Derived from `docs/architecture/ARCHITECTURE_TODO.md`, `docs/ui_mockups/PHASE2_UI_DESIGN_GUIDE_ZH.md`, and the approved Phase 2 requirement review |
| v2 | 2026-04-09 | Clarified layered file-ownership expectations and deferred `Stress testing` implementation while keeping its future ownership under `Application / Production` | Sections 2, 3 F-07, 4 NFR-08, 5, 6 AC-09 | Incorporated user review feedback before coding |
| v3 | 2026-04-09 | Removed the fixed future ownership rule for `Stress testing` and clarified that future specialized tools may be introduced from different pages or buttons as long as the shell remains layered and extensible | Sections 2, 3 F-04/F-07, 4 NFR-09, 5, 6 AC-09/AC-13 | Incorporated follow-up user review feedback before coding |
