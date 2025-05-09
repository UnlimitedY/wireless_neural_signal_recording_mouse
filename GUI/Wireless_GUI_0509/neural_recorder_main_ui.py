import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QLabel, QWidget, QTabWidget, QGroupBox,
    QGridLayout, QSizePolicy, QCheckBox, QFrame, QFileDialog, 
    QSpinBox, QDoubleSpinBox, QMessageBox, QLineEdit, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPalette, QColor, QFont, QIcon

class SerialConnectionDialog(QDialog):
    connection_established = pyqtSignal(str) # Signal to emit when connection is made

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Serial port connection")
        self.setMinimumWidth(350)
        self.setMinimumHeight(180)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # 标题
        title_label = QLabel("Please select a serial port")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # Serial port selection
        self.serial_ports_combobox = QComboBox()
        self.serial_ports_combobox.setMinimumHeight(30)
        self.refresh_serial_ports() # Initial population

        refresh_button = QPushButton("Read ports")
        refresh_button.setMinimumHeight(30)
        refresh_button.clicked.connect(self.refresh_serial_ports)

        serial_layout = QHBoxLayout()
        serial_layout.addWidget(QLabel("Serial ports:"))
        serial_layout.addWidget(self.serial_ports_combobox, 1)
        serial_layout.addWidget(refresh_button)
        layout.addLayout(serial_layout)

        # Connect/Disconnect buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        self.connect_button = QPushButton("Connect")
        self.connect_button.setMinimumHeight(35)
        self.connect_button.clicked.connect(self.attempt_connection)
        
        self.disconnect_button = QPushButton("disconnect")
        self.disconnect_button.setMinimumHeight(35)
        self.disconnect_button.clicked.connect(self.attempt_disconnection)
        self.disconnect_button.setEnabled(False)

        button_layout.addWidget(self.connect_button)
        button_layout.addWidget(self.disconnect_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)
        self.selected_port = None

    def refresh_serial_ports(self):
        self.serial_ports_combobox.clear()
        try:
            from serial.tools.list_ports import comports
            ports = [port.device for port in comports()]
            if not ports:
                self.serial_ports_combobox.addItem("There are no available serial ports")
            else:
                self.serial_ports_combobox.addItems(ports)
        except ImportError:
            print("simulated ports!!!!")
            mock_ports = [f"COM{i}" for i in range(1, 5)]  # 模拟数据
            if not mock_ports:
                self.serial_ports_combobox.addItem("There are no available serial ports")
                self.connect_button.setEnabled(False)
            else:
                self.serial_ports_combobox.addItems(mock_ports)
                self.connect_button.setEnabled(True)


    def attempt_connection(self):
        port = self.serial_ports_combobox.currentText()
        if port and port != "There are no available serial ports":
            # Simulate connection success
            print(f"尝试连接到 {port}...")
            self.selected_port = port
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)
            self.serial_ports_combobox.setEnabled(False)
            self.connection_established.emit(self.selected_port) # Emit signal
            self.accept() # Close dialog with QDialog.Accepted status
        else:
            print("未选择串口或无可用串口")
            # Optionally show a QMessageBox error

    def attempt_disconnection(self):
        if self.selected_port:
            print(f"断开与 {self.selected_port} 的连接...")
            # In a real app, you'd close the serial connection here
            self.selected_port = None
            if hasattr(self, 'connect_button'):
                self.connect_button.setEnabled(True)
            if hasattr(self, 'disconnect_button'):
                self.disconnect_button.setEnabled(False)
            if hasattr(self, 'serial_ports_combobox'):
                self.serial_ports_combobox.setEnabled(True)
            print("已断开连接")
            # self.reject() # Or handle as needed, maybe just update UI

    def closeEvent(self, event):
        # 添加关闭确认对话框
        from PyQt6.QtWidgets import QMessageBox
        
        reply = QMessageBox.question(
            self, 
            'check quit', 
            'Are you sure to quit?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 处理关闭前的清理工作
            print("主窗口关闭。")
            if self.selected_port:  # 修改这里，使用 selected_port 而不是 connected_port
                print(f"确保与 {self.selected_port} 的连接已断开。")
            event.accept()
        else:
            event.ignore()
        # Ensure disconnection if window is closed while connected
        if self.selected_port:
            self.attempt_disconnection()
        super().closeEvent(event)





class BaseDisplayTab(QWidget):
    """所有显示选项卡的基类"""
    def __init__(self, title="show displayTab", parent=None):
        super().__init__(parent)
        self.title = title
        self.setup_ui()
        self.populate_controls()
        
    def setup_ui(self):
        """设置基本UI布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # 使用QSplitter分割控制面板和图表区域
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 控制面板 - 缩小控制面板
        self.control_panel = QGroupBox("Control panel")
        self.control_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.control_panel.setMaximumHeight(150)  # 限制最大高度
        self.control_panel_layout = QGridLayout(self.control_panel)
        self.control_panel_layout.setContentsMargins(5, 5, 5, 5)
        self.control_panel_layout.setSpacing(5)
        splitter.addWidget(self.control_panel)
        
        # 图表区域 - 增大图表区域
        self.chart_area = QWidget()
        self.chart_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.chart_layout = QVBoxLayout(self.chart_area)
        self.chart_layout.setContentsMargins(0, 0, 0, 0)
        
        # 添加图表容器
        self.chart_container = QFrame()
        self.chart_container.setFrameShape(QFrame.Shape.StyledPanel)
        self.chart_container.setStyleSheet("background-color: #F5F5F5; border-radius: 5px;")
        self.chart_container.setMinimumHeight(400)
        self.chart_container_layout = QVBoxLayout(self.chart_container)
        
        self.chart_layout.addWidget(self.chart_container)
        splitter.addWidget(self.chart_area)
        
        # 设置分割器的初始大小比例 (20% 控制面板, 80% 图表)
        splitter.setSizes([150, 600])
        
        main_layout.addWidget(splitter)
        
    def populate_controls(self):
        """填充控制面板，子类应重写此方法"""
        pass
        
    def update_chart(self, data):
        """更新图表，子类应重写此方法"""
        pass
        
    def select_file(self):
        """选择文件保存路径"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存数据文件", "", "npy文件 (*.npy);;所有文件 (*)"
        )
        if file_path:
            self.file_path_label.setText(file_path)
            
    def start_save(self):
        """开始保存数据"""
        if hasattr(self, 'file_path_label') and self.file_path_label.text() != "File path don't selected":
            self.start_save_button.setEnabled(False)
            self.stop_save_button.setEnabled(True)
            print(f"开始保存数据到 {self.file_path_label.text()}")
        else:
            QMessageBox.warning(self, "warning", "Select file path first!")
            
    def stop_save(self):
        """停止保存数据"""
        self.start_save_button.setEnabled(True)
        self.stop_save_button.setEnabled(False)
        print("停止保存数据")

