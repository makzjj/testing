# Architecture And Migration

This document is the lean migration contract for the current codebase. It is not a rewrite plan. It exists to keep ownership clear while `main_window.py` remains active during staged replacement work.

## A. Current known architecture risks

- Raw packet fan-out:
  - `MainWindow.packet_received` is emitted before shared runtime handling runs.
  - Direct raw subscribers are now narrow rather than broad:
    - `ProductionParameterTransportAdapter` now owns parameter-operation relevance filtering
    - Mechanical page and Single Axis popup still use raw packet listeners only as runtime-backed UI invalidation timing workarounds
    - canonical workflow ingress adapters exist for Sampling, Single Axis / Functional, Production Test, and Production Parameters
- Duplicated packet decoding:
  - Semantic decoding exists in shared helpers, but several controllers/pages decode the same packet classes again locally.
- Page-local protocol/runtime state:
  - Some pages keep local sensor, interrupt, parameter, or node-config caches instead of rendering one canonical shared state.
- Controller exposure to unrelated traffic:
  - This is materially reduced for Sampling, Single Axis, and Production Test after narrow ingress-adapter migration.
- Legacy `main_window.py` ownership:
  - `main_window.py` still owns the central packet signal, runtime-handler bridge, and remaining legacy runtime-shell behavior while newer services and workspace pages coexist beside it.
- Node discovery lifecycle still lives in the legacy shell:
  - duplicate `info_requested` state is gone, but burst scan lifecycle/timer orchestration still remains in `main_window.py`.
- Known parameter-path duplication:
  - `ProductionParameterController` still owns parameter pending-operation state, but packet filtering now sits in a narrow ingress adapter instead of a direct raw subscription.

## B. Target ownership model

Protocol
-> frame parsing and semantic decoding only

Runtime state
-> shared per-node/system state and unsolicited events

Request/operation routing
-> only matching packets reach active workflows

Controllers
-> workflow state only

UI/pages
-> start operations and render canonical state only

## C. MainWindow migration rule

- `main_window.py` remains active during migration.
- No responsibility is removed until a replacement owner exists, tests pass, callers migrate, and live validation passes where hardware behavior matters.

## D. Short migration order

1. low-risk pilot responsibility
2. prove migration pattern
3. Sampling
4. Single Axis
5. unified parameter-pipeline migration
6. Mechanical utility ownership
7. remaining `main_window.py` responsibilities
8. Runtime tab removal after parity

## Pilot update

- Selected Phase 0B pilot:
  - firmware/version runtime state ownership
- Why this pilot:
  - lower risk than Sampling because it is passive status traffic, already uses shared semantic decode, and does not sit on motion timing or workflow timeouts
- Canonical owner before:
  - per-node firmware lived in shared `node_status`, but MCU firmware lived as a legacy `MainWindow.mcu_version` attribute and `CommMonitorDialog` kept its own node-version cache for reporting
- Canonical owner after:
  - runtime firmware/version state is owned by Runtime packet handling plus runtime state on `MainWindow`
  - per-node firmware is read from `node_status`
  - MCU firmware is read from one runtime-owned `runtime_system_state["mcu_version"]` slot exposed through `MainWindow.mcu_version`
- Legacy path removed/deprecated:
  - removed active `CommMonitorDialog.node_versions` state cache
  - retained `comm_monitor.handle_node_version(...)` only as a pre-test workflow signal, not a state owner
- Tests run:
  - `python -m pytest tests/test_backend_runtime_services.py tests/test_workspace_runtime_bridge.py tests/test_comm_monitor.py`
  - `python -m pytest tests/test_workspace_session_panel.py tests/test_single_axis_functional_controller.py tests/test_sampling_controller.py`
- Remaining deletion condition:
  - `main_window.py` still remains the legacy runtime shell
  - direct event delivery to `CommMonitorDialog.handle_node_version(...)` can be removed only after that pre-test workflow has a migrated request/response owner outside raw runtime callbacks

## Pilot update

- Selected Phase 0C pilot:
  - node discovery and node-info scheduling ownership
