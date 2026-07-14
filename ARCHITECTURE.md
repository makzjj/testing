# IPQC Architecture

This document explains how the IPQC application is structured today. It describes the ownership model, the layering strategy, and the reasoning behind the design. For exact current owners and deferred technical items, see [CANONICAL_PIPELINE_REGISTRY.md](CANONICAL_PIPELINE_REGISTRY.md).

## Project Philosophy

The architecture is built around a small set of rules:

- one responsibility should have one owner
- runtime state is the single source of truth
- protocol logic should not be duplicated in pages or workflows
- workflow state should stay inside controllers
- UI should render state, not own it
- new behavior should extend existing canonical layers instead of creating parallel paths

This structure exists because the application spans production programming, motion workflows, diagnostics, workbook handling, and live robot communication. Without explicit ownership, packet handling and state tend to spread across pages, controllers, and helpers. The layered model keeps those responsibilities separated.

## Layered Architecture

The current design is:

```text
Protocol
  ->
Runtime
  ->
Request / Operation Adapters
  ->
Workflow Controllers
  ->
UI
```

### Protocol

The protocol layer owns raw frame and command handling:

- binary payload builders
- UART / CAN-over-UART frame parsing
- semantic command decoding

Protocol code is responsible for converting bytes into structured packet meaning and converting application intent back into bytes. It should not own workflow state, page state, or UI behavior.

### Runtime

The runtime layer owns shared state that represents the current system view:

- per-node connectivity
- firmware and version data
- interrupt state
- motor-current runtime data
- emergency and system-wide status

Runtime is the single source of truth. If multiple pages need the same live data, that data belongs in runtime state rather than in page-local caches.

### Request / Operation Adapters

Adapters are narrow filters on the shared packet stream. Their job is to ensure that active workflows receive only relevant traffic.

Examples in the current codebase include:

- Sampling transport adapter
- Functional / Single Axis transport adapter
- Production test transport adapter
- Production parameter transport adapter
- Firmware transport adapter for Firmware Integration Test ingress

Adapters do not own workflow policy. They own relevance filtering only.

### Workflow Controllers

Controllers own operation-local behavior:

- sequencing
- timeout handling
- pass/fail decisions
- pending request tracking
- workbook-step progression where applicable

Controllers should not become alternate runtime stores. They may keep workflow state, but shared node/system state belongs below them in runtime.

### UI

The UI layer starts workflows and renders canonical state. It includes:

- workspace pages
- dialogs and popups
- the workspace shell
- the still-active embedded legacy runtime surface

UI should consume runtime-backed data and controller outputs. It should not become a second protocol layer.

## Ownership Model

### Single Source of Truth

Runtime-backed state is the authoritative view for shared robot state. Firmware, interrupts, node connectivity, and motor-current data should not be re-owned by each page that renders them.

### Canonical Ownership

When a responsibility already has a clear owner, new changes should extend that owner instead of creating a second implementation. This applies especially to:

- binary command builders and parsers
- parameter pipelines
- workbook serialization
- runtime state updates
- bridge-facing runtime access

### Avoiding Duplicate Implementations

The repository still contains some legacy code paths because the application is in an incremental layered refactor, not a full rewrite. Even so, new work should reduce duplication rather than add to it. If a change introduces a second place that builds the same packet, stores the same state, or decides the same workflow rule, the ownership is probably wrong.

## Runtime, Bridge, and UI

`WorkspaceRuntimeBridge` is the page-facing access layer between the workspace UI and the active runtime surface. Its role is to:

- expose runtime-backed state to pages and dialogs
- provide page-friendly access to configuration and session data
- keep pages from reaching directly into mixed legacy runtime internals unless no cleaner owner exists yet

This keeps UI code focused on rendering and interaction while runtime and services remain the owners of shared data and protocol behavior.

## Controllers and Adapters

The split between adapters and controllers is deliberate:

- adapters decide whether a packet is relevant
- controllers decide what the workflow should do with that relevant packet

That separation reduces accidental coupling between unrelated robot traffic and active workflows.

## Protocol and Shared Builders

New command families should flow through the canonical protocol path:

```text
constants / command definitions
  ->
data/binary_cmd_builders.py
  ->
data/binary_cmd_parser.py
  ->
runtime handling and storage
  ->
WorkspaceRuntimeBridge
  ->
UI and workflow consumers
```

This keeps binary behavior discoverable and testable in one place.

## Current Architecture Status

Completed work:

- Runtime ownership
- Narrow workflow adapters
- Production parameter adapter
- Mechanical cleanup
- Workbook cleanup
- Motor Current plotting
- Firmware Integration Manual Binary mode
- Firmware Integration Manual Text core transport/controller path
- Firmware Integration Manual Text dialog
- Firmware Integration Automated Binary FIT core logic
- Firmware Integration Automated Binary FIT configuration and report dialogs
- Firmware Integration Automated Text FIT core logic
- Firmware Integration Automated Text FIT configuration and report dialogs
- Firmware Integration shared report model, HTML builder, and Reports / Export UI
- Firmware Integration complete canonical Text command catalog representation
- Firmware Integration complete canonical Binary command catalog representation

Current state:

- the layered ownership model is active and usable
- the legacy `main_window.py` shell still exists beside the newer workspace shell
- runtime-backed UI rendering is established for shared state such as interrupts and motor current
- Manual Text protocol construction remains canonical in the protocol layer, and Manual Text UI now renders controller-owned state through a dialog
- `FirmwareIntegrationController` remains the single public Firmware Integration owner; any mode-specific workflow helpers are private implementation details under that controller boundary
- `FirmwareCommandDefinition` remains reusable command metadata, while `FirmwareTestCase` describes automated FIT case metadata and `FirmwareTestResult` is the shared per-case reporting contract for future export work
- Automated Binary FIT core sequencing now lives in a private `_BinaryFitWorkflow` under `FirmwareIntegrationController`; response-match, semantic-decode, no-response, reboot-recovery, logging-cleanup, timeout, and manual-verification transitions stay workflow-owned
- The complete legacy Binary command catalog is represented as controller-owned `FirmwareCommandDefinition` metadata and `FirmwareTestCase` metadata. The current catalog has 83 definitions/cases: 80 legacy entries plus the already-proven `NODECONFIG Query`, `INTERRUPT Query`, and `MOTOR_I Query` forms. Legacy FIT behavior is the Binary FIT functional acceptance contract: documented commands remain executable when request framing and response opcode are known, semantic decoding enhances verification where available, manual-verification commands still send and pause for operator confirmation, logging commands execute start/stop cleanup, reboot/no-response commands use explicit lifecycle policies, and only `CONTRACT_UNKNOWN` remains non-sending.
- Binary FIT configuration and report dialogs are UI-only and render controller-owned state through one read-only snapshot contract rather than owning sequencing, timeout, parameter validation, cleanup policy, or result truth
- Automated Text FIT core sequencing now lives in a private `_TextFitWorkflow` under `FirmwareIntegrationController`; policy-specific Text execution and cleanup remain workflow-owned, not UI-owned
- The complete legacy Text command catalog is represented as controller-owned `FirmwareCommandDefinition` metadata and `FirmwareTestCase` metadata; commands still requiring hardware validation remain visible through policy/unsupported metadata rather than being silently omitted
- Text FIT configuration and report dialogs are UI-only and render controller-owned state through one read-only snapshot contract rather than owning sequencing, timeout, or result truth
- The legacy Firmware Integration Test UI is the layout and workflow specification for the refactored Firmware Integration module: main actions, Manual Binary/Text command rows, Binary/Text FIT configuration dialogs, Binary/Text live report dialogs, table columns, and operator flow should match the legacy surface while using the BioBot orange theme. The legacy widget remains reference-only and is not imported or instantiated.
- `FirmwareFitReport` is the shared run-level reporting contract assembled from completed Binary/Text FIT results, and `FirmwareReportBuilder` owns pure in-memory HTML generation using the legacy report information hierarchy with BioBot orange styling
- Reports / Export is a shared UI-only dialog for selecting the latest completed Binary/Text FIT report and invoking the export service; Binary/Text live report dialogs may expose the legacy Export button but delegate HTML generation and filesystem writing to `FirmwareReportBuilder` and `FirmwareReportExportService`. `FirmwareReportExportService` owns HTML file writing, filename collision handling, and last-folder persistence through `QSettings("Biobot", "RobotArmTester")` key `report_save_location`.
- PDF/CSV export, report history, and final hardware validation remain future work

Remaining work is primarily additive rather than structural:

- additional diagnostic plots
- Binary/Text hardware validation
- FIT PDF/CSV export and report history if those become product requirements
- UI polish
- documentation refinement
- future workflow and product features

## Reference

Use [CANONICAL_PIPELINE_REGISTRY.md](CANONICAL_PIPELINE_REGISTRY.md) when you need the exact current owner of a responsibility or the deferred items that still exist in the repository.