class LfpTab(BaseDisplayTab):
    def __init__(self, parent=None):
        super().__init__("16 channels LFP signal", parent)

    def populate_controls(self):
        # 文件保存功能 - 简化布局
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("File:"))
        self.file_path_label = QLabel("File path don't selected")
        file_layout.addWidget(self.file_path_label, 1)
        
        self.select_file_button = QPushButton("Choice")
        self.select_file_button.setMaximumWidth(60)
        self.select_file_button.clicked.connect(self.select_file)
        file_layout.addWidget(self.select_file_button)
        
        self.control_panel_layout.addLayout(file_layout, 0, 0, 1, 2)
        
        # 文件保存和滤波器控制按钮 - 放在同一行
        button_layout = QHBoxLayout()
        
        self.start_save_button = QPushButton("Save Start")
        self.start_save_button.clicked.connect(self.start_save)
        button_layout.addWidget(self.start_save_button)
        
        self.stop_save_button = QPushButton("Save Stop")
        self.stop_save_button.clicked.connect(self.stop_save)
        self.stop_save_button.setEnabled(False)
        button_layout.addWidget(self.stop_save_button)
        
        # 滤波器设置
        button_layout.addWidget(QLabel("Low cutoff:"))
        self.low_cutoff = QComboBox()
        self.low_cutoff.addItems(["0.5", "4", "8", "13", "30", "None"])
        self.low_cutoff.setMaximumWidth(80)
        button_layout.addWidget(self.low_cutoff)
        
        button_layout.addWidget(QLabel("High cutoff:"))
        self.high_cutoff = QComboBox()
        self.high_cutoff.addItems(["4", "8", "13", "30", "None"])
        self.high_cutoff.setMaximumWidth(80)
        button_layout.addWidget(self.high_cutoff)
        
        self.enable_filter_button = QPushButton("filter enable")
        self.enable_filter_button.clicked.connect(self.enable_filter)
        button_layout.addWidget(self.enable_filter_button)
        
        self.disable_filter_button = QPushButton("filter disable")
        self.disable_filter_button.clicked.connect(self.disable_filter)
        self.disable_filter_button.setEnabled(False)
        button_layout.addWidget(self.disable_filter_button)
        
        self.control_panel_layout.addLayout(button_layout, 1, 0, 1, 2)
    
    def enable_filter(self):
        """启用滤波器"""
        low = self.low_cutoff.currentText()
        high = self.high_cutoff.currentText()
        print(f"启用滤波器: {low} - {high}")
        self.enable_filter_button.setEnabled(False)
        self.disable_filter_button.setEnabled(True)
        
    def disable_filter(self):
        """禁用滤波器"""
        print("禁用滤波器")
        self.enable_filter_button.setEnabled(True)
        self.disable_filter_button.setEnabled(False)