- Canonical owner before:
  - `main_window.py` owned node discovery, but node-info scheduling was split across `process_node_id_response(...)` and `update_node_activity(...)`
  - deduplication was split between `MainWindow.node_info_requested` and `node_status[node_id]["info_requested"]`
- Canonical owner after:
  - `services/node_discovery_coordinator.py` owns discovery-cycle identity/state, per-node deduplication, already-scheduled-this-cycle tracking, and reset policy
  - `MainWindow._schedule_node_info_requests_for_node(...)` is only the legacy integration adapter that receives runtime events, calls the coordinator, integrates with `QTimer`, and invokes the existing node-info command-burst sender
- Duplicate path removed/deactivated:
  - removed active `node_info_requested` scheduling set
  - removed active `node_status["info_requested"]` scheduling path
  - `process_node_id_response(...)` and `update_node_activity(...)` now both route through the same scheduler
- Deduplication policy:
  - schedule node info once per node per discovery cycle
  - clear transient pending state when the scheduled dispatch begins
  - reset the discovery cycle only on a new scan cycle or discovery teardown
- Tests run:
  - `python -m pytest tests/test_backend_runtime_services.py tests/test_workspace_runtime_bridge.py tests/test_workspace_session_panel.py`
  - `python -m pytest tests/test_comm_monitor.py tests/test_single_axis_functional_controller.py tests/test_sampling_controller.py`
- Remaining deletion condition:
  - `main_window.py` still owns the legacy scan lifecycle and timer orchestration
  - a full removal waits until scan lifecycle ownership itself is migrated out of `main_window.py` without changing UI behavior or controller access

## Pilot update

- Selected Phase 0D pilot:
  - obsolete sequential node-scan workflow removal
- Canonical owner before:
  - burst scan already existed in `MainWindow.dispatch_node_scan_batch(...)`
  - legacy sequential scan entry points still coexisted in `main_window.py`
  - startup and bridge scan hooks could still reach sequential paths
- Canonical owner after:
  - burst CAN scan is the sole canonical node-scan workflow
  - `MainWindow.start_communication()` now starts `dispatch_node_scan_batch()`
  - `WorkspaceRuntimeBridge.request_runtime_node_scan()` now calls only `dispatch_node_scan_batch()`
- Legacy path removed/deprecated:
  - removed sequential-only scan methods and their entry points
  - removed the sequential branch from `on_node_scan_timeout()`
- Remaining `MainWindow` responsibility:
  - receiving legacy runtime events
  - opening and closing the burst scan window
  - integrating the batch timeout timer with the event loop
  - invoking the existing node-info command-burst sender through the Phase 0C coordinator path
- Tests run:
  - `python -m pytest tests/test_workspace_session_panel.py tests/test_workspace_runtime_bridge.py`
  - `python -m pytest tests/test_backend_runtime_services.py tests/test_workspace_runtime_bridge.py tests/test_workspace_session_panel.py tests/test_comm_monitor.py tests/test_single_axis_functional_controller.py tests/test_sampling_controller.py`
- Live validation required:
  - confirm one burst scan starts on connect
  - confirm `Update Nodes` sends one `86 3F` burst with no sequential delay loop
  - confirm each responding node gets one node-info burst only
  - confirm disconnect during a burst leaves no stale active scan state

## Closeout update

- Selected closeout:
  - burst-scan lifecycle policy and tests
- Canonical owner remains:
  - `MainWindow` temporarily owns burst scan start/end, the Qt batch-window timer, disconnect teardown, and legacy runtime-event integration
  - no new lifecycle coordinator was introduced
- Burst-window versus runtime-connectivity semantics:
  - `detected_nodes` means nodes detected during the active `Update Nodes` batch window only
  - `node_status.connected` and node information remain broader runtime knowledge and persist until disconnect/reset
- Late-response policy:
  - after the burst window ends, late packets may still update runtime connectivity and runtime node information
  - late packets must not add nodes to `detected_nodes`
  - late packets must not trigger a new node-info request burst for the completed scan
  - completed scan LED results therefore remain frozen because the workspace UI renders `detected_nodes` for the current scan result
