# gui/firmware_integration_test.py
"""Firmware Integration Test Widget, Dialogs, and Latency Monitoring."""

import time
import os
from PyQt6.QtWidgets import (
    QWidget, QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QCheckBox, QTextEdit, QDialog, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QSpinBox,
    QStackedWidget, QFileDialog, QCompleter, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, QDateTime, QSettings
from PyQt6.QtGui import QColor, QFont

from serial_conn.app_protocol_handler import AppProtocolHandler
from serial_conn.packet_parser import parse_uart_rx_packets
from utils.checksum import calc_checksum
from data.binary_cmd_parser import decode_command, parse_get_interrupt

# Comprehensive list of Section 6 Text-based Commands
ALL_TEXT_COMMANDS = [
    {"cmd": "uartstat?", "type": "query", "expected": "uartstat:", "default": ""},
    {"cmd": "opmode?", "type": "query", "expected": "opmode:", "default": ""},
    {"cmd": "opmode=", "type": "set", "expected": "opmode:", "default": "1"},
    {"cmd": "spimem?", "type": "query", "expected": "spimem:", "default": ""},
    {"cmd": "serialno?", "type": "query", "expected": "serialno:", "default": ""},
    {"cmd": "serialno=", "type": "set", "expected": "serialno:", "default": "SN1002"},
    {"cmd": "product?", "type": "query", "expected": "product:", "default": ""},
    {"cmd": "product=", "type": "set", "expected": "product:", "default": "MonaLisa2.0"},
    {"cmd": "mfgdate?", "type": "query", "expected": "mfgdate:", "default": ""},
    {"cmd": "mfgdate=", "type": "set", "expected": "mfgdate:", "default": "20260520"},
    {"cmd": "HWI?", "type": "query", "expected": "HWI:", "default": ""},
    {"cmd": "HWI=", "type": "set", "expected": "HWI:", "default": "HW01"},
    {"cmd": "factorydef!", "type": "action", "expected": "factorydef", "default": ""},
    {"cmd": "save", "type": "action", "expected": "save:ACK", "default": ""},
    {"cmd": "dltxfifo=", "type": "set", "expected": "dltxfifo", "default": "3"},
    {"cmd": "dlrxfifo=", "type": "set", "expected": "dlrxfifo", "default": "3"},
    {"cmd": "utxfifo?", "type": "query", "expected": "utxfifo", "default": ""},
    {"cmd": "urxfifo?", "type": "query", "expected": "urxfifo", "default": ""},
    {"cmd": "cmdparser?", "type": "query", "expected": "cmdparser", "default": ""},
    {"cmd": "m_amx?", "type": "query", "expected": "m_amx:", "default": ""},
    {"cmd": "ver?", "type": "query", "expected": "ver:", "default": ""},
    {"cmd": "i2cPC?", "type": "query", "expected": "i2cPC:", "default": ""},
    {"cmd": "i2cMOT?", "type": "query", "expected": "i2cMOT:", "default": ""},
    {"cmd": "i2cUSB?", "type": "query", "expected": "i2cUSB:", "default": ""},
    {"cmd": "i2cMON?", "type": "query", "expected": "i2cMON:", "default": ""},
    {"cmd": "viPC?", "type": "query", "expected": "viPC:", "default": ""},
    {"cmd": "viMON?", "type": "query", "expected": "viMON:", "default": ""},
    {"cmd": "viMOT?", "type": "query", "expected": "viMOT:", "default": ""},
    {"cmd": "viUSB?", "type": "query", "expected": "viUSB:", "default": ""},
    {"cmd": "onRB?", "type": "query", "expected": "onRB:", "default": ""},
    {"cmd": "onRB=", "type": "set", "expected": "onRB:", "default": "1"},
    {"cmd": "onMON?", "type": "query", "expected": "onMON:", "default": ""},
    {"cmd": "onMON=", "type": "set", "expected": "onMON:", "default": "1"},
    {"cmd": "onUSB?", "type": "query", "expected": "onUSB:", "default": ""},
    {"cmd": "onUSB=", "type": "set", "expected": "onUSB:", "default": "1"},
    {"cmd": "onPC?", "type": "query", "expected": "onPC:", "default": ""},
    {"cmd": "onPC=", "type": "set", "expected": "onPC:", "default": "1"},
    {"cmd": "onExtUSB?", "type": "query", "expected": "onExtUSB:", "default": ""},
    {"cmd": "onExtUSB=", "type": "set", "expected": "onExtUSB:", "default": "1"},
    {"cmd": "onSLPWR?", "type": "query", "expected": "onSLPWR:", "default": ""},
    {"cmd": "onSLPWR=", "type": "set", "expected": "onSLPWR:", "default": "1"},
    {"cmd": "sysbtn?", "type": "query", "expected": "sysbtn:", "default": ""},
    {"cmd": "keybtn?", "type": "query", "expected": "keybtn:", "default": ""},
    {"cmd": "emobtn?", "type": "query", "expected": "emobtn:", "default": ""},
    {"cmd": "ONbtndc?", "type": "query", "expected": "ONbtndc:", "default": ""},
    {"cmd": "ONbtndc=", "type": "set", "expected": "ONbtndc:", "default": "50"},
    {"cmd": "SWReady?", "type": "query", "expected": "SWReady:", "default": ""},
    {"cmd": "SWReady=", "type": "set", "expected": "SWReady:", "default": "2"},
    {"cmd": "commandshutdown=", "type": "set", "expected": "commandshutdown:", "default": "0"},
    {"cmd": "shdnthreshold?", "type": "query", "expected": "shdnthreshold:", "default": ""},
    {"cmd": "shdnthreshold=", "type": "set", "expected": "shdnthreshold:", "default": "200"},
    {"cmd": "shdnsampleperiod?", "type": "query", "expected": "shdnsampleperiod:", "default": ""},
    {"cmd": "shdnsampleperiod=", "type": "set", "expected": "shdnsampleperiod:", "default": "4000"},
    {"cmd": "ONbtnrt?", "type": "query", "expected": "ONbtnrt:", "default": ""},
    {"cmd": "ONbtnrt=", "type": "set", "expected": "ONbtnrt:", "default": "100"},
    {"cmd": "autoSWReady?", "type": "query", "expected": "autoSWReady:", "default": ""},
    {"cmd": "autoSWReady=", "type": "set", "expected": "autoSWReady:", "default": "0"},
    {"cmd": "logEMObtn?", "type": "query", "expected": "logEMObtn:", "default": ""},
    {"cmd": "logEMObtn=", "type": "set", "expected": "logEMObtn:", "default": "500"},
    {"cmd": "logPC?", "type": "query", "expected": "logPC:", "default": ""},
    {"cmd": "logPC=", "type": "set", "expected": "logPC:", "default": "1000"},
    {"cmd": "logUSB?", "type": "query", "expected": "logUSB:", "default": ""},
    {"cmd": "logUSB=", "type": "set", "expected": "logUSB:", "default": "1000"},
    {"cmd": "logMOT?", "type": "query", "expected": "logMOT:", "default": ""},
    {"cmd": "logMOT=", "type": "set", "expected": "logMOT:", "default": "1000"},
    {"cmd": "logMON?", "type": "query", "expected": "logMON:", "default": ""},
    {"cmd": "logMON=", "type": "set", "expected": "logMON:", "default": "1000"},
    {"cmd": "diagLED?", "type": "query", "expected": "diagLED:", "default": ""},
    {"cmd": "diagLED=", "type": "set", "expected": "diagLED:", "default": "2"},
    {"cmd": "reset!", "type": "action", "expected": "reset", "default": ""}
]

# Comprehensive list of Section 7 Binary Commands
ALL_BINARY_COMMANDS = [
    {"cmd": 0x81, "name": "bcmd_TPOS (Move Motor Position)", "params_type": "int32", "default": "0", "manual": True,
     "prompt": "Did you observe motor axis rotating to target position?"},
    {"cmd": 0x82, "name": "bcmd_GETPOS (Get Position)", "params_type": "int32", "default": "0"},
    {"cmd": 0x83, "name": "bcmd_GETRPS (Get Speed)", "params_type": "none", "default": ""},
    {"cmd": 0x84, "name": "bcmd_VEL (Set Velocity)", "params_type": "int16", "default": "30"},
    {"cmd": 0x85, "name": "bcmd_GETVEL (Get Velocity)", "params_type": "none", "default": ""},
    {"cmd": 0x86, "name": "bcmd_NODEIDref (Get ID Reference)", "params_type": "query_3f", "default": ""},
    {"cmd": 0x86, "name": "bcmd_NODEIDref (Set ID Reference)", "params_type": "set_3d", "default": "01"},
    {"cmd": 0x88, "name": "bcmd_RUN (Run Motor)", "params_type": "int16", "default": "30", "manual": True,
     "prompt": "Did you observe the motor running?"},
    {"cmd": 0x89, "name": "bcmd_RD_SLOPE (Ramp Down Slope)", "params_type": "set_3d", "default": "00 1E"},
    {"cmd": 0x8B, "name": "bcmd_RD_STEP (Ramp Down Step)", "params_type": "set_3d", "default": "01"},
    {"cmd": 0x8C, "name": "bcmd_RD_MINVEL (Ramp Down Min Velocity)", "params_type": "set_3d", "default": "0A"},
    {"cmd": 0x8D, "name": "bcmd_BITRATE (CAN Bit Rate)", "params_type": "query_3f", "default": ""},
    {"cmd": 0x8E, "name": "bcmd_FWDSIZE (Forward Size Parameter)", "params_type": "set_3d", "default": "05"},
    {"cmd": 0x8F, "name": "bcmd_OUTDIAGLED (Diagnostic LED Output)", "params_type": "set_3d", "default": "02"},
    {"cmd": 0x90, "name": "bcmd_SJW (CAN SJW Parameter)", "params_type": "set_3d", "default": "01"},
    {"cmd": 0x91, "name": "bcmd_PRSEG (CAN PRSEG Parameter)", "params_type": "set_3d", "default": "02"},
    {"cmd": 0x92, "name": "bcmd_SEG1PH (CAN SEG1PH Parameter)", "params_type": "set_3d", "default": "03"},
    {"cmd": 0x93, "name": "bcmd_SEG2PH (CAN SEG2PH Parameter)", "params_type": "set_3d", "default": "03"},
    {"cmd": 0x94, "name": "bcmd_BAUDRATE (CAN Baud Rate)", "params_type": "set_3d", "default": "04"},
    {"cmd": 0x96, "name": "bcmd_EXTINT (Get EXT Interrupt)", "params_type": "query_3f", "default": ""},
    {"cmd": 0x96, "name": "bcmd_EXTINT (Set EXT Interrupt)", "params_type": "set_3d", "default": "01"},
    {"cmd": 0x97, "name": "bcmd_FACTORYDEF (Restore Factory Defaults)", "params_type": "none", "default": ""},
    {"cmd": 0x98, "name": "bcmd_MSTPEVNT (Motor stop event delay)", "params_type": "set_3d", "default": "0F"},
    {"cmd": 0x99, "name": "bcmd_ZPOSEVNT (Zero Position Event)", "params_type": "set_3d", "default": "0A"},
    {"cmd": 0x9A, "name": "bcmd_FIFOSTAT (FIFO Statistics)", "params_type": "query_3f", "default": ""},
    {"cmd": 0x9B, "name": "bcmd_AMXPSTAT (AMX Packet Statistic)", "params_type": "query_3f", "default": ""},
    {"cmd": 0x9C, "name": "bcmd_HOSTNODENO (Host Node Number)", "params_type": "query_3f", "default": ""},
    {"cmd": 0x9D, "name": "bcmd_FLASHLED (Flash Heart Beat LED)", "params_type": "none", "default": "", "manual": True,
     "prompt": "Did the node LED flash?"},
    {"cmd": 0x9E, "name": "bcmd_LOGFLAGS (Log INT0/INT1 Flags)", "params_type": "set_3d", "default": "01"},
    {"cmd": 0x9F, "name": "bcmd_LOG_NGSW (Log Needle Guide Switch)", "params_type": "set_3d", "default": "01"},
    {"cmd": 0xA0, "name": "bcmd_QEIENCODER (QEI Encoder ISR Counts)", "params_type": "none", "default": ""},
    {"cmd": 0xA1, "name": "bcmd_FFmsg (Free Form Message)", "params_type": "hex", "default": "AA BB CC"},
    {"cmd": 0xA2, "name": "bcmd_CHARVALUE (Minimum forward/rev PWM)", "params_type": "set_3d", "default": "01 0F"},
    {"cmd": 0xA4, "name": "bcmd_RETRY (Retries count)", "params_type": "set_3d", "default": "03"},
    {"cmd": 0xA5, "name": "bcmd_SWABPARAM (Configure swab parameters)", "params_type": "set_3d", "default": "01 02"},
    {"cmd": 0xA6, "name": "bcmd_ACCPPARAM (Acceptable error/parameter)", "params_type": "set_3d", "default": "05"},
    {"cmd": 0xA7, "name": "bcmd_RESTARTDLY (Restart delay config)", "params_type": "set_3d", "default": "0A 00"},
    {"cmd": 0xA8, "name": "bcmd_ENABLEOPT (Enable operational options)", "params_type": "set_3d", "default": "01"},
    {"cmd": 0xA9, "name": "bcmd_MINMOVINGPWM (Min PWM during motion)", "params_type": "set_3d", "default": "1E"},
    {"cmd": 0xAA, "name": "bcmd_UCHARVALUE (Optional datatype)", "params_type": "set_3d", "default": "02 55"},
    {"cmd": 0xC3, "name": "bcmd_HUNTING (Enable hunting/dithering)", "params_type": "set_3d", "default": "01"},
    {"cmd": 0xC4, "name": "bcmd_NODECONFIG (Configure node operating mode)", "params_type": "set_3d", "default": "01"},
    {"cmd": 0xC5, "name": "bcmd_SAVEEEPROM (Save settings)", "params_type": "none", "default": ""},
    {"cmd": 0xC6, "name": "bcmd_TOGGLELED (Toggle LED1/LED2)", "params_type": "hex", "default": "01", "manual": True,
     "prompt": "Did you see LED 1 toggle?"},
    {"cmd": 0xC7, "name": "bcmd_RESET (Reset microcontroller)", "params_type": "hex", "default": "21"},
    {"cmd": 0xC8, "name": "bcmd_GETVER (Query firmware version)", "params_type": "query_3f", "default": ""},
    {"cmd": 0xC9, "name": "bcmd_LFLAG (Left sensor flag behavior)", "params_type": "set_3d", "default": "01"},
    {"cmd": 0xCA, "name": "bcmd_RFLAG (Right sensor flag behavior)", "params_type": "set_3d", "default": "01"},
    {"cmd": 0xCB, "name": "bcmd_ECHOTEST (Test comm link)", "params_type": "hex", "default": "AA 55"},
    {"cmd": 0xCC, "name": "bcmd_BTNP (Push button input)", "params_type": "hex", "default": "01"},
    {"cmd": 0xCD, "name": "bcmd_NODETYPE (Get node type)", "params_type": "query_3f", "default": ""},
    {"cmd": 0xCD, "name": "bcmd_NODETYPE (Set node type)", "params_type": "set_3d", "default": "01"},
    {"cmd": 0xCE, "name": "bcmd_STT_FAULT (Motor driver fault status)", "params_type": "none", "default": ""},
    {"cmd": 0xCF, "name": "bcmd_MOTOR_I (Motor current reading)", "params_type": "hex", "default": "00 00"},
    {"cmd": 0xD0, "name": "bcmd_FSR1 (FSR1 force sensor reading)", "params_type": "hex", "default": "00 00 01"},
    {"cmd": 0xD1, "name": "bcmd_FSR2 (FSR2 force sensor reading)", "params_type": "hex", "default": "00 00 01"},
    {"cmd": 0xD2, "name": "bcmd_INFOR1 (Send node info)", "params_type": "hex", "default": "01 10 00"},
    {"cmd": 0xD3, "name": "bcmd_LOGMOTOR_I (Motor current logging rate)", "params_type": "set_3d", "default": "03 E8"},
    {"cmd": 0xD4, "name": "bcmd_LOGFSR1 (FSR1 logging rate)", "params_type": "set_3d", "default": "03 E8"},
    {"cmd": 0xD5, "name": "bcmd_LOGFSR2 (FSR2 logging rate)", "params_type": "set_3d", "default": "03 E8"},
    {"cmd": 0xD6, "name": "bcmd_HMILED (Set RGB for HMI LED)", "params_type": "set_3d", "default": "01"},
    {"cmd": 0xD7, "name": "bcmd_HMILEDRATE (Set RGB LED update rate)", "params_type": "set_3d", "default": "00 64"},
    {"cmd": 0xD8, "name": "bcmd_INTERRUPT (Get INT0/INT1 switch status)", "params_type": "none", "default": ""},
    {"cmd": 0xDB, "name": "bcmd_STARTMOVE (Initiate motor movement)", "params_type": "none", "default": ""},
    {"cmd": 0xDC, "name": "bcmd_BRAKEMOTOR (Apply motor braking)", "params_type": "none", "default": ""},
    {"cmd": 0xDD, "name": "bcmd_STOPMOTOR (Stop motor immediately)", "params_type": "none", "default": ""},
    {"cmd": 0xDE, "name": "bcmd_NGSWSTATE (Get needle guide force sensor)", "params_type": "none", "default": ""},
    {"cmd": 0xDF, "name": "bcmd_NGSW_SET (Set upper/lower FSR limits)", "params_type": "hex",
     "default": "01 00 64 03 E8"},
    {"cmd": 0xE1, "name": "bcmd_RD_OFFSET (Target offset for ramp down)", "params_type": "set_3d", "default": "00 64"},
    {"cmd": 0xE2, "name": "bcmd_RD_REGION (Ramp down region %)", "params_type": "set_3d", "default": "0A"},
    {"cmd": 0xE3, "name": "bcmd_POSCHANGE (Log position change count)", "params_type": "set_3d", "default": "0A"},
    {"cmd": 0xE4, "name": "bcmd_LOGPOS (Set position logging rate)", "params_type": "set_3d", "default": "00 64"},
    {"cmd": 0xE6, "name": "bcmd_LOGDATA (Configure general logging rate)", "params_type": "set_3d", "default": "03 E8"},
    {"cmd": 0xE7, "name": "bcmd_PID_Gain (Set PID P/I/D gains)", "params_type": "set_3d", "default": "01 00 A0"},
    {"cmd": 0xEA, "name": "bcmd_POSITION (Get current position)", "params_type": "query_3f", "default": ""},
    {"cmd": 0xEA, "name": "bcmd_POSITION (Set current position)", "params_type": "set_3d", "default": "00 00 00 00"},
    {"cmd": 0xEB, "name": "bcmd_TPOSREL (Move relative to position)", "params_type": "set_3d",
     "default": "00 00 27 10"},
    {"cmd": 0xEC, "name": "bcmd_ACCERROR (Set tracking error limit)", "params_type": "set_3d", "default": "00 0F"},
    {"cmd": 0xED, "name": "bcmd_PID_RATE (PID slew rate/delay)", "params_type": "set_3d", "default": "00 0A"},
    {"cmd": 0xFA, "name": "bcmd_NVDATASELECT (Select NVRAM data block)", "params_type": "set_3d", "default": "01"}
]

# DOC-00 Rev 01 expected response formats for Section 6 Text Commands
TEXT_CMD_EXPECTED_FORMATS = {
    "uartstat?": "uartstat:ok,err,empty,end",
    "opmode?": "opmode:<number> (operating mode)",
    "opmode=": "opmode:<number> (operating mode)",
    "spimem?": "spimem:<errStat(0=OK)>,<nvStatus(1=READ|2=SAVE|4=FACTORYDEF)>",
    "serialno?": "serialno:<text>",
    "serialno=": "serialno:<text>",
    "product?": "product:<text>",
    "product=": "product:<text>",
    "mfgdate?": "mfgdate:<text>",
    "mfgdate=": "mfgdate:<text>",
    "HWI?": "HWI:<text>",
    "HWI=": "HWI:<text>",
    "factorydef!": "factorydef",
    "save": "save:ACK",
    "dltxfifo=": "dltxfifo<fifo_index>:nodeID,overrun,maxused,size",
    "dlrxfifo=": "dlrxfifo<fifo_index>:nodeID,overrun,maxused,size",
    "utxfifo?": "utxfifo<fifo_index>:overrun,maxused,size",
    "urxfifo?": "urxfifo<fifo_index>:overrun,maxused,size",
    "cmdparser?": "cmdparser<fifo_index>:overrun,maxused,size",
    "m_amx?": "m_amx:pktSizeMax,dataSize",
    "ver?": "ver:Maj.Min.Sub_<build_number>",
    "i2cPC?": "i2cPC:<status> (0=OK)",
    "i2cMOT?": "i2cMOT:<status> (0=OK)",
    "i2cUSB?": "i2cUSB:<status> (0=OK)",
    "i2cMON?": "i2cMON:<status> (0=OK)",
    "viPC?": "viPC:voltage_mV,current_mA",
    "viMON?": "viMON:voltage_mV,current_mA",
    "viMOT?": "viMOT:voltage_mV,current_mA",
    "viUSB?": "viUSB:voltage_mV,current_mA",
    "onRB?": "onRB:<0|1> (0=OFF, 1=ON)",
    "onRB=": "onRB:<0|1>",
    "onMON?": "onMON:<0|1> (0=OFF, 1=ON)",
    "onMON=": "onMON:<0|1>",
    "onUSB?": "onUSB:<0|1> (0=OFF, 1=ON)",
    "onUSB=": "onUSB:<0|1>",
    "onPC?": "onPC:<0|1> (0=OFF, 1=ON)",
    "onPC=": "onPC:<0|1>",
    "onExtUSB?": "onExtUSB:<0|1> (0=OFF, 1=ON)",
    "onExtUSB=": "onExtUSB:<0|1>",
    "onSLPWR?": "onSLPWR:<0|1> (0=OFF, 1=ON)",
    "onSLPWR=": "onSLPWR:<0|1>",
    "sysbtn?": "sysbtn:0",
    "keybtn?": "keybtn:0",
    "emobtn?": "emobtn:<number> (button state)",
    "ONbtndc?": "ONbtndc:<0-100> (duty cycle %)",
    "ONbtndc=": "ONbtndc:<number>",
    "SWReady?": "SWReady:<0|1|2> (0=NotReady, 1=Ready, 2=Active)",
    "SWReady=": "SWReady:<number>",
    "commandshutdown=": "commandshutdown:<number>",
    "shdnthreshold?": "shdnthreshold:<number> (milliamps)",
    "shdnthreshold=": "shdnthreshold:<number>",
    "shdnsampleperiod?": "shdnsampleperiod:<number> (milliseconds)",
    "shdnsampleperiod=": "shdnsampleperiod:<number>",
    "ONbtnrt?": "ONbtnrt:<number> (milliseconds)",
    "ONbtnrt=": "ONbtnrt:<number>",
    "autoSWReady?": "autoSWReady:<number> (seconds)",
    "autoSWReady=": "autoSWReady:<number>",
    "logEMObtn?": "logEMObtn:<number> (milliseconds)",
    "logEMObtn=": "logEMObtn:<number>",
    "logPC?": "logPC:<number> (log rate ms)",
    "logPC=": "logPC:<number>",
    "logUSB?": "logUSB:<number> (log rate ms)",
    "logUSB=": "logUSB:<number>",
    "logMOT?": "logMOT:<number> (log rate ms)",
    "logMOT=": "logMOT:<number>",
    "logMON?": "logMON:<number> (log rate ms)",
    "logMON=": "logMON:<number>",
    "diagLED?": "diagLED:<number> (LED state)",
    "diagLED=": "diagLED:<number>",
    "reset!": "(no response - MCU reboots)",
}

# DOC-00 Rev 01 expected response descriptions for Section 7 Binary Commands
BINARY_CMD_EXPECTED_RESP = {
    0x81: "Multiple response states: 'S' = Start moving [0x81]['S'][pos_byte3]..., 'E' = End reached [0x81]['E']...",
    0x82: "[0x82][pos_byte3][pos_byte2][pos_byte1][pos_byte0]",
    0x83: "[0x83][rps_b3][rps_b2][rps_b1][rps_b0]",
    0x84: "[0x84]['S'][code_hi][code_lo]",
    0x85: "[0x85][vel_hi][vel_lo]",
    0x86: "[0x86][0x3A][node_id]",
    0x88: "[0x88]['S'][velocity_hi][velocity_lo]",
    0x89: "[0x89][0x3A][value_hi][value_lo]",
    0x8B: "[0x8B][0x3A][value]",
    0x8C: "[0x8C][0x3A][value]",
    0x8D: "[0x8D][0x3A][bitrate_code]",
    0x8E: "[0x8E][0x3A][value]",
    0x8F: "[0x8F][0x3A][value]",
    0x90: "[0x90][0x3A][value]",
    0x91: "[0x91][0x3A][value]",
    0x92: "[0x92][0x3A][value]",
    0x93: "[0x93][0x3A][value]",
    0x94: "[0x94][0x3A][value]",
    0x96: "[0x96][0x3A][0x00][value_hi][value_lo]",
    0x97: "[0x97]['A']",
    0x98: "[0x98][0x3A][value_hi][value_lo]",
    0x99: "[0x99][0x3A][value_hi][value_lo]",
    0x9A: "[0x9A][0x3A][stat_bytes]",
    0x9B: "[0x9B][0x3A][stat_bytes]",
    0x9C: "[0x9C][0x3A][value]",
    0x9D: "[0x9D]['A']",
    0x9E: "[0x9E][0x3A][value_hi][value_lo]",
    0x9F: "[0x9F][0x3A][value_hi][value_lo]",
    0xA0: "[0xA0][count_byte3][count_byte2][count_byte1][count_byte0]",
    0xA1: "[0xA1][length][message_bytes]",
    0xA2: "[0xA2][0x3A][datatype][value]",
    0xA4: "[0xA4][0x3A][value]",
    0xA5: "[0xA5][0x3A][maxRotarySwabOperationTime]",
    0xA6: "No active response handler found in source",
    0xA7: "[0xA7][0x3A][value_hi][value_lo]",
    0xA8: "[0xA8][0x3A][value_hi][value_lo]",
    0xA9: "[0xA9][0x3A]['v'][value_b3][value_b2][value_b1][value_b0]",
    0xAA: "[0xAA][0x3A][datatype][value]",
    0xC3: "[0xC3]['A'/'N'][nodeconfig]",
    0xC4: "[0xC4][0x3A][operation_mode]",
    0xC5: "[0xC5]['A']",
    0xC6: "LED toggles",
    0xC7: "[0xC7][0x3A][node_id]",
    0xC8: "[0xC8][0x3A][V1][V2][V3] V1 = (verMaj<<4)...",
    0xC9: "[0xC9][0x3A][value]",
    0xCA: "[0xCA][0x3A][value]",
    0xCB: "Echo: [0xCB][test_data]",
    0xCC: "[0xCC]['0'/'1']",
    0xCD: "[0xCD][0x3A][node_type]",
    0xCE: "[0xCE][status][fault_flags]",
    0xCF: "[0xCF][adc_hi][adc_lo]",
    0xD0: "[0xD0][adc_hi][adc_lo][state]",
    0xD1: "[0xD1][adc_hi][adc_lo][state]",
    0xD2: "[0xD2][0x3A][N][port_1]...[port_N]",
    0xD3: "[0xD3][0x3A][value_hi][value_lo]",
    0xD4: "[0xD4][0x3A][value_hi][value_lo]",
    0xD5: "[0xD5][0x3A][value_hi][value_lo]",
    0xD6: "[0xD6][0x3A][red][green][blue]",
    0xD7: "[0xD7][0x3A][red_hi][red_lo][green_hi][green_lo][blue_hi][blue_lo]",
    0xD8: "[0xD8][int0_status][int1_status]",
    0xDB: "[0xDB][isSpeedControl]",
    0xDC: "Motor brakes",
    0xDD: "Motor stops",
    0xDE: "[0xDE][fsr_value_hi][fsr_value_lo]",
    0xDF: "[0xDF][sw_id][0x3A][lower_hi][lower_lo][upper_hi][upper_lo]",
    0xE1: "[0xE1][0x3A][value_hi][value_lo]",
    0xE2: "[0xE2][0x3A][value]",
    0xE3: "[0xE3][0x3A][value_hi][value_lo]",
    0xE4: "[0xE4][0x3A][value_hi][value_lo]",
    0xE6: "[0xE6][0x3A][datatype][value_hi][value_lo]",
    0xE7: "[0xE7][0x3A][gain_type][value_b3][value_b2][value_b1][value_b0]",
    0xEA: "[0xEA][0x3A][pos_b3][pos_b2][pos_b1][pos_b0]",
    0xEB: "[0xEB]['S'][pos_b3][pos_b2][pos_b1][pos_b0]",
    0xEC: "[0xEC][0x3A][value_hi][value_lo]",
    0xED: "[0xED][0x3A][value_hi][value_lo]",
    0xFA: "[0xFA][0x3A][block_id]",
}


class TextTestConfigDialog(QDialog):
    """Pre-run configuration dialog to select and parameterize Text Commands."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Text Command Suite Configuration")
        self.resize(700, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Configure and select Text-based commands to verify:"))

        # Table of commands
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Test?", "Command Format", "Value/Param", "Type"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 55)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 180)

        layout.addWidget(self.table)

        # Populate table
        self.table.setRowCount(len(ALL_TEXT_COMMANDS))
        self.row_widgets = []
        for idx, tc in enumerate(ALL_TEXT_COMMANDS):
            # Checkbox
            chk = QCheckBox()
            chk.setChecked(tc["type"] == "query")  # Check queries by default, setters unchecked (safer)
            self.table.setCellWidget(idx, 0, chk)

            # Command label
            self.table.setItem(idx, 1, QTableWidgetItem(tc["cmd"]))

            # Parameter field
            val_input = QLineEdit()
            val_input.setText(tc["default"])
            if tc["type"] == "query" or tc["type"] == "action" and not tc["cmd"].endswith("="):
                val_input.setEnabled(False)
                val_input.setStyleSheet("background-color: #eee;")
            self.table.setCellWidget(idx, 2, val_input)

            # Type label
            self.table.setItem(idx, 3, QTableWidgetItem(tc["type"].upper()))

            self.row_widgets.append((chk, tc["cmd"], val_input, tc["type"], tc["expected"]))

        # Top selection buttons
        btn_control = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all)
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self.deselect_all)
        reset_defaults_btn = QPushButton("Reset Defaults")
        reset_defaults_btn.clicked.connect(self.reset_defaults)

        btn_control.addWidget(select_all_btn)
        btn_control.addWidget(deselect_all_btn)
        btn_control.addWidget(reset_defaults_btn)
        btn_control.addStretch()
        layout.addLayout(btn_control)

        # Dialog bottom row
        dialog_btns = QHBoxLayout()
        self.start_btn = QPushButton("Start Test Run")
        self.start_btn.setStyleSheet("font-weight: bold; background-color: #0088cc; color: white; padding: 6px 12px;")
        self.start_btn.clicked.connect(self.accept)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)

        dialog_btns.addStretch()
        dialog_btns.addWidget(self.start_btn)
        dialog_btns.addWidget(self.cancel_btn)
        layout.addLayout(dialog_btns)

    def select_all(self):
        for chk, _, _, _, _ in self.row_widgets:
            chk.setChecked(True)

    def deselect_all(self):
        for chk, _, _, _, _ in self.row_widgets:
            chk.setChecked(False)

    def reset_defaults(self):
        for idx, tc in enumerate(ALL_TEXT_COMMANDS):
            chk, _, val_input, _, _ = self.row_widgets[idx]
            chk.setChecked(tc["type"] == "query")
            val_input.setText(tc["default"])

    def get_selected_tests(self):
        selected = []
        for chk, cmd, val_input, c_type, expected in self.row_widgets:
            if chk.isChecked():
                # Form final packet payload
                payload = cmd
                if cmd.endswith("="):
                    payload = cmd + val_input.text().strip()

                # Build expected display string per DOC-00
                if c_type == "set" and cmd.endswith("=") and expected.endswith(":"):
                    # For setters with colon prefix: show prefix + the value being sent
                    expected_display = expected + val_input.text().strip()
                else:
                    # For queries/actions/special setters: show DOC-00 response format
                    expected_display = TEXT_CMD_EXPECTED_FORMATS.get(cmd, expected)

                selected.append({
                    "name": payload,
                    "type": "text",
                    "payload": payload,
                    "expected": expected,
                    "expected_display": expected_display,
                    "manual_verify": False,
                    "status": "PENDING",
                    "tx_bytes": b"",
                    "rx_bytes": b"",
                    "time_sent": 0.0,
                    "latency": None,
                    "decoded": ""
                })
        return selected


class BinaryTestConfigDialog(QDialog):
    """Pre-run configuration dialog to select and parameterize Binary Commands."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Binary Command Suite Configuration")
        self.resize(750, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Target Node ID
        node_layout = QHBoxLayout()
        node_layout.addWidget(QLabel("Target CAN Node ID (2-17):"))
        self.node_combo = QComboBox()
        self.node_combo.addItems([str(i) for i in range(2, 18)])
        self.node_combo.setCurrentText("3")
        self.node_combo.setMaximumWidth(60)
        node_layout.addWidget(self.node_combo)
        node_layout.addStretch()
        layout.addLayout(node_layout)

        layout.addWidget(QLabel("Configure and select Binary commands (Section 7) to verify:"))

        # Table of commands
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Test?", "Hex Code", "Command Name", "Parameters (Hex bytes)", "Param Type"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 55)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(3, 160)

        layout.addWidget(self.table)

        # Populate table
        self.table.setRowCount(len(ALL_BINARY_COMMANDS))
        self.row_widgets = []
        for idx, bc in enumerate(ALL_BINARY_COMMANDS):
            # Checkbox
            chk = QCheckBox()
            # Default to checking queries or LEDs, unchecking writes for safety
            chk.setChecked(bc["params_type"] == "none" or "GET" in bc["name"] or bc["cmd"] in [0xC8, 0xCD, 0xCB, 0x9D])
            self.table.setCellWidget(idx, 0, chk)

            # Command Hex ID
            hex_str = f"0x{bc['cmd']:02X}"
            self.table.setItem(idx, 1, QTableWidgetItem(hex_str))

            # Command label
            self.table.setItem(idx, 2, QTableWidgetItem(bc["name"]))

            # Parameter field
            val_input = QLineEdit()
            val_input.setText(bc["default"])
            if bc["params_type"] in ("none", "query_3f"):
                val_input.setEnabled(False)
                val_input.setVisible(False)
                val_input.setStyleSheet("background-color: #eee;")
            self.table.setCellWidget(idx, 3, val_input)

            # Type label
            self.table.setItem(idx, 4, QTableWidgetItem(bc["params_type"].upper()))

            self.row_widgets.append((chk, bc["cmd"], bc["name"], val_input, bc["params_type"], bc.get("manual", False),
                                     bc.get("prompt", "")))

        # Top selection buttons
        btn_control = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all)
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self.deselect_all)
        reset_defaults_btn = QPushButton("Reset Defaults")
        reset_defaults_btn.clicked.connect(self.reset_defaults)

        btn_control.addWidget(select_all_btn)
        btn_control.addWidget(deselect_all_btn)
        btn_control.addWidget(reset_defaults_btn)
        btn_control.addStretch()
        layout.addLayout(btn_control)

        # Dialog bottom row
        dialog_btns = QHBoxLayout()
        self.start_btn = QPushButton("Start Test Run")
        self.start_btn.setStyleSheet("font-weight: bold; background-color: #0066cc; color: white; padding: 6px 12px;")
        self.start_btn.clicked.connect(self.accept)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)

        dialog_btns.addStretch()
        dialog_btns.addWidget(self.start_btn)
        dialog_btns.addWidget(self.cancel_btn)
        layout.addLayout(dialog_btns)

    def select_all(self):
        for chk, _, _, _, _, _, _ in self.row_widgets:
            chk.setChecked(True)

    def deselect_all(self):
        for chk, _, _, _, _, _, _ in self.row_widgets:
            chk.setChecked(False)

    def reset_defaults(self):
        for idx, bc in enumerate(ALL_BINARY_COMMANDS):
            chk, _, _, val_input, _, _, _ = self.row_widgets[idx]
            chk.setChecked(bc["params_type"] == "none" or "GET" in bc["name"] or bc["cmd"] in [0xC8, 0xCD, 0xCB, 0x9D])
            val_input.setText(bc["default"])

    def get_target_node(self):
        return int(self.node_combo.currentText())

    def get_selected_tests(self):
        selected = []
        for chk, cmd_byte, name, val_input, param_type, is_manual, prompt in self.row_widgets:
            if chk.isChecked():
                params = []
                param_text = val_input.text().strip()

                # Parse parameter text depending on data format
                if param_type == "query_3f":
                    params = [0x3F]
                elif param_type == "set_3d":
                    if param_text:
                        try:
                            params = [0x3D] + [int(b, 16) for b in param_text.split()]
                        except ValueError:
                            pass
                    else:
                        params = [0x3D]
                elif param_text and param_type != "none":
                    if param_type == "int32":
                        try:
                            val = int(param_text)
                            params = list(val.to_bytes(4, byteorder='big', signed=True))
                        except ValueError:
                            pass
                    elif param_type == "int16":
                        try:
                            val = int(param_text)
                            params = list(val.to_bytes(2, byteorder='big', signed=True))
                        except ValueError:
                            pass
                    else:  # hex format, separated by spaces
                        try:
                            params = [int(b, 16) for b in param_text.split()]
                        except ValueError:
                            pass

                selected.append({
                    "name": name,
                    "type": "binary",
                    "cmd_byte": cmd_byte,
                    "params": params,
                    "expected": cmd_byte,
                    "expected_display": BINARY_CMD_EXPECTED_RESP.get(cmd_byte, f"0x{cmd_byte:02X} echo"),
                    "manual_verify": is_manual,
                    "prompt": prompt,
                    "status": "PENDING",
                    "tx_bytes": b"",
                    "rx_bytes": b"",
                    "time_sent": 0.0,
                    "latency": None,
                    "decoded": ""
                })
        return selected


