# Canonical Pipeline Registry

This registry is the technical source of truth for canonical ownership in the current repository. It records what is canonical today, where legacy or duplicate paths still exist, and what conditions apply before older paths are removed.

For the higher-level design and rationale, see [ARCHITECTURE.md](ARCHITECTURE.md).

| Responsibility | Canonical owner / pipeline today | Known duplicate or legacy path | Notes / deferred items |
|---|---|---|---|
| shared motion command builders (`RUN` / `TPOS` / `GETPOS` / `HUNTING` / `STOPMOTOR`) | `data/binary_cmd_builders.py` | page/controller-local duplicates should not be added | All shared motion command families should build payloads here. |
| motor-current query payload (`0xCF` / `MOTOR_I`) | `data/binary_cmd_builders.py::build_motor_current_query_payload()` | no page/controller-local builder is canonical | Live plot polling exists today and should continue to reuse the shared builder. |
| frame parsing | `serial_conn/packet_parser.py` | some local decode logic still exists above parser level | Raw UART/CAN-over-UART framing should be parsed here. |
| semantic command decoding | `data/binary_cmd_parser.py` | some packet-specific local decode logic still exists in higher layers | Semantic decode belongs here, with packet-specific helpers kept in the protocol layer. |
| runtime node and system state | `services/runtime_packet_handler.py` plus `services/node_status_store.py`, updating shared runtime state on the active runtime window | narrow raw UI invalidation listeners still exist while legacy runtime code remains active | Runtime is the single source of truth for shared node/system status. |
| firmware and version state | `services/runtime_packet_handler.py` writing per-node firmware into `node_status` and MCU firmware into runtime system state | legacy rendering still exists in `main_window.py` while migration continues | Callers should read runtime-owned firmware/version state rather than keeping private caches. |
| interrupt state | `services/runtime_packet_handler.py` plus shared runtime `node_status` | Mechanical and Single Axis still use narrow refresh listeners for UI timing only | Interrupt truth is runtime-owned; pages render through the bridge. |
| motor-current runtime state | `services/runtime_packet_handler.py` plus `services/node_status_store.py`; `WorkspaceRuntimeBridge` is the canonical read path | `gui/workspace/dialogs/motor_current_plot_dialog.py` owns polling/timer lifecycle only | Current truth and bounded sample series remain runtime-owned. |
| node discovery | burst CAN scan in `MainWindow.dispatch_node_scan_batch(...)` plus `services/node_discovery_coordinator.py` for cycle state and deduplication | burst lifecycle timing and event-loop integration still live in `main_window.py` | Sequential scan paths are gone; any future discovery change should reuse the burst path and coordinator. |
| Production parameter programming | `gui/workspace/pages/production_parameter_controller.py` shared `ParameterDefinition` / `ParameterRequest` pipeline | Mechanical still keeps local orchestration on top of shared definitions; Production test-profile UUID verification remains specialized | Canonical owner for parameter verify/write/read-back and EEPROM sequencing in Production programming flows. |
| UUID parameter programming | Production workbook actions through `ProductionParameterController` shared parameter pipeline | runtime UUID inventory reads and Production test-profile UUID verification are separate non-programming behaviors | Extend the shared parameter pipeline for new UUID programming behavior. |
| PWM parameter programming | Production workbook actions through `ProductionParameterController` shared parameter pipeline | Mechanical keeps a separate PWM utility workflow on top of shared definitions | Production programming should continue through the shared pipeline. |
| PID / Ramp parameter definitions | `ProductionParameterController` parameter definitions reused by Mechanical | Mechanical still owns page-local orchestration | Shared definitions are canonical; separate utility initiation remains page-owned for now. |
| EEPROM save / settle behavior | shared `ProductionParameterController` EEPROM save logic | Mechanical keeps page-local gating around persistent writes | EEPROM save behavior should converge on one shared save/settle path. |
| Production workbook parameter result serialization | `services/ipqc_excel_adapter.py::write_programming_parameter_result(...)` | no UUID/PWM-specific workbook helper path remains canonical | Production workbook reporting belongs in the Excel adapter. |
| Sampling workbook serialization | `services/ipqc_excel_adapter.py::write_sampling_result(...)` and `clear_sampling_results(...)` | workbook aggregate formulas remain template-owned | Sampling controllers should serialize results only through the Excel adapter. |
| shared motion measurement primitives | `services/motion_measurements.py` | workflow-specific sequencing remains controller-owned | Outward range, return range, return error, midpoint target, and safe park target are canonical here. |
| NODECONFIG motion polarity interpretation | `services/node_motion_polarity.py`, surfaced to UI/workflows through `WorkspaceRuntimeBridge` | page-local mapping tables are not canonical | Shared polarity interpretation should be extended here, not reinvented per page. |
| workspace bridge APIs | `gui/workspace/bridges/workspace_runtime_bridge.py` | legacy direct runtime access still exists in older UI paths | The bridge is the page-facing owner for runtime-backed reads, config-editor access, and workspace session actions. |
| UI runtime rendering | `WorkspaceRuntimeBridge` as the canonical UI access layer | Mechanical and Single Axis still use narrow raw packet listeners only to schedule refresh after runtime updates; Sampling LED rendering remains deferred | Pages should render canonical runtime state rather than storing duplicate runtime truth. |
| Single Axis workflow ingress | `services/functional_transport_adapter.py` | same-node same-command ambiguity still exists where the protocol has no request ID | The adapter owns relevance filtering only. |
| Single Axis workflow state | `gui/workspace/controllers/single_axis_functional_test_controller.py` | none canonical beyond popup/operator-visibility helpers | Sequencing, tolerance, timeout, and pass/fail logic stay controller-owned. |
| Single Axis interrupt UI | `gui/workspace/pages/single_axis_functional_popup.py` reading runtime interrupt state through `WorkspaceRuntimeBridge` | popup release-watch is visibility-only and does not own sensor truth | Popup LEDs render canonical runtime state. |
| Sampling workflow ingress | `services/sampling_transport_adapter.py` | not yet a general request router | The adapter owns relevance filtering only. |
| Sampling workflow state | `gui/workspace/controllers/sampling_test_controller.py` | none canonical | Sampling timing, speed, result emission, and workbook progression remain controller-owned. |
| Production test workflow ingress | `services/production_test_transport_adapter.py` | same-node same-command ambiguity remains limited by protocol shape | Relevance filtering belongs to the adapter. |
| Production test workflow state | `gui/workspace/pages/production_test_controller.py` | none canonical | Timeout, sequencing, decode/validation, and pass/fail logic remain controller-owned. |
| Production parameter operation ingress | `services/production_parameter_transport_adapter.py` | no broader general router is canonical | Filtering stays narrow and parameter-operation-specific. |
| Firmware Integration workflow state | `gui/workspace/controllers/firmware_integration_controller.py` | no legacy widget path is canonical on the workspace shell | The single public FIT controller owns Manual Binary and Manual Text pending state, timeout, latency, response matching, cancellation, and UI-facing status/result emission. |
| Firmware Integration Automated Binary FIT sequencing | private `_BinaryFitWorkflow` inside `gui/workspace/controllers/firmware_integration_controller.py` | no UI-owned sequencing or page-local FIT runner is canonical | The workflow owns selected cases, one-at-a-time progression, timeout/error/manual-verification transitions, and `FirmwareTestResult` creation, while `FirmwareIntegrationController` remains the only public owner and active-operation facade. |
| Firmware Integration Automated Binary FIT UI snapshot | `FirmwareIntegrationController.binary_fit_status_snapshot()` returning `FirmwareBinaryFitSnapshot` | no dialog-local mutable workflow cache is canonical | The snapshot is the read-only UI render contract for Binary FIT progress, current case, manual-verification prompt state, and accumulated results. |
| Firmware Integration Automated Text FIT sequencing | private `_TextFitWorkflow` inside `gui/workspace/controllers/firmware_integration_controller.py` | no UI-owned sequencing or page-local FIT runner is canonical | The workflow owns selected cases, one-at-a-time progression, timeout/error/manual-verification transitions, and `FirmwareTestResult` creation, while `FirmwareIntegrationController` remains the only public owner and active-operation facade. |
| Firmware Integration Automated Text FIT UI snapshot | `FirmwareIntegrationController.text_fit_status_snapshot()` returning `FirmwareTextFitSnapshot` | no dialog-local mutable workflow cache is canonical | The snapshot is the future read-only UI render contract for Text FIT progress, current case, manual-verification prompt state, and accumulated results. |
| Firmware Integration workflow ingress | `services/firmware_transport_adapter.py` | no page-level packet subscription is canonical | The adapter owns Manual Binary CAN-over-UART filtering and Manual Text direct-UART filtering and forwarding only; it does not own timeout, latency, or pending request state. |
| Firmware Integration text packet construction | `data/text_cmd_builders.py` | no page/controller/dialog-local text framing is canonical | Manual Text command normalization, ASCII encoding, AMX framing, checksum, and direct-UART ASCII response decode live in the protocol layer. |
| Firmware Integration command metadata | `gui/workspace/models/firmware_command_definition.py` | legacy FIT tables are reference-only and not canonical in the refactored shell | The lightweight model now backs the initial Manual Binary subset and the initial Manual Text subset only; no broad legacy command registry is canonical yet. |
| Firmware Integration automated test case/result metadata | `gui/workspace/models/firmware_test_case.py` | legacy FIT case tables are reference-only and not canonical in the refactored shell | `FirmwareTestCase` and `FirmwareTestResult` are data-only models for future automated FIT workflows. They are distinct from reusable `FirmwareCommandDefinition` command metadata. |
| Firmware Integration Manual Text UI | `gui/workspace/dialogs/manual_text_command_dialog.py` | no page-local or protocol-local dialog logic is canonical | The dialog owns user input collection, definition-driven rendering, and local visual history only. It does not own packet building, backend access, timeout, latency, or response matching. |
| Firmware Integration Automated Binary FIT configuration UI | `gui/workspace/dialogs/binary_fit_config_dialog.py` | no controller-owned case-selection widget is canonical | The config dialog owns node/case selection only. It does not own sequencing, timeout, pass/fail logic, or backend access. |
| Firmware Integration Automated Binary FIT report UI | `gui/workspace/dialogs/binary_fit_report_dialog.py` | no workflow-owned report widget is canonical | The report dialog renders controller signals and the read-only Binary FIT snapshot, including manual-verification prompt delegation. It does not own sequencing, result truth, export, or save-location behavior. |
| Firmware Integration Automated Text FIT configuration UI | `gui/workspace/dialogs/text_fit_config_dialog.py` | no controller-owned case-selection widget is canonical | The config dialog owns case selection only. It does not own sequencing, timeout, prefix matching, pass/fail logic, or backend access. |
| Firmware Integration Automated Text FIT report UI | `gui/workspace/dialogs/text_fit_report_dialog.py` | no workflow-owned report widget is canonical | The report dialog renders controller signals and the read-only Text FIT snapshot, including manual-verification prompt delegation. It does not own sequencing, result truth, export, or save-location behavior. |
| Mechanical diagnostics and utility orchestration | `gui/workspace/pages/mechanical_page.py` | narrow raw packet listener remains as a runtime-backed UI invalidation workaround | Mechanical page owns utility initiation and display-local results, while shared state stays below it. |
| interrupt release-watch polling | `services/release_watch_helper.py` | workflows could still add ad hoc polling if they bypass the helper | Bounded `0xD8` polling is helper-owned and workflow-opt-in only; runtime remains the interrupt-state owner. |
| diagnostic plot launch wiring | `gui/workspace/pages/application_production_page.py` (`PlotsPage`) | future plots are placeholders only | The page launches plot tools; it does not own runtime current truth. |
| communication log storage and formatting | `services/communication_log_store.py` | UI consumers should not become alternate log owners | Shared communication history, formatting, export text, and display filtering belong here. |

## Deferred Items

The following items are still intentionally deferred or only partially consolidated:

- remaining legacy `main_window.py` lifecycle responsibilities
- Sampling popup runtime-backed L/R LED display
- optional cleanup of narrow raw UI invalidators if a post-runtime notification path becomes worth the churn
- additional diagnostic plots beyond Motor Current
- workbook-template validation and hardening work that requires live confirmation
- any future routing work that would replace narrow adapters with a broader request router

## Registry Usage

When changing behavior:

1. identify the responsibility you are touching
2. confirm the current canonical owner here
3. extend that owner instead of creating a parallel implementation
4. update this registry if canonical ownership changes