- `cancel_scanning` status:
  - removed
  - repo-wide search showed no active readers after sequential scan removal
- Tests run:
  - `python -m pytest tests/test_workspace_session_panel.py tests/test_workspace_runtime_bridge.py`
  - `python -m pytest tests/test_backend_runtime_services.py tests/test_workspace_runtime_bridge.py tests/test_workspace_session_panel.py tests/test_comm_monitor.py tests/test_single_axis_functional_controller.py tests/test_sampling_controller.py`

## Pilot update

- Selected Phase 1B pilot:
  - narrow Sampling workflow ingress adapter
- Canonical owner:
  - runtime layer still owns global/status packets and runtime state updates
  - `services/sampling_transport_adapter.py` owns Sampling relevance filtering on the shared packet bus
  - `SamplingTestController` owns Sampling workflow state only
- Existing path reused or replaced:
  - reused existing parsed packet bus and existing runtime handling
  - replaced direct Production-page raw packet subscription to `SamplingTestController.handle_runtime_packet(...)`
- Legacy path removed:
  - Production page no longer subscribes Sampling directly to raw global packet fan-out
- Remaining limitation:
  - `MainWindow.packet_received` still emits before runtime handling updates shared runtime state
  - this phase adds a narrow Sampling adapter only; it is not a general request router
- Tests and live validation required:
  - wrong-node, runtime-only, and stale same-node packets must not fail or advance Sampling
  - expected Sampling packets must still advance the workflow
  - live validation must confirm runtime status/firmware/emergency updates continue while Sampling runs

## Pilot update

- Selected Phase 1D pilot:
  - strengthen Single Axis workflow ingress by extending `FunctionalTransportAdapter`
- Canonical owner:
  - runtime layer still owns global/status packets and runtime state updates
  - `services/functional_transport_adapter.py` is the canonical Single Axis ingress owner
  - `SingleAxisFunctionalTestController` owns workflow state only
- Forwarding rule:
  - active node
  - semantic decoded kind
  - current Single Axis state/wait predicate
  - expected value where it is safely checkable, including RUN ACK velocity
- Existing path reused or replaced:
  - reused the existing `FunctionalTransportAdapter`
  - no new Single Axis adapter was created
- Legacy/duplicate path affected:
  - removed broad same-node forwarding of all parsed packets into Single Axis controller logic
- Remaining limitation:
  - protocol correlation is still limited where the same node can emit two identical same-command responses and no request ID/sequence token exists
  - this phase drops avoidable stale traffic but does not claim to solve identical same-node GETPOS ambiguity fully
- Tests and live validation required:
  - wrong-node, global/status, and stale same-node packets must not reach or advance Single Axis
  - genuine wrong-sensor and expected fault paths must still fail safely
  - live validation must confirm unrelated runtime traffic remains visible to runtime/global logging while Single Axis ignores it

## Pilot update

- Selected Phase 2B pilot:
  - live UUID and PWM caller migration onto the unified parameter pipeline
- Canonical owner:
  - `ProductionParameterController` plus `ParameterDefinition` plus generic `ParameterRequest` orchestration
  - Production workbook reporting continues through `IpqcExcelAdapter.write_programming_parameter_result(...)`
- Existing path reused or replaced:
  - reused the existing generic parameter pipeline already used by the Production workbook flow
  - no new parameter framework or registry was introduced
- Live caller migration completed:
  - Production page UUID and PWM actions now rely on the generic `build_parameter_request(...)`, `write_parameters(...)`, `verify_parameters(...)`, and generic workbook result handling only
  - centralized EEPROM decision remains unchanged: persistent writes first, one EEPROM save if needed, runtime-only PWM afterward
- Legacy path retained:
  - UUID/PWM wrapper APIs, legacy timers, compatibility signals, and UUID CSV helpers remain active for compatibility and test coverage
  - they are not yet removed in this phase