class Spike4ChTab(BaseDisplayTab):
    def __init__(self, parent=None):
        super().__init__("4 channels Spike signal", parent)

    def populate_controls(self):
        # 文件保存功能 - 简化布局
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("File:"))
        self.file_path_label = QLabel("file path don't selected")
        file_layout.addWidget(self.file_path_label, 1)
        
        self.select_file_button = QPushButton("Choice")
        self.select_file_button.setMaximumWidth(60)
        self.select_file_button.clicked.connect(self.select_file)
        file_layout.addWidget(self.select_file_button)
        
        self.control_panel_layout.addLayout(file_layout, 0, 0, 1, 4)
        
        # 文件保存控制按钮
        button_layout = QHBoxLayout()
        self.start_save_button = QPushButton("Save Start")
        self.start_save_button.clicked.connect(self.start_save)
        button_layout.addWidget(self.start_save_button)
        
        self.stop_save_button = QPushButton("Save Stop")
        self.stop_save_button.clicked.connect(self.stop_save)
        self.stop_save_button.setEnabled(False)
        button_layout.addWidget(self.stop_save_button)
        
        # 4通道选择功能 - 放在同一行
        button_layout.addWidget(QLabel("Channel:"))
        
        self.channel_combos = []
        for i in range(4):
            button_layout.addWidget(QLabel(f"{i+1}:"))
            combo = QComboBox()
            combo.addItems([f"{j}" for j in range(16)])  # 0-15通道
            combo.setMaximumWidth(50)
            self.channel_combos.append(combo)
            button_layout.addWidget(combo)
        
        self.send_channels_button = QPushButton("Send")
        self.send_channels_button.clicked.connect(self.send_channels)
        button_layout.addWidget(self.send_channels_button)
        
        self.control_panel_layout.addLayout(button_layout, 1, 0, 1, 4)
        
    def select_file(self):
        # 这里应该使用QFileDialog来选择文件
        file_path = "C:/Data/spike4ch_recording.dat"  # 模拟选择的文件路径
        self.file_path_label.setText(file_path)
        print(f"选择文件保存路径: {file_path}")
        
    def start_save(self):
        print(f"开始保存文件: {self.file_path_label.text()}")
        self.start_save_button.setEnabled(False)
        self.stop_save_button.setEnabled(True)
        
    def stop_save(self):
        print("停止保存文件")
        self.start_save_button.setEnabled(True)
        self.stop_save_button.setEnabled(False)
        
    def send_channels(self):
        selected_channels = [combo.currentText() for combo in self.channel_combos]
        print(f"发送通道选择命令: {', '.join(selected_channels)}")
        # 在实际应用中，这里会发送命令到设备

class ImuTab(BaseDisplayTab):
    def __init__(self, parent=None):
        super().__init__("IMU signal", parent)

    def populate_controls(self):
        # 控制面板设置为空
        empty_label = QLabel("3-axis IMU signal")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.control_panel_layout.addWidget(empty_label, 0, 0)

class RasterTab(BaseDisplayTab):
    def __init__(self, parent=None):
        super().__init__("16 channels Raster signal", parent)

    def populate_controls(self):
        # 通道阈值设置 - 简化布局
        control_layout = QHBoxLayout()
        
        control_layout.addWidget(QLabel("Channel:"))
        self.channel_combo = QComboBox()
        self.channel_combo.addItems([f"Channel {i}" for i in range(16)])
        self.channel_combo.setMaximumWidth(100)
        self.channel_combo.currentIndexChanged.connect(self.channel_changed)
        control_layout.addWidget(self.channel_combo)
        
        control_layout.addWidget(QLabel("Threshold(negative):"))
        self.threshold_combo = QComboBox()
        self.threshold_combo.addItems(["50", "100", "150", "200", "500" ,"600", "700"])
        self.threshold_combo.setMaximumWidth(80)
        control_layout.addWidget(self.threshold_combo)
        
        self.auto_threshold_button = QPushButton("Auto threshold update")
        self.auto_threshold_button.clicked.connect(self.auto_threshold)
        control_layout.addWidget(self.auto_threshold_button)
        
        # 添加弹性空间
        control_layout.addStretch(1)
        
        self.control_panel_layout.addLayout(control_layout, 0, 0)
        
    def channel_changed(self, index):
        print(f"选择通道: {index + 1}")
        
    def auto_threshold(self):
        channel = self.channel_combo.currentText()
        threshold = self.threshold_combo.currentText()
        print(f"为{channel}设置自动阈值更新: {threshold}")

