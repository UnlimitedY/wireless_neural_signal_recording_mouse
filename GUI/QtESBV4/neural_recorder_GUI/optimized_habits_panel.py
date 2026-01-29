"""
Optimized Habits Panel for Neural Recorder GUI
优化的Habits面板，整合了所有核心功能，简化界面，优化布局
"""

import os
import sys
import time
import json
import pickle
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import threading
from collections import defaultdict, deque

import serial
import serial.tools.list_ports
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import (QThread, pyqtSignal, QTimer, Qt, QDate)
from path_utils import get_data_directory, get_mouse_data_directory, get_default_save_path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QSpinBox, QDoubleSpinBox, QLineEdit, QTextEdit,
    QComboBox, QListWidget, QDateEdit, QMessageBox, QSizePolicy,
    QFrame, QSplitter, QFileDialog
)
from PyQt6.QtGui import QFont, QColor, QPalette


class SerialWorker(QThread):
    """Serial communication worker thread"""
    data_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, port: str, baudrate: int = 115200):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.serial_connection = None
        self.running = False
        
    def run(self):
        """Run serial listener"""
        try:
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1
            )
            self.running = True
            
            while self.running:
                if self.serial_connection.in_waiting > 0:
                    try:
                        data = self.serial_connection.readline().decode('utf-8').strip()
                        if data:
                            self.data_received.emit(data)
                    except UnicodeDecodeError:
                        continue
                        
        except Exception as e:
            self.error_occurred.emit(f"Serial connection error: {str(e)}")
            
    def send_data(self, data: str) -> bool:
        """Send data"""
        try:
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.write((data + '\n').encode('utf-8'))
                return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to send data: {str(e)}")
        return False
        
    def stop(self):
        """Stop serial communication"""
        self.running = False
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
        self.quit()
        self.wait()