- Intentionally untouched:
  - runtime node-info UUID inventory reads
  - Mechanical PWM utility orchestration and EEPROM gating
  - Production test-profile UUID verification flow
- Deletion condition:
  - no live callers remain
  - focused UUID/PWM and workbook regression tests pass
  - EEPROM behavior is validated live before deleting the legacy UUID/PWM wrapper internals

## Pilot update

- Selected Phase 2C pilot:
  - remove obsolete UUID/PWM legacy wrapper paths from the parameter controller
- Canonical parameter owner:
  - `ProductionParameterController` plus `ParameterDefinition` plus generic `ParameterRequest` orchestration
  - generic read/write/read-back remains `build_parameter_request(...)`, `write_parameters(...)`, `verify_parameters(...)`, and `save_parameters_to_eeprom(...)`
- Removed:
  - legacy UUID/PWM wrapper pipeline components in `ProductionParameterController` that had no active callers
  - UUID/PWM-specific wrapper methods, wrapper timers, wrapper signals, CSV-row state, wrapper packet handlers, and wrapper helper loops
  - Production-page UUID/PWM workbook compatibility wrappers
- Retained:
  - UUID/PWM command-family builders and decoders because `ParameterDefinition` still uses them
  - runtime node-info UUID inventory reads in `main_window.py`, owned by runtime inventory behavior
  - Production test-profile UUID verification, retained as a specialized test-profile path rather than a parameter-programming path
  - Mechanical PWM/PID/Ramp orchestration, retained as separate workflow ownership
- UUID CSV outcome:
  - removed with the wrapper pipeline because no live UI caller or supported Production workflow depended on it
- Workbook helper outcome:
  - canonical Production workbook path remains `IpqcExcelAdapter.write_programming_parameter_result(...)`
  - UUID/PWM-specific workbook helper wrappers were removed after live callers were proven absent
- Remaining deletion condition:
  - none for the removed wrapper pipeline
  - any later Mechanical parameter migration or test-profile UUID migration must be handled as separate responsibilities

## Pilot update

- Selected Phase 3B pilot:
  - normalize shared motion measurement primitives only
- Canonical shared measurement primitives:
  - outward endpoint range
  - return endpoint range
  - return error
  - midpoint target
  - `Z` / `PZ` safe park target

## Pilot update

- Selected Phase LED-0A pilot:
  - runtime interrupt-state ownership
- Canonical owner:
  - `services/runtime_packet_handler.py` updates per-node interrupt state inside shared runtime `node_status`
  - workspace pages read interrupt state through `WorkspaceRuntimeBridge`
- Runtime interrupt-state coverage in this phase:
  - `0x81` decoded `Z/L` and `Z/R` events mark the sender node sensor as cut
  - `0xD8` interrupt responses update canonical `INT0`, `INT1`, and left/right cut state
- Mechanical outcome:
  - Mechanical page no longer owns canonical interrupt LED state
  - Mechanical sensor LEDs render runtime-owned interrupt state only
  - Mechanical utility reads and writes remain page-owned
- Single Axis outcome after later LED phases:
  - Single Axis popup LEDs also render runtime-owned interrupt state only
- Explicitly not added in this phase:
  - no global `0xD8` polling
  - no release-watch polling workflow
  - no general runtime request router
- Tests run:
  - `python -m pytest tests/test_backend_runtime_services.py tests/test_workspace_runtime_bridge.py tests/test_mechanical_page.py -q`
  - `python -m pytest tests/test_sampling_controller.py tests/test_single_axis_functional_controller.py tests/test_production_test_controller.py tests/test_comm_monitor.py -k "not test_production_page_robot_power_button_order_and_connection_state" -q`
- Remaining limitation:
  - bounded `0xD8` release-watch polling is still unimplemented and must remain workflow-owned when introduced later

## Pilot update

- Selected Phase LED-0B pilot:
  - shared bounded interrupt release-watch helper
- Canonical owner:
  - `services/runtime_packet_handler.py` remains the canonical owner of per-node interrupt state
  - `services/release_watch_helper.py` owns bounded `0xD8` polling only when a workflow explicitly opts in
