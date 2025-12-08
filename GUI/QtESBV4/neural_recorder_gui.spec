# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

# 添加项目路径到Python路径
project_path = r"e:\wirelessNeuralRecording-mouse\firmware\LFP\QtESBV4\neural_recorder_GUI"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

block_cipher = None

a = Analysis(
    [r"e:\wirelessNeuralRecording-mouse\firmware\LFP\QtESBV4\neural_recorder_GUI\neural_recorder_GUI.py"],
    pathex=[r"e:\wirelessNeuralRecording-mouse\firmware\LFP\QtESBV4", r"e:\wirelessNeuralRecording-mouse\firmware\LFP\QtESBV4\neural_recorder_GUI"],
    binaries=[],
    datas=[
        # 包含所有Python模块
        (r"e:\wirelessNeuralRecording-mouse\firmware\LFP\QtESBV4\neural_recorder_GUI\neural_reader.py", '.'),
        (r"e:\wirelessNeuralRecording-mouse\firmware\LFP\QtESBV4\neural_recorder_GUI\neural_recorder_main_ui.py", '.'),
        (r"e:\wirelessNeuralRecording-mouse\firmware\LFP\QtESBV4\neural_recorder_GUI\RFPowerControl.py", '.'),
        (r"e:\wirelessNeuralRecording-mouse\firmware\LFP\QtESBV4\neural_recorder_GUI\camera_module.py", '.'),
        (r"e:\wirelessNeuralRecording-mouse\firmware\LFP\QtESBV4\neural_recorder_GUI\optimized_habits_panel.py", '.'),
        (r"e:\wirelessNeuralRecording-mouse\firmware\LFP\QtESBV4\neural_recorder_GUI\path_utils.py", '.'),
    ],
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtWidgets', 
        'PyQt6.QtGui',
        'pyqtgraph',
        'numpy',
        'scipy',
        'scipy.signal',
        'scipy.fft',
        'scipy.fftpack',
        'serial',
        'serial.tools.list_ports',
        'cv2',
        'threading',
        'multiprocessing',
        'json',
        'datetime',
        'warnings',
        'neural_reader',
        'neural_recorder_main_ui',
        'RFPowerControl',
        'camera_module', 
        'optimized_habits_panel',
        'path_utils'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='NeuralRecorderGUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 设置为True以便调试，发布时可改为False
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可以添加图标文件路径
)
