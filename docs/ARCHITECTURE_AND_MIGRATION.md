# Architecture And Migration

This document is the lean migration contract for the current codebase. It is not a rewrite plan. It exists to keep ownership clear while `main_window.py` remains active during staged replacement work.

## A. Current known architecture risks

- Raw packet fan-out:
  - `MainWindow.packet_received` is emitted before shared runtime handling runs.
  - Multiple pages and controllers subscribe directly to raw packet traffic.
- Duplicated packet decoding:
  - Semantic decoding exists in shared helpers, but several controllers/pages decode the same packet classes again locally.
- Page-local protocol/runtime state:
  - Some pages keep local sensor, interrupt, parameter, or node-config caches instead of rendering one canonical shared state.
- Controller exposure to unrelated traffic:
  - Workflow controllers can still see unrelated packets from the shared runtime stream and may fail or ignore traffic based on local expectations.
- Legacy `main_window.py` ownership:
  - `main_window.py` still owns important runtime behavior, state updates, and packet distribution while newer services and workspace pages coexist beside it.
- Duplicate node discovery/info behavior:
  - Node connectivity and follow-up info requests are triggered from more than one legacy path.
- Known parameter-path duplication:
  - A shared parameter pipeline exists, but legacy UUID-only and PWM-only flows still coexist beside it.

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
  - this phase adds a narrow Sampling adapter only; it is not yet a general request router
- Tests and live validation required:
  - wrong-node, runtime-only, and stale same-node packets must not fail or advance Sampling
  - expected Sampling packets must still advance the workflow
  - live validation must confirm runtime status/firmware/emergency updates continue while Sampling runs

## E. Governing rule

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