- Helper scope in this phase:
  - starts an optional release-watch for one node and one expected sensor
  - sends one immediate `0xD8 0x3F` query, then bounded repeat queries on a fixed interval until release, timeout, disconnect, or caller stop
  - observes release through runtime-owned interrupt state exposed by `WorkspaceRuntimeBridge`
- Explicitly not added in this phase:
  - no global `0xD8` polling
  - no runtime-owned polling loop
  - no workflow auto-integration
  - no general runtime request router
- Workflow ownership outcome:
  - Mechanical, Single Axis, and Sampling remain unchanged in this phase
  - future workflows may opt into the helper individually without moving interrupt ownership out of runtime state
- Tests run:
  - `python -m pytest tests/test_backend_runtime_services.py -q`
  - `python -m pytest tests/test_workspace_runtime_bridge.py tests/test_sampling_controller.py tests/test_single_axis_functional_controller.py tests/test_mechanical_page.py tests/test_comm_monitor.py -q`
  - `python -m pytest tests/test_production_test_controller.py -k "not test_production_page_robot_power_button_order_and_connection_state" -q`
- Remaining limitation:
  - no workflow currently starts release-watch automatically
  - release-watch cancellation on workflow abort/completion/node-change must be wired by each workflow when it explicitly adopts the helper

## Pilot update

- Selected Phase LED-0C pilot:
  - Mechanical-only opt-in release-watch integration
- Canonical owners:
  - `services/runtime_packet_handler.py` remains the canonical owner of per-node interrupt state
  - `services/release_watch_helper.py` remains the only bounded `0xD8` polling owner
  - `gui/workspace/pages/mechanical_page.py` now decides whether one Mechanical movement should opt into release-watch
- Mechanical integration in this phase:
  - only popup `Run +` and `Run -` actions opt in
  - release-watch starts only after a live RUN send and only when movement is away from a currently cut runtime-known sensor
  - popup `Stop` and selected-node changes cancel any active Mechanical release-watch
- Explicitly unchanged:
  - no global `0xD8` polling
  - no runtime-owned polling loop
  - no Sampling release-watch
  - no Single Axis release-watch
  - no Production workflow change
  - no new packet-routing layer
- Tests run:
  - `python -m pytest tests/test_mechanical_page.py -q`
  - `python -m pytest tests/test_backend_runtime_services.py tests/test_workspace_runtime_bridge.py tests/test_sampling_controller.py tests/test_single_axis_functional_controller.py tests/test_comm_monitor.py -q`
  - `python -m pytest tests/test_production_test_controller.py -k "not test_production_page_robot_power_button_order_and_connection_state" -q`
- Remaining limitation:
  - Mechanical release-watch is limited to popup RUN direction where away-from-sensor mapping is explicit
  - popup Home, absolute move, and relative move remain unintegrated in this phase

## Pilot update

- Selected Phase LED-0C-Fix pilot:
  - NODECONFIG-aware Mechanical release-watch mapping
- Canonical owners remain:
  - `services/runtime_packet_handler.py` owns interrupt state
  - `services/release_watch_helper.py` owns bounded polling only
  - `WorkspaceRuntimeBridge` resolves canonical NODECONFIG/home-direction interpretation for callers
- Behavior change in this fix:
  - RUN command behavior is unchanged
  - Mechanical release-watch no longer assumes a fixed RUN-sign-to-sensor mapping
  - Mechanical now starts release-watch only when bridge-exposed NODECONFIG polarity confirms that the current RUN sign is moving away from the currently cut sensor
- Mapping source:
  - runtime `node_status[node_id]["nodeconfig"]` when available
  - otherwise current project config `node_config`
  - no node IDs or observed rig-specific NODECONFIG values are hardcoded
- Safety rule:
  - when NODECONFIG polarity is unknown, unsupported, or interrupt state is ambiguous, Mechanical still sends RUN normally and skips release-watch
