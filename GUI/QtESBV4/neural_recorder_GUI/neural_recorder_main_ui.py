import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QLabel, QWidget, QTabWidget, QGroupBox,
    QGridLayout, QSizePolicy, QCheckBox, QFrame, QFileDialog, 
    QSpinBox, QDoubleSpinBox, QMessageBox, QLineEdit, QSplitter,
    QProgressBar, QTextBrowser
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QDateTime
from PyQt6.QtGui import QPalette, QColor, QFont, QIcon, QImage, QPixmap
import cv2
import os
from camera_module import CameraModule, get_available_cameras
from optimized_habits_panel import OptimizedHabitsPanel
from path_utils import get_default_save_path, get_data_directory
import pyqtgraph as pg
import time
import numpy as np

class TimelineWidget(QWidget):
    """
    Widget to display 24-hour timeline of recording modes and battery level.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Plot Widget
        self.plot_widget = pg.PlotWidget()
        self.layout.addWidget(self.plot_widget)
        
        # Set background to white
        self.plot_widget.setBackground('w')
        
        # Style axes for white background
        styles = {'color': 'k', 'font-size': '10pt'}
        self.plot_widget.setLabel('left', 'Battery', units='%', **styles)
        self.plot_widget.setLabel('bottom', 'Time', **styles)
        # self.plot_widget.setTitle("24-Hour Timeline: Battery & Recording Modes", color='k', size='12pt')
        
        # Axis pens
        self.plot_widget.getAxis('bottom').setPen(pg.mkPen('k'))
        self.plot_widget.getAxis('bottom').setTextPen(pg.mkPen('k'))
        self.plot_widget.getAxis('left').setPen(pg.mkPen('k'))
        self.plot_widget.getAxis('left').setTextPen(pg.mkPen('k'))

        self.plot_widget.setYRange(0, 105)
        
        # Use DateAxisItem for X axis
        self.date_axis = pg.DateAxisItem(orientation='bottom')
        self.date_axis.setPen(pg.mkPen('k'))
        self.date_axis.setTextPen(pg.mkPen('k'))
        self.plot_widget.setAxisItems({'bottom': self.date_axis})
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Data storage
        # Battery: list of (timestamp, value)
        self.battery_timestamps = []
        self.battery_values = []
        # Battery curve will be updated dynamically based on level
        self.battery_curve = self.plot_widget.plot(pen=pg.mkPen(color='k', width=2), name='Battery')
        
        # RF Power: list of (timestamp, value)
        self.rf_timestamps = []
        self.rf_values = []
        # Magenta for RF Power
        self.rf_curve = self.plot_widget.plot(pen=pg.mkPen(color='k', width=1, style=Qt.PenStyle.DashLine), name='RF Power')
        
        # Modes: list of LinearRegionItem
        self.mode_regions = [] 
        self.current_mode_region = None
        self.current_mode_start = None
        self.current_mode = None
        
        # Colors for different modes (Increased opacity for better visibility)
        self.mode_colors = {
            "Idle": (220, 220, 220, 255),         # Solid Light Grey
            "16 channels LFP": (100, 149, 237, 255),   # Cornflower Blue
            "single channel Spike": (255, 99, 71, 255), # Tomato Red
            "4 channels Spike": (60, 179, 113, 255),  # Medium Sea Green
            "ESA&MUA": (255, 165, 0, 255)          # Orange
        }
        
        # Legend
        self.legend = self.plot_widget.addLegend()
        self.legend.setBrush(pg.mkBrush(255, 255, 255, 200)) # Semi-transparent white background for legend
        self.legend.setLabelTextColor('k')

    def get_battery_color(self, level):
        """
        Return color based on battery level (5 levels, 20% intervals)
        Ensure high contrast with mode colors.
        """
        if level > 80:
            return '#006400'  # Dark Green (High)
        elif level > 60:
            return '#228B22'  # Forest Green
        elif level > 40:
            return '#DAA520'  # Goldenrod (Medium)
        elif level > 20:
            return '#D2691E'  # Chocolate
        else:
            return '#8B0000'  # Dark Red (Low)

    def update_data(self, timestamp, battery_level, mode, rf_status):
        """
        Update the timeline with new data.
        timestamp: unix timestamp (float)
        battery_level: percentage (0-100)
        mode: string (current recording mode)
        rf_status: int (1 for OFF, 2 for ON) -> mapped to 0 or 100
        """
        
        # Optimize updates: only update if data changed or enough time passed (e.g., 1 min)
        # However, for battery curve we want continuous points for plot. 
        # But we can limit the resolution if needed.
        # For now, let's keep adding points but ensure efficient memory management.

        # 1. Update Battery Data
        self.battery_timestamps.append(timestamp)
        self.battery_values.append(battery_level)
        
        # 2. Update RF Data
        self.rf_timestamps.append(timestamp)
        # Map RF status: 2 (ON) -> 100, 1 (OFF) -> 0, others -> 0
        rf_value = 100 if rf_status == 2 else 0
        self.rf_values.append(rf_value)
        
        # Remove old data (> 24 hours)
        cutoff_time = timestamp - 24 * 3600
        
        # Efficiently remove old battery data
        # Use bisect or simpler method if array is sorted (it is sorted by time)
        # Simple loop popping from front is O(N) but N is small (1 point per update)
        # However, pop(0) on list is O(N). If array grows large (e.g. 1s update -> 86400 points), this is slow.
        # Optimization: Use deque or just slice when it grows too large.
        # Or better: batch remove.
        
        # Check if we need to cleanup (e.g. every 100 updates)
        if len(self.battery_timestamps) > 1000 and self.battery_timestamps[0] < cutoff_time:
             # Find index to slice
             # Since timestamps are sorted, we can find the first index >= cutoff_time
             import bisect
             idx = bisect.bisect_left(self.battery_timestamps, cutoff_time)
             if idx > 0:
                 # Slice lists to remove old data
                 # This creates new list objects but releases old ones
                 self.battery_timestamps = self.battery_timestamps[idx:]
                 self.battery_values = self.battery_values[idx:]
                 
                 # Sync RF data (assuming sync updates)
                 if len(self.rf_timestamps) >= idx:
                     self.rf_timestamps = self.rf_timestamps[idx:]
                     self.rf_values = self.rf_values[idx:]
                 
                 # Force garbage collection occasionally if needed
                 # import gc
                 # gc.collect()
        
        # Update curves
        # Optimization: Downsample for display if too many points?
        # PyQtGraph handles large datasets relatively well, but 24h at 1s resolution is ~86k points.
        # It should be fine.
        
        # Update battery curve color based on current level
        battery_color = self.get_battery_color(battery_level)
        self.battery_curve.setData(self.battery_timestamps, self.battery_values, pen=pg.mkPen(color=battery_color, width=3))
        
        # Update RF curve
        self.rf_curve.setData(self.rf_timestamps, self.rf_values)
        
        # 3. Update Mode Regions
        if self.current_mode != mode:
            # Finish previous mode region
            if self.current_mode_region:
                self.current_mode_region.setRegion([self.current_mode_start, timestamp])
                
            # Start new mode region
            self.current_mode = mode
            self.current_mode_start = timestamp
            
            # Use get() with default but ensure color is tuple
            color = self.mode_colors.get(mode, (200, 200, 200, 255))
            
            # LinearRegionItem for background color
            region = pg.LinearRegionItem(values=[timestamp, timestamp], brush=color, movable=False)
            # Remove lines for cleaner look
            for line in region.lines:
                line.setPen(pg.mkPen(None))
                
            self.plot_widget.addItem(region)
            # Push to back so grid and curve are on top
            region.setZValue(-10) 
            
            self.current_mode_region = region
            self.mode_regions.append(region)
            
        else:
            # Extend current region
            if self.current_mode_region:
                self.current_mode_region.setRegion([self.current_mode_start, timestamp])
            elif mode: # First time initialization if mode is set
                 self.current_mode = mode
                 self.current_mode_start = timestamp
                 color = self.mode_colors.get(mode, (200, 200, 200, 255))
                 region = pg.LinearRegionItem(values=[timestamp, timestamp], brush=color, movable=False)
                 for line in region.lines:
                    line.setPen(pg.mkPen(None))
                 self.plot_widget.addItem(region)
                 region.setZValue(-10)
                 self.current_mode_region = region
                 self.mode_regions.append(region)

        # Cleanup old mode regions
        # Optimization: only check periodically or if many regions exist
        if len(self.mode_regions) > 10: 
            regions_to_remove = []
            # Check only the oldest few
            for i in range(min(len(self.mode_regions), 5)):
                region = self.mode_regions[i]
                r_start, r_end = region.getRegion()
                if r_end < cutoff_time:
                    self.plot_widget.removeItem(region)
                    regions_to_remove.append(region)
                elif r_start < cutoff_time:
                    # Truncate start
                    region.setRegion([cutoff_time, r_end])
            
            for region in regions_to_remove:
                self.mode_regions.remove(region)
            if region == self.current_mode_region:
                # This shouldn't happen for current region unless it's > 24 hours long and ends before cutoff? No.
                # If current region started > 24h ago, r_start < cutoff_time, so we truncate it.
                pass


import json

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
            print(f"Attempting connection to {port}...")
            self.selected_port = port
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)
            self.serial_ports_combobox.setEnabled(False)
            self.connection_established.emit(self.selected_port) # Emit signal
            self.accept() # Close dialog with QDialog.Accepted status
        else:
            print("No serial port selected or no ports available")
            self.accept()
            # Optionally show a QMessageBox error

    def attempt_disconnection(self):
        if self.selected_port:
            print(f"disconnect {self.selected_port} ...")
            # In a real app, you'd close the serial connection here
            self.selected_port = None
            if hasattr(self, 'connect_button'):
                self.connect_button.setEnabled(True)
            if hasattr(self, 'disconnect_button'):
                self.disconnect_button.setEnabled(False)
            if hasattr(self, 'serial_ports_combobox'):
                self.serial_ports_combobox.setEnabled(True)
            print("Disconnected")
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
            print("Main window closed.")
            if self.selected_port:  # 修改这里，使用 selected_port 而不是 connected_port
                print(f"Ensured the connection to {self.selected_port} is closed.")
            event.accept()
        else:
            event.ignore()
        # Ensure disconnection if window is closed while connected
        if self.selected_port:
            self.attempt_disconnection()
        super().closeEvent(event)





class BaseDisplayTab(QWidget):
    """Base class for all display tabs"""
    def __init__(self, title="show displayTab", parent=None):
        super().__init__(parent)
        self.title = title
        self.setup_ui()
        self.populate_controls()
        
    def setup_ui(self):
        """Set up base UI layout"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # 使用QSplitter分割控制面板和图表区域
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 控制面板 - 缩小控制面板
        self.control_panel = QGroupBox("Control panel")
        self.control_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.control_panel.setMaximumHeight(150)  # 提升控制面板最大高度以避免拥挤
        self.control_panel_layout = QGridLayout(self.control_panel)
        self.control_panel_layout.setContentsMargins(5, 5, 5, 5)
        self.control_panel_layout.setSpacing(8)
        splitter.addWidget(self.control_panel)
        
        # 图表区域 - 增大图表区域
        self.chart_area = QWidget()
        self.chart_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.chart_layout = QVBoxLayout(self.chart_area)
        self.chart_layout.setContentsMargins(0, 0, 0, 0)
        
        # 添加图表容器
        self.chart_container = QFrame()
        self.chart_container.setFrameShape(QFrame.Shape.StyledPanel)
        self.chart_container.setStyleSheet("background-color: #FFFFFF;") # #F5F5F5
        self.chart_container.setMinimumHeight(400)
        self.chart_container_layout = QVBoxLayout(self.chart_container)
        
        self.chart_layout.addWidget(self.chart_container)
        splitter.addWidget(self.chart_area)
        
        # 设置分割器的初始大小比例 (15% 控制面板, 85% 图表)
        splitter.setSizes([100, 800])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        
        main_layout.addWidget(splitter)
        
    def populate_controls(self):
        """Populate control panel (override in subclasses)"""
        pass
        
    def update_chart(self, data):
        """Update chart (override in subclasses)"""
        pass
        
    def select_file(self):
        """Select save path"""
        # 使用exe所在目录下的Data文件夹作为默认路径
        default_dir = get_data_directory()
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save data file", default_dir, "EDF Files (*.edf);;All Files (*)"
        )
        if file_path:
            self.file_path_label.setText(file_path)
            
    def start_save(self):
        """Start saving data"""
        if hasattr(self, 'file_path_label'): # and self.file_path_label.text() != "File path don't selected"
            self.start_save_button.setEnabled(False)
            self.stop_save_button.setEnabled(True)
            print(f"Start saving data to {self.file_path_label.text()}")
        else:
             # This base method might need to access main window for logging, 
             # but standard QMessageBox is used in base class. 
             # We can leave it or try to find parent main window.
             # For now, let's assume the subclasses handle specific logic or we pass parent correctly.
             # But wait, BaseDisplayTab is a QWidget. 
             # Let's try to find if it's main window
             window = self.window()
             if hasattr(window, "log_message"):
                 window.log_message("Warning: Select file path first!", level="warning")
             else:
                 QMessageBox.warning(self, "warning", "Select file path first!")
            
    def stop_save(self):
        """Stop saving data"""
        self.start_save_button.setEnabled(True)
        self.stop_save_button.setEnabled(False)
        print("Stop saving data")

