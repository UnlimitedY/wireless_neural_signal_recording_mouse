#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Neural Recorder GUI 依赖安装脚本
自动安装打包所需的所有依赖包

使用方法:
python install_dependencies.py
"""

import subprocess
import sys
import importlib

def install_package(package_name):
    """安装指定的包"""
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', package_name])
        return True
    except subprocess.CalledProcessError:
        return False

def check_package(package_name, import_name=None):
    """检查包是否已安装"""
    if import_name is None:
        import_name = package_name.replace('-', '_').lower()
    
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False

def main():
    """主函数"""
    print("Neural Recorder GUI 依赖安装工具")
    print("="*50)
    
    # 定义所需的包
    required_packages = [
        ('PyQt6', 'PyQt6'),
        ('pyqtgraph', 'pyqtgraph'),
        ('numpy', 'numpy'),
        ('scipy', 'scipy'),
        ('pyserial', 'serial'),
        ('opencv-python', 'cv2'),
        ('pyinstaller', 'PyInstaller')
    ]
    
    print("检查已安装的包...")
    
    to_install = []
    for package_name, import_name in required_packages:
        if check_package(package_name, import_name):
            print(f"✓ {package_name} 已安装")
        else:
            print(f"✗ {package_name} 未安装")
            to_install.append(package_name)
    
    if not to_install:
        print("\n所有依赖包都已安装!")
        return
    
    print(f"\n需要安装 {len(to_install)} 个包:")
    for package in to_install:
        print(f"  - {package}")
    
    # 询问用户是否继续
    response = input("\n是否继续安装? (y/n): ").lower().strip()
    if response not in ['y', 'yes', '是']:
        print("安装已取消")
        return
    
    print("\n开始安装依赖包...")
    
    # 升级pip
    print("升级pip...")
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'])
        print("✓ pip 升级完成")
    except subprocess.CalledProcessError:
        print("⚠ pip 升级失败，继续安装其他包...")
    
    # 安装包
    failed_packages = []
    for package in to_install:
        print(f"\n安装 {package}...")
        if install_package(package):
            print(f"✓ {package} 安装成功")
        else:
            print(f"✗ {package} 安装失败")
            failed_packages.append(package)
    
    # 总结
    print("\n" + "="*50)
    if failed_packages:
        print("安装完成，但以下包安装失败:")
        for package in failed_packages:
            print(f"  - {package}")
        print("\n请手动安装失败的包:")
        print(f"pip install {' '.join(failed_packages)}")
    else:
        print("✓ 所有依赖包安装成功!")
        print("\n现在可以运行打包脚本:")
        print("  python build_exe.py        # 完整打包")
        print("  python simple_build.py     # 简化打包")

if __name__ == "__main__":
    main()