- Explicitly unchanged:
  - no Sampling or Single Axis release-watch adoption
  - no global `0xD8` polling
  - no general router
  - no workbook or Production workflow change
- Tests run:
  - `python -m pytest tests/test_mechanical_page.py -q`
  - `python -m pytest tests/test_backend_runtime_services.py tests/test_workspace_runtime_bridge.py tests/test_sampling_controller.py tests/test_single_axis_functional_controller.py tests/test_comm_monitor.py -q`
  - `python -m pytest tests/test_production_test_controller.py -k "not test_production_page_robot_power_button_order_and_connection_state" -q`
- Existing path reused or replaced:
  - reused Single Axis and Sampling controllers as workflow owners
  - added one narrow pure-helper module for identical endpoint math only
- Single Axis owner after Phase 3B:
  - `SingleAxisFunctionalTestController` now stores an explicit verified home/reference position from the existing zero-verification `GETPOS`
  - it remains the owner of Single Axis sequencing, tolerance, and pass/fail lifecycle
- Sampling owner after Phase 3B:
  - `SamplingTestController` remains the owner of timing, speed, sample lifecycle, result emission, and workbook output
- Single Axis popup rule:
  - the measured `Range` field must remain controller-derived `Range 1` / `Range 2` data
  - middle-target preview may be logged separately, but must not overwrite the measured `Range` field
- Explicitly unchanged:
  - motion sequencing
  - timeout values
  - tolerances
  - safe-position policy
  - workbook templates
  - Sampling aggregate-statistics ownership
- Deferred:
  - Sampling aggregate statistics ownership
  - `2/4/8/16/32` formula-range and workbook-template audit

## Pilot update

- Selected Phase LED-0D pilot:
  - Single Axis popup runtime-backed interrupt LED migration
- Canonical owner unchanged:
  - `services/runtime_packet_handler.py` plus shared runtime node status own per-node interrupt state
  - `WorkspaceRuntimeBridge` remains the popup/runtime access path
  - `SingleAxisFunctionalTestController` remains the owner of Single Axis workflow state only
- Existing path reused or replaced:
  - reused the existing runtime interrupt state and bridge exposure already adopted by Mechanical
  - removed active controller-to-popup LED truth wiring from `SingleAxisFunctionalPopup`
- Single Axis popup behavior in this phase:
  - popup L/R LEDs now render from runtime interrupt state for the active/selected node
  - `0x81` cut events and `0xD8` interrupt responses update the popup only through runtime state refresh
  - no release-watch polling was added to Single Axis
- Explicitly unchanged:
  - Single Axis workflow sequencing
  - HUNTING / RUN / TPOS / GETPOS / STOPMOTOR behavior
  - timeout values
  - Sampling, Mechanical release-watch, and Production workflow behavior
- Tests run:
  - `python -m pytest tests/test_single_axis_functional_popup.py -q`
  - `python -m pytest tests/test_single_axis_transport_integration.py -q`
  - broader regression remains required before closeout

## Pilot update

- Selected Phase LED-0E pilot:
  - Single Axis popup opt-in release-watch for operator visibility only
- Canonical owners remain:
  - `services/runtime_packet_handler.py` plus shared runtime node status own interrupt state
  - `WorkspaceRuntimeBridge` exposes interrupt state and NODECONFIG-derived motion polarity
  - `services/release_watch_helper.py` owns bounded `0xD8` polling only
  - `SingleAxisFunctionalTestController` still owns workflow state, sequencing, and pass/fail logic only
- Single Axis behavior in this phase:
  - popup may start bounded release-watch after a movement command only when runtime interrupt state and shared polarity confirm the move is away from the currently cut sensor
  - release-watch exists only to keep runtime-backed popup LEDs fresh for operator visibility
  - release-watch timeout, release, cancel, or disconnect do not block, advance, fail, pass, or otherwise alter the Single Axis state machine
- Explicitly unchanged:
  - Single Axis workflow correctness and timeout policy
  - Mechanical release-watch behavior
  - Sampling behavior
  - no global `0xD8` polling