class Spike1ChTab(BaseDisplayTab):
    def __init__(self, parent=None):
        super().__init__("单通道 Spike 信号", parent)

    def populate_controls(self):
        # 简化布局
        control_layout = QHBoxLayout()
        
        control_layout.addWidget(QLabel("Select channel:"))
        self.channel_combo = QComboBox()
        self.channel_combo.addItems([f"Channel {i}" for i in range(16)])
        self.channel_combo.setMaximumWidth(100)
        control_layout.addWidget(self.channel_combo)
        
        self.send_command_button = QPushButton("Send")
        self.send_command_button.clicked.connect(self.send_command)
        control_layout.addWidget(self.send_command_button)
        
        # 添加弹性空间
        control_layout.addStretch(1)
        
        self.control_panel_layout.addLayout(control_layout, 0, 0)
        
    def send_command(self):
        channel = self.channel_combo.currentText()
        print(f"发送单通道选择命令: {channel}")
        # 在实际应用中，这里会发送命令到设备

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Neural Signal Recorder")
        self.setGeometry(100, 100, 1200, 800) # Default size

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        # Top Control Bar
        control_bar_widget = QWidget()
        control_bar_layout = QHBoxLayout(control_bar_widget)
        control_bar_layout.setContentsMargins(5, 5, 5, 5)
        control_bar_layout.setSpacing(10)
        
        # 控制按钮组 - 去除重复的采样模式选择
        control_group = QFrame()
        control_group.setFrameShape(QFrame.Shape.StyledPanel)
        control_group.setStyleSheet("QFrame { border-radius: 8px; background-color: #F0F0F0; }")
        control_group_layout = QHBoxLayout(control_group)
        control_group_layout.setContentsMargins(10, 5, 10, 5)
        control_group_layout.setSpacing(8)
        
        # 采样模式选择
        self.sampling_mode_label = QLabel("Neural recorder mode:")
        control_group_layout.addWidget(self.sampling_mode_label)
        
        self.sampling_mode_combo = QComboBox()
        self.sampling_mode_combo.addItems(["16 channels LFP", "single channel Spike" ,"4 channels Spike"])
        self.sampling_mode_combo.setCurrentIndex(0)
        control_group_layout.addWidget(self.sampling_mode_combo)
        
        self.start_sampling_button = QPushButton("Sample start")
        self.start_sampling_button.setMinimumHeight(35)
        self.start_sampling_button.clicked.connect(self.start_sampling)
        control_group_layout.addWidget(self.start_sampling_button)
        
        self.stop_sampling_button = QPushButton("Sample Stop")
        self.stop_sampling_button.setMinimumHeight(35)
        self.stop_sampling_button.setEnabled(False)
        self.stop_sampling_button.clicked.connect(self.stop_sampling)
        control_group_layout.addWidget(self.stop_sampling_button)
        
        control_bar_layout.addWidget(control_group)
        
        # 状态指示器组
        status_group = QFrame()
        status_group.setFrameShape(QFrame.Shape.StyledPanel)
        status_group.setStyleSheet("QFrame { border-radius: 8px; background-color: #F0F0F0; }")
        status_group_layout = QHBoxLayout(status_group)
        status_group_layout.setContentsMargins(10, 5, 10, 5)
        status_group_layout.setSpacing(8)
        
        # 电池状态下拉框
        self.battery_status_combo = QComboBox()
        self.battery_status_combo.addItems(["charging", "shipping", "Hiz"])
        self.battery_status_combo.setCurrentIndex(0)
        # self.battery_status_combo.currentIndexChanged.connect(self.battery_status_changed)
        status_group_layout.addWidget(self.battery_status_combo)
        
        # 更新电池状态按钮
        self.update_battery_button = QPushButton("battery_status")
        self.update_battery_button.clicked.connect(self.update_battery_status)
        status_group_layout.addWidget(self.update_battery_button)
        
        # RSSI值显示
        self.rssi_indicator = QLabel("RSSI: dBm")
        self.rssi_indicator.setFixedWidth(120)
        self.rssi_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rssi_indicator.setStyleSheet("background-color: #66BB6A; color: black; border-radius: 4px; padding: 5px;")
        status_group_layout.addWidget(self.rssi_indicator)
        
        # 丢包率显示
        self.packet_loss_indicator = QLabel("Loss: 0%")
        self.packet_loss_indicator.setFixedWidth(120)
        self.packet_loss_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.packet_loss_indicator.setStyleSheet("background-color: #66BB6A; color: black; border-radius: 4px; padding: 5px;")
        status_group_layout.addWidget(self.packet_loss_indicator)
        
        control_bar_layout.addWidget(status_group)
        
        main_layout.addWidget(control_bar_widget)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(line)
        
        # Tab Widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.tab_widget.setDocumentMode(True)
        
        self.lfp_tab = LfpTab()
        self.spike4ch_tab = Spike4ChTab()
        self.imu_tab = ImuTab()
        self.raster_tab = RasterTab()
        self.spike1ch_tab = Spike1ChTab()
        
        self.tab_widget.addTab(self.lfp_tab, "16 channels LFP")
        self.tab_widget.addTab(self.spike4ch_tab, "4 channels Spike")
        self.tab_widget.addTab(self.imu_tab, "IMU")
        self.tab_widget.addTab(self.raster_tab, "16 channels Raster")
        self.tab_widget.addTab(self.spike1ch_tab, "single channel Spike")
        
        self.tab_widget.currentChanged.connect(self.tab_changed)
        
        main_layout.addWidget(self.tab_widget)

        # 状态栏
        self.statusBar().showMessage("Ready")
    
    def tab_changed(self, index):
        """处理选项卡切换事件"""
        tab_titles = ["16 channels LFP", "4 channels Spike", "IMU", "16 channels Raster", "single channel Spike"]
        if 0 <= index < len(tab_titles):
            self.statusBar().showMessage(f"Current displayTab: {tab_titles[index]}")
        print(f"切换到选项卡: {index}")
    
    def start_sampling(self):
        """开始采样"""
        print("Sample begaining...")
        self.start_sampling_button.setEnabled(False)
        self.stop_sampling_button.setEnabled(True)
        
        self.statusBar().showMessage(f"Sampling")
    
    def stop_sampling(self):
        """停止采样"""
        print("Stop sampling...")
        self.start_sampling_button.setEnabled(True)
        self.stop_sampling_button.setEnabled(False)
        self.statusBar().showMessage("Sample stop")
    
    
    def update_battery_status(self):
        """更新电池状态"""
        print(f"发送电池状态更新命令: {self.battery_status_combo.currentText()}")
    
    def update_battery_indicator(self, level, PPM, PG):
        """更新电池状态指示器 charging status 表示颜色； 文字表示PPM状态"""
        color = "w"
        if level == 0: ## not charging
            color = "#FF5252"  # 红色
        elif level == 1: ## Pre-charging
            color = "#d96c58"  
        elif level == 2: ## CC charging fast charging
            color =  "#64B5F6"  # 蓝色
        elif level == 3: ## CV charging
            color = "#8ca164"  
        elif level == 4: ## Charging complete
            color = "#66BB6A"  # 绿色
        
        self.update_battery_button.setStyleSheet(f"background-color: {color}; color: black; border-radius: 4px; padding: 5px;")

        if(PPM == 1):
            PPM = "PPM"
        else:
            PPM = "NO PPM"

        if(PG == 1):
            PG = "PG"
        else:
            PG = "PF"

        self.update_battery_button.setText(PPM + " " + PG)
    
    def update_rssi(self, value):
        """更新RSSI值显示"""
        self.rssi_indicator.setText(f"RSSI: {-1 * value} dBm")
        if value < -90:
            color = "#FF5252"  # 红色 - 信号弱
        elif value < -70:
            color = "#FFD740"  # 黄色 - 信号中等
        else:
            color = "#66BB6A"  # 绿色 - 信号强
        self.rssi_indicator.setStyleSheet(f"background-color: {color}; color: black; border-radius: 4px; padding: 5px;")
    
    def update_packet_loss(self, value):
        """更新丢包率显示"""
        self.packet_loss_indicator.setText(f"Loss: {value}%")
        if value > 10:
            color = "#FF5252"  # 红色 - 丢包率高
        elif value > 5:
            color = "#FFD740"  # 黄色 - 丢包率中等
        else:
            color = "#66BB6A"  # 绿色 - 丢包率低
        self.packet_loss_indicator.setStyleSheet(f"background-color: {color}; color: black; border-radius: 4px; padding: 5px;")
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        reply = QMessageBox.question(
            self, 
            'Are you sure you want to quit?',
            'Check neural recorder have been Stopped', 
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            
                # 处理关闭前的清理工作
                print("主窗口关闭。")
                event.accept()
        else:
            event.ignore()