class LfpTab(BaseDisplayTab):
    def __init__(self, parent=None):
        super().__init__("16 channels LFP+ESA signal", parent)

    def populate_controls(self):
        # LFP Control Row (File Selection + Save Controls)
        lfp_layout = QHBoxLayout()
        
        # File Selection Part
        lfp_layout.addWidget(QLabel("LFP File:"))
        self.lfp_file_path_label = QLabel("File path don't selected")
        # Ensure path label has some space but doesn't squash buttons too much, 
        # but here we use stretch 1 to let it take available space
        lfp_layout.addWidget(self.lfp_file_path_label, 1)
        
        self.lfp_select_file_button = QPushButton("Choice")
        self.lfp_select_file_button.setMaximumWidth(70)
        self.lfp_select_file_button.clicked.connect(self.select_lfp_file)
        lfp_layout.addWidget(self.lfp_select_file_button)
        
        # Separator
        lfp_layout.addSpacing(20)
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.VLine)
        line1.setFrameShadow(QFrame.Shadow.Sunken)
        lfp_layout.addWidget(line1)
        lfp_layout.addSpacing(20)
        
        # Save Controls Part
        self.start_save_button = QPushButton("LFP Save Start")
        lfp_layout.addWidget(self.start_save_button)
        
        self.stop_save_button = QPushButton("LFP Save Stop")
        self.stop_save_button.setEnabled(False)
        lfp_layout.addWidget(self.stop_save_button)
        
        self.lfp_progress_bar = QProgressBar()
        self.lfp_progress_bar.setRange(0, 100)
        self.lfp_progress_bar.setValue(0)
        self.lfp_progress_bar.setTextVisible(True)
        self.lfp_progress_bar.setFormat("%p%")
        self.lfp_progress_bar.setFixedWidth(120) # Fixed width for clearer layout
        lfp_layout.addWidget(self.lfp_progress_bar)
        
        self.control_panel_layout.addLayout(lfp_layout, 0, 0, 1, 2)

        # Mode3 Control Row (File Selection + Save Controls)
        mode3_layout = QHBoxLayout()
        
        # File Selection Part
        mode3_layout.addWidget(QLabel("Mode3 File:"))
        self.mode3_file_path_label = QLabel("File path don't selected")
        mode3_layout.addWidget(self.mode3_file_path_label, 1)
        
        self.mode3_select_file_button = QPushButton("Choice")
        self.mode3_select_file_button.setMaximumWidth(70)
        self.mode3_select_file_button.clicked.connect(self.select_mode3_file)
        mode3_layout.addWidget(self.mode3_select_file_button)
        
        # Separator
        mode3_layout.addSpacing(20)
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.VLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        mode3_layout.addWidget(line2)
        mode3_layout.addSpacing(20)
        
        # Save Controls Part
        self.start_save_mode3_button = QPushButton("Mode3 Save Start")
        mode3_layout.addWidget(self.start_save_mode3_button)
        
        self.stop_save_mode3_button = QPushButton("Mode3 Save Stop")
        self.stop_save_mode3_button.setEnabled(False)
        mode3_layout.addWidget(self.stop_save_mode3_button)
        
        self.mode3_progress_bar = QProgressBar()
        self.mode3_progress_bar.setRange(0, 100)
        self.mode3_progress_bar.setValue(0)
        self.mode3_progress_bar.setTextVisible(True)
        self.mode3_progress_bar.setFormat("%p%")
        self.mode3_progress_bar.setFixedWidth(120)
        mode3_layout.addWidget(self.mode3_progress_bar)
        
        self.control_panel_layout.addLayout(mode3_layout, 1, 0, 1, 2)

        # Filter Control Row
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Low cutoff:"))
        self.low_cutoff = QComboBox()
        self.low_cutoff.addItems(["0.5", "4", "8", "13", "30", "50", "100", "150",  "250", "300", "None"])
        self.low_cutoff.setMaximumWidth(90)
        filter_layout.addWidget(self.low_cutoff)

        filter_layout.addSpacing(20)

        filter_layout.addWidget(QLabel("High cutoff:"))
        self.high_cutoff = QComboBox()
        self.high_cutoff.addItems(["4", "8", "13", "30","50" ,"100", "150", "250",  "300", "None"])
        self.high_cutoff.setMaximumWidth(90)
        filter_layout.addWidget(self.high_cutoff)

        filter_layout.addSpacing(30)
        
        # Separator
        line3 = QFrame()
        line3.setFrameShape(QFrame.Shape.VLine)
        line3.setFrameShadow(QFrame.Shadow.Sunken)
        filter_layout.addWidget(line3)
        filter_layout.addSpacing(20)

        self.enable_filter_button = QPushButton("filter enable")
        self.enable_filter_button.clicked.connect(self.enable_filter)
        filter_layout.addWidget(self.enable_filter_button)

        self.disable_filter_button = QPushButton("filter disable")
        self.disable_filter_button.clicked.connect(self.disable_filter)
        self.disable_filter_button.setEnabled(False)
        filter_layout.addWidget(self.disable_filter_button)
        
        filter_layout.addStretch(1)
        self.control_panel_layout.addLayout(filter_layout, 2, 0, 1, 2)

        # Scale Control Row
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("LFP Scale:"))
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["100", "200", "500", "1000", "2000", "3000", "5000", "10000"])
        self.scale_combo.setCurrentText("2000")
        self.scale_combo.setMaximumWidth(90)
        scale_layout.addWidget(self.scale_combo)

        scale_layout.addSpacing(20)

        scale_layout.addWidget(QLabel("ESA Factor:"))
        self.esa_scale_combo = QComboBox()
        self.esa_scale_combo.addItems(["1", "2", "3", "4", "5", "10"])
        self.esa_scale_combo.setCurrentText("1")
        self.esa_scale_combo.setMaximumWidth(90)
        scale_layout.addWidget(self.esa_scale_combo)

        scale_layout.addSpacing(30)
        
        # Separator
        line4 = QFrame()
        line4.setFrameShape(QFrame.Shape.VLine)
        line4.setFrameShadow(QFrame.Shadow.Sunken)
        scale_layout.addWidget(line4)
        scale_layout.addSpacing(20)

        self.update_scale_button = QPushButton("Update Scale")
        scale_layout.addWidget(self.update_scale_button)
        
        scale_layout.addStretch(1)
        self.control_panel_layout.addLayout(scale_layout, 3, 0, 1, 2)
    
    def enable_filter(self):
        """Enable filter"""
        low = self.low_cutoff.currentText()
        high = self.high_cutoff.currentText()
        print(f"Enable filter: {low} - {high}")
        self.enable_filter_button.setEnabled(False)
        self.disable_filter_button.setEnabled(True)
        
    def disable_filter(self):
        """Disable filter"""
        print("Disable filter")
        self.enable_filter_button.setEnabled(True)
        self.disable_filter_button.setEnabled(False)

    def select_lfp_file(self):
        """Select LFP save path"""
        default_dir = get_data_directory()
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save LFP data file", default_dir, "EDF Files (*.edf);;All Files (*)"
        )
        if file_path:
            self.lfp_file_path_label.setText(file_path)

    def select_mode3_file(self):
        """Select Mode3 save path"""
        default_dir = get_data_directory()
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Mode3 data file", default_dir, "EDF Files (*.edf);;All Files (*)"
        )
        if file_path:
            self.mode3_file_path_label.setText(file_path)

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
        
        # Mode2 Progress Bar
        self.mode2_progress_bar = QProgressBar()
        self.mode2_progress_bar.setRange(0, 100)
        self.mode2_progress_bar.setValue(0)
        self.mode2_progress_bar.setTextVisible(True)
        self.mode2_progress_bar.setFormat("%p%")
        button_layout.addWidget(self.mode2_progress_bar)
        
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
        
    def send_channels(self):
        selected_channels = [combo.currentText() for combo in self.channel_combos]
        print(f"Send channel selection command: {', '.join(selected_channels)}")
        # 在实际应用中，这里会发送命令到设备

class ImuTab(BaseDisplayTab):
    def __init__(self, parent=None):
        super().__init__("IMU signal", parent)

    def populate_controls(self):
        # 控制面板设置为空
        empty_label = QLabel("6-axis IMU signal")
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
        print(f"Select channel: {index + 1}")
        
    def auto_threshold(self):
        channel = self.channel_combo.currentText()
        threshold = self.threshold_combo.currentText()
        print(f"Set auto-threshold update for {channel}: {threshold}")

class Spike1ChTab(BaseDisplayTab):
    def __init__(self, parent=None):
        super().__init__("Single-Channel Spike Signal", parent)

    def populate_controls(self):
        # 顶部文件保存布局（Mode1）
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("Mode1 File:"))
        self.mode1_file_path_label = QLabel("File path don't selected")
        file_layout.addWidget(self.mode1_file_path_label, 1)
        self.mode1_select_file_button = QPushButton("Choice")
        self.mode1_select_file_button.setMaximumWidth(60)
        self.mode1_select_file_button.clicked.connect(self.select_mode1_file)
        file_layout.addWidget(self.mode1_select_file_button)
        self.control_panel_layout.addLayout(file_layout, 0, 0, 1, 1)

        # 控制面板布局（滤波与通道控制）
        control_layout = QHBoxLayout()

        # 通道选择
        control_layout.addWidget(QLabel("Select channel:"))
        self.channel_combo = QComboBox()
        self.channel_combo.addItems([f"Channel {i}" for i in range(16)])
        self.channel_combo.setMaximumWidth(100)
        control_layout.addWidget(self.channel_combo)

        self.send_command_button = QPushButton("Send")
        self.send_command_button.clicked.connect(self.send_command)
        control_layout.addWidget(self.send_command_button)

        # 分隔线
        control_layout.addSpacing(15)

        # 滤波器设置
        self.filter_enable_checkbox = QCheckBox("Enable filter")
        control_layout.addWidget(self.filter_enable_checkbox)

        control_layout.addWidget(QLabel("Low cutoff (Hz):"))
        self.low_cut_spin = QDoubleSpinBox()
        self.low_cut_spin.setRange(1.0, 9999.0)
        self.low_cut_spin.setDecimals(1)
        self.low_cut_spin.setSingleStep(10.0)
        self.low_cut_spin.setValue(300.0)
        self.low_cut_spin.setMaximumWidth(100)
        control_layout.addWidget(self.low_cut_spin)

        control_layout.addWidget(QLabel("High cutoff (Hz):"))
        self.high_cut_spin = QDoubleSpinBox()
        self.high_cut_spin.setRange(10.0, 10000.0)
        self.high_cut_spin.setDecimals(1)
        self.high_cut_spin.setSingleStep(10.0)
        self.high_cut_spin.setValue(3000.0)
        self.high_cut_spin.setMaximumWidth(100)
        control_layout.addWidget(self.high_cut_spin)

        # 采样率选择
        control_layout.addWidget(QLabel("Sample rate:"))
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(["12500 Hz", "20000 Hz"])  # 对应 12.5k 与 20k
        self.sample_rate_combo.setCurrentIndex(1)  # 默认 20000 Hz
        self.sample_rate_combo.setMaximumWidth(110)
        control_layout.addWidget(self.sample_rate_combo)

        # 频谱按钮
        self.open_spectrum_button = QPushButton("Open Spectrum")
        control_layout.addWidget(self.open_spectrum_button)

        # Mode1保存按钮
        self.start_save_button = QPushButton("Mode1 Save Start")
        control_layout.addWidget(self.start_save_button)
        self.stop_save_button = QPushButton("Mode1 Save Stop")
        self.stop_save_button.setEnabled(False)
        control_layout.addWidget(self.stop_save_button)

        # Mode1 Progress Bar
        self.mode1_progress_bar = QProgressBar()
        self.mode1_progress_bar.setRange(0, 100)
        self.mode1_progress_bar.setValue(0)
        self.mode1_progress_bar.setTextVisible(True)
        self.mode1_progress_bar.setFormat("%p%")
        control_layout.addWidget(self.mode1_progress_bar)

        control_layout.addWidget(QLabel("RMS:"))
        self.rms_label = QLabel("-- uVrms")
        self.rms_label.setMinimumWidth(90)
        control_layout.addWidget(self.rms_label)

        # 添加弹性空间
        control_layout.addStretch(1)

        self.control_panel_layout.addLayout(control_layout, 1, 0)

    def select_mode1_file(self):
        """Select Mode1 save path"""
        default_dir = get_data_directory()
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Mode1 data file", default_dir, "EDF Files (*.edf);;All Files (*)"
        )
        if file_path:
            self.mode1_file_path_label.setText(file_path)
        
    def send_command(self):
        channel = self.channel_combo.currentText()
        print(f"Send single-channel selection command: {channel}")
        # 在实际应用中，这里会发送命令到设备