- Tests run:
  - `python -m pytest tests/test_single_axis_functional_popup.py -q`
  - `python -m pytest tests/test_single_axis_transport_integration.py -q`
  - broader regression remains required before closeout

## Cleanup update

- Selected Phase L2A.5 cleanup:
  - ProductionParameterController command-builder consolidation
- Canonical owner:
  - shared `RUN` / `TPOS` / `GETPOS` / `HUNTING` / `STOPMOTOR` builders remain in `data/binary_cmd_builders.py`
- What changed:
  - removed duplicate local generic motion-command builder definitions from `ProductionParameterController`
  - Production parameter sequencing and workbook behavior stayed unchanged
- Explicitly unchanged:
  - Production parameter workflow logic
  - Production test workflow logic
  - runtime ownership
  - packet routing and ingress structure

## Cleanup update

- Selected Phase L2B cleanup:
  - narrow ProductionTestController ingress adapter
- Canonical owners after this phase:
  - `services/production_test_transport_adapter.py` owns Production test relevance filtering only
  - `gui/workspace/pages/production_test_controller.py` still owns Production test workflow state, timeout, decode, and pass/fail logic
  - `gui/workspace/pages/production_parameter_controller.py` remains unchanged and still owns parameter pending-operation correlation
- What changed:
  - ProductionTestController no longer subscribes directly to raw packet fan-out
  - runtime packet ownership and ordering remain unchanged
- Explicitly unchanged:
  - Production parameter workflow behavior
  - workbook behavior
  - timeout values
  - no general router introduced

## Cleanup update

- Selected Phase L3C cleanup:
  - narrow ProductionParameterController ingress adapter
- Canonical owners after this phase:
  - `services/production_parameter_transport_adapter.py` owns Production parameter relevance filtering only
  - `gui/workspace/pages/production_parameter_controller.py` still owns parameter definitions, verify/write sequencing, EEPROM save sequencing, pending request state, timeout behavior, quiet-mode diagnostics, decode, and emitted signals
  - runtime packet ownership and ordering remain unchanged
- What changed:
  - `ProductionParameterController` no longer subscribes directly to raw `packet_received` fan-out
  - parameter verify/write/EEPROM behavior remains controller-owned
- Explicitly unchanged:
  - workbook behavior and workbook formulas
  - Production Test ingress adapter
  - no general router introduced

## Cleanup update

- Selected Phase L3A cleanup:
  - delete proven dead leftovers after ingress and runtime-LED migrations
- What changed:
  - removed dead `ProductionTestController._handle_runtime_packet(...)` wrapper after `ProductionTestTransportAdapter` became the Production Test ingress owner
  - removed dead Single Axis popup LED compatibility methods and unused middle-travel refresh helper after popup LED rendering became runtime-backed
  - removed stale `node_status["info_requested"]` field from default runtime node state
- Explicitly unchanged:
  - Sampling popup compatibility no-op methods
  - `serial_conn/app_protocol_handler.py`
  - workflow behavior, runtime ownership, and packet ordering

## F. Current deferred items

- Sampling popup runtime-backed L/R LED display remains deferred and optional
- Sampling save/export gating remains a workflow decision, not an active migration requirement
- Sampling duplicate workbook-label validation remains deferred hardening
- Sampling real workbook template validation remains a live-validation item
- `ProductionParameterController` ingress migration is complete; any future parameter-routing work would be optional narrowing only
- Mechanical visual polish remains optional
- Sampling popup compatibility no-op cleanup remains optional
- `serial_conn/app_protocol_handler.py` removal remains deferred until external/manual usage is ruled out
- a post-runtime packet-bus notification path is deferred unless replacing raw UI invalidators becomes worth the churn

## G. Governing rule

Every touched responsibility must end with fewer owners, fewer active paths, and a clear deletion plan.

## Future implementation report requirements

Architecture impact:
- Canonical owner:
- Existing path reused or replaced:
- Legacy/duplicate path affected:
- Migration or removal performed:
- Remaining migration work:
- Regression tests:
- Live validation required:
