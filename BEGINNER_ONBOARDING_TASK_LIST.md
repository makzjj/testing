# Beginner Onboarding Task List

## 1) Project entry and app flow
- [ ] Read `main.py` (`main()` startup).
- [ ] Read `gui/program_selector_window.py` (project selection to workspace).
- [ ] Read `gui/workspace/shell/project_workspace_window.py` (`_build_pages`, `set_active_page`).

## 2) Architecture in 3 layers
- [ ] UI pages: `gui/workspace/pages/`
- [ ] Bridge layer: `gui/workspace/bridges/workspace_runtime_bridge.py`
- [ ] Backend/services: `services/` + `serial_conn/`

## 3) First high-level functions
- [ ] `ProductionPage._handle_run_test()` (`production_page.py`)
- [ ] `ProductionTestController.run_test()` (`production_test_controller.py`)
- [ ] `ProductionTestController._handle_runtime_packet()` (`production_test_controller.py`)
- [ ] `ProductionParameterController.load_uuid_csv()` + `verify_loaded_uuid()` (`production_parameter_controller.py`)
- [ ] `ProductionCsvLogger.append_result()` (`services/production_csv_logger.py`)
- [ ] `MainWindow.read_serial_data()` (`gui/main_window.py`)
- [ ] `RuntimePacketHandler.handle_packet()` (`services/runtime_packet_handler.py`)

## 4) Features to learn in sequence
- [ ] Connection + serial port behavior (`refresh_ports`, `connect_serial`) in `gui/main_window.py`
- [ ] Node detection/status display (`main_window.py`, `production_page.py`)
- [ ] UUID CSV load/verify/write-readback (`production_parameter_controller.py`, `production_page.py`)
- [ ] Production profile engine basic + movement (`production_test_models.py`, `production_test_controller.py`)
- [ ] CSV result logging per step/profile (`production_page.py`, `production_csv_logger.py`)

## 5) Protocol and packet basics
- [ ] Outgoing command build: `serial_conn/commands.py`
- [ ] Incoming parse: `serial_conn/packet_parser.py`
- [ ] Command decoding: `data/binary_cmd_parser.py`
- [ ] Command table reference: `myconfig/constants.py`

## 6) Testing-first path
- [ ] Read `tests/test_production_test_controller.py`
- [ ] Read `tests/test_production_csv_logger.py`
- [ ] Read `tests/test_backend_runtime_services.py`
- [ ] Run tests: `scripts/test.sh`
- [ ] Run build check: `scripts/build.sh`

## 7) Practical first contribution tasks
- [ ] Add one small edge-case test in `test_production_test_controller.py`
- [ ] Trace one command end-to-end (UI click → send command → packet receive → decode → CSV row)
- [ ] Write personal architecture notes (no code change required)
- [ ] Identify one low-risk refactor candidate in Production page/controller

## 8) Postpone until later
- [ ] Deep refactor of `gui/main_window.py`
- [ ] Broad protocol changes in packet parser
- [ ] New module families (PWM/PID/QEI/HMI/Needle) before mastering current Production flow

## Day 1 / Day 2 / Day 3
- Day 1: sections 1-3
- Day 2: sections 4-5 + one end-to-end trace
- Day 3: section 6 + one small test-only contribution
