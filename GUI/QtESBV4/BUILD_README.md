# Neural Recorder GUI 打包说明

本文档说明如何将 Neural Recorder GUI 打包为独立的 Windows 可执行文件(.exe)。

## 文件说明

- `build_exe.py` - 完整的打包脚本，包含详细配置
- `simple_build.py` - 简化的打包脚本，快速打包
- `install_dependencies.py` - 依赖安装脚本
- `requirements.txt` - 依赖包列表（由build_exe.py自动生成）

## 快速开始

### 方法一：自动安装依赖并打包

```bash
# 1. 安装依赖
python install_dependencies.py

# 2. 完整打包（推荐）
python build_exe.py
```

### 方法二：手动安装依赖

```bash
# 1. 安装PyInstaller和其他依赖
pip install pyinstaller PyQt6 pyqtgraph numpy scipy pyserial opencv-python

# 2. 简化打包
python simple_build.py
```

## 详细说明

### 1. 依赖要求

打包需要以下Python包：
- `PyQt6` - GUI框架
- `pyqtgraph` - 图表绘制
- `numpy` - 数值计算
- `scipy` - 科学计算
- `pyserial` - 串口通信
- `opencv-python` - 图像处理
- `pyinstaller` - 打包工具

### 2. 打包选项

#### 完整打包 (build_exe.py)
- 创建详细的PyInstaller配置文件
- 包含所有必要的数据文件和隐藏导入
- 生成 `dist/NeuralRecorderGUI.exe`
- 创建启动脚本 `start_neural_recorder.bat`
- 适合生产环境使用

#### 简化打包 (simple_build.py)
- 使用PyInstaller的基本命令
- 快速打包，适合测试
- 生成单个exe文件
- 可能需要手动处理一些依赖问题

### 3. 生成的文件

打包成功后会生成：
- `NeuralRecorderGUI.exe` - 主程序
- `start_neural_recorder.bat` - 启动脚本（仅完整打包）
- `requirements.txt` - 依赖列表

### 4. 重要文件

打包会自动包含以下重要文件：
- `IIR_1order_highpass_250Hz_coeffi.fcf` - 高通滤波器系数
- `IIR_1order_lowpass_12Hz_coeffi.fcf` - 低通滤波器系数  
- `IIR_2order_lowpass_250Hz_coeffi.fcf` - 二阶低通滤波器系数

## 使用说明

### 运行打包后的程序

1. **直接运行**：双击 `NeuralRecorderGUI.exe`
2. **使用启动脚本**：双击 `start_neural_recorder.bat`（如果存在）
3. **命令行运行**：在命令行中运行exe文件可以看到详细的错误信息

### 首次运行

- 首次启动可能需要较长时间（10-30秒）
- 程序会自动解压必要的文件到临时目录
- 确保有足够的磁盘空间（至少500MB）

### 部署到其他机器

生成的exe文件可以在没有Python环境的Windows机器上运行，但需要：

1. **Visual C++ Redistributable**：确保目标机器安装了Microsoft Visual C++ Redistributable
2. **滤波器文件**：确保.fcf文件与exe在同一目录（通常已自动包含）
3. **权限**：确保有足够的文件系统权限

## 故障排除

### 常见问题

1. **导入错误**
   ```
   ModuleNotFoundError: No module named 'xxx'
   ```
   解决：在打包脚本中添加 `--hidden-import=xxx`

2. **文件未找到**
   ```
   FileNotFoundError: [Errno 2] No such file or directory: 'xxx.fcf'
   ```
   解决：确保数据文件正确添加到 `--add-data` 参数中

3. **PyQt6相关错误**
   ```
   ImportError: DLL load failed
   ```
   解决：确保PyQt6版本兼容，尝试重新安装

4. **打包失败**
   - 检查Python环境是否正常
   - 确保有足够的磁盘空间
   - 尝试清理之前的构建文件

### 调试技巧

1. **查看详细错误**：在命令行中运行exe文件
2. **启用控制台**：在spec文件中设置 `console=True`
3. **检查依赖**：使用 `install_dependencies.py` 验证所有包都已安装
4. **逐步排查**：先确保Python脚本能正常运行，再进行打包

## 高级配置

### 自定义图标

在 `build_exe.py` 中修改：
```python
icon=r"path/to/your/icon.ico"
```

### 优化文件大小

1. 使用 `--exclude-module` 排除不需要的模块
2. 启用UPX压缩（已在脚本中启用）
3. 使用 `--onefile` 创建单文件版本

### 添加版本信息

创建版本信息文件并在spec中引用：
```python
version='version_info.txt'
```

## 联系支持

如果遇到问题，请检查：
1. Python版本（推荐3.8+）
2. 所有依赖包的版本兼容性
3. Windows版本兼容性
4. 防病毒软件是否误报

---

**注意**：打包后的exe文件较大（通常100-300MB），这是正常的，因为包含了完整的Python运行时和所有依赖库。