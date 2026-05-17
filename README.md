# Biobot_Robot_Arm_Tester
This test software is a comprehensive serial communication application for testing BioBot robot arms. Here's main features:

## Key Components

- **Serial Communication Management**: Handles connection/disconnection to serial ports with automatic port refreshing
- **Robot Control Commands**: Implements various predefined commands for robot control and diagnostics
- **Target Nodes Monitoring (0xBF)**: Tracks per-node packet count and detects sequence gaps (loss).
- **MCU Support Monitoring (0xBC)**: Monitors MCU-level CAN RX (filtered for 0xBF frames) and UART TX statistics.
- **Auto-Stop**: The test automatically terminates when all target nodes report completion (via 0xBD notification).
- **Safety**: Automatically restores MCU periodic updates on exit or test stop.
- **Data Visualization**: Provides ADC to physical value mapping with real-time chart updates

## Main Functionalities

1. **Node Detection System**:
   - Automatically scans for connected nodes (2-13)
   - Maintains node status and response times
   - Visualizes node connectivity in a table format

2. **ZPOSS Sensor Handling**:
   - Decodes ZPOSS sensor data from raw ADC values
   - Provides real-time plotting of ADC vs physical values
   - Supports periodic data sending with configurable intervals

3. **MCU Version Management**:
   - Queries and displays MCU firmware version on connection
   - Parses version information from UART responses

28. **Data Visualization**:
   - Real-time scatter plot for ADC/physical value mapping
   - Dynamic plot updates during periodic data collection
   - Configurable plot window with start/stop controls

5. **Communication Data Monitor**:
   - **Real-time Health Monitoring**: Tracks per-node packet count and detects sequence gaps/frame loss using `0x BF` test frames.
   - **Pre-Test Sequential Validation**: Automatically verifies node readiness by querying firmware versions sequentially (50ms interval) before starting tests. Aborts safely if any node is unresponsive.
   - **MCU Hardware Statistics**: Monitors low-level MCU performance (CAN Rx, UART Tx/Rx) via `0xBC` polling.
   - **Auto-Stats Synchronization**: Automatically fetches terminal statistics upon manual stop or test completion for perfectly synchronized counts.
   - **Diagnostic Reporting**: Exports detailed Google Test (gTest) style reports including test conditions, node versions, and cumulative statistics.
   - **Path Failure Analysis**: Intelligent diagnostic logic distinguishes between **CAN Transmission** failure and **UART Communication** loss based on hardware vs. software counters.
   - **Configurable Stress Testing**: Supports customized node masks, frame counts, and intervals (ms) for performance profiling.

## Technical Implementation

- Uses `PyQt6` for GUI components and event handling
- Implements `matplotlib` for data visualization
- Employs `pyserial` for serial communication
- Features multithreading for periodic operations
- Includes comprehensive error handling and logging

The application serves as a diagnostic tool for BioBot robot arm systems, enabling developers to monitor, control, and troubleshoot the robotic system through serial communication.

## Create executable file from Python script
In Python project root directory from Terminal when using PyCharm IDE , run:
 [pyinstaller --noconfirm --onefile --windowed --name RobotArmTest --add-data "resources/biobot_logo.png;resources"  --icon=resources/biobot_robot_arm.ico main.py]()