class HabitsTab(BaseDisplayTab):
    """Habits tracking panel tab"""
    def __init__(self, parent=None):
        super().__init__("Habits Tracking", parent)

    def populate_controls(self):
        """Populate control panel"""
        # Simplified control panel, main functionality is in HabitsPanel
        control_layout = QHBoxLayout()
        
        info_label = QLabel("Habits Tracking System - Data Recording & Analysis")
        info_label.setStyleSheet("font-weight: bold; color: #2E7D32;")
        control_layout.addWidget(info_label)
        
        # Add flexible space
        control_layout.addStretch(1)
        
        self.control_panel_layout.addLayout(control_layout, 0, 0)
        
        # 在图表容器中添加OptimizedHabitsPanel
        self.habits_panel = OptimizedHabitsPanel()
        self.chart_container_layout.addWidget(self.habits_panel)

class CameraWindow(QWidget):
    """Separate window for camera display"""
    closed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Camera View")
        self.resize(640, 480)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.video_label = QLabel("Camera not opened")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: black; color: white;")
        self.video_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.video_label)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Neural Signal Recorder")
        self.setGeometry(100, 100, 1200, 800) # Default size
        
        self.current_recording_mode = "Idle"

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        # 初始化摄像头相关属性
        self.is_camera_on = False
        self.is_camera_display_on = False
        self.is_recording = False

        self.video_save_path = None
        self.camera_module = CameraModule()  # 实例化CameraModule
        self.camera_timer = QTimer()  # 添加定时器用于更新摄像头画面
        self.camera_timer.timeout.connect(self.update_camera_frame)

        # 添加摄像头控制按钮
        camera_control_bar = QFrame()
        camera_control_bar.setFrameShape(QFrame.Shape.StyledPanel)
        camera_control_bar.setStyleSheet("QFrame { border-radius: 8px; background-color: #F0F0F0; }")
        camera_control_layout = QHBoxLayout(camera_control_bar)
        camera_control_layout.setContentsMargins(10, 5, 10, 5)
        camera_control_layout.setSpacing(8)
        
        self.camera_label = QLabel("camera:")
        camera_control_layout.addWidget(self.camera_label)
        
        # 摄像头选择下拉框
        self.camera_selection_combo = QComboBox()
        self.camera_selection_combo.setMinimumWidth(150)
        self.camera_selection_combo.setMinimumHeight(35)
        camera_control_layout.addWidget(self.camera_selection_combo)
        
        # 刷新摄像头列表按钮
        self.refresh_cameras_button = QPushButton("Refresh")
        self.refresh_cameras_button.setMinimumHeight(35)
        self.refresh_cameras_button.clicked.connect(self.refresh_camera_list)
        camera_control_layout.addWidget(self.refresh_cameras_button)
        
        self.toggle_camera_button = QPushButton("Open camera")
        self.toggle_camera_button.setMinimumHeight(35)
        self.toggle_camera_button.clicked.connect(self.toggle_camera)
        camera_control_layout.addWidget(self.toggle_camera_button)
        
        # 新增：独立的摄像头显示切换按钮
        self.toggle_camera_display_button = QPushButton("Show camera")
        self.toggle_camera_display_button.setMinimumHeight(35)
        self.toggle_camera_display_button.setEnabled(False)
        self.toggle_camera_display_button.clicked.connect(self.toggle_camera_display)
        camera_control_layout.addWidget(self.toggle_camera_display_button)
        
        self.toggle_recording_button = QPushButton("Start recording")
        self.toggle_recording_button.setMinimumHeight(35)
        self.toggle_recording_button.setEnabled(False)
        self.toggle_recording_button.clicked.connect(self.toggle_recording)
        camera_control_layout.addWidget(self.toggle_recording_button)
        
        self.select_save_path_button = QPushButton("Choice save path")
        self.select_save_path_button.setMinimumHeight(35)
        self.select_save_path_button.clicked.connect(self.select_video_save_path)
        camera_control_layout.addWidget(self.select_save_path_button)
        
        self.save_path_label = QLabel("File path don't selected")
        camera_control_layout.addWidget(self.save_path_label, 1)
        
        main_layout.addWidget(camera_control_bar)

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
        self.sampling_mode_combo.addItems(["16 channels LFP", "single channel Spike" ,"4 channels Spike", "ESA&MUA"])
        self.sampling_mode_combo.setCurrentIndex(0)
        control_group_layout.addWidget(self.sampling_mode_combo)
        
        self.start_sampling_button = QPushButton("Sample start")
        self.start_sampling_button.setMinimumHeight(35)
        self.start_sampling_button.clicked.connect(self.start_sampling)
        control_group_layout.addWidget(self.start_sampling_button)
        
        self.stop_sampling_button = QPushButton("Sample Stop")
        self.stop_sampling_button.setMinimumHeight(35)
        # self.stop_sampling_button.setEnabled(False)
        self.stop_sampling_button.clicked.connect(self.stop_sampling)
        control_group_layout.addWidget(self.stop_sampling_button)
        
        # 自动配置按钮
        self.auto_config_button = QPushButton("Auto Config")
        self.auto_config_button.setMinimumHeight(35)
        self.auto_config_button.clicked.connect(self.auto_configure_paths)
        control_group_layout.addWidget(self.auto_config_button)

        self.mode3_reref_mode_combo = QComboBox()
        self.mode3_reref_mode_combo.addItems(["Mode3 ReRef: OFF", "Mode3 ReRef: FAST", "Mode3 ReRef: STABLE"])
        self.mode3_reref_mode_combo.setCurrentIndex(0)
        self.mode3_reref_mode_combo.setMinimumHeight(35)
        self.mode3_reref_mode_combo.setStyleSheet("background-color: #F44336; color: white; border-radius: 4px;")
        control_group_layout.addWidget(self.mode3_reref_mode_combo)
        
        # Global Save Enable Button
        self.global_save_enable_button = QPushButton("Global Save: ON")
        self.global_save_enable_button.setCheckable(True)
        self.global_save_enable_button.setChecked(True)
        self.global_save_enable_button.setMinimumHeight(35)
        self.global_save_enable_button.clicked.connect(self.toggle_global_save)
        self.global_save_enable_button.setStyleSheet("background-color: #4CAF50; color: white; border-radius: 4px;") # Green for ON
        control_group_layout.addWidget(self.global_save_enable_button)
        
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
        self.battery_status_combo.addItems(["low-power", "Accel", "Accel+gyro"])
        self.battery_status_combo.setCurrentIndex(0)
        self.battery_status_combo.currentIndexChanged.connect(self.IMU_status_changed)
        status_group_layout.addWidget(self.battery_status_combo)
        
        # 更新电池状态按钮
        self.update_battery_button = QPushButton("battery_status")
        # self.update_battery_button.clicked.connect(self.update_battery_status)
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
        
        # 在状态指示器组中添加RF power控制按钮
        # 大约在第530行，在packet_loss_indicator之后添加
        
        # RF串口选择下拉框
        self.rf_serial_combo = QComboBox()
        self.rf_serial_combo.setMinimumWidth(80)
        self.rf_serial_combo.setMaximumWidth(100)
        self.rf_serial_combo.addItem("Select RF Port")
        status_group_layout.addWidget(self.rf_serial_combo)

        self.rf_channel_combo = QComboBox()
        self.rf_channel_combo.setMinimumWidth(55)
        self.rf_channel_combo.setMaximumWidth(60)
        self.rf_channel_combo.addItems(["CH1", "CH2", "CH3", "CH4"])
        status_group_layout.addWidget(self.rf_channel_combo)
        
        # RF串口刷新按钮
        self.rf_refresh_button = QPushButton("Refresh")
        self.rf_refresh_button.setMaximumWidth(50)
        self.rf_refresh_button.clicked.connect(self.refresh_rf_serial_ports)
        status_group_layout.addWidget(self.rf_refresh_button)
        
        # RF串口连接按钮
        self.rf_connect_button = QPushButton("Connect RF")
        self.rf_connect_button.setMaximumWidth(60)
        self.rf_connect_button.setStyleSheet("background-color: #4CAF50; color: white; border: none; border-radius: 4px; padding: 5px; font-weight: bold;")
        self.rf_connect_button.clicked.connect(self.toggle_rf_connection)
        status_group_layout.addWidget(self.rf_connect_button)
        
        # RF power开启按钮
        self.rf_power_on_button = QPushButton("RF On")
        self.rf_power_on_button.setMaximumWidth(60)
        # 信号连接将在ESBMainWindow中设置
        self.rf_power_on_button.setEnabled(False)  # 初始禁用，需要先连接串口
        self.rf_power_on_button.setStyleSheet("background-color: #2196F3; color: white; border: none; border-radius: 4px; padding: 5px; font-weight: bold;")
        status_group_layout.addWidget(self.rf_power_on_button)
        
        # RF power关闭按钮
        self.rf_power_off_button = QPushButton("RF Off")
        self.rf_power_off_button.setMaximumWidth(60)
        # 信号连接将在ESBMainWindow中设置
        self.rf_power_off_button.setEnabled(False)  # 初始禁用，需要先连接串口
        self.rf_power_off_button.setStyleSheet("background-color: #F44336; color: white; border: none; border-radius: 4px; padding: 5px; font-weight: bold;")
        status_group_layout.addWidget(self.rf_power_off_button)

        self.rf_status_button = QPushButton("Query")
        self.rf_status_button.setMaximumWidth(50)
        self.rf_status_button.setEnabled(False)
        self.rf_status_button.setStyleSheet("background-color: #FF9800; color: white; border: none; border-radius: 4px; padding: 5px; font-weight: bold;")
        status_group_layout.addWidget(self.rf_status_button)

        self.rf_status_indicator = QLabel("RF: --")
        self.rf_status_indicator.setFixedWidth(70)
        self.rf_status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rf_status_indicator.setStyleSheet("background-color: #E0E0E0; color: black; border-radius: 4px; padding: 5px;")
        status_group_layout.addWidget(self.rf_status_indicator)

        # Run Time Indicator
        self.run_time_label = QLabel("Run: 0.00 min")
        self.run_time_label.setFixedWidth(100)
        self.run_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.run_time_label.setStyleSheet("background-color: #90CAF9; color: black; border-radius: 4px; padding: 5px;")
        status_group_layout.addWidget(self.run_time_label)
        
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
        self.habits_tab = HabitsTab()
        
        self.tab_widget.addTab(self.lfp_tab, "16 channels LFP")
        self.tab_widget.addTab(self.spike4ch_tab, "4 channels Spike")
        self.tab_widget.addTab(self.imu_tab, "IMU")
        self.tab_widget.addTab(self.raster_tab, "16 channels Raster")
        self.tab_widget.addTab(self.spike1ch_tab, "single channel Spike")
        self.tab_widget.addTab(self.habits_tab, "Habits Tracking")
        
        self.tab_widget.currentChanged.connect(self.tab_changed)
        
        main_layout.addWidget(self.tab_widget)

        # Log Box Area
        log_group = QGroupBox("System Log")
        log_group.setMaximumHeight(60)
        log_layout = QHBoxLayout(log_group)
        log_layout.setContentsMargins(5, 2, 5, 2)
        
        self.clear_log_button = QPushButton("Clear")
        self.clear_log_button.setFixedWidth(60)
        self.clear_log_button.clicked.connect(self.clear_log)
        log_layout.addWidget(self.clear_log_button)
        
        self.log_box = QTextBrowser()
        self.log_box.setOpenExternalLinks(True)
        self.log_box.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        log_layout.addWidget(self.log_box)
        
        main_layout.addWidget(log_group)

        # Timeline Widget
        self.timeline_group = QGroupBox("24-Hour Timeline")
        self.timeline_group.setMaximumHeight(100)
        timeline_layout = QVBoxLayout(self.timeline_group)
        timeline_layout.setContentsMargins(5, 5, 5, 5)
        
        self.timeline_widget = TimelineWidget()
        timeline_layout.addWidget(self.timeline_widget)
        
        main_layout.addWidget(self.timeline_group)

        # 状态栏
        self.statusBar().showMessage("Ready")
        
        # 初始化摄像头列表
        self.refresh_camera_list()
        
        # 初始化RF控制相关属性
        self.rf_serial_connection = None
        self.rf_connected = False
        
        # 初始化RF串口列表
        self.refresh_rf_serial_ports()
    
    def toggle_global_save(self, checked):
        """Toggle global save state"""
        if checked:
            self.global_save_enable_button.setText("Global Save: ON")
            self.global_save_enable_button.setStyleSheet("background-color: #4CAF50; color: white; border-radius: 4px;")
        else:
            self.global_save_enable_button.setText("Global Save: OFF")
            self.global_save_enable_button.setStyleSheet("background-color: #F44336; color: white; border-radius: 4px;")

    def auto_configure_paths(self):
        """Auto configure paths from config.json"""
        try:
            default_dir = os.path.dirname(os.path.abspath(__file__))
            config_path, _ = QFileDialog.getOpenFileName(
                self, 
                "Select Configuration File", 
                default_dir, 
                "JSON Files (*.json);;All Files (*)"
            )
            
            if not config_path:
                return

            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Update paths in different tabs
            if 'lfp_save_path' in config:
                self.lfp_tab.lfp_file_path_label.setText(config['lfp_save_path'])
                self.log_message(f"LFP path set to: {config['lfp_save_path']}", level="success")
            
            if 'mode3_save_path' in config:
                self.lfp_tab.mode3_file_path_label.setText(config['mode3_save_path'])
                self.log_message(f"Mode3 path set to: {config['mode3_save_path']}", level="success")

            if 'mode1_save_path' in config:
                self.spike1ch_tab.mode1_file_path_label.setText(config['mode1_save_path'])
                self.log_message(f"Mode1 path set to: {config['mode1_save_path']}", level="success")

            if 'mode2_save_path' in config:
                self.spike4ch_tab.file_path_label.setText(config['mode2_save_path'])
                self.log_message(f"Mode2 path set to: {config['mode2_save_path']}", level="success")
                
            if 'video_save_path' in config:
                self.video_save_path = config['video_save_path']
                self.save_path_label.setText(config['video_save_path'])
                self.log_message(f"Video path set to: {config['video_save_path']}", level="success")

            if 'mice_id_directory' in config:
                if hasattr(self.habits_tab, 'habits_panel'):
                    directory = config['mice_id_directory']
                    self.habits_tab.habits_panel.set_data_directory(directory)
                    self.log_message(f"Mice ID directory set to: {directory}", level="success")
            elif 'mice_id_file_path' in config: # Backward compatibility
                 if hasattr(self.habits_tab, 'habits_panel'):
                    directory = config['mice_id_file_path']
                    # Check if it's a file, get dirname
                    if os.path.isfile(directory):
                        directory = os.path.dirname(directory)
                    self.habits_tab.habits_panel.set_data_directory(directory)
                    self.log_message(f"Mice ID directory set to: {directory}", level="success")

            if 'habits_serial_port' in config:
                if hasattr(self.habits_tab, 'habits_panel'):
                    habits_port = config['habits_serial_port']
                    combo = self.habits_tab.habits_panel.serial_combo
                    index = combo.findText(habits_port, Qt.MatchFlag.MatchContains)
                    if index >= 0:
                        combo.setCurrentIndex(index)
                        self.log_message(f"Habits serial port selected: {habits_port}", level="success")
                    else:
                        self.log_message(f"Warning: Habits serial port {habits_port} not found", level="warning")

            if 'rf_serial_port' in config:
                rf_port = config['rf_serial_port']
                index = self.rf_serial_combo.findText(rf_port, Qt.MatchFlag.MatchContains)
                if index >= 0:
                    self.rf_serial_combo.setCurrentIndex(index)
                    self.log_message(f"RF serial port selected: {rf_port}", level="success")
                    # Optionally auto-connect
                    # self.connect_rf_serial() 
                else:
                    self.log_message(f"Warning: RF serial port {rf_port} not found", level="warning")

            self.log_message("Auto configuration completed", level="success")

        except Exception as e:
            self.log_message(f"Error loading config: {str(e)}", level="error")

    def tab_changed(self, index):
        """Handle tab switching event"""
        tab_titles = ["16 channels LFP", "4 channels Spike", "IMU", "16 channels Raster", "single channel Spike", "Habits Tracking"]
        if 0 <= index < len(tab_titles):
            self.statusBar().showMessage(f"Current displayTab: {tab_titles[index]}")
        print(f"Switched to tab: {index}")
    
    def start_sampling(self):
        """Start sampling"""
        print("Sample begaining...")
        # self.start_sampling_button.setEnabled(False)
        # self.stop_sampling_button.setEnabled(True)
        
        self.statusBar().showMessage(f"Sampling")
    
    def stop_sampling(self):
        """Stop sampling"""
        # print("Stop sampling...")
        # self.start_sampling_button.setEnabled(True)
        # self.stop_sampling_button.setEnabled(False)
        self.statusBar().showMessage("Sample stop")
    
    
    def IMU_status_changed(self):
        """Update IMU status"""
        print(f"Send IMU status update command: {self.battery_status_combo.currentText()}")
    
    def update_battery_indicator(self, level, Charging_STAT, Battery_Voltage):
        """Update battery indicator"""
        # PG + PG_STAT
        # print(Charging_STAT)
        PG = 0
        PG_STAT = 0
        if(Charging_STAT == 0):
            PG = 0
            PG_STAT = 0
        elif(Charging_STAT == 1):
            PG = 1
            PG_STAT = 0
        elif(Charging_STAT == 256): 
            PG = 0
            PG_STAT = 1
        elif(Charging_STAT == 257):
            PG = 1
            PG_STAT = 1

        color = "w"
        if PG == 1: # power failed
            color = "#FF5252"  # 红色
        elif PG == 0: # power good
            if PG_STAT == 1: # shipping
                color = "#d96c58"  # 橙色
            elif PG_STAT == 0: # charging
                color = "#66BB6A"  # green

        self.update_battery_button.setStyleSheet(f"background-color: {color}; color: black; border-radius: 4px; padding: 5px;")

        RSOC = str(level) + "%"
        Battery_Voltage = str(Battery_Voltage/1000)

        self.update_battery_button.setText(RSOC + " " + Battery_Voltage)
        
        # Update Timeline
        if hasattr(self, 'timeline_widget'):
            current_time = time.time()
            # Get RF status if available, default to 1 (OFF)
            rf_status = getattr(self, 'rf_power_status', 1)
            self.timeline_widget.update_data(current_time, level, self.current_recording_mode, rf_status)
    
    def update_rssi(self, value):
        """Update RSSI indicator"""
        self.rssi_indicator.setText(f"RSSI: {-1 * value} dBm")
        if value < -90:
            color = "#FF5252"  # 红色 - 信号弱
        elif value < -70:
            color = "#FFD740"  # 黄色 - 信号中等
        else:
            color = "#66BB6A"  # 绿色 - 信号强
        self.rssi_indicator.setStyleSheet(f"background-color: {color}; color: black; border-radius: 4px; padding: 5px;")
    
    def update_packet_loss(self, value):
        """Update packet loss indicator"""
        self.packet_loss_indicator.setText(f"Loss: {value}%")
        if value > 10:
            color = "#FF5252"  # 红色 - 丢包率高
        elif value > 5:
            color = "#FFD740"  # 黄色 - 丢包率中等
        else:
            color = "#66BB6A"  # 绿色 - 丢包率低
        self.packet_loss_indicator.setStyleSheet(f"background-color: {color}; color: black; border-radius: 4px; padding: 5px;")
    
    def refresh_camera_list(self):
        """Refresh camera list"""
        self.camera_selection_combo.clear()
        available_cameras = get_available_cameras()
        
        if not available_cameras:
            self.camera_selection_combo.addItem("No cameras found")
            self.toggle_camera_button.setEnabled(False)
            self.toggle_camera_display_button.setEnabled(False)
        else:
            for camera in available_cameras:
                display_text = f"{camera['name']} ({camera['resolution']}, {camera['fps']:.1f}fps)"
                self.camera_selection_combo.addItem(display_text, camera['id'])
            self.toggle_camera_button.setEnabled(True)
    
    def get_selected_camera_id(self):
        """Get selected camera ID"""
        current_data = self.camera_selection_combo.currentData()
        return current_data if current_data is not None else 0
    
    def refresh_rf_serial_ports(self):
        """Refresh RF serial port list"""
        self.rf_serial_combo.clear()
        self.rf_serial_combo.addItem("Select RF Port")
        
        try:
            import serial.tools.list_ports
            ports = list(serial.tools.list_ports.comports())
            if ports:
                for port in ports:
                    display_text = f"{port.device} - {port.description}"
                    self.rf_serial_combo.addItem(display_text, port.device)
            else:
                self.rf_serial_combo.addItem("No ports available")
        except ImportError:
            # 如果没有安装pyserial，添加模拟串口用于测试
            mock_ports = [f"COM{i}" for i in range(1, 10)]
            for port in mock_ports:
                self.rf_serial_combo.addItem(port, port)
    
    def toggle_rf_connection(self):
        """Toggle RF serial connection"""
        if self.rf_connected:
            self.disconnect_rf_serial()
        else:
            self.connect_rf_serial()
    

    
    def connect_rf_serial(self):
        """Connect RF control serial"""
        selected_port = self.rf_serial_combo.currentData()
        if selected_port is None:
            selected_port = self.rf_serial_combo.currentText()
            if " - " in selected_port:
                selected_port = selected_port.split(" - ", 1)[0]

        if selected_port == "Select RF Port" or selected_port == "No ports available" or not selected_port:
            self.log_message("Warning: Please select a valid RF serial port first", level="warning")
            return
        
        try:
            import serial
            self.rf_serial_connection = serial.Serial(selected_port, 9600, timeout=1)
            self.rf_connected = True
            self.rf_power_on_button.setEnabled(True)
            self.rf_power_off_button.setEnabled(True)
            if hasattr(self, 'rf_status_button'):
                self.rf_status_button.setEnabled(True)
            self.rf_connect_button.setText("Disconnect RF")
            self.rf_connect_button.setStyleSheet("background-color: #F44336; color: white; border: none; border-radius: 4px; padding: 5px; font-weight: bold;")
            self.log_message(f"Success: RF control serial connected: {selected_port}", level="success")
            if hasattr(self, 'rf_query_status'):
                try:
                    self.rf_query_status()
                except Exception:
                    pass
        except Exception as e:
            self.log_message(f"Error: Failed to connect RF control serial: {str(e)}", level="error")
            self.rf_connected = False
    
    def disconnect_rf_serial(self):
        """Disconnect RF control serial"""
        if self.rf_serial_connection:
            self.rf_serial_connection.close()
            self.rf_serial_connection = None
        self.rf_connected = False
        self.rf_power_on_button.setEnabled(False)
        self.rf_power_off_button.setEnabled(False)
        if hasattr(self, 'rf_status_button'):
            self.rf_status_button.setEnabled(False)
        self.rf_connect_button.setText("Connect RF")
        self.rf_connect_button.setStyleSheet("background-color: #4CAF50; color: white; border: none; border-radius: 4px; padding: 5px; font-weight: bold;")
        if hasattr(self, 'rf_status_indicator'):
            self.rf_status_indicator.setText("RF: --")
            self.rf_status_indicator.setStyleSheet("background-color: #E0E0E0; color: black; border-radius: 4px; padding: 5px;")
        self.log_message("Info: RF control serial disconnected", level="info")

    def closeEvent(self, event):
        """Window close event"""
        reply = QMessageBox.question(
            self, 
            'check quit', 
            'Are you sure to quit?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            
                # 处理关闭前的清理工作
                print("Main window closed.")
                event.accept()
        else:
            event.ignore()


    def toggle_camera(self):
        """Toggle camera on/off"""
        if not self.is_camera_on:
            # 获取选择的摄像头ID
            camera_id = self.get_selected_camera_id()
            
            # 打开摄像头
            if self.camera_module.open_camera(camera_id):
                self.is_camera_on = True
                self.toggle_camera_button.setText("Close camera")
                self.toggle_recording_button.setEnabled(True)
                self.toggle_camera_display_button.setEnabled(True)
                
                # 初始化独立摄像头窗口
                if not hasattr(self, 'camera_window') or self.camera_window is None:
                    self.camera_window = CameraWindow()
                    self.camera_window.closed.connect(self.on_camera_window_closed)
                
                # 默认不显示窗口，等待点击“Show camera”
            else:
                self.log_message("Error: Cannot open camera", level="error")
        else:
            # 关闭摄像头
            # 若显示开启，先停止更新并隐藏
            if self.is_camera_display_on:
                self.camera_timer.stop()
                self.is_camera_display_on = False
                self.toggle_camera_display_button.setText("Show camera")
            
            self.camera_module.close_camera()
            self.is_camera_on = False
            self.toggle_camera_button.setText("Open camera")
            self.toggle_recording_button.setEnabled(False)
            self.toggle_camera_display_button.setEnabled(False)
            if self.is_recording:
                self.toggle_recording()
            
            # 关闭摄像头窗口
            if hasattr(self, 'camera_window') and self.camera_window is not None:
                self.camera_window.close()

    def on_camera_window_closed(self):
        """Handle camera window closed by user"""
        self.camera_timer.stop()
        self.is_camera_display_on = False
        self.toggle_camera_display_button.setText("Show camera")

    def toggle_camera_display(self):
        """Toggle camera display show/hide"""
        if not self.is_camera_on:
            self.log_message("Warning: Please open the camera first", level="warning")
            return
        
        if not self.is_camera_display_on:
            # Show camera window
            if hasattr(self, 'camera_window') and self.camera_window:
                self.camera_window.show()
                self.camera_timer.start(16)
                self.is_camera_display_on = True
                self.toggle_camera_display_button.setText("Hide camera")
        else:
            # Hide camera window
            if hasattr(self, 'camera_window') and self.camera_window:
                self.camera_window.hide()
            self.camera_timer.stop()
            self.is_camera_display_on = False
            self.toggle_camera_display_button.setText("Show camera")

    def clear_log(self):
        self.log_box.clear()

    def log_message(self, message, level="info"):
        timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        color = "black"
        if level == "warning":
            color = "orange"
        elif level == "error":
            color = "red"
        elif level == "success":
            color = "green"
        
        formatted_message = f'<span style="color:gray;">[{timestamp}]</span> <span style="color:{color};">{message}</span>'
        self.log_box.append(formatted_message)
        
        # Limit log size to prevent memory issues
        doc = self.log_box.document()
        if doc.blockCount() > 1000:
            cursor = self.log_box.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor, 100) # Remove top 100 lines
            cursor.removeSelectedText()
            
        # Scroll to bottom
        self.log_box.moveCursor(self.log_box.textCursor().MoveOperation.End)
            
        
    def update_camera_frame(self):
        """Update camera frame"""
        if not self.is_camera_display_on:
            return
        if hasattr(self, 'camera_window') and self.camera_window and self.camera_window.isVisible():
            # 当录制开启时，使用录制线程更新的最新帧，避免双线程抓帧
            if self.is_recording and self.camera_module.frame is not None:
                frame = self.camera_module.frame
            else:
                frame = self.camera_module.get_frame()
            if frame is not None:
                # 转换OpenCV图像为Qt图像
                # Reuse existing buffer if possible to avoid reallocation
                rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                bytes_per_line = ch * w
                # Create QImage pointing to data (careful with lifetime)
                qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                # setPixmap creates a copy, which is fine, but make sure to not leak references
                self.camera_window.video_label.setPixmap(QPixmap.fromImage(qt_image))
                
                # Force garbage collection if memory usage is high? Not usually recommended in Python unless critical.
                # Just ensure rgb_image and qt_image go out of scope.
        
    def toggle_recording(self):
        """Toggle recording"""
        if not self.is_recording:
            # Global Save Check
            if hasattr(self, 'global_save_enable_button') and not self.global_save_enable_button.isChecked():
                self.log_message("Save Disabled: Global saving is disabled.", level="warning")
                QMessageBox.warning(self, "Save Disabled", "Global saving is disabled. Please enable it in the top control bar.")
                return

            # 开始录制
            if self.camera_module.start_recording(self.video_save_path):
                self.is_recording = True
                self.toggle_recording_button.setText("Stop recording")
                self.select_save_path_button.setEnabled(False)
        else:
            # 停止录制
            if self.camera_module.stop_recording():
                self.is_recording = False
                self.toggle_recording_button.setText("Start recording")
                self.select_save_path_button.setEnabled(True)
        
    def select_video_save_path(self):
        """Select video save path"""
        # 使用exe所在目录下的recordings文件夹作为默认路径
        from path_utils import get_recordings_directory
        default_dir = get_recordings_directory()
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save video file", default_dir, "AVI file (*.avi);;All files (*)"
        )
        if file_path:
            self.video_save_path = file_path
            self.save_path_label.setText(file_path)
    
    def closeEvent(self, event):
        """Window close event"""
        reply = QMessageBox.question(
            self, 
            'check quit', 
            'Are you sure to quit?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 确保关闭摄像头
            if self.is_camera_on:
                self.camera_timer.stop()
                self.camera_module.close_camera()
            # 关闭摄像头窗口
            if hasattr(self, 'camera_window') and self.camera_window:
                self.camera_window.close()
            
            # 停止录制
            if self.is_recording:
                self.camera_module.stop_recording()
            
            # 断开RF串口连接
            if self.rf_connected:
                self.disconnect_rf_serial()
            
            # 处理关闭前的清理工作
            print("Main window closed.")
            event.accept()
        else:
            event.ignore()