class SaveLocationDialog(QDialog):
    """Dialog to ask the user for a save location for test reports and remember it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Save Location")
        self.resize(500, 150)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Select a directory to save the test report:"))

        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setReadOnly(True)
        path_layout.addWidget(self.path_input)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_directory)
        path_layout.addWidget(browse_btn)

        layout.addLayout(path_layout)

        self.remember_chk = QCheckBox("Use this location for future test reports")
        self.remember_chk.setChecked(True)
        layout.addWidget(self.remember_chk)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self.accept)
        self.ok_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", "")
        if directory:
            self.path_input.setText(directory)
            self.ok_btn.setEnabled(True)

    def get_selected_path(self):
        return self.path_input.text()

    def should_remember(self):
        return self.remember_chk.isChecked()


class TestReportDialog(QDialog):
    """Dialog that runs automated text/binary tests and measures response latency."""

    def __init__(self, parent, test_type, test_cases, target_node=2):
        super().__init__(parent)
        self.main_win = parent
        self.test_type = test_type
        self.target_node = target_node
        self.test_cases = test_cases
        self.current_idx = 0
        self.test_timer = QTimer(self)
        self.test_timer.timeout.connect(self.run_next_test)

        self.active_test = None
        self.active_test_sent_time = 0.0
        self.timeout_ms = 1500

        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle(f"Automated {self.test_type.capitalize()} Integration Test")
        self.resize(1150, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.status_lbl = QLabel(f"Preparing to run {len(self.test_cases)} tests...")
        self.status_lbl.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Command/Feature", "Expected Response", "Actual Response", "TX (Hex)", "RX (Hex)", "Latency (ms)",
            "Test Status"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(1, 250)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 85)
        layout.addWidget(self.table)

        self.table.setRowCount(len(self.test_cases))
        for idx, tc in enumerate(self.test_cases):
            self.table.setItem(idx, 0, QTableWidgetItem(tc["name"]))
            self.table.setItem(idx, 1, QTableWidgetItem(str(tc.get("expected_display", tc["expected"]))))
            self.table.setItem(idx, 2, QTableWidgetItem("--"))
            self.table.setItem(idx, 3, QTableWidgetItem("--"))
            self.table.setItem(idx, 4, QTableWidgetItem("--"))
            self.table.setItem(idx, 5, QTableWidgetItem("--"))
            status_item = QTableWidgetItem("PENDING")
            status_item.setForeground(QColor("#666666"))
            self.table.setItem(idx, 6, status_item)

        btn_layout = QHBoxLayout()
        self.export_btn = QPushButton("Export Report")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_report)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.setEnabled(False)

        btn_layout.addStretch()
        btn_layout.addWidget(self.export_btn)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

    def start_test_run(self):
        if not self.main_win.serial_conn.is_connected():
            QMessageBox.critical(self, "Error",
                                 "Serial connection is not active! Please connect to a serial port first.")
            self.reject()
            return

        if not self.test_cases:
            QMessageBox.information(self, "Info", "No commands selected to test!")
            self.reject()
            return

        self.status_lbl.setText(f"Running test 1 of {len(self.test_cases)}...")
        self.current_idx = 0
        self.progress_bar.setValue(0)
        self.test_timer.start(50)

    def run_next_test(self):
        if self.current_idx >= len(self.test_cases):
            self.finish_test_run()
            return

        tc = self.test_cases[self.current_idx]

        if self.active_test is not None:
            elapsed = (time.perf_counter() - self.active_test_sent_time) * 1000.0
            if elapsed >= self.timeout_ms:
                self.record_test_outcome(self.current_idx, "TIMEOUT")
                self.active_test = None
                self.current_idx += 1
                self.progress_bar.setValue(int((self.current_idx / len(self.test_cases)) * 100))
                if self.current_idx < len(self.test_cases):
                    self.status_lbl.setText(f"Running test {self.current_idx + 1} of {len(self.test_cases)}...")
            return

        self.active_test = tc
        self.active_test_sent_time = time.perf_counter()
        tc["time_sent"] = self.active_test_sent_time

        if tc["type"] == "text":
            packet = self.build_text_packet(tc["payload"])
            tc["tx_bytes"] = bytes(packet)
            self.table.setItem(self.current_idx, 3, QTableWidgetItem(" ".join(f"{b:02X}" for b in packet)))
            self.main_win.serial_conn.write(packet)
            self.main_win.fit_widget.append_log(
                f"[TX] TEXT CMD: {tc['payload']} (Raw: {' '.join(f'{b:02X}' for b in packet)})")
        else:
            packet = self.build_binary_packet(self.target_node, tc["cmd_byte"], tc["params"])
            tc["tx_bytes"] = bytes(packet)
            self.table.setItem(self.current_idx, 3, QTableWidgetItem(" ".join(f"{b:02X}" for b in packet)))
            self.main_win.serial_conn.write(packet)
            self.main_win.fit_widget.append_log(
                f"[TX] BINARY CMD to Node {self.target_node:02X}: {tc['name']} (Raw: {' '.join(f'{b:02X}' for b in packet)})")

    def build_text_packet(self, cmd_str):
        if not cmd_str.endswith("\r\n\r\n"):
            if cmd_str.endswith("\r\n"):
                cmd_str += "\r\n"
            else:
                cmd_str += "\r\n\r\n"
        cmd_bytes = cmd_str.encode('ascii')
        payload = [0x25, 0xA5, 0x01, 0x01, 0x31, len(cmd_bytes)] + list(cmd_bytes)
        chk_a, chk_b = calc_checksum(payload)
        payload += [chk_a, chk_b]
        return bytearray(payload)

    def build_binary_packet(self, target_id, cmd_byte, params):
        cmd_payload = [cmd_byte] + params
        payload = [0x25, 0xA5, 0x01, target_id, 0x31, len(cmd_payload)] + cmd_payload
        chk_a, chk_b = calc_checksum(payload)
        payload += [chk_a, chk_b]
        return bytearray(payload)

    def process_incoming_packet(self, pkt):
        if self.active_test is None:
            return

        tc = self.active_test
        pkt_type = pkt.get("type")

        if tc["type"] == "text":
            payload = b""
            if pkt_type == "direct_uart":
                payload = pkt.get("raw_payload", b"")
            elif pkt_type == "can_over_uart":
                sender = pkt.get("sender")
                if sender == 1:
                    params = pkt.get("params", [])
                    payload = bytes([pkt.get("cmd", 0)] + params)

            if payload:
                if isinstance(payload, list):
                    payload = bytes(payload)
                try:
                    resp_str = payload.decode('ascii', errors='ignore')
                    if tc["expected"] in resp_str:
                        latency = (time.perf_counter() - tc["time_sent"]) * 1000.0
                        tc["latency"] = latency
                        tc["rx_bytes"] = payload

                        self.record_test_outcome(self.current_idx, "PASS", rx_hex=" ".join(f"{b:02X}" for b in payload),
                                                 latency=latency, decoded=resp_str.strip())
                        self.active_test = None
                        self.current_idx += 1
                        self.progress_bar.setValue(int((self.current_idx / len(self.test_cases)) * 100))
                        if self.current_idx < len(self.test_cases):
                            self.status_lbl.setText(f"Running test {self.current_idx + 1} of {len(self.test_cases)}...")
                except Exception:
                    pass

        elif tc["type"] == "binary" and pkt_type == "can_over_uart":
            sender = pkt.get("sender")
            cmd = pkt.get("cmd")
            params = pkt.get("params", [])

            if sender == self.target_node and cmd == tc["expected"]:
                latency = (time.perf_counter() - tc["time_sent"]) * 1000.0
                tc["latency"] = latency
                raw_pkt = pkt.get("raw_packet", b"")
                if not raw_pkt:
                    target_id = pkt.get("target", 0)
                    port_char = pkt.get("port", '1')
                    port = ord(port_char) if isinstance(port_char, str) else port_char
                    can_data = [cmd] + params
                    amx_body = [0x25, 0xA5, sender, target_id, port, len(can_data)] + can_data
                    chk_a, chk_b = calc_checksum(amx_body)
                    raw_pkt = bytes(amx_body + [chk_a, chk_b])
                tc["rx_bytes"] = bytes(raw_pkt)

                status = "PASS"
                decoded_str = ""
                key, val = decode_command(cmd, params)
                if val:
                    decoded_str = str(val)

                if tc["manual_verify"]:
                    self.test_timer.stop()
                    self.main_win.fit_widget.append_log(
                        f"📥 Response received for {tc['name']} in {latency:.1f}ms. Prompting for user check...")

                    reply = QMessageBox.question(
                        self, "Tester Verification Required",
                        f"Firmware response for {tc['name']} was received correctly (Latency: {latency:.1f} ms).\n\n{tc['prompt']}",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        status = "PASS"
                        decoded_str += " (Verified by User)"
                        self.main_win.fit_widget.append_log("✅ Tester confirmed physical action was successful.")
                    else:
                        status = "FAIL (User Rejected)"
                        decoded_str += " (User rejected action)"
                        self.main_win.fit_widget.append_log("❌ Tester reported physical action failed.")

                    self.test_timer.start(50)

                self.record_test_outcome(self.current_idx, status, rx_hex=" ".join(f"{b:02X}" for b in raw_pkt),
                                         latency=latency, decoded=decoded_str)
                self.active_test = None
                self.current_idx += 1
                self.progress_bar.setValue(int((self.current_idx / len(self.test_cases)) * 100))
                if self.current_idx < len(self.test_cases):
                    self.status_lbl.setText(f"Running test {self.current_idx + 1} of {len(self.test_cases)}...")

    def record_test_outcome(self, idx, status, rx_hex="--", latency=None, decoded=""):
        tc = self.test_cases[idx]
        tc["status"] = status
        tc["decoded"] = decoded

        # Actual Response column (decoded firmware response)
        self.table.setItem(idx, 2, QTableWidgetItem(decoded if decoded else "--"))

        self.table.setItem(idx, 4, QTableWidgetItem(rx_hex))

        latency_str = f"{latency:.1f}" if latency is not None else "--"
        self.table.setItem(idx, 5, QTableWidgetItem(latency_str))

        status_item = QTableWidgetItem(status)
        if status == "PASS":
            status_item.setForeground(QColor("#00AA00"))
        elif status == "TIMEOUT":
            status_item.setForeground(QColor("#FF8C00"))
        else:
            status_item.setForeground(QColor("#FF0000"))
        self.table.setItem(idx, 6, status_item)
        self.table.scrollToItem(status_item)

    def finish_test_run(self):
        self.test_timer.stop()
        self.active_test = None

        passed = sum(1 for tc in self.test_cases if tc["status"] == "PASS")
        total = len(self.test_cases)

        self.status_lbl.setText(f"Test run completed. Passed {passed} of {total} test cases.")
        self.progress_bar.setValue(100)
        self.export_btn.setEnabled(True)
        self.close_btn.setEnabled(True)

        self.main_win.fit_widget.append_log(f"📋 Automated test finished. {passed}/{total} Passed.")

    def export_report(self):
        settings = QSettings("Biobot", "RobotArmTester")
        saved_dir = settings.value("report_save_location", "")

        save_dir = ""
        if saved_dir and os.path.isdir(saved_dir):
            # Ask user if they want to use existing location or change it
            reply = QMessageBox.question(
                self, "Save Location",
                f"Save report to:\n{saved_dir}\n\nClick 'No' to choose a different location.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                save_dir = saved_dir
            elif reply == QMessageBox.StandardButton.No:
                dlg = SaveLocationDialog(self)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    save_dir = dlg.get_selected_path()
                    if dlg.should_remember():
                        settings.setValue("report_save_location", save_dir)
                else:
                    return
            else:
                return
        else:
            dlg = SaveLocationDialog(self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                save_dir = dlg.get_selected_path()
                if dlg.should_remember():
                    settings.setValue("report_save_location", save_dir)
            else:
                return

        timestamp_file = QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')
        timestamp_display = QDateTime.currentDateTime().toString('yyyy-MM-dd HH:mm:ss')
        filename = f"FIT_Report_{self.test_type}_{timestamp_file}.html"
        path = os.path.join(save_dir, filename)

        try:
            passed = sum(1 for tc in self.test_cases if tc["status"] == "PASS")
            total = len(self.test_cases)
            pass_percent = (passed / total * 100) if total > 0 else 0

            summary_class = "pass" if passed == total else "fail"

            html = [
                "<!DOCTYPE html>",
                "<html>",
                "<head>",
                "    <style>",
                "        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 40px; color: #333; background-color: #f4f7f6; }",
                "        .container { max-width: 1100px; margin: auto; background: #fff; padding: 40px; border-radius: 10px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); }",
                "        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #eee; padding-bottom: 20px; margin-bottom: 30px; }",
                "        h1 { color: #2c3e50; margin: 0; font-size: 24px; }",
                "        .meta-info { display: flex; gap: 30px; font-size: 14px; color: #555; }",
                "        .meta-item { display: flex; flex-direction: column; }",
                "        .meta-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #888; font-weight: bold; margin-bottom: 4px; }",
                "        .meta-value { font-size: 15px; font-weight: 500; color: #333; }",
                "        .summary { font-size: 18px; font-weight: bold; margin-bottom: 30px; padding: 20px; border-radius: 8px; display: flex; align-items: center; justify-content: space-between; }",
                "        .summary.pass { background-color: #eafaf1; color: #27ae60; border: 1px solid #d5f5e3; }",
                "        .summary.fail { background-color: #fadbd8; color: #c0392b; border: 1px solid #f5b7b1; }",
                "        table { width: 100%; border-collapse: collapse; font-size: 14px; }",
                "        th, td { padding: 15px 15px; text-align: left; border-bottom: 1px solid #eee; }",
                "        th { background-color: #f8f9fa; font-weight: 600; color: #555; text-transform: uppercase; font-size: 12px; letter-spacing: 0.5px; }",
                "        tr:hover { background-color: #fcfcfc; }",
                "        .badge { padding: 5px 10px; border-radius: 20px; font-size: 11px; font-weight: bold; color: #fff; text-transform: uppercase; letter-spacing: 0.5px; }",
                "        .badge.pass { background-color: #2ecc71; }",
                "        .badge.fail { background-color: #e74c3c; }",
                "        .badge.timeout { background-color: #f39c12; }",
                "        .details { font-family: 'Consolas', 'Courier New', monospace; font-size: 12px; color: #7f8c8d; display: block; margin-top: 8px; background: #f8f9fa; padding: 8px; border-radius: 4px; }",
                "    </style>",
                "</head>",
                "<body>",
                "    <div class='container'>",
                "        <div class='header'>",
                "            <h1>BioBot Firmware Integration Test Report</h1>",
                "            <div class='meta-info'>",
                f"                <div class='meta-item'><span class='meta-label'>Timestamp</span><span class='meta-value'>{timestamp_display}</span></div>",
                f"                <div class='meta-item'><span class='meta-label'>Test Type</span><span class='meta-value'>{self.test_type.upper()}</span></div>"
            ]

            if self.test_type == "binary":
                html.append(
                    f"                <div class='meta-item'><span class='meta-label'>Target Node ID</span><span class='meta-value'>{self.target_node}</span></div>")

            html.extend([
                "            </div>",
                "        </div>",
                f"        <div class='summary {summary_class}'>",
                f"            <span>Overall Result: {passed} / {total} Passed</span>",
                f"            <span>{pass_percent:.1f}%</span>",
                "        </div>",
                "        <table>",
                "            <thead>",
                "                <tr>",
                "                    <th width='30%'>Command Name</th>",
                "                    <th width='10%'>Status</th>",
                "                    <th width='15%'>Expected</th>",
                "                    <th width='35%'>Actual Response</th>",
                "                    <th width='10%'>Latency</th>",
                "                </tr>",
                "            </thead>",
                "            <tbody>"
            ])

            for tc in self.test_cases:
                badge_class = tc['status'].lower().split()[0]
                if badge_class not in ["pass", "fail", "timeout"]:
                    badge_class = "fail"

                lat_str = f"{tc['latency']:.1f} ms" if tc['latency'] is not None else "--"
                exp_display = tc.get('expected_display', str(tc['expected']))

                tx_str = " ".join(f"{b:02X}" for b in tc['tx_bytes'])
                rx_str = " ".join(f"{b:02X}" for b in tc['rx_bytes']) if tc['rx_bytes'] else "None"

                # HTML escape decoded string to prevent layout breaking
                decoded_escaped = tc['decoded'].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                details = f"TX: {tx_str}<br>RX: {rx_str}"

                html.extend([
                    "                <tr>",
                    f"                    <td>{tc['name']}</td>",
                    f"                    <td><span class='badge {badge_class}'>{tc['status']}</span></td>",
                    f"                    <td>{exp_display}</td>",
                    f"                    <td>{decoded_escaped}<span class='details'>{details}</span></td>",
                    f"                    <td>{lat_str}</td>",
                    "                </tr>"
                ])

            html.extend([
                "            </tbody>",
                "        </table>",
                "    </div>",
                "</body>",
                "</html>"
            ])

            with open(path, 'w', encoding='utf-8-sig') as f:
                f.write("\n".join(html))

            QMessageBox.information(self, "Success", f"Report exported successfully!\n{path}")
            # Open the report in the default browser
            try:
                os.startfile(path)
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export report: {e}")


class FirmwareIntegrationTestWidget(QGroupBox):
    """The visual integration test panel displayed in the MainWindow."""

    def __init__(self, parent=None):
        super().__init__("Firmware Integration Test", parent)
        self.main_win = parent
        self.rx_buffer = bytearray()
        self.active_dialog = None

        self.pending_manual_cmd = None

        callbacks = {
            'mcu_version': self.on_mcu_version_cb,
            'node_version': self.on_node_version_cb,
            'status_field': self.on_status_field_cb,
            'packet_error': self.on_packet_error_cb,
            'log': self.on_log_cb
        }
        self.protocol_handler = AppProtocolHandler(callbacks=callbacks)

        self.setup_ui()

    def setup_ui(self):
        self.setContentsMargins(8, 8, 8, 8)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(8)

        # Row 1: Automated & Hardware Test buttons
        auto_layout = QHBoxLayout()
        auto_layout.setSpacing(6)

        self.run_bin_test_btn = QPushButton("Run Binary Tests")
        self.run_bin_test_btn.setStyleSheet(
            "font-weight: bold; background-color: #395C6B; color: white; padding: 10px 14px;")
        self.run_bin_test_btn.clicked.connect(self.run_binary_integration_test)

        self.run_text_test_btn = QPushButton("Run Text-based Tests")
        self.run_text_test_btn.setStyleSheet(
            "font-weight: bold; background-color: #92BCEA; color: #1a1a2e; padding: 10px 14px;")
        self.run_text_test_btn.clicked.connect(self.run_text_integration_test)

        self.diag_mode_chk = QCheckBox("Diagnostic Mode")
        self.diag_mode_chk.setToolTip("Quietens background terminal printing to prioritize test logs.")

        self.change_save_loc_btn = QPushButton("📁 Save Location")
        self.change_save_loc_btn.setToolTip("View or change the save location for test reports and diagnostic logs.")
        self.change_save_loc_btn.setStyleSheet("padding: 10px 10px;")
        self.change_save_loc_btn.clicked.connect(self.change_save_location)

        auto_layout.addWidget(self.run_bin_test_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        auto_layout.addWidget(self.run_text_test_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        auto_layout.addWidget(self.diag_mode_chk, alignment=Qt.AlignmentFlag.AlignVCenter)
        auto_layout.addWidget(self.change_save_loc_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        auto_layout.addStretch()
        layout.addLayout(auto_layout)

        # Row 2: Mode Selector
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Manual Testing Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Text Command Mode", "Binary Command Mode"])
        self.mode_combo.currentIndexChanged.connect(self.switch_manual_mode_view)
        self.mode_combo.setMinimumWidth(180)
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)

        # Row 3: Manual Interactive Stack
        self.manual_stack = QStackedWidget()

        # Stack Page 1: Text Command UI
        text_widget = QWidget()
        text_layout = QHBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)

        text_layout.addWidget(QLabel("Text Command:"))
        self.text_cmd_combo = QComboBox()
        self.text_cmd_combo.setEditable(True)
        # Load unique base names for dropdown
        comb_items = sorted(list(set(c["cmd"] for c in ALL_TEXT_COMMANDS)))
        self.text_cmd_combo.addItems(comb_items)
        self.text_cmd_combo.setMinimumWidth(140)
        self.text_cmd_combo.currentTextChanged.connect(self.on_text_cmd_changed)

        completer = QCompleter(comb_items, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.text_cmd_combo.setCompleter(completer)
        text_layout.addWidget(self.text_cmd_combo)

        self.text_param_lbl = QLabel("Value:")
        self.text_param_lbl.setVisible(False)
        text_layout.addWidget(self.text_param_lbl)

        self.text_param_input = QLineEdit()
        self.text_param_input.setPlaceholderText("Enter parameter...")
        self.text_param_input.setVisible(False)
        self.text_param_input.setMaximumWidth(120)
        text_layout.addWidget(self.text_param_input)

        self.send_text_btn = QPushButton("Send Text")
        self.send_text_btn.clicked.connect(self.send_manual_text)
        text_layout.addWidget(self.send_text_btn)
        text_layout.addStretch()
        self.manual_stack.addWidget(text_widget)

        # Stack Page 2: Binary Command UI
        bin_widget = QWidget()
        bin_layout = QHBoxLayout(bin_widget)
        bin_layout.setContentsMargins(0, 0, 0, 0)
        bin_layout.setSpacing(6)

        bin_layout.addWidget(QLabel("Node ID:"))
        self.node_id_combo = QComboBox()
        self.node_id_combo.addItems([str(i) for i in range(2, 18)])
        self.node_id_combo.setCurrentText("3")
        self.node_id_combo.setMaximumWidth(55)
        bin_layout.addWidget(self.node_id_combo)

        bin_layout.addWidget(QLabel("Cmd:"))
        self.bin_cmd_combo = QComboBox()
        for item in ALL_BINARY_COMMANDS:
            self.bin_cmd_combo.addItem(item["name"], item["cmd"])
        self.bin_cmd_combo.setMinimumWidth(180)
        self.bin_cmd_combo.currentIndexChanged.connect(self.on_bin_cmd_changed)
        bin_layout.addWidget(self.bin_cmd_combo)

        self.param_stack = QStackedWidget()

        self.pos_spin = QSpinBox()
        self.pos_spin.setRange(-2147483648, 2147483647)
        self.pos_spin.setValue(0)
        self.pos_spin.setMinimumWidth(110)
        self.pos_spin.setMaximumWidth(130)
        self.param_stack.addWidget(self.pos_spin)

        self.vel_spin = QSpinBox()
        self.vel_spin.setRange(-32768, 32767)
        self.vel_spin.setValue(30)
        self.vel_spin.setMinimumWidth(110)
        self.vel_spin.setMaximumWidth(130)
        self.param_stack.addWidget(self.vel_spin)

        self.bin_hex_input = QLineEdit()
        self.bin_hex_input.setPlaceholderText("Hex bytes (e.g. 00 AA 55)")
        self.bin_hex_input.setMinimumWidth(130)
        self.bin_hex_input.setMaximumWidth(130)
        self.param_stack.addWidget(self.bin_hex_input)

        self.param_stack.setMaximumWidth(130)
        self.param_stack.setSizePolicy(self.bin_hex_input.sizePolicy())
        bin_layout.addWidget(self.param_stack)

        self.raw_hex_chk = QCheckBox("Raw Hex")
        self.raw_hex_chk.toggled.connect(self.toggle_raw_hex_mode)
        bin_layout.addWidget(self.raw_hex_chk)

        self.send_bin_btn = QPushButton("Send Binary")
        self.send_bin_btn.clicked.connect(self.send_manual_binary)
        bin_layout.addWidget(self.send_bin_btn)
        bin_layout.addStretch()
        self.manual_stack.addWidget(bin_widget)

        layout.addWidget(self.manual_stack)
        layout.addStretch(1)

        self.switch_manual_mode_view(0)
        self.on_text_cmd_changed(self.text_cmd_combo.currentText())
        self.on_bin_cmd_changed(0)

    def switch_manual_mode_view(self, idx):
        self.manual_stack.setCurrentIndex(idx)

    def on_text_cmd_changed(self, text):
        is_setter = "=" in text
        self.text_param_lbl.setVisible(is_setter)
        self.text_param_input.setVisible(is_setter)
        if is_setter:
            self.text_param_input.setFocus()

    def on_bin_cmd_changed(self, idx):
        if self.raw_hex_chk.isChecked():
            return

        cmd = self.bin_cmd_combo.currentData()
        command_info = ALL_BINARY_COMMANDS[idx]

        if cmd == 0x81:
            self.param_stack.setCurrentIndex(0)
            self.pos_spin.setFocus()
        elif cmd in [0x84, 0x88]:
            self.param_stack.setCurrentIndex(1)
            self.vel_spin.setFocus()
        else:
            self.param_stack.setCurrentIndex(2)
            if command_info["params_type"] in ("none", "query_3f"):
                self.bin_hex_input.clear()
                self.bin_hex_input.setEnabled(False)
                self.bin_hex_input.setVisible(False)
            else:
                self.bin_hex_input.setEnabled(True)
                self.bin_hex_input.setVisible(True)
                if command_info["params_type"] in ("hex", "set_3d"):
                    self.bin_hex_input.setText(command_info["default"])
                else:
                    self.bin_hex_input.clear()
            self.bin_hex_input.setFocus()

    def toggle_raw_hex_mode(self, checked):
        if checked:
            self.bin_cmd_combo.setEnabled(False)
            self.node_id_combo.setEnabled(False)
            self.param_stack.setCurrentIndex(2)
            self.bin_hex_input.setPlaceholderText("Raw Hex (e.g. 25 A5 01 03 31 ...)")
            self.bin_hex_input.setFocus()
        else:
            self.bin_cmd_combo.setEnabled(True)
            self.node_id_combo.setEnabled(True)
            self.bin_hex_input.setPlaceholderText("Hex bytes (e.g. 00 AA 55)")
            self.on_bin_cmd_changed(self.bin_cmd_combo.currentIndex())

    def append_log(self, msg):
        if hasattr(self.main_win, 'diag_log_text'):
            timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss.zzz")
            self.main_win.diag_log_text.append(f"[{timestamp}] {msg}")
            scrollbar = self.main_win.diag_log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def process_incoming_raw_bytes(self, data: bytes):
        if not data:
            return

        self.protocol_handler.process_incoming_data(data)

        self.rx_buffer += data
        try:
            packets, self.rx_buffer = parse_uart_rx_packets(self.rx_buffer)
            for pkt in packets:
                self.handle_parsed_packet(pkt)
        except Exception as e:
            self.append_log(f"⚠️ Error parsing incoming packet: {e}")

    def handle_parsed_packet(self, pkt):
        pkt_status = pkt.get("status")
        pkt_type = pkt.get("type")

        if pkt_status != "ok":
            self.append_log(f"❌ RX Packet Error: {pkt_status}")
            return

        latency_str = ""
        if self.pending_manual_cmd is not None:
            pm = self.pending_manual_cmd
            is_match = False

            if pm["type"] == "text" and pkt_type == "direct_uart":
                payload = pkt.get("raw_payload", b"")
                if isinstance(payload, list):
                    payload = bytes(payload)
                try:
                    resp_str = payload.decode("ascii", errors="ignore").strip()
                    if pm["expected"] in resp_str:
                        is_match = True
                except Exception:
                    pass
            elif pm["type"] == "binary" and pkt_type == "can_over_uart":
                sender = pkt.get("sender")
                cmd = pkt.get("cmd")
                if sender == pm["node_id"] and cmd == pm["expected"]:
                    is_match = True

            if is_match:
                lat_ms = (time.perf_counter() - pm["time_sent"]) * 1000.0
                latency_str = f" (Latency: {lat_ms:.1f} ms)"
                self.pending_manual_cmd = None

        if self.active_dialog and self.active_dialog.isVisible():
            self.active_dialog.process_incoming_packet(pkt)

        if pkt_type == "direct_uart":
            payload = pkt.get("raw_payload", b"")
            if isinstance(payload, list):
                payload = bytes(payload)
            try:
                decoded = payload.decode("ascii", errors="ignore").strip()
                self.append_log(
                    f"[RX] TEXT RESP: {decoded}{latency_str} (Raw: {' '.join(f'{b:02X}' for b in payload)})")
            except Exception:
                self.append_log(f"[RX] TEXT RESP{latency_str} (Raw: {' '.join(f'{b:02X}' for b in payload)})")

        elif pkt_type == "can_over_uart":
            sender = pkt.get("sender")
            cmd = pkt.get("cmd")
            params = pkt.get("params", [])
            raw_pkt = pkt.get("raw_packet", b"")

            param_str = " ".join(f"{b:02X}" for b in params)
            decoded_key, decoded_val = decode_command(cmd, params)

            log_msg = f"[RX] CAN RESP from Node {sender:02X}: Cmd:{cmd:02X} Params:[{param_str}]{latency_str}"
            if decoded_val:
                log_msg += f" -> {decoded_key}: {decoded_val}"
            self.append_log(log_msg)

    def build_text_packet(self, cmd_str):
        if not cmd_str.endswith("\r\n\r\n"):
            if cmd_str.endswith("\r\n"):
                cmd_str += "\r\n"
            else:
                cmd_str += "\r\n\r\n"
        cmd_bytes = cmd_str.encode('ascii')
        payload = [0x25, 0xA5, 0x01, 0x01, 0x31, len(cmd_bytes)] + list(cmd_bytes)
        chk_a, chk_b = calc_checksum(payload)
        payload += [chk_a, chk_b]
        return bytearray(payload)

    def send_manual_text(self):
        if not self.main_win.serial_conn.is_connected():
            QMessageBox.warning(self, "Warning", "Serial port is not connected!")
            return

        cmd_base = self.text_cmd_combo.currentText().strip()
        if not cmd_base:
            return

        if "=" in cmd_base:
            param = self.text_param_input.text().strip()
            if param:
                parts = cmd_base.split('=')
                cmd_to_send = f"{parts[0]}={param}"
            else:
                cmd_to_send = cmd_base
        else:
            cmd_to_send = cmd_base

        packet = self.build_text_packet(cmd_to_send)

        expected_prefix = cmd_to_send.split('=')[0].split('?')[0] + ":"
        if cmd_to_send.endswith("!"):
            expected_prefix = cmd_to_send.replace("!", "") + ":"

        self.pending_manual_cmd = {
            "type": "text",
            "expected": expected_prefix,
            "time_sent": time.perf_counter()
        }

        self.append_log(f"[TX] TEXT CMD: {cmd_to_send} (Raw: {' '.join(f'{b:02X}' for b in packet)})")
        self.main_win.serial_conn.write(packet)

    def send_manual_binary(self):
        if not self.main_win.serial_conn.is_connected():
            QMessageBox.warning(self, "Warning", "Serial port is not connected!")
            return

        if self.raw_hex_chk.isChecked():
            raw_text = self.bin_hex_input.text().strip().replace(" ", "")
            try:
                packet = bytearray.fromhex(raw_text)
                self.append_log(f"[TX] RAW HEX: {' '.join(f'{b:02X}' for b in packet)}")
                self.main_win.serial_conn.write(packet)
            except ValueError:
                QMessageBox.critical(self, "Error", "Invalid hex character sequence in Raw Hex field.")
            return

        try:
            node_id = int(self.node_id_combo.currentText())
        except ValueError:
            node_id = 3

        cmd = self.bin_cmd_combo.currentData()
        idx = self.bin_cmd_combo.currentIndex()
        command_info = ALL_BINARY_COMMANDS[idx] if idx >= 0 else None
        param_type = command_info["params_type"] if command_info else "hex"

        params = []
        if cmd == 0x81:
            pos = self.pos_spin.value()
            params = list(pos.to_bytes(4, byteorder='big', signed=True))
        elif cmd in [0x84, 0x88]:
            vel = self.vel_spin.value()
            params = list(vel.to_bytes(2, byteorder='big', signed=True))
        else:
            hex_str = self.bin_hex_input.text().strip()
            if param_type == "query_3f":
                params = [0x3F]
            elif param_type == "none":
                params = []
            elif param_type == "set_3d":
                if hex_str:
                    try:
                        params = [0x3D] + [int(b, 16) for b in hex_str.split()]
                    except ValueError:
                        QMessageBox.warning(self, "Warning", "Hex parameters should be space-separated hex bytes.")
                        return
                else:
                    params = [0x3D]
            else:
                if hex_str:
                    try:
                        params = [int(b, 16) for b in hex_str.split()]
                    except ValueError:
                        QMessageBox.warning(self, "Warning", "Hex parameters should be space-separated hex bytes.")
                        return

        cmd_payload = [cmd] + params
        payload = [0x25, 0xA5, 0x01, node_id, 0x31, len(cmd_payload)] + cmd_payload
        chk_a, chk_b = calc_checksum(payload)
        payload += [chk_a, chk_b]

        packet = bytearray(payload)
        cmd_name = self.bin_cmd_combo.currentText()

        self.pending_manual_cmd = {
            "type": "binary",
            "node_id": node_id,
            "expected": cmd,
            "time_sent": time.perf_counter()
        }

        self.append_log(
            f"[TX] BINARY CMD to Node {node_id:02X}: {cmd_name} (Raw: {' '.join(f'{b:02X}' for b in packet)})")
        self.main_win.serial_conn.write(packet)

    def change_save_location(self):
        """Allow the user to view/change the saved report and log directory."""
        settings = QSettings("Biobot", "RobotArmTester")
        current_dir = settings.value("report_save_location", "")

        if current_dir and os.path.isdir(current_dir):
            reply = QMessageBox.question(
                self, "Current Save Location",
                f"Current save location:\n{current_dir}\n\nWould you like to change it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        dlg = SaveLocationDialog(self.main_win)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_dir = dlg.get_selected_path()
            if new_dir:
                settings.setValue("report_save_location", new_dir)
                QMessageBox.information(self, "Save Location Updated",
                                        f"Reports and logs will now be saved to:\n{new_dir}")

    # Automated Test Runners using Config screens
    def run_binary_integration_test(self):
        config_dlg = BinaryTestConfigDialog(self.main_win)
        if config_dlg.exec() == QDialog.DialogCode.Accepted:
            selected_cases = config_dlg.get_selected_tests()
            target_node = config_dlg.get_target_node()

            self.active_dialog = TestReportDialog(self.main_win, "binary", selected_cases, target_node)
            self.active_dialog.show()
            self.active_dialog.start_test_run()

    def run_text_integration_test(self):
        config_dlg = TextTestConfigDialog(self.main_win)
        if config_dlg.exec() == QDialog.DialogCode.Accepted:
            selected_cases = config_dlg.get_selected_tests()

            self.active_dialog = TestReportDialog(self.main_win, "text", selected_cases)
            self.active_dialog.show()
            self.active_dialog.start_test_run()

    # AppProtocolHandler Callbacks
    def on_mcu_version_cb(self, version):
        self.append_log(f"[AppProtocolCallback] MCU Version: {version}")

    def on_node_version_cb(self, node_id, version):
        self.append_log(f"[AppProtocolCallback] Node {node_id} Version: {version}")

    def on_status_field_cb(self, node_id, key, val):
        self.append_log(f"[AppProtocolCallback] Node {node_id} Status update: {key} = {val}")

    def on_packet_error_cb(self, error_desc):
        self.append_log(f"[AppProtocolCallback] Packet Error received: {error_desc}")

    def on_log_cb(self, msg):
        self.append_log(f"[AppProtocolCallback] Log: {msg}")