class TrialDataManager:
    """Efficient trial data manager"""
    
    def __init__(self, max_memory_trials: int = 100000):
        self.max_memory_trials = max_memory_trials
        self.trial_data = deque(maxlen=max_memory_trials)  # 使用deque限制内存使用
        
        # 缓存变量，避免重复计算
        self._daily_trial_cache = {}  # 日期 -> 试验次数
        self._performance_cache = deque(maxlen=max_memory_trials)  
        self._last_cache_update = None
        self._cache_dirty = True
        
        # 按日期索引的数据，用于快速查找
        self._trials_by_date = defaultdict(list)
        
        # Mode switches storage
        self.mode_switches = [] # List of dicts: {'start': datetime, 'end': datetime}

    def add_mode_switch(self, switch_data: Dict[str, datetime]):
        """Add a mode switch interval"""
        self.mode_switches.append(switch_data)
        
    def get_recent_mode_switches(self, hours: int = 24) -> List[Dict[str, datetime]]:
        """Get mode switches from the last N hours"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent = []
        for switch in self.mode_switches:
            # Check if the interval overlaps with the recent period
            if switch['end'] >= cutoff_time: 
                recent.append(switch)
        return recent
        
    def add_trial(self, trial_data: Dict[str, Any]):
        """Add trial data"""
        self.trial_data.append(trial_data)
        # 更新日期索引
        date_key = trial_data['timestamp'].date()
        self._trials_by_date[date_key].append(trial_data)
        
        # 更新性能缓存（如果有相关字段）
        if 'trial_num' in trial_data and 'performance' in trial_data:
            self._performance_cache.append({
                'trial_num': trial_data['trial_num'],
                'performance': trial_data['performance'],
                'early_lick': trial_data.get('early_lick_rate', 0),
                'protocol_perf': trial_data.get('protocol_perf', 0)
            })
        
        # 标记缓存为脏
        self._cache_dirty = True
        
        # 清理过期的日期索引（保留最近30天）
        # self._cleanup_old_indices()
        

    def get_daily_trial_count(self, date: datetime.date = None) -> int:
        """Get trial count for a given date (cached)"""
        if date is None:
            date = datetime.now().date()
            
        # 检查缓存
        if not self._cache_dirty and date in self._daily_trial_cache:
            return self._daily_trial_cache[date]
            
        # 使用索引快速计算
        count = len(self._trials_by_date[date])
        self._daily_trial_cache[date] = count
        
        return count
        
    def get_recent_trials(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get trials from the last N hours"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        # 使用deque的高效遍历
        recent_trials = []
        for trial in reversed(self.trial_data):  # 从最新的开始
            if trial['timestamp'] >= cutoff_time:
                recent_trials.append(trial)
            else:
                break  # 由于数据是按时间顺序的，可以提前退出
                
        return list(reversed(recent_trials))  # 恢复时间顺序
        
    def get_performance_data(self ) -> tuple:
        """Get performance data for recent trials"""
        if len(self._performance_cache) == 0:
            return [], [], [], []
            
        # 使用缓存的性能数据
        recent_data = list(self._performance_cache)[-self.max_memory_trials:]
        x_data = [d['trial_num'] for d in recent_data]
        y_perf = [d['performance'] for d in recent_data]
        y_early = [d.get('early_lick', 0) for d in recent_data]
        y_proto = [d.get('protocol_perf', 0) for d in recent_data]
        
        return x_data, y_perf, y_early, y_proto
        
    def _cleanup_old_indices(self):
        """Clean up expired date indices"""
        cutoff_date = datetime.now().date() - timedelta(days=30)
        
        # 使用字典推导式一次性重建，比删除更高效
        self._trials_by_date = {date: trials for date, trials in self._trials_by_date.items() 
                               if date >= cutoff_date}
        self._daily_trial_cache = {date: count for date, count in self._daily_trial_cache.items() 
                                  if date >= cutoff_date}
            
    def clear_cache(self):
        """Clear all caches"""
        self._daily_trial_cache.clear()
        self._cache_dirty = True
        
    def get_memory_usage(self) -> Dict[str, int]:
        """Get memory usage"""
        return {
            'trial_data_count': len(self.trial_data),
            'trials_by_date_keys': len(self._trials_by_date),
            'daily_cache_keys': len(self._daily_trial_cache),
            'performance_cache_count': len(self._performance_cache)
        }
        
    def cleanup_old_data(self, days_to_keep: int = 30):
        """Remove data older than N days"""
        cutoff_time = datetime.now() - timedelta(days=days_to_keep)
        
        # 清理试验数据
        original_trial_count = len(self.trial_data)
        # 由于deque不支持直接过滤，我们需要重建
        filtered_trials = deque(maxlen=self.max_memory_trials)
        for trial in self.trial_data:
            if trial['timestamp'] >= cutoff_time:
                filtered_trials.append(trial)
        self.trial_data = filtered_trials
        
        # 重建索引
        self._rebuild_indices()
        
        return {
            'trials_removed': original_trial_count - len(self.trial_data)
        }
        
    def _rebuild_indices(self):
        """Rebuild indices"""
        self._trials_by_date.clear()
        self._performance_cache.clear()
        self.clear_cache()
        
        # 重建试验数据索引
        for trial in self.trial_data:
            date_key = trial['timestamp'].date()
            self._trials_by_date[date_key].append(trial)
            
            # 重建性能缓存
            if 'trial_num' in trial and 'performance' in trial:
                self._performance_cache.append({
                    'trial_num': trial['trial_num'],
                    'performance': trial['performance'],
                    'early_lick': trial.get('early_lick_rate', 0),
                    'protocol_perf': trial.get('protocol_perf', 0)
                })
            
    def force_cleanup(self):
        """Force cleanup to free memory"""
        # 清理过期索引
        self._cleanup_old_indices()
        
        # 清理缓存
        self.clear_cache()
        
        # 如果数据量过大，保留最近的数据
        if len(self.trial_data) > self.max_memory_trials * 0.8:
            self.cleanup_old_data(days_to_keep=7)  # 只保留最近7天
            
    def get_all_trial_data(self) -> List[Dict[str, Any]]:
        """Get all trial data"""
        return list(self.trial_data)
        

        
    def clear_data(self):
        """Clear all data"""
        self.trial_data.clear()
        self._trials_by_date.clear()
        self.mode_switches.clear()
        self.clear_cache()
        
    def load_from_list(self, trial_list: List[Dict[str, Any]]):
        """Load trial data from a list"""
        self.clear_data()
        
        # 重新构建数据和索引
        for trial in trial_list:
            # 确保timestamp是datetime对象
            if isinstance(trial['timestamp'], str):
                trial['timestamp'] = datetime.fromisoformat(trial['timestamp'])
            self.add_trial(trial)


class OptimizedHabitsPanel(QWidget):
    """优化的Habits面板"""
    Neural_recorder_command = pyqtSignal(str)
    TrialStarted = pyqtSignal() # Signal emitted when trial starts ('C' received)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(1000, 700)
        
        # 数据存储 - 使用exe所在目录下的Data文件夹
        self.data_folder = get_data_directory("Data")
        self.selected_data_dir = None
            
        # 串口通信
        self.serial_worker = None
        self.serial_data_log = []
        
        # 当前试验编号跟踪
        self.current_trial_num = 0
        
        # 使用优化的数据管理器
        self.data_manager = TrialDataManager()
        
        # Track active ESA block
        self.current_esa_start_time = None
        
        # 定时器
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_gui)
        self.update_timer.start(600000)  # 10分钟更新一次
        
        # 数据清理定时器 - 每小时清理一次
        # self.cleanup_timer = QTimer()
        # self.cleanup_timer.timeout.connect(self.periodic_cleanup)
        # self.cleanup_timer.start(3600000)  # 1小时清理一次
        
        # 颜色映射
        self.color_map = [
            QColor(255, 0, 0),      # 红色
            QColor(255, 128, 0),    # 橙色
            QColor(255, 255, 0),    # 黄色
            QColor(128, 255, 0),    # 黄绿色
            QColor(0, 255, 0),      # 绿色
            QColor(0, 255, 128),    # 青绿色
            QColor(0, 255, 255),    # 青色
            QColor(0, 128, 255),    # 蓝色
        ]
        
        self.setup_ui()
        self.setup_connections()
        
        
    def setup_ui(self):
        """设置用户界面"""
        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 创建分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧控制面板
        left_panel = self.create_left_panel()
        left_panel.setMaximumWidth(350)
        left_panel.setMinimumWidth(300)
        
        # 右侧图表和状态面板
        right_panel = self.create_right_panel()
        
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)  # 左侧固定宽度
        splitter.setStretchFactor(1, 1)  # 右侧可伸缩
        
        main_layout.addWidget(splitter)
        
    def create_left_panel(self) -> QWidget:
        """创建左侧控制面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)  # 与右侧panel保持一致的间距
        layout.setContentsMargins(0, 0, 0, 0)  # 与右侧panel保持一致的边距
        
        # 串口连接区域
        connection_group = self.create_connection_group()
        layout.addWidget(connection_group)
        
        # 控制面板
        control_group = self.create_control_group()
        layout.addWidget(control_group)
        
        # 状态信息
        status_group = self.create_status_group()
        layout.addWidget(status_group)
        
        # 错误消息
        error_group = self.create_error_group()
        layout.addWidget(error_group)
        
        # 参数管理
        param_group = self.create_param_group()
        layout.addWidget(param_group)
        
        layout.addStretch()
        return panel
        
    def create_connection_group(self) -> QGroupBox:
        """创建连接控制组"""
        group = QGroupBox("Connection")
        layout = QGridLayout(group)
        layout.setSpacing(0)
        
        # 鼠标ID
        layout.addWidget(QLabel("Mouse ID:"), 0, 0)
        self.mouse_id_edit = QLineEdit("Mouse_001")
        self.mouse_id_edit.setReadOnly(True)  # 由目录选择决定
        self.mouse_id_edit.setStyleSheet("background-color: #f0f0f0; color: #333;")
        layout.addWidget(self.mouse_id_edit, 0, 1)
        
        # 目录选择按钮
        self.select_dir_btn = QPushButton("📂")
        self.select_dir_btn.setMaximumWidth(30)
        self.select_dir_btn.setToolTip("Select Data Directory")
        self.select_dir_btn.clicked.connect(self.select_data_directory)
        layout.addWidget(self.select_dir_btn, 0, 2)
        
        # 串口选择
        layout.addWidget(QLabel("Serial Port:"), 1, 0)
        self.serial_combo = QComboBox()
        self.refresh_serial_ports()
        layout.addWidget(self.serial_combo, 1, 1)
        
        self.refresh_btn = QPushButton("🔄")
        self.refresh_btn.setMaximumWidth(30)
        self.refresh_btn.clicked.connect(self.refresh_serial_ports)
        layout.addWidget(self.refresh_btn, 1, 2)
        
        # 连接按钮
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        layout.addWidget(self.connect_btn, 2, 0, 1, 3)
        
        # 开始日期
        layout.addWidget(QLabel("Start Date:"), 3, 0)
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setDate(QDate.currentDate())
        self.start_date_edit.setCalendarPopup(True)
        layout.addWidget(self.start_date_edit, 3, 1, 1, 2)
        
        return group
        
    def create_control_group(self) -> QGroupBox:
        """创建控制面板组"""
        group = QGroupBox("Control Panel")
        layout = QGridLayout(group)
        layout.setSpacing(5)
        
        # 奖励设置
        layout.addWidget(QLabel("Reward:"), 0, 0)
        self.reward_left_edit = QSpinBox()
        self.reward_left_edit.setRange(0, 999)
        self.reward_left_edit.setValue(30)
        self.reward_left_edit.setToolTip("Left")
        
        self.reward_middle_edit = QSpinBox()
        self.reward_middle_edit.setRange(0, 999)
        self.reward_middle_edit.setValue(30)
        self.reward_middle_edit.setToolTip("Middle")
        
        self.reward_right_edit = QSpinBox()
        self.reward_right_edit.setRange(0, 999)
        self.reward_right_edit.setValue(30)
        self.reward_right_edit.setToolTip("Right")
        
        self.reward_btn = QPushButton("Set Reward")
        
        layout.addWidget(self.reward_left_edit, 0, 1)
        layout.addWidget(self.reward_middle_edit, 0, 2)
        layout.addWidget(self.reward_right_edit, 0, 3)
        layout.addWidget(self.reward_btn, 0, 4)
        
        # 光强控制
        layout.addWidget(QLabel("Light:"), 1, 0)
        self.low_light_edit = QSpinBox()
        self.low_light_edit.setRange(0, 255)
        self.low_light_edit.setValue(1)
        
        self.high_light_edit = QSpinBox()
        self.high_light_edit.setRange(0, 255)
        self.high_light_edit.setValue(255)
        
        self.light_btn = QPushButton("Set Light")
        
        layout.addWidget(self.low_light_edit, 1, 1)
        layout.addWidget(self.high_light_edit, 1, 2)
        layout.addWidget(self.light_btn, 1, 3, 1, 2)
        
        # 协议和超时
        layout.addWidget(QLabel("Protocol:"), 2, 0)
        self.protocol_edit = QSpinBox()
        self.protocol_edit.setRange(0, 999)
        layout.addWidget(self.protocol_edit, 2, 1)
        
        self.protocol_btn = QPushButton("Set Protocol")
        layout.addWidget(self.protocol_btn, 2, 2, 1, 3)
        
        # 读取所有值按钮
        self.read_all_btn = QPushButton("Read All Values")
        self.read_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #1565C0;
            }
        """)
        layout.addWidget(self.read_all_btn, 3, 0, 1, 5)
        
        # 控制按钮
        button_layout = QHBoxLayout()
        self.pause_btn = QPushButton("Pause Habits")
        self.handshake_btn = QPushButton("Handshake")
        
        # Sync Time按钮和时间显示
        sync_layout = QVBoxLayout()
        self.time_btn = QPushButton("Sync Time")
        self.sync_time_label = QLabel("Not synced")
        self.sync_time_label.setStyleSheet("font-size: 10px; color: #666; text-align: center;")
        self.sync_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        sync_layout.addWidget(self.time_btn)
        sync_layout.addWidget(self.sync_time_label)
        
        button_layout.addWidget(self.pause_btn)
        button_layout.addWidget(self.handshake_btn)
        button_layout.addLayout(sync_layout)
        
        layout.addLayout(button_layout, 4, 0, 1, 5)
        
        return group
        
    def create_status_group(self) -> QGroupBox:
        """创建状态信息组"""
        group = QGroupBox("Status Information")
        layout = QGridLayout(group)
        layout.setSpacing(5)
        
        # 试验信息
        layout.addWidget(QLabel("Trial:"), 0, 0)
        self.trial_label = QLabel("0 - 0.0%")
        self.trial_label.setStyleSheet("font-weight: bold; color: #2196F3;")
        layout.addWidget(self.trial_label, 0, 1)
        
        # 天数信息
        layout.addWidget(QLabel("Days:"), 1, 0)
        self.days_label = QLabel("0.0 d")
        self.days_label.setStyleSheet("font-weight: bold; color: #FF9800;")
        layout.addWidget(self.days_label, 1, 1)
        
        # 试验次数/天
        layout.addWidget(QLabel("Trials/Day:"), 2, 0)
        self.trials_day_label = QLabel("0/d")
        self.trials_day_label.setStyleSheet("font-weight: bold; color: #9C27B0;")
        layout.addWidget(self.trials_day_label, 2, 1)
        
        # Protocol Trials
        layout.addWidget(QLabel("Protocol Trials:"), 3, 0)
        self.protocol_trials_label = QLabel("0")
        self.protocol_trials_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.protocol_trials_label, 3, 1)

        # Trial Type
        layout.addWidget(QLabel("Trial Type:"), 4, 0)
        self.trial_type_label = QLabel("-")
        self.trial_type_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.trial_type_label, 4, 1)

        # Outcome
        layout.addWidget(QLabel("Outcome:"), 5, 0)
        self.outcome_label = QLabel("-")
        self.outcome_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.outcome_label, 5, 1)

        # Protocol Perf
        layout.addWidget(QLabel("Protocol Perf:"), 6, 0)
        self.protocol_perf_label = QLabel("0%")
        self.protocol_perf_label.setStyleSheet("font-weight: bold; color: green;")
        layout.addWidget(self.protocol_perf_label, 6, 1)
        
        return group
        
    def create_error_group(self) -> QGroupBox:
        """创建错误消息组"""
        group = QGroupBox("Messages")
        layout = QVBoxLayout(group)
        layout.setSpacing(5)
        
        self.error_listbox = QListWidget()
        self.error_listbox.setMaximumHeight(120)
        layout.addWidget(self.error_listbox)
        
        # 控制按钮
        button_layout = QHBoxLayout()
        self.delete_sel_btn = QPushButton("Delete Selected")
        self.clear_all_btn = QPushButton("Clear All")
        
        button_layout.addWidget(self.delete_sel_btn)
        button_layout.addWidget(self.clear_all_btn)
        layout.addLayout(button_layout)
        
        return group
        
    def create_param_group(self) -> QGroupBox:
        """创建参数管理组"""
        group = QGroupBox("Parameters")
        layout = QHBoxLayout(group)
        
        self.save_params_btn = QPushButton("Save Parameters")
        self.load_params_btn = QPushButton("Load Parameters")
        
        layout.addWidget(self.save_params_btn)
        layout.addWidget(self.load_params_btn)
        
        return group
        
    def create_right_panel(self) -> QWidget:
        """创建右侧面板"""
        panel = QWidget()
        main_layout = QVBoxLayout(panel)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建垂直分割器用于图表区域和Serial data log
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 上半部分：图表区域
        charts_container = QWidget()
        charts_main_layout = QVBoxLayout(charts_container)
        charts_main_layout.setSpacing(10)
        charts_main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Performance图表
        perf_group = QGroupBox("Performance Chart")
        perf_layout = QVBoxLayout(perf_group)
        perf_layout.setContentsMargins(5, 5, 5, 5)
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('#0B0F14')
        self.plot_widget.setLabel('left', 'Performance (%)')
        self.plot_widget.setLabel('bottom', 'Trial Number')
        self.plot_widget.setTitle('Real-time Trial Performance')
        self.plot_widget.showGrid(True, True, alpha=0.3)
        self.plot_widget.setYRange(0, 100)
        
        # 添加性能基准线
        self.plot_widget.addLine(y=50, pen=pg.mkPen('#FFB300', width=2, style=Qt.PenStyle.DashLine))
        self.plot_widget.addLegend()
        
        # 初始化数据曲线
        # Global Performance (Blue)
        self.performance_curve = self.plot_widget.plot(
            [], [], 
            name='Global Perf',
            pen=pg.mkPen(color=(0, 229, 255), width=2),
            symbol='o', 
            symbolBrush=pg.mkBrush(0, 229, 255, 200),
            symbolPen=pg.mkPen(0, 229, 255, 255),
            symbolSize=7
        )

        # Early Lick Rate (Orange)
        self.early_lick_curve = self.plot_widget.plot(
            [], [], 
            name='Early Lick',
            pen=pg.mkPen(color=(255, 128, 0), width=2),
            symbol='t', 
            symbolBrush=pg.mkBrush(255, 128, 0, 200),
            symbolPen=pg.mkPen(255, 128, 0, 255),
            symbolSize=7
        )

        # Protocol Performance (Green)
        self.protocol_perf_curve = self.plot_widget.plot(
            [], [], 
            name='Protocol Perf',
            pen=pg.mkPen(color=(0, 255, 0), width=2),
            symbol='s', 
            symbolBrush=pg.mkBrush(0, 255, 0, 200),
            symbolPen=pg.mkPen(0, 255, 0, 255),
            symbolSize=7
        )
        
        perf_layout.addWidget(self.plot_widget)
        
        # 24h Trials图表
        trials_24h_group = QGroupBox("24h Trials Chart")
        trials_24h_layout = QVBoxLayout(trials_24h_group)
        trials_24h_layout.setContentsMargins(5, 5, 5, 5)
        
        self.trials_24h_widget = pg.PlotWidget()
        self.trials_24h_widget.setBackground('#0B0F14')
        self.trials_24h_widget.setLabel('left', 'Trial Type (0=Left, 1=Right)')
        self.trials_24h_widget.setLabel('bottom', 'Hours Ago')
        self.trials_24h_widget.setTitle('Trials in Last 24 Hours')
        self.trials_24h_widget.showGrid(True, True, alpha=0.3)
        self.trials_24h_widget.setXRange(0, 24)
        self.trials_24h_widget.setYRange(-0.2, 1.2)
        
        # 初始化24h数据
        self.plot_24h_trials()
        
        trials_24h_layout.addWidget(self.trials_24h_widget)
        
        # 将两个图表添加到垂直布局中
        charts_main_layout.addWidget(perf_group, 1)  # 占用 1 份空间
        charts_main_layout.addWidget(trials_24h_group, 1)  # 占用 1 份空间
        
        # 下半部分：串口数据显示
        data_group = QGroupBox("Serial Data Log")
        data_layout = QVBoxLayout(data_group)
        data_layout.setContentsMargins(5, 5, 5, 5)
        
        self.serial_data_display = QTextEdit()
        self.serial_data_display.setReadOnly(True)
        self.serial_data_display.setFont(QFont("Consolas", 9))
        # 设置最小高度而不是最大高度，让它可以伸缩
        self.serial_data_display.setMinimumHeight(100)
        data_layout.addWidget(self.serial_data_display)
        
        # 清除按钮
        clear_btn = QPushButton("Clear Serial Data")
        clear_btn.clicked.connect(self.clear_serial_data)
        data_layout.addWidget(clear_btn)
        
        # 将图表容器和数据日志添加到主分割器
        main_splitter.addWidget(charts_container)
        main_splitter.addWidget(data_group)
        
        # 设置分割器比例：图表区域占大部分空间，Serial data log占较小空间
        main_splitter.setStretchFactor(0, 4)  # 图表区域占4/5 (增加高度)
        main_splitter.setStretchFactor(1, 1)  # Serial data log占1/5
        
        main_layout.addWidget(main_splitter)
        
        return panel
        
    def setup_connections(self):
        """设置信号连接"""
        # 连接按钮
        self.connect_btn.clicked.connect(self.toggle_serial_connection)
        
        # 控制面板按钮
        self.reward_btn.clicked.connect(self.send_reward_command)
        self.light_btn.clicked.connect(self.send_light_command)
        self.protocol_btn.clicked.connect(self.send_protocol_command)
        self.read_all_btn.clicked.connect(self.send_read_all_command)
        self.pause_btn.clicked.connect(self.send_pause_command)
        self.handshake_btn.clicked.connect(self.send_handshake_command)
        self.time_btn.clicked.connect(self.send_time_command)
        
        # 错误消息按钮
        self.delete_sel_btn.clicked.connect(self.delete_selected_error)
        self.clear_all_btn.clicked.connect(self.clear_all_errors)
        
        # 参数管理按钮
        self.save_params_btn.clicked.connect(self.save_parameters)
        self.load_params_btn.clicked.connect(self.load_parameters)
        
    def select_data_directory(self):
        """选择数据保存目录"""
        directory = QFileDialog.getExistingDirectory(self, "Select Data Directory", self.data_folder)
        if directory:
            self.set_data_directory(directory)

    def set_data_directory(self, directory):
        """Set data directory programmatically"""
        if os.path.exists(directory):
            self.selected_data_dir = directory
            # 从目录名提取Mouse ID
            mouse_id = os.path.basename(directory)
            if not mouse_id: # 处理根目录情况
                mouse_id = os.path.basename(os.path.dirname(directory))
            
            self.mouse_id_edit.setText(mouse_id)
            self.add_message(f"Data directory set to: {directory}")
            self.add_message(f"Mouse ID updated to: {mouse_id}")
            
            # 自动加载新目录下的参数
            self.load_parameters()
        else:
            self.add_message(f"Error: Directory does not exist: {directory}")

    def refresh_serial_ports(self):
        """刷新串口列表"""
        self.serial_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.serial_combo.addItem(f"{port.device} - {port.description}")
            
    def toggle_serial_connection(self):
        """切换串口连接"""
        if self.connect_btn.text() == "Connect":
            # 连接串口
            port_text = self.serial_combo.currentText()
            if not port_text:
                QMessageBox.warning(self, "Warning", "Please select a serial port!")
                return
                
            port = port_text.split(" - ")[0]
            
            try:
                self.serial_worker = SerialWorker(port)
                self.serial_worker.data_received.connect(self.handle_serial_data)
                self.serial_worker.error_occurred.connect(self.handle_serial_error)
                self.serial_worker.start()
                
                self.connect_btn.setText("Disconnect")
                self.connect_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #f44336;
                        color: white;
                        border: none;
                        padding: 8px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #da190b;
                    }
                """)
                self.mouse_id_edit.setEnabled(False)
                self.serial_combo.setEnabled(False)
                self.refresh_btn.setEnabled(False)
                
                self.load_parameters()
                # 发送时间校正命
                time.sleep(1)
                self.send_time_command()
                self.add_message("Serial connection established successfully")

                # 初始化图表
                self.plot_24h_trials()
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open serial port: {str(e)}")
        else:
            # 断开串口
            if self.serial_worker:
                self.serial_worker.stop()
                self.serial_worker = None
                
            self.connect_btn.setText("Connect")
            self.connect_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    padding: 8px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
            """)
            self.mouse_id_edit.setEnabled(True)
            self.serial_combo.setEnabled(True)
            self.refresh_btn.setEnabled(True)

            self.save_parameters()
            self.add_message("Serial connection closed")
            
    def handle_serial_data(self, data: str):
        """处理接收到的串口数据"""
        # Check for Trial Start signal 'C'
        if data.strip() == 'C':
            self.TrialStarted.emit()
            # Log it but maybe don't clutter the display if it's too frequent?
            # User said it represents trial start, so it's an event.
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.serial_data_display.append(f"[{timestamp}] Trial Start (C)")
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {data}"
        # 用于处理时间对齐事件，用来自动化switch 在mode0 和mode3 之间
        if data.startswith("ModeSwitch:"):
            # self.save_time_align_data()
            cmd = data[11:].strip()
            
            # Record ESA blocks (Mode 3 intervals)
            if cmd == 'ESA': # ESA Start
                self.current_esa_start_time = datetime.now()
                # Refresh chart to show the new active block immediately
                self.plot_24h_trials()
            elif cmd == 'LFP': # ESA End (Back to LFP)
                if self.current_esa_start_time:
                    end_time = datetime.now()
                    self.data_manager.add_mode_switch({
                        'start': self.current_esa_start_time,
                        'end': end_time
                    })
                    self.current_esa_start_time = None
                    # Refresh chart to show the new block
                    self.plot_24h_trials()

            self.Neural_recorder_command.emit(cmd) # 2 -> mode3; 1-> mode0
        
        # 添加到日志
        self.serial_data_log.append(log_entry)
        self.serial_data_display.append(log_entry)
        
        # 保持日志大小
        if len(self.serial_data_log) > 1000:
            self.serial_data_log = self.serial_data_log[-500:]
            self.serial_data_display.clear()
            for entry in self.serial_data_log[-100:]:
                self.serial_data_display.append(entry)
                
        # 保存原始数据到文件
        # self.save_data_to_file(data)
        
        # 解析数据
        self.parse_received_data(data)
        
    def parse_received_data(self, data: str):
        """解析接收到的数据, 由于状态机结束的时候为上一个trial"""
        if not data:
            return
            
        try:
            if data.startswith('T'):  # 试验数据
                parts = data[1:].split(',')
                if len(parts) >= 8:
                    try:
                        trial_num = int(parts[0])
                        trial_type = int(parts[1])
                        protocol_index = int(parts[2])
                        outcome = int(parts[3])
                        early_lick_rate = float(parts[4])
                        perf_100 = float(parts[5])
                        protocol_trials = int(parts[6])
                        protocol_perf = float(parts[7])
                        
                        # Update Protocol UI
                        self.protocol_edit.blockSignals(True)
                        self.protocol_edit.setValue(protocol_index)
                        self.protocol_edit.blockSignals(False)

                        # Update Status Labels
                        self.current_trial_num = trial_num + 1
                        self.trial_label.setText(f"{trial_num} - {perf_100:.1f}%")
                        self.protocol_trials_label.setText(str(protocol_trials))
                        
                        type_str = "Left" if trial_type == 1 else "Right" if trial_type == 2 else "Middle" if trial_type == 3 else "Unknown"
                        self.trial_type_label.setText(f"{trial_type} ({type_str})")
                        
                        outcome_str = "No Resp" if outcome == 0 else "Correct" if outcome == 1 else "Error" if outcome == 2 else "Early Lick" if outcome == 3 else "Other"
                        self.outcome_label.setText(f"{outcome} ({outcome_str})")
                        
                        self.protocol_perf_label.setText(f"{protocol_perf:.1f}%")
                        
                        # 保存试验数据
                        trial_data = {
                            'timestamp': datetime.now(),
                            'trial_num': trial_num,
                            'trial_type': trial_type,
                            'protocol': protocol_index,
                            'outcome': outcome,
                            'early_lick_rate': early_lick_rate,
                            'performance': perf_100,
                            'protocol_trials': protocol_trials,
                            'protocol_perf': protocol_perf
                        }
                        self.data_manager.add_trial(trial_data)
                        
                        # 更新试验次数/天
                        current_trials = self.data_manager.get_daily_trial_count()
                        self.trials_day_label.setText(f"{current_trials}/d")
                        
                        # 更新图表
                        self.update_performance_chart()
                        # 更新24小时试验图表
                        self.plot_24h_trials()
                    except ValueError as e:
                        self.add_message(f"Error parsing T data: {e}")
                    

            elif data.startswith('A'):  # 读取所有值的返回数据
                # 数据格式: A30;30;30;1;255;0;20.75;1761175304;0;
                # 分别为: reward_left, reward_right, reward_middle, low_light_intensity, 
                #        high_light_intensity, currProtocolIndex, random_value, timestamp, extra_TimeOut
                data_part = data[1:]  # 去掉开头的'A'
                if data_part.endswith(';'):
                    data_part = data_part[:-1]  # 去掉结尾的';'
                
                parts = data_part.split(';')
                if len(parts) >= 9:
                    try:
                        reward_left = int(parts[0])
                        reward_right = int(parts[1])
                        reward_middle = int(parts[2])
                        low_light_intensity = int(parts[3])
                        high_light_intensity = int(parts[4])
                        curr_protocol_index = int(parts[5])
                        random_value = float(parts[6])
                        teensy_timestamp = int(parts[7])
                        extra_timeout = int(parts[8])
                        
                        # 更新GUI控件的值
                        self.update_gui_values(reward_left, reward_right, reward_middle, 
                                             low_light_intensity, high_light_intensity, 
                                             curr_protocol_index, teensy_timestamp)
                        
                        # 添加成功消息
                        self.add_message(f"All values updated: R({reward_left},{reward_right},{reward_middle}) "
                                       f"L({low_light_intensity},{high_light_intensity}) P({curr_protocol_index})")
                        
                    except (ValueError, IndexError) as e:
                        self.add_message(f"Failed to parse A response: {str(e)}")
                else:
                    self.add_message(f"Invalid A response format: expected 9 values, got {len(parts)}")
                    
            elif data.startswith('E'):  # 错误消息
                error_msg = data[2:] if len(data) > 2 else "Unknown error"
                self.add_message(f"Error: {error_msg}")
                
        except Exception as e:
            self.add_message(f"Data parsing error: {str(e)}")
            
    def update_performance_chart(self):
        """更新性能图表"""
        # 使用数据管理器的高效方法获取性能数据
        x_data, y_perf, y_early, y_proto = self.data_manager.get_performance_data()
        
        if not x_data:
            return

        # 处理回环连线问题：检测 trial_num 减小的地方，插入 NaN 断开连线
        x_plot = []
        y_perf_plot = []
        y_early_plot = []
        y_proto_plot = []
        
        for i in range(len(x_data)):
            if i > 0 and x_data[i] < x_data[i-1]:
                # 插入断点
                x_plot.append(x_data[i]) 
                y_perf_plot.append(np.nan)
                y_early_plot.append(np.nan)
                y_proto_plot.append(np.nan)
            
            x_plot.append(x_data[i])
            y_perf_plot.append(y_perf[i])
            y_early_plot.append(y_early[i])
            y_proto_plot.append(y_proto[i])
        
        # 更新曲线，使用 connect="finite" 来处理 NaN 断点
        self.performance_curve.setData(x_plot, y_perf_plot, connect="finite")
        self.early_lick_curve.setData(x_plot, y_early_plot, connect="finite")
        self.protocol_perf_curve.setData(x_plot, y_proto_plot, connect="finite")
        
        # 自动调整X轴范围
        if len(x_plot) > 0:
            # 过滤掉NaN用于计算范围
            valid_x = [x for x in x_plot if not np.isnan(x)]
            if valid_x:
                self.plot_widget.setXRange(max(0, min(valid_x) - 5), max(valid_x) + 5)
            
    def handle_serial_error(self, error: str):
        """处理串口错误"""
        self.add_message(f"Serial error: {error}")
        QMessageBox.critical(self, "Serial Error", error)
        
    def send_serial_command(self, command: str) -> bool:
        """发送串口命令"""
        if self.serial_worker:
            success = self.serial_worker.send_data(command)
            if not success:
                self.add_message(f"Failed to send command: {command}")
            return success
        else:
            self.add_message("Serial port not connected")
            return False
            
    def send_reward_command(self):
        """发送奖励命令"""
        left = self.reward_left_edit.value()
        middle = self.reward_middle_edit.value()
        right = self.reward_right_edit.value()
        command = f"R{left},{right},{middle},"
        self.send_serial_command(command)
        
    def send_light_command(self):
        """发送光强命令"""
        low = self.low_light_edit.value()
        high = self.high_light_edit.value()
        command = f"L{low},{high},"
        self.send_serial_command(command)
        
    def send_protocol_command(self):
        """发送协议命令"""
        reply = QMessageBox.question(
            self, "Confirm", "Are you sure you want to change the protocol?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            protocol = self.protocol_edit.value()
            command = f"Z{protocol},"
            self.send_serial_command(command)
            
    def send_pause_command(self):
        """发送暂停/恢复命令"""
        if self.pause_btn.text() == "Pause Habits":
            self.send_serial_command("P")
            self.pause_btn.setText("Resume Habits")
        else:
            self.send_serial_command("M")
            self.pause_btn.setText("Pause Habits")
            
    def send_handshake_command(self):
        """发送握手命令"""
        self.send_serial_command("H")
        
    def send_time_command(self):
        """发送时间校正命令"""
        timestamp = int(time.time())
        command = f"T{timestamp}"
        self.send_serial_command(command)
        
        # 更新同步时间显示
        current_time = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
        self.sync_time_label.setText(f"Synced: {current_time}")
        self.add_message(f"Time synchronized at {current_time}")
        
    def send_read_all_command(self):
        """发送读取所有值命令"""
        command = "A"
        success = self.send_serial_command(command)
        if success:
            self.add_message("Read all values command sent")
            
    def update_gui_values(self, reward_left: int, reward_right: int, reward_middle: int,
                         low_light_intensity: int, high_light_intensity: int, 
                         curr_protocol_index: int, teensy_timestamp: int):
        """更新GUI控件的值"""
        try:
            # 更新奖励值
            self.reward_left_edit.setValue(reward_left)
            self.reward_right_edit.setValue(reward_right)
            self.reward_middle_edit.setValue(reward_middle)
            
            # 更新光强值
            self.low_light_edit.setValue(low_light_intensity)
            self.high_light_edit.setValue(high_light_intensity)
            
            # 更新协议索引
            self.protocol_edit.setValue(curr_protocol_index)
            # update sync time label
            self.sync_time_label.setText(f"Synced: {datetime.fromtimestamp(float(teensy_timestamp)).strftime('%H:%M:%S')}")
            
            self.add_message("GUI values updated successfully")
            
        except Exception as e:
            self.add_message(f"Failed to update GUI values: {str(e)}")
        
    def add_message(self, message: str):
        """添加消息到错误列表"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.error_listbox.addItem(f"[{timestamp}] {message}")
        
        # 保持列表大小
        if self.error_listbox.count() > 100:
            self.error_listbox.takeItem(0)
            
        # 滚动到底部
        self.error_listbox.scrollToBottom()
        
    def delete_selected_error(self):
        """删除选中的错误消息"""
        current_row = self.error_listbox.currentRow()
        if current_row >= 0:
            self.error_listbox.takeItem(current_row)
            
    def clear_all_errors(self):
        """清除所有错误消息"""
        self.error_listbox.clear()
        
    def clear_serial_data(self):
        """清除串口数据"""
        self.serial_data_display.clear()
        self.serial_data_log.clear()
        
    def save_parameters(self):
        """保存参数"""
        try:
            mouse_id = self.mouse_id_edit.text()
            if not mouse_id:
                mouse_id = "Mouse_001"  # 默认值
                
            # 确定保存目录
            if self.selected_data_dir:
                mouse_data_folder = self.selected_data_dir
            else:
                mouse_data_folder = get_mouse_data_directory(mouse_id)
            
            # 确保目录存在
            if not os.path.exists(mouse_data_folder):
                os.makedirs(mouse_data_folder)
            
            params = {
                'mouse_id': mouse_id,
                'reward_left': self.reward_left_edit.value(),
                'reward_middle': self.reward_middle_edit.value(),
                'reward_right': self.reward_right_edit.value(),
                'low_light': self.low_light_edit.value(),
                'high_light': self.high_light_edit.value(),
                'protocol': self.protocol_edit.value(),
                'start_date': self.start_date_edit.date().toString()
            }
            
            # 保存参数到mouse ID文件夹下
            params_file = os.path.join(mouse_data_folder, "habits_params.json")
            with open(params_file, 'w') as f:
                json.dump(params, f, indent=2)
            
            # 保存试验数据到mouse ID文件夹下
            trial_data_file = os.path.join(mouse_data_folder, "trial_data.json")
            
            # 直接保存内存中的所有数据（覆盖模式），作为当前状态的快照
            # 这样可以避免追加模式导致的重复数据问题，且能完美还原当前内存状态
            all_trial_data = []
            for trial in self.data_manager.trial_data:
                trial_dict = {
                    'timestamp': trial['timestamp'].isoformat(),
                    'trial_type': trial.get('trial_type', 0),
                    'outcome': trial.get('outcome', 0),
                    'response_time': trial.get('response_time', 0)
                }
                # 保存所有必要字段以还原状态
                if 'trial_num' in trial:
                    trial_dict['trial_num'] = trial['trial_num']
                if 'performance' in trial:
                    trial_dict['performance'] = trial['performance']
                if 'protocol' in trial:
                    trial_dict['protocol'] = trial['protocol']
                if 'early_lick_rate' in trial:
                    trial_dict['early_lick_rate'] = trial['early_lick_rate']
                if 'protocol_trials' in trial:
                    trial_dict['protocol_trials'] = trial['protocol_trials']
                if 'protocol_perf' in trial:
                    trial_dict['protocol_perf'] = trial['protocol_perf']
                    
                all_trial_data.append(trial_dict)
            
            # 保存数据
            with open(trial_data_file, 'w') as f:
                json.dump(all_trial_data, f, indent=2)
                
            # Save mode switches
            mode_switch_file = os.path.join(mouse_data_folder, "mode_switch_data.json")
            switches_to_save = []
            for switch in self.data_manager.mode_switches:
                switches_to_save.append({
                    'start': switch['start'].isoformat(),
                    'end': switch['end'].isoformat()
                })
            with open(mode_switch_file, 'w') as f:
                json.dump(switches_to_save, f, indent=2)
                
            self.add_message("Parameters updated and trial data snapshot saved successfully")
            
        except Exception as e:
            self.add_message(f"Failed to save parameters: {str(e)}")
            
    def load_parameters(self):
        """加载参数"""
        try:
            # 首先尝试从当前mouse ID文件夹加载
            mouse_id = self.mouse_id_edit.text()
            if not mouse_id:
                mouse_id = "Mouse_001"  # 默认值
                
            # 确定加载目录
            if self.selected_data_dir:
                mouse_data_folder = self.selected_data_dir
            else:
                mouse_data_folder = get_mouse_data_directory(mouse_id)
                
            params_file = os.path.join(mouse_data_folder, "habits_params.json")
            
            # 如果mouse ID文件夹不存在，尝试从旧的根目录加载
            if not os.path.exists(params_file) and not self.selected_data_dir:
                params_file = os.path.join(self.data_folder, "habits_params.json")
                
            if os.path.exists(params_file):
                with open(params_file, 'r') as f:
                    params = json.load(f)
                    
                self.mouse_id_edit.setText(params.get('mouse_id', mouse_id))
                self.reward_left_edit.setValue(params.get('reward_left', 30))
                self.reward_middle_edit.setValue(params.get('reward_middle', 30))
                self.reward_right_edit.setValue(params.get('reward_right', 30))
                self.low_light_edit.setValue(params.get('low_light', 1))
                self.high_light_edit.setValue(params.get('high_light', 255))
                self.protocol_edit.setValue(params.get('protocol', 0))
                
                if 'start_date' in params:
                    date = QDate.fromString(params['start_date'])
                    if date.isValid():
                        self.start_date_edit.setDate(date)
                        
                self.add_message("Parameters loaded successfully")
                
                # 如果没有选择目录，更新目录路径
                if not self.selected_data_dir:
                    mouse_id = params.get('mouse_id', mouse_id)
                    mouse_data_folder = get_mouse_data_directory(mouse_id)
            else:
                self.add_message("No parameter file found")
            
            # 加载试验数据
            trial_data_file = os.path.join(mouse_data_folder, "trial_data.json")
            
            # 如果mouse ID文件夹中没有数据，尝试从旧的根目录加载
            if not os.path.exists(trial_data_file) and not self.selected_data_dir:
                trial_data_file = os.path.join(self.data_folder, "trial_data.json")
                
            if os.path.exists(trial_data_file):
                with open(trial_data_file, 'r') as f:
                    trial_data_saved = json.load(f)
                
                # 清空现有数据并重新加载
                self.data_manager.clear_data()
                
                for trial_dict in trial_data_saved:
                    trial_data = {
                        'timestamp': datetime.fromisoformat(trial_dict['timestamp']),
                        'trial_type': trial_dict.get('trial_type', 0),
                        'outcome': trial_dict.get('outcome', 0),
                        'response_time': trial_dict.get('response_time', 0)
                    }
                    # 加载可选字段
                    if 'trial_num' in trial_dict:
                        trial_data['trial_num'] = trial_dict['trial_num']
                    if 'performance' in trial_dict:
                        trial_data['performance'] = trial_dict['performance']
                    if 'protocol' in trial_dict:
                        trial_data['protocol'] = trial_dict['protocol']
                    if 'early_lick_rate' in trial_dict:
                        trial_data['early_lick_rate'] = trial_dict['early_lick_rate']
                    elif 'early_lick' in trial_dict: # 兼容旧格式
                        trial_data['early_lick_rate'] = trial_dict['early_lick']
                    if 'protocol_trials' in trial_dict:
                        trial_data['protocol_trials'] = trial_dict['protocol_trials']
                    if 'protocol_perf' in trial_dict:
                        trial_data['protocol_perf'] = trial_dict['protocol_perf']
                        
                    self.data_manager.add_trial(trial_data)
                
                self.add_message(f"Loaded {len(trial_data_saved)} trial records")

                # 更新图表
                self.update_performance_chart()
                self.plot_24h_trials()
            
            # Load mode switches
            mode_switch_file = os.path.join(mouse_data_folder, "mode_switch_data.json")
            # Fallback check
            if not os.path.exists(mode_switch_file):
                 mode_switch_file = os.path.join(self.data_folder, "mode_switch_data.json")
            
            if os.path.exists(mode_switch_file):
                with open(mode_switch_file, 'r') as f:
                    saved_switches = json.load(f)
                
                self.data_manager.mode_switches.clear()
                for s in saved_switches:
                    self.data_manager.add_mode_switch({
                        'start': datetime.fromisoformat(s['start']),
                        'end': datetime.fromisoformat(s['end'])
                    })
                self.add_message(f"Loaded {len(saved_switches)} mode switch records")
                # Refresh chart again to show blocks
                self.plot_24h_trials()
            
            self._refresh_status_information()
                
        except Exception as e:
            self.add_message(f"Failed to load parameters: {str(e)}")

    def _refresh_status_information(self):
        try:
            start_date = self.start_date_edit.date().toPyDate()
            current_date = datetime.now().date()
            days = (current_date - start_date).days
            self.days_label.setText(f"{days:.1f} d")

            if len(self.data_manager.trial_data) == 0:
                self.trial_label.setText("0 - 0.0%")
                self.trials_day_label.setText("0/d")
                self.current_trial_num = 0
                self.protocol_trials_label.setText("0")
                self.trial_type_label.setText("-")
                self.outcome_label.setText("-")
                self.protocol_perf_label.setText("0%")
                return

            last_trial = self.data_manager.trial_data[-1]
            trial_num = last_trial.get('trial_num', len(self.data_manager.trial_data) - 1)
            perf = last_trial.get('performance', 0.0)
            
            self.trial_label.setText(f"{int(trial_num)} - {float(perf):.1f}%")

            self.current_trial_num = int(trial_num) + 1
            current_trials = self.data_manager.get_daily_trial_count()
            self.trials_day_label.setText(f"{current_trials}/d")
            
            # 恢复其他标签
            protocol_trials = last_trial.get('protocol_trials', 0)
            self.protocol_trials_label.setText(str(protocol_trials))
            
            trial_type = last_trial.get('trial_type', 0)
            type_str = "Left" if trial_type == 1 else "Right" if trial_type == 2 else "Middle" if trial_type == 3 else "Unknown"
            self.trial_type_label.setText(f"{trial_type} ({type_str})")
            
            outcome = last_trial.get('outcome', 0)
            outcome_str = "No Resp" if outcome == 0 else "Correct" if outcome == 1 else "Error" if outcome == 2 else "Early Lick" if outcome == 3 else "Other"
            self.outcome_label.setText(f"{outcome} ({outcome_str})")
            
            protocol_perf = last_trial.get('protocol_perf', 0.0)
            self.protocol_perf_label.setText(f"{float(protocol_perf):.1f}%")
            
        except Exception:
            pass
            
    def save_data_to_file(self, data: str):
        """保存原始数据到文件"""
        try:
            mouse_id = self.mouse_id_edit.text()
            date_str = datetime.now().strftime("%Y%m%d")
            filename = f"{mouse_id}_{date_str}.txt"
            
            # 确定保存目录
            if self.selected_data_dir:
                filepath = os.path.join(self.selected_data_dir, filename)
            else:
                filepath = os.path.join(self.data_folder, filename)
            
            with open(filepath, 'a', encoding='utf-8') as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] {data}\n")
                
        except Exception as e:
            self.add_message(f"Failed to save data: {str(e)}")
    
    def save_time_align_data(self):
        """保存TimeAlign时间戳数据到专用文件"""
        try:
            mouse_id = self.mouse_id_edit.text()
            if not mouse_id:
                self.add_message("Warning: Mouse ID is empty, using 'Unknown' for TimeAlign file")
                mouse_id = "Unknown"
            
            # 确定保存目录
            if self.selected_data_dir:
                mouse_folder = self.selected_data_dir
            else:
                mouse_folder = get_mouse_data_directory(mouse_id)
            
            # 生成TimeAlign文件名
            date_str = datetime.now().strftime("%Y%m%d")
            filename = f"TimeAlign_{date_str}.txt"
            filepath = os.path.join(mouse_folder, filename)
            
            # 获取高精度时间戳（毫秒级）
            now = datetime.now()
            timestamp_ms = int(now.timestamp() * 1000)  # 毫秒时间戳
            
            # 保存数据：trial_num 和 时间戳(ms)
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(f"{self.current_trial_num}\t{timestamp_ms}\n")
            
            # 添加日志消息
            self.add_message(f"TimeAlign recorded: Trial {self.current_trial_num}, Time {timestamp_ms}ms")
            
        except Exception as e:
            self.add_message(f"Failed to save TimeAlign data: {str(e)}")
    
    def plot_24h_trials(self):
        """绘制24小时试验散点图"""
        try:
            # 清除现有图表
            self.trials_24h_widget.clear()
            
            # 获取当前时间
            now = datetime.now()
            cutoff_time = now - timedelta(hours=24)
            
            # 使用数据管理器获取24小时内的数据
            recent_trials = self.data_manager.get_recent_trials(24)
            
            # 如果没有trial数据，显示空图表
            if not recent_trials:
                self.trials_24h_widget.setLabel('left', 'Trial Type')
                self.trials_24h_widget.setLabel('bottom', 'Time (hours ago)')
                self.trials_24h_widget.setTitle('24h Trials (No Recent Data)')
                return
            
            # 准备数据
            times = []  # 相对于当前时间的小时数（负值表示过去）
            trial_types = []  # 0=left, 1=right
            outcomes = []  # 0=no response, 1=correct, 2=error
            
            for trial in recent_trials:
                # 计算相对时间（小时前）
                time_diff = (now - trial['timestamp']).total_seconds() / 3600
                times.append(-time_diff)  # 负值表示过去
                
                # 转换trial_type: 1=left->0, 2=right->1, 3=middle->0.5
                if trial['trial_type'] == 1:  # left
                    trial_types.append(0)
                elif trial['trial_type'] == 2:  # right
                    trial_types.append(1)
                else:  # middle or other
                    trial_types.append(0.5)
                
                outcomes.append(trial['outcome'])
            
            # 根据outcome分组绘制散点
            import numpy as np
            times = np.array(times)
            trial_types = np.array(trial_types)
            outcomes = np.array(outcomes)
            
            # 绘制不同outcome的散点
            # Correct trials (outcome=1) - 绿色圆点
            correct_mask = outcomes == 1
            if np.any(correct_mask):
                scatter_correct = pg.ScatterPlotItem(
                    x=times[correct_mask], 
                    y=trial_types[correct_mask],
                    pen=pg.mkPen(None),
                    brush=pg.mkBrush(0, 255, 0, 180),  # 绿色
                    size=12,
                    symbol='o'
                )
                self.trials_24h_widget.addItem(scatter_correct)
            
            # Error trials (outcome=2) - 红色X
            error_mask = outcomes == 2
            if np.any(error_mask):
                scatter_error = pg.ScatterPlotItem(
                    x=times[error_mask], 
                    y=trial_types[error_mask],
                    pen=pg.mkPen(255, 0, 0, 255),  # 红色
                    brush=pg.mkBrush(None),
                    size=16,
                    symbol='x'
                )
                self.trials_24h_widget.addItem(scatter_error)
            
            # Early Lick trials (outcome=3) - 紫色菱形 (显眼)
            early_lick_mask = outcomes == 3
            if np.any(early_lick_mask):
                scatter_early_lick = pg.ScatterPlotItem(
                    x=times[early_lick_mask], 
                    y=trial_types[early_lick_mask],
                    pen=pg.mkPen(255, 0, 255, 255),  # 紫色
                    brush=pg.mkBrush(255, 0, 255, 200),
                    size=18,
                    symbol='d'
                )
                self.trials_24h_widget.addItem(scatter_early_lick)
            
            # No response trials (outcome=0) - 蓝色圆圈
            no_response_mask = outcomes == 0
            if np.any(no_response_mask):
                scatter_no_response = pg.ScatterPlotItem(
                    x=times[no_response_mask], 
                    y=trial_types[no_response_mask],
                    pen=pg.mkPen(255, 255, 255, 255),  # 白色
                    brush=pg.mkBrush(None),
                    size=12,
                    symbol='o'
                )
                self.trials_24h_widget.addItem(scatter_no_response)
            
            # 设置坐标轴
            self.trials_24h_widget.setLabel('left', 'Trial Type')
            self.trials_24h_widget.setLabel('bottom', 'Time (hours ago)')
            
            # 设置Y轴刻度和标签
            y_ticks = [(0, 'Left'), (0.5, 'Middle'), (1, 'Right')]
            self.trials_24h_widget.getAxis('left').setTicks([y_ticks])
            
            # 设置X轴范围和刻度
            self.trials_24h_widget.setXRange(-24, 0)
            self.trials_24h_widget.setYRange(-0.2, 1.2)
            x_ticks = [(-24, '24'), (-18, '18'), (-12, '12'), (-6, '6'), (0, '0')]
            self.trials_24h_widget.getAxis('bottom').setTicks([x_ticks])
            
            # 添加当前时间线
            current_line = pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen('red', width=2))
            self.trials_24h_widget.addItem(current_line)
            
            # 绘制 ESA Mode Blocks (ModeSwitch Intervals)
            # 包括当前正在进行的区间（如果有）
            active_intervals = self.data_manager.get_recent_mode_switches(24)
            if self.current_esa_start_time:
                active_intervals.append({
                    'start': self.current_esa_start_time,
                    'end': now
                })
            for switch in active_intervals:
                # Calculate relative time (hours ago)
                t_end = (now - switch['end']).total_seconds() / 3600
                t_start = (now - switch['start']).total_seconds() / 3600
                
                # Convert to X coordinates (negative values)
                x_start = -t_start
                x_end = -t_end
                
                # Clip to visible range
                if x_end < -24: continue
                if x_start > 0: x_start = 0 
                # Create a semi-transparent block
                # Using Cyan/Teal color with higher opacity for better visibility
                # Add to bottom (z-value) to not obscure dots
                region = pg.LinearRegionItem(
                    values=[x_start, x_end], 
                    brush=pg.mkBrush(0, 150, 136, 100),  # Teal, alpha=100 (increased)
                    pen=None,
                    movable=False
                )
                region.setZValue(-100) # Put behind scatter plots
                self.trials_24h_widget.addItem(region)

            # 计算性能统计
            total_trials = len(recent_trials)
            correct_trials = np.sum(outcomes == 1)
            error_trials = np.sum(outcomes == 2)
            no_response_trials = np.sum(outcomes == 0)
            early_lick_trials = np.sum(outcomes == 3)
            
            # 计算性能百分比（排除no response）
            if total_trials - no_response_trials > 0:
                performance = correct_trials / (total_trials - no_response_trials) * 100
            else:
                performance = 0
            
            # 设置标题
            title = f'24h Trials: {total_trials} total (Perf: {performance:.1f}%, EL: {early_lick_trials})'
            self.trials_24h_widget.setTitle(title)
            
        except Exception as e:
            self.add_message(f"Failed to plot 24h trials: {str(e)}")
            
    def update_gui(self):
        """更新GUI显示"""
        # 更新天数
        start_date = self.start_date_edit.date().toPyDate()
        current_date = datetime.now().date()
        days = (current_date - start_date).days
        self.days_label.setText(f"{days:.1f} d")

        self.save_parameters()
        
    def periodic_cleanup(self):
        """定期数据清理"""
        try:
            # 获取清理前的内存使用情况
            memory_before = self.data_manager.get_memory_usage()
            
            # 执行清理
            self.data_manager.force_cleanup()
            
            # 获取清理后的内存使用情况
            memory_after = self.data_manager.get_memory_usage()
            
            # 记录清理信息
            trials_before = memory_before['trial_data_count']
            trials_after = memory_after['trial_data_count']
            
            if trials_before != trials_after:
                self.add_message(f"Cleanup completed: trials {trials_before}→{trials_after}")
                
        except Exception as e:
            self.add_message(f"Cleanup failed: {str(e)}")
            
    def get_memory_status(self) -> str:
        """获取内存状态信息"""
        memory_info = self.data_manager.get_memory_usage()
        return (f"Memory: trials {memory_info['trial_data_count']}, "
                f"cache keys {memory_info['daily_cache_keys']}")
        
    def closeEvent(self, event):
        """关闭事件处理"""
        if self.serial_worker:
            self.serial_worker.stop()
        # 停止定时器
        if hasattr(self, 'cleanup_timer'):
            self.cleanup_timer.stop()
        event.accept()


if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    app.setApplicationName("Optimized Habits Panel")
    
    window = OptimizedHabitsPanel()
    window.show()
    
    sys.exit(app.exec())
