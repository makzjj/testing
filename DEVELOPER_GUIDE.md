# IPQC Developer Guide

This guide is the developer-facing entry point for setting up the repository, running tests, building releases, and extending the codebase without fighting the ownership model.

## Project Setup

### Clone the Repository

Use the repository remote for your environment:

```powershell
git clone <repo-url>
cd testing
```

If your checkout directory name is different, adjust the `cd` command accordingly.

### Create a Virtual Environment

From the repository root:

```powershell
python -m venv .venv
```

PowerShell activation:

```powershell
.\.venv\Scripts\Activate.ps1
```

Command Prompt activation:

```cmd
.\.venv\Scripts\activate.bat
```

### Install Dependencies

Runtime dependencies:

```powershell
pip install -r requirements.txt
```

Build and test tooling:

```powershell
pip install -r requirements-build.txt
```

Current tracked dependencies include:

- application runtime packages in `requirements.txt`
- PyInstaller and pytest in `requirements-build.txt`

### Run the Application

```powershell
python main.py
```

Expected startup behavior:

- runtime directories are prepared automatically
- the project selector window opens
- available project YAML files are listed
- no hardware connection is started automatically

## Testing

Run the full suite:

```powershell
python -m pytest
```

Important targeted suites:

```powershell
python -m pytest tests/test_backend_runtime_services.py tests/test_workspace_runtime_bridge.py tests/test_workspace_session_panel.py
python -m pytest tests/test_sampling_controller.py tests/test_single_axis_functional_controller.py tests/test_single_axis_transport_integration.py
python -m pytest tests/test_production_test_controller.py tests/test_mechanical_page.py tests/test_motor_current_plot_dialog.py
python -m pytest tests/test_ipqc_excel_adapter.py tests/test_config_services.py tests/test_config_end_to_end.py tests/test_project_loader.py
python -m pytest tests/test_binary_command_helpers.py tests/test_serial_packet_parser.py tests/test_tpos_decoder.py
```

Known intentional Production test note:

- broader documented regression commands intentionally exclude `test_production_page_robot_power_button_order_and_connection_state`
- use this when following those commands:

```powershell
python -m pytest tests/test_production_test_controller.py -k "not test_production_page_robot_power_button_order_and_connection_state" -q
```

## Building

Windows build and deployment instructions live in [DEPLOYMENT_WINDOWS.md](DEPLOYMENT_WINDOWS.md).

Current build command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

Expected build output:

```text
dist/IPQC/
```

Do not duplicate deployment steps here; keep them in the deployment document.

## Development Workflow

Recommended flow:

1. Understand ownership.
2. Implement the feature or fix in the canonical owner.
3. Add or update tests.
4. Run targeted regression and then broader regression as needed.
5. Update documentation.

Before changing architecture-sensitive behavior, read:

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [CANONICAL_PIPELINE_REGISTRY.md](CANONICAL_PIPELINE_REGISTRY.md)

## Adding a New Binary Command

Use the canonical path:

```text
constants / command definition
  ->
data/binary_cmd_builders.py
  ->
data/binary_cmd_parser.py
  ->
RuntimePacketHandler
  ->
NodeStatusStore
  ->
WorkspaceRuntimeBridge
  ->
UI
  ->
Tests
  ->
Architecture docs
```

Practical checklist:

1. add or confirm the command definition and identifiers
2. add or extend the builder in `data/binary_cmd_builders.py`
3. add or extend semantic decode in `data/binary_cmd_parser.py`
4. update `services/runtime_packet_handler.py` if the command changes shared runtime state
5. update `services/node_status_store.py` if runtime storage changes
6. expose the new runtime-backed data through `WorkspaceRuntimeBridge` if UI needs it
7. update the relevant page, dialog, or controller consumer
8. add regression tests
9. update [ARCHITECTURE.md](ARCHITECTURE.md) and [CANONICAL_PIPELINE_REGISTRY.md](CANONICAL_PIPELINE_REGISTRY.md) if ownership changed

## Adding a New Feature

Start by identifying what kind of feature it is.

### Diagnostic Plot

- query payloads belong in `data/binary_cmd_builders.py`
- shared live data belongs in runtime if more than one consumer can need it
- plot-launch wiring belongs in the Plots page
- popup polling/timer lifecycle belongs in the dialog, not in runtime truth

### Parameter Feature

- Production parameter programming belongs in `ProductionParameterController`
- shared parameter definitions should be reused instead of copied
- workbook result writing belongs in `IpqcExcelAdapter`

### Workflow Feature

- packet filtering belongs in the workflow adapter
- workflow state belongs in the controller
- shared node/system state belongs in runtime
- Firmware Integration Test uses one public controller owner: `FirmwareIntegrationController`
- mode-specific Firmware Integration workflow helpers may exist only as private implementation details under `FirmwareIntegrationController`
- Firmware Integration packet ingress belongs in `services/firmware_transport_adapter.py`
- Manual Binary dialog is UI-only and should not build packets, parse packets, or access the backend directly
- Manual Text dialog is UI-only and should not build packets, parse packets, or access the backend directly
- Automated Binary FIT core sequencing lives in a private `_BinaryFitWorkflow`; Config UI, Report UI, Export, Save Location, and Automated Text FIT are still future work
- Binary FIT Configuration and Report dialogs are UI-only and should render `FirmwareIntegrationController.binary_fit_status_snapshot()` plus controller signals rather than reaching into workflow internals
- Automated Text FIT core sequencing lives in a private `_TextFitWorkflow`; Export and Save Location are still future work
- Text FIT Config and Report dialogs are UI-only and should render `FirmwareIntegrationController.text_fit_status_snapshot()` plus controller signals rather than reaching into workflow internals
- `WorkspaceRuntimeBridge` owns the Firmware Integration send boundaries for Manual Binary and Manual Text
- command builders and parsers for Manual Binary remain canonical in `data/binary_cmd_builders.py` and `data/binary_cmd_parser.py`
- Manual Text framing and direct-UART ASCII decode remain canonical in `data/text_cmd_builders.py`
- `FirmwareCommandDefinition` describes reusable commands, while `FirmwareTestCase` / `FirmwareTestResult` describe future automated FIT instances and outcomes

### Protocol Command

- builders and semantic decoders belong in the protocol layer
- avoid page-local binary encoding or decoding

## Development Principles

- One responsibility.
- One owner.
- Runtime owns shared state.
- UI renders runtime-backed state.
- Controllers own workflows.
- Adapters own filtering.
- Avoid duplicate implementations.
- Prefer extending existing canonical layers over adding side paths.
- Add regression tests for new behavior.
- Keep documentation aligned with ownership changes.

## Advice for Future Engineers

- Always confirm the canonical owner before editing code.
- Reuse existing builders, parsers, bridge APIs, and workbook helpers where possible.
- If a change seems to require a second copy of logic, stop and re-check ownership.
- Update tests before merging architecture-sensitive behavior.
- Update the docs whenever canonical ownership changes.
- Avoid parallel implementations, especially around binary commands, runtime state, and workbook handling.
