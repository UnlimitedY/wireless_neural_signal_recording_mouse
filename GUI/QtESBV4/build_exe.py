#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Neural Recorder GUI 打包脚本
使用PyInstaller将GUI应用打包为exe文件

使用方法:
1. 安装依赖: pip install pyinstaller
2. 运行脚本: python build_exe.py
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def check_dependencies():
    """检查必要的依赖是否已安装"""
    required_packages = [
        'PyInstaller',
        'PyQt6',
        'pyqtgraph', 
        'numpy',
        'scipy',
        'serial',
        'cv2'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
            
            print(f"✓ {package} 已安装")
        except ImportError:
            missing_packages.append(package)
            print(f"✗ {package} 未安装")
    
    if missing_packages:
        print(f"\n缺少以下依赖包: {', '.join(missing_packages)}")
        print("请运行以下命令安装:")
        print(f"pip install {' '.join(missing_packages)}")
        return False
    
    return True

def create_spec_file():
    """创建PyInstaller spec文件"""
    
    # 获取当前脚本所在目录
    current_dir = Path(__file__).parent.absolute()
    gui_dir = current_dir / "neural_recorder_GUI"
    
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

# 添加项目路径到Python路径
project_path = r"{gui_dir}"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

block_cipher = None

a = Analysis(
    [r"{gui_dir / 'neural_recorder_GUI.py'}"],
    pathex=[r"{current_dir}", r"{gui_dir}"],
    binaries=[],
    datas=[
        # 包含所有Python模块
        (r"{gui_dir / 'neural_reader.py'}", '.'),
        (r"{gui_dir / 'neural_recorder_main_ui.py'}", '.'),
        (r"{gui_dir / 'RFPowerControl.py'}", '.'),
        (r"{gui_dir / 'camera_module.py'}", '.'),
        (r"{gui_dir / 'optimized_habits_panel.py'}", '.'),
        (r"{gui_dir / 'path_utils.py'}", '.'),
    ],
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtWidgets', 
        'PyQt6.QtGui',
        'PyQt6.sip',
        'pyqtgraph',
        'numpy',
        'scipy',
        'scipy.signal',
        'scipy.fft',
        'scipy.fftpack',
        'scipy.special',
        'scipy.integrate',
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
    hooksconfig={{}},
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
'''
    
    spec_file_path = current_dir / "neural_recorder_gui.spec"
    with open(spec_file_path, 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print(f"已创建spec文件: {spec_file_path}")
    return spec_file_path

def build_executable():
    """构建可执行文件"""
    current_dir = Path(__file__).parent.absolute()
    
    # 检查依赖
    print("检查依赖包...")
    if not check_dependencies():
        return False
    
    # 创建spec文件
    print("创建PyInstaller配置文件...")
    spec_file = create_spec_file()
    
    # 清理之前的构建
    build_dir = current_dir / "build"
    dist_dir = current_dir / "dist"
    
    if build_dir.exists():
        print("清理之前的构建文件...")
        shutil.rmtree(build_dir)
    
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    
    # 运行PyInstaller
    print("开始构建可执行文件...")
    try:
        cmd = [
            sys.executable, '-m', 'PyInstaller',
            '--clean',
            '--noconfirm',
            str(spec_file)
        ]
        
        print(f"执行命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=current_dir, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✓ 构建成功!")
            exe_path = dist_dir / "NeuralRecorderGUI.exe"
            if exe_path.exists():
                print(f"可执行文件位置: {exe_path}")
                print(f"文件大小: {exe_path.stat().st_size / (1024*1024):.1f} MB")
                
                # 创建启动脚本
                create_launcher_script(current_dir)
                
                return True
            else:
                print("✗ 构建失败: 找不到生成的exe文件")
                return False
        else:
            print("✗ 构建失败:")
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            return False
            
    except Exception as e:
        print(f"✗ 构建过程中出现错误: {e}")
        return False

def create_launcher_script(base_dir):
    """创建启动脚本"""
    launcher_content = '''@echo off
echo Starting Neural Recorder GUI...
cd /d "%~dp0"
if exist "dist\\NeuralRecorderGUI.exe" (
    start "" "dist\\NeuralRecorderGUI.exe"
) else (
    echo Error: NeuralRecorderGUI.exe not found!
    pause
)
'''
    
    launcher_path = base_dir / "start_neural_recorder.bat"
    with open(launcher_path, 'w', encoding='utf-8') as f:
        f.write(launcher_content)
    
    print(f"已创建启动脚本: {launcher_path}")

def create_requirements_file():
    """创建requirements.txt文件"""
    current_dir = Path(__file__).parent.absolute()
    
    requirements_content = '''# Neural Recorder GUI 依赖包
PyQt6>=6.4.0
pyqtgraph>=0.13.0
numpy>=1.21.0
scipy>=1.7.0
pyserial>=3.5
opencv-python>=4.5.0
pyinstaller>=5.0.0
'''
    
    requirements_path = current_dir / "requirements.txt"
    with open(requirements_path, 'w', encoding='utf-8') as f:
        f.write(requirements_content)
    
    print(f"已创建依赖文件: {requirements_path}")

def main():
    """主函数"""
    print("=" * 60)
    print("Neural Recorder GUI 打包工具")
    print("=" * 60)
    
    # 创建requirements文件
    create_requirements_file()
    
    # 构建可执行文件
    success = build_executable()
    
    if success:
        print("\n" + "=" * 60)
        print("✓ 打包完成!")
        print("=" * 60)
        print("使用说明:")
        print("1. 可执行文件位于 dist/NeuralRecorderGUI.exe")
        print("2. 可以直接运行 start_neural_recorder.bat 启动程序")
        print("3. 首次运行可能需要一些时间来解压和初始化")
        print("4. 确保目标机器上有必要的Visual C++ Redistributable")
        print("\n注意事项:")
        print("- 生成的exe文件包含了所有依赖，可以在没有Python环境的机器上运行")
        print("- 如果遇到问题，可以在命令行中直接运行exe文件查看错误信息")
    else:
        print("\n" + "=" * 60)
        print("✗ 打包失败!")
        print("=" * 60)
        print("请检查:")
        print("1. 所有依赖包是否正确安装")
        print("2. Python环境是否正常")
        print("3. 是否有足够的磁盘空间")
        print("4. 查看上面的错误信息进行调试")

if __name__ == "__main__":
    main()