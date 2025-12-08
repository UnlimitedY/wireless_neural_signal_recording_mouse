"""
数据处理流程：
1. Habits 数据不考虑其timestamp，每个trial开始的时候触发一个serial 信号，读取该信号出现的PC 时间记录为一个文件为trialnum + PC_time, 加上 Trial.txt 记录的状态和Tevent.txt记录的事件offset作为标准认知行为学时间
2. 神经信号数据 直接使用每一个包上传的时候的PC时间，通过预实验来构建时间延迟模型进行时间校正
(不再使用led 和摄像头时间，数据处理过于复杂)
"""

""" 
Imports
"""
# from asyncore import read
# from email import message
# import asyncio
# from aioserial import AioSerial
import serial
import time
import datetime
# import threading
import binascii
import numpy as np
# import json
# from multiprocessing import Process, freeze_support
import collections as coll
from PyQt6.QtCore import QThread, pyqtSignal, QObject
import re
try:
    from pyedflib import EdfWriter, FILETYPE_EDFPLUS
    EDF_AVAILABLE = True
except Exception:
    EDF_AVAILABLE = False

# -------------------- Async EDF writer --------------------
import threading
import queue

class EDFWriterWorker(threading.Thread):
    """Background worker to write EDF files asynchronously to avoid GUI stutter.

    Use enqueue_write(...) to schedule write tasks; the worker will process
    tasks sequentially in the background.
    """
    def __init__(self):
        super().__init__(daemon=True)
        self._q = queue.Queue()
        self._stop = threading.Event()
        self.start()

    def enqueue_write(self, filename, channel_arrays, labels, sample_rates,
                      physical_min=-10000.0, physical_max=10000.0,
                      dimension='uV', annotations=None):
        self._q.put({
            'filename': filename,
            'channel_arrays': channel_arrays,
            'labels': labels,
            'sample_rates': sample_rates,
            'physical_min': physical_min,
            'physical_max': physical_max,
            'dimension': dimension,
            'annotations': annotations,
        })

    def run(self):
        while not self._stop.is_set():
            try:
                task = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                _safe_write_edf(
                    task['filename'],
                    task['channel_arrays'],
                    task['labels'],
                    task['sample_rates'],
                    physical_min=task['physical_min'],
                    physical_max=task['physical_max'],
                    dimension=task['dimension'],
                    annotations=task['annotations']
                )
            except Exception:
                # Swallow errors to keep background thread healthy
                pass
            finally:
                self._q.task_done()

    def stop(self):
        self._stop.set()

def _safe_write_edf(filename, channel_arrays, labels, sample_rates, physical_min=-10000.0, physical_max=10000.0, dimension='uV', annotations=None):
    """Write signals to an EDF/EDF+ file using pyedflib.
    Falls back by raising if pyedflib is unavailable so caller can handle.

    - channel_arrays: list of 1D arrays, one per channel
    - labels: list of string labels for channels
    - sample_rates: list of ints (same length as channel_arrays)
    - annotations: optional list of tuples (onset_seconds, duration_seconds, description)

    注意： edf 文件按 秒来对齐数据，所有每一个edf文件最后都会补充一段0值来对齐到下一秒，在后续数据处理过程中需要裁切一下
    """
    if not EDF_AVAILABLE:
        raise RuntimeError('pyedflib is not available')

    n_channels = len(channel_arrays)
    signal_headers = []
    # Build headers per channel
    for i in range(n_channels):
        sr = int(sample_rates[i])
        label = labels[i] if i < len(labels) else f"Ch{i}"
        # Allow per-channel dimensions via list/tuple
        dim = dimension[i] if isinstance(dimension, (list, tuple)) and i < len(dimension) else dimension
        sh = {
            'label': label,
            'dimension': dim,
            'sample_frequency': sr,
            'physical_min': float(physical_min),
            'physical_max': float(physical_max),
            'digital_min': -32768,
            'digital_max': 32767,
            'transducer': '',
            'prefilter': ''
        }
        signal_headers.append(sh)

    # Writer
    writer = EdfWriter(filename, n_channels=n_channels, file_type=FILETYPE_EDFPLUS)
    writer.setSignalHeaders(signal_headers)

    # Convert arrays to float64 and ensure equal lengths per channel for writeSamples
    samples = []
    min_len = None
    for arr in channel_arrays:
        a = np.asarray(arr, dtype=np.float64)
        if min_len is None:
            min_len = len(a)
        else:
            min_len = min(min_len, len(a))
        samples.append(a)
    # Trim to common minimal length to avoid mismatch errors
    if min_len is None:
        min_len = 0
    samples = [a[:min_len] for a in samples]

    if min_len > 0:
        writer.writeSamples(samples)

    # Optional annotations
    if annotations:
        for onset, duration, desc in annotations:
            try:
                writer.writeAnnotation(float(onset), float(duration), str(desc))
            except Exception:
                # Continue without blocking if any annotation fails
                pass

    writer.close()

def _interpolate_missing_packets_by_min(channel_arrays, timestamps, packet_samples, max_interval):
    """Insert filler samples for detected missing packets using a fixed minimum value 0.0.
    Returns new arrays suitable for EDF writing.
    """
    if not isinstance(channel_arrays, (list, tuple)):
        return channel_arrays
    n_packets_ts = len(timestamps)
    chunks_per_channel = []
    mins_per_channel = []
    usable_n_packets = n_packets_ts
    for arr in channel_arrays:
        a = list(arr)
        # Use fixed minimum value 0.0 for filler
        mins_per_channel.append(-10000)
        n_pack_arr = (len(a) // packet_samples) if packet_samples > 0 else 0
        usable_n_packets = min(usable_n_packets, n_pack_arr)
        chunks = [a[i*packet_samples:(i+1)*packet_samples] for i in range(n_pack_arr)]
        chunks_per_channel.append(chunks)

    if usable_n_packets <= 1:
        return [np.asarray(arr, dtype=np.float64) for arr in channel_arrays]

    missing_counts = {}
    for j in range(usable_n_packets - 1):
        try:
            diff = float(timestamps[j+1]) - float(timestamps[j])
        except Exception:
            diff = 0.0
        if diff > max_interval:
            missing = int(np.ceil(diff / max_interval)) - 1
        elif diff <= 0:
            missing = 1
        else:
            missing = 0
        if missing > 0:
            missing_counts[j] = missing

    filled_arrays = [list() for _ in channel_arrays]
    for j in range(usable_n_packets):
        for ch_idx in range(len(channel_arrays)):
            filled_arrays[ch_idx].extend(chunks_per_channel[ch_idx][j])
        # 避免在最后一个数据包之后插零，以免文件尾部出现多余零点
        if j in missing_counts and j < (usable_n_packets - 1 - 1):
            filler_packets = missing_counts[j]
            filler_len = filler_packets * packet_samples
            for ch_idx in range(len(channel_arrays)):
                filled_arrays[ch_idx].extend([mins_per_channel[ch_idx]] * filler_len)

    # 不再追加超出usable_n_packets的额外数据块，避免文件尾部长度超过当前时间戳对应的包范围

    return [np.asarray(a, dtype=np.float64) for a in filled_arrays]

def _interpolate_missing_packets_by_min_variable(raw_array, timestamps, packet_sizes, max_interval):
    """Interpolate missing packets for a single-channel array where packet sizes may vary.
    - raw_array: flat list/array of samples concatenated across packets
    - timestamps: list of per-packet timestamps (ms)
    - packet_sizes: list of per-packet sample counts
    - max_interval: threshold (ms) above which a gap indicates missing packets
    Returns a single numpy array with -10000 fillers inserted for missing packets.
    """
    import numpy as np
    if raw_array is None or timestamps is None:
        return np.asarray([], dtype=np.float64)
    raw = list(raw_array)
    n_packets = len(timestamps)
    if n_packets == 0:
        return np.asarray(raw, dtype=np.float64)
    # Ensure packet_sizes length; if missing, assume constant size from average
    if not packet_sizes or len(packet_sizes) != n_packets:
        avg_size = int(round(len(raw) / max(1, n_packets)))
        packet_sizes = [avg_size] * n_packets
    # Reconstruct per-packet chunks
    chunks = []
    idx = 0
    for sz in packet_sizes:
        chunks.append(raw[idx:idx+sz])
        idx += sz
    # Detect missing counts
    missing_counts = {}
    for j in range(n_packets - 1):
        try:
            diff = float(timestamps[j+1]) - float(timestamps[j])
        except Exception:
            diff = 0.0
        if diff > max_interval:
            missing = int(np.ceil(diff / max_interval)) - 1
        elif diff <= 0:
            missing = 1
        else:
            missing = 0
        if missing > 0:
            missing_counts[j] = missing
    # Filler size: use median packet size for stability
    med_size = int(np.median(packet_sizes)) if packet_sizes else 0
    filled = []
    for j in range(n_packets):
        filled.extend(chunks[j])
        if j in missing_counts and j < (n_packets - 1 - 1):
            filler_len = missing_counts[j] * med_size
            if filler_len > 0:
                filled.extend([-10000] * filler_len)
    return np.asarray(filled, dtype=np.float64)

def _build_timestamp_samples(timestamps, packet_samples, max_interval=None, insert_filler=True):
    """Build a per-sample TimeStamp channel from per-packet timestamps.
    - Repeats each packet timestamp for `packet_samples` samples.
    - Optionally inserts zeros for detected missing packets using `max_interval`.
    """
    import numpy as np
    if timestamps is None:
        return np.asarray([], dtype=np.float64)
    try:
        n_packets = len(timestamps)
    except Exception:
        timestamps = list(timestamps)
        n_packets = len(timestamps)
    if n_packets == 0 or packet_samples <= 0:
        return np.asarray([], dtype=np.float64)

    ts_samples = []
    for j in range(n_packets - 1):
        t = float(timestamps[j])
        ts_samples.extend([t] * packet_samples)
        # 仅在中间缺口插零，避免在文件末尾造成多余零点
        if insert_filler and max_interval is not None and j < (n_packets - 2):
            try:
                diff = float(timestamps[j + 1]) - t
            except Exception:
                diff = max_interval
            if diff > max_interval:
                missing = int(np.ceil(diff / max_interval)) - 1
            elif diff <= 0:
                missing = 1
            else:
                missing = 0
            if missing > 0:
                ts_samples.extend([0.0] * (missing * packet_samples))

    # Append last packet timestamp
    last_t = float(timestamps[-1])
    ts_samples.extend([last_t] * packet_samples)

    return np.asarray(ts_samples, dtype=np.float64)

def _broadcast_channel_to_samples_by_variable(channels, packet_sizes, timestamps, max_interval, filler_value=-10000):
    """Broadcast per-packet Raw_channel to per-sample array using variable packet sizes.
    - channels: list of per-packet channel indices
    - packet_sizes: list of per-packet sample counts
    - timestamps: list of per-packet timestamps (ms)
    - max_interval: gap threshold (ms) to insert missing packet fillers
    Returns numpy array aligned to raw data length, with filler for gaps.
    """
    import numpy as np
    if channels is None or timestamps is None:
        return np.asarray([], dtype=np.float64)
    n_packets = len(timestamps)
    if n_packets == 0:
        return np.asarray([], dtype=np.float64)
    # Ensure packet_sizes length; if missing, fallback to median size
    if not packet_sizes or len(packet_sizes) != n_packets:
        packet_sizes = [1] * n_packets
    # Detect missing packet gaps
    missing_counts = {}
    for j in range(n_packets - 1):
        try:
            diff = float(timestamps[j+1]) - float(timestamps[j])
        except Exception:
            diff = 0.0
        if diff > max_interval:
            missing = int(np.ceil(diff / max_interval)) - 1
        elif diff <= 0:
            missing = 1
        else:
            missing = 0
        if missing > 0:
            missing_counts[j] = missing
    med_size = int(np.median(packet_sizes)) if packet_sizes else 0
    out = []
    for j in range(n_packets):
        ch = channels[j] if j < len(channels) else filler_value
        sz = int(packet_sizes[j])
        out.extend([float(ch)] * sz)
        # 插入中间缺口的填充值，避免在文件末尾追加
        if j in missing_counts and j < (n_packets - 2):
            out.extend([float(filler_value)] * (missing_counts[j] * med_size))
    return np.asarray(out, dtype=np.float64)

############################################################
############################################################
############################Recording Modes################################
############################################################
############################################################
""" Mode 0/3 LFP/ESA 1kHz recording """
def get_raw_data_container(): # LFP raw data
    raw_data = {  # maximum 16 channels
        "Channel_0":[],
        "Channel_1":[],
        "Channel_2":[], 
        "Channel_3":[],
        "Channel_4":[], 
        "Channel_5":[],
        "Channel_6":[],
        "Channel_7":[],
        "Channel_8":[], 
        "Channel_9":[],
        "Channel_10":[],
        "Channel_11":[],
        "Channel_12":[],
        "Channel_13":[],
        "Channel_14":[],
        "Channel_15":[],
       
        "TimeStamp":[] , # real PC time after time calibration every packets (ms)
        
        "MissPackets":0, 
        "MissPacketsIndex":[]
        } 
    return raw_data

def get_mode3_data_container(): # LFP raw data
    raw_data = {  # maximum 16 channels
        "Channel_0":[],
        "Channel_1":[],
        "Channel_2":[], 
        "Channel_3":[],
        "Channel_4":[], 
        "Channel_5":[],
        "Channel_6":[],
        "Channel_7":[],
        "Channel_8":[], 
        "Channel_9":[],
        "Channel_10":[],
        "Channel_11":[],
        "Channel_12":[],
        "Channel_13":[],
        "Channel_14":[],
        "Channel_15":[],

        "ESA_Channel_0":[],
        "ESA_Channel_1":[],
        "ESA_Channel_2":[], 
        "ESA_Channel_3":[],
        "ESA_Channel_4":[], 
        "ESA_Channel_5":[],
        "ESA_Channel_6":[],
        "ESA_Channel_7":[],
        "ESA_Channel_8":[], 
        "ESA_Channel_9":[],
        "ESA_Channel_10":[],
        "ESA_Channel_11":[],
        "ESA_Channel_12":[],
        "ESA_Channel_13":[],
        "ESA_Channel_14":[],
        "ESA_Channel_15":[],
       
        "TimeStamp":[] , # real PC time after time calibration every packets (ms)

        "AP_timestamp":[] , # raster
        "Electrode":[] , # firing electrode
        "SpikeThreshold":[],

        "Raw_data":[], # 12.5Khz data
        "Raw_channel":[], # firing channel
        "Raw_timestamp":[], # raw timestamp
        "Raw_packet_sizes":[], # per-packet raw sample count for interpolation
        
        "MissPackets":0, 
        "MissPacketsIndex":[]
        } 
    return raw_data

""" IMU & Battery Status """
def get_events_data_container(): # Action potiential events & other recorded data
    events_data =  {
        "AcclX":[],
        "AcclY":[],
        "AcclZ":[],
        "GryoX":[],
        "GryoY":[],
        "GryoZ":[],

        "RSOC":[],
        "Battery_STAT":[],
        "Battery_voltage":[],
        "UpdateFlag":[]
        } 
    return events_data

############################################################
############################################################
############################Test Modes################################
############################################################
############################################################
""" Mode 1 SPike 20kHz recording """
def spike_data_container(): # mode 1; raster 16 channels + 1 channel raw data
    spike_data = {
        "AP_timestamp":[] , # raster
        "Electrode":[] , # firing electrode

        "Raw_data":[], # 20Khz data
        "Raw_channel":[], # firing channel
        "Raw_timestamp":[], # raw timestamp

        "SpikeThreshold":[],

        "MissPackets":0,
        "MissPacketsIndex":[]
    }
    return spike_data


############################################################
############################################################
############################Functions################################
############################################################
############################################################
def swap16Hex(str):
    return str[2:4] + str[0:2]

def my_gaussian_filter1d(seq, sigma=50 ,truncate=4.0 ,order=0): 
    """allow NaN elements
    sigma: 50 windows 401
    seq's type is ndarray
    """
    if seq.ndim > 1:
        seq = np.squeeze(seq ,1)
    length = len(seq)
    ## prepare Kernel
    sd = float(sigma)
    # make the radius of the filter equal to truncate standard deviations
    lw = int(truncate * sd + 0.5) # radius 
    weights = gaussian_kernel1d(sigma, order, lw)
    #print("weights_length:" ,weights.shape[0])
    ## NaN padding
    pad = lw 
    out = np.zeros((length + pad * 2), dtype=np.float64) # 1 dim
    out[pad: pad + length] = seq.copy().astype(np.float64)
    out[0:pad] = np.nan
    out[-pad:] = np.nan
    tmp = out.copy()
    ## filtering
    for y in range(length):
        mask = np.where(np.isnan(tmp[y: y + len(weights)]) == False) # 选择不是nan的部分,并返回对应的index值
        if np.size(mask) != 0:
            out[pad + y] = np.sum(weights[mask] * tmp[y: y + len(weights)][mask]) / np.sum(weights[mask]) #TODO 再检查一下
        else:
            out[pad + y] = np.nan
    #out = np.clip(out, 0, 1) # 对于有nan值不适用
    out = out[pad:pad + length]
    return out

def gaussian_kernel1d(sigma, order, radius):
    """
    Computes a 1-D Gaussian convolution kernel.
    """
    if order < 0:
        raise ValueError('order must be non-negative')
    exponent_range = np.arange(order + 1)
    sigma2 = sigma * sigma
    x = np.arange(-radius, radius+1)
    phi_x = np.exp(-0.5 / sigma2 * x ** 2)
    phi_x = phi_x / phi_x.sum()

    if order == 0:
        return phi_x
    else:
        q[0] = 1
        D = np.diag(exponent_range[1:], 1)  # D @ q(x) = q'(x)
        P = np.diag(np.ones(order)/-sigma2, -1)  # P @ q(x) = q(x) * p'(x)
        Q_deriv = D + P
        for _ in range(order):
            q = Q_deriv.dot(q)
        q = (x[:, None] ** exponent_range).dot(q)
        return q * phi_x

# filter
def LFP_filter(data, low_cutoff="None", high_cutoff="None", fs=1250, order=4): 
    """
    对神经信号进行带通、低通或高通滤波
    
    参数:
    data: numpy数组，输入的神经信号数据
    low_cutoff: 低截止频率（Hz），如果为None则执行低通滤波
    high_cutoff: 高截止频率（Hz），如果为None则执行高通滤波
    fs: 采样频率（Hz），默认为1000Hz
    order: 滤波器阶数，默认为4
    
    返回:
    filtered_data: 滤波后的数据，与输入数据维度相同
    """
    from scipy.signal import butter, filtfilt
    import numpy as np
    
    # 检查输入数据类型
    if not isinstance(data, np.ndarray):
        data = np.array(data)
    
    # 保存原始数据形状
    original_shape = data.shape
    
    # 将数据转换为一维数组进行处理
    data_1d = data.flatten()

    # 根据提供的截止频率确定滤波器类型
    if low_cutoff != "None" and high_cutoff != "None":
        low_cutoff = float(low_cutoff)
        high_cutoff = float(high_cutoff)
        # 带通滤波
        nyq = 0.5 * fs
        low = low_cutoff / nyq
        high = high_cutoff / nyq
        b, a = butter(order, [low, high], btype='band')
    elif low_cutoff != "None":
        low_cutoff = float(low_cutoff)
        # 高通滤波
        nyq = 0.5 * fs
        cutoff = low_cutoff / nyq
        b, a = butter(order, cutoff, btype='high')
    elif high_cutoff != "None":
        high_cutoff = float(high_cutoff)
        # 低通滤波
        nyq = 0.5 * fs
        cutoff = high_cutoff / nyq
        b, a = butter(order, cutoff, btype='low')
    else:
        # 如果没有提供截止频率，则返回原始数据
        return data
    
    # 应用滤波器
    filtered_data = filtfilt(b, a, data_1d)
    
    # 将滤波后的数据恢复为原始形状
    filtered_data = filtered_data.reshape(original_shape)
    # print(filtered_data)
    
    return filtered_data

def Timestamp_neural_calibration(x): #TODO offline calibration; Mode0 and mode3 maybe need different calibration
    return x
"""""""""""""""""""""""""""""""""""""""""""Main Class"""""""""""""""""""""""""""""""""""""""""""""""""""""""
class SerialPort(QThread):
    GUIUpdate = pyqtSignal(list) # for Recording modes
    EmptyGUIUpdate = pyqtSignal(list) # for idle mode
    CameraGUIUpdate = pyqtSignal(list) # for camera recording

    def __init__(self ,port ,buand) -> None:
        super(SerialPort ,self).__init__()

        """ GUI system """

        """ Data stream """
        self.port = serial.Serial(port ,buand)
        self.port.close() # close the port to avoid the error at the begining of Serial initalization

        # alignment 时间对齐策略： 每次记录
        """ 
        时间对齐：60分钟一个文件
        """
        self.Timestamp_recorder_counter = 0 # for information print
        self.Timestamp_HABITS_Trial = 0 # onset of one trial
        self.Timestamp_neural_signal = 0 # Raw timestamp of neural signal

        self.GUIUpdateInterval = 20 # packets num

        self.rssi = 0 # real-time rssi
        """ neural signal buffer """
        # mode 0 & 3
        self.lfptimestamp_GUI = []
        self.lfpdata_GUI = [[] for _ in range(16)]
        self.ESAdata_GUI = [[] for _ in range(16)]
        # sensor
        self.sensordata_GUI = [[] for _ in range(9)]
        #######
        ####### test modes
        # spike mode 1
        self.spiketimestamp_GUI = []
        self.spikedata_GUI = [] # only 1 channel
        self.spikerasterdata_GUI = [[] for _ in range(16)] 
        # spike mode 2
        self.spiketimestamp_mode2_GUI = []
        self.spikechannel_mode2_GUI = []
        self.spikedata_mode2_GUI = [[] for _ in range(16)] # 16 channel with 4 active channels

        """ packages processing """
        self.DAC_resolution = 1/(int('ffff' ,16)) * 1.225 * 2 # 1.225 is the reference voltage of the series of RHD2000 (bipolar ADC)

        """ raw data packets index"""
        # mode 0
        self.raw_data_per_packet_channel = 4
        self.raw_data_index_base = np.arange(9, 9 + self.raw_data_per_packet_channel, dtype=np.int64)
        # mode 3
        self.raw_data_per_packet_mode3 = 3
        self.raw_data_index_base_mode3 = np.arange(9, 9 + self.raw_data_per_packet_mode3, dtype=np.int64)
        # sensors
        self.sensor_index = np.arange(9, dtype=np.int64)
        
        """ Test Modes """
        # mode 1
        self.spike_channel_index_mode1_3 = 16 # mode 1
        # mode 2
        self.spike_FIFO_mode2 = coll.deque(maxlen=1000)
        self.spike_raw_channel = [0, 1, 2, 3] # 记录当前记录spike的raw channel; mode 2
         # remove duplicate packets and sorting acoording to timestamp and packets_index
        self.spike_maxlen_mode2 = 10

        """ Logging """
        self.sample_times = 0 # 记录 sample 开始的次数；也就是暂停sample 的次数
        
        """ File saving """
        # counter
        self.LFPRawCounter = 0 # Mode 0 LFP recording file counter
        self.Mode3RawCounter = 0 # Mode 3
        self.Mode2RawCounter = 0 # Mode 2
        self.SPIKERawCounter = 0 # Mode 1

        self.lfp_file_addr = ''
        self.mode3_file_addr = ''

        self.mode1_file_addr = ''
        self.mode2_file_addr = ''
        
        self.save_file_lfp_flag = False
        self.save_file_mode1_flag = False
        self.save_file_mode2_flag = False
        self.save_file_mode3_flag = False
        # LFP raw data or spike raw data
        self.raw_data = get_raw_data_container() # mode 0
        # Action potiential events & other recorded data
        self.sensors_data = get_events_data_container() 
        # Action potiential events data
        self.AP_data = spike_data_container() # mode 1
        self.AP_LFP_data = get_raw_data_container() # mode 2
        self.ESA_data = get_mode3_data_container() # mode 3
        # Async EDF writer to avoid GUI stutter for large saves
        self.edf_writer = EDFWriterWorker()
        
        self.sensor_fs = 0
        self.file_duration_lfp = 1000 * 60 * 60 # minutes
        self.file_duration_mode1 = 1000 * 60 * 10
        self.file_duration_mode2 = 1000 * 60  * 0.5
        self.file_duration_mode3 = 1000 * 60 * 60 # minutes 考虑到一个trial block 最大 60分钟
        # packets; default: equal to self.GUIUpdateInterval; in 1khz LFP: it's 12s；# 这个值不能设置太大，否则会导致缓存问题
        self.file_size_lfp = self.file_duration_lfp // 3.2 # ~1.25khz 4points per channel one packets 这样保证每一个文件的大小都是一样的，但对应的数据duration不一定（丢包问题）
        self.file_size_mode1 = self.file_duration_mode1 // 4.32 # 90points per channel at 20833Hz, single channel one packets
        self.file_size_mode2 = self.file_duration_mode2 // 1.44 # 30points per channel at 20833Hz, 4 channel one packets
        self.file_size_mode3 = self.file_duration_mode3 // 2.4 # 3points per channel at 1250Hz, 16 channel LFP&ESA (1.25Khz + 1.25Khz) one packets
        
        self.overflowSignal = [0, 0] # last and current

        self.LFP_max_interval = 5 # the maximum interval between raw data packets: 1khz lfp 32 channels: 3
        self.Spike_max_interval = 6 # same as above but for the minimum value
        self.mode2_max_interval = 2
        self.mode3_max_interval = 4
        self.mode3_raw_max_interval = 15

        """ IMU & LC data recording """
        self.sensor_update_flag = None
        self.sensor_name = list(self.sensors_data.keys())
        self.batteryStatus = 0

    def port_open(self):
        """ seiral ports opening """
        #### read parameters
        if not self.port.isOpen():
            self.port.open()
    
    def port_close(self):
        """ serial ports closing """
        self.port.close()
    
    def send_data(self ,data):
        """ write commands to peripheral """
        n = self.port.write(data) # must is bytes
        return n
    
    def read_data(self):
        """ read fifo of usbd """
        # # 清除 uart 的buffer
        self.flush()
        full_frame = bytearray()

        """ Main loop: read data from usbd """
        while(True): 
            temp_frame = self.port.read_all()
            if(len(temp_frame) == 0):
                continue
            full_frame += bytearray(temp_frame)
            if(full_frame[-4:] != b'%&\'('):
                continue
            else:
                self.data_process_full(full_frame)
                self.data_file_saving_control()
                full_frame = bytearray()
     
    def data_process_full(self, read_data):
        # GUI updater
        self.GUIUpate_enable()

        if(len(read_data)!= 0):
            read_data = str(binascii.b2a_hex(read_data ,' ', 2))
            spilt_temp = re.split('[ ][2][1][2][2][ ][2][3][2][4][ ]',read_data[2:-10])[0:-1] # 注意，这个正则化表达式很重要
            
            for _, packets in enumerate(spilt_temp):
                # get the category of packets
                try:
                    packets_type = int(packets[2:4], 16)
                    # rssi value occupy one short
                    self.rssi = round(int(packets[-4:-2], 16) * 0.01 + self.rssi * 0.99 , 2) # averaged
                    packets = packets[0:-5]
                    packet_length = (len(packets) + 1) / 5 
                except:
                    packets_type = -1
                    packet_length = 0
                    pass
                # packet proprocessing 
                """ mode 0 """
                if(packets_type == 1 and packet_length == 77): 
                    self.sensor_fs = 1250 / 4 # 4个点对应 1个IMU 数据点
                    # get timestamp ms
                    self.Timestamp_recorder_counter = int(swap16Hex(packets[5:9]) + swap16Hex(packets[10:14]), 16)
                    self.Timestamp_neural_signal = self.Timestamp_recorder_counter # int(time.time() * 1000) 

                    ###### Data process ######
                    _ = int(packets[0:2] ,16) # channel num of each packets
                    self.overflowSignal[1] = int(packets[15:17] ,16) # current signal
                    self.sensor_update_flag = int(packets[17:19] ,16) # sensor signal
                    # lfp packets
                    self.lfp_packets_process(packets[20:] + ' ')

                    # file saving
                    if(self.save_file_lfp_flag):
                        self.LFPRawCounter += 1

                    """  Test Mode: mode 1 """
                elif(packets_type == 2 and packet_length == 108): 
                    self.sensor_fs = 20833 / 90
                    self.Timestamp_recorder_counter = int(swap16Hex(packets[5:9]) + swap16Hex(packets[10:14]), 16)
                    self.Timestamp_neural_signal = self.Timestamp_recorder_counter # int(time.time() * 1000)
                    
                    self.spike_channel_index_mode1_3 = int(packets[0:2] ,16) # channel index of current packets
                    self.overflowSignal[1] = int(packets[15:17] ,16) # current signal
                    self.sensor_update_flag = int(packets[17:19] ,16) # sensor signal

                    self.spike_packets_process(packets[20:] + ' ')
                    # file saving
                    if(self.save_file_mode1_flag):
                        self.SPIKERawCounter += 1
                    pass
                
                    """  IMU packets: mode 2 not used """
                elif(packets_type == 6 and packet_length == 13): # other sensor data: 1 packets every 6ms
                    _ = int(swap16Hex(packets[5:9]) + swap16Hex(packets[10:14]), 16) # timestamp
                    self.overflowSignal[1] = int(packets[15:17] ,16) # current signal
                    self.sensor_update_flag = int(packets[17:19] ,16) # sensor signal
                    # sensor data proprocessing
                    self.spike_sensor_packets_process_mode2(packets[20:] + ' ') 
                    pass
                    
                    """  spike packets: mode 2 """
                elif(packets_type == 5 and packet_length == 126): # spike raw data with lfp: 3 packets every 6ms
                    """ 注意，这里需要做一下包的排序，包之间的间隔过短 会出现包顺序的错乱和重复: TODO"""
                    # timestamp
                    self.Timestamp_neural_signal = int(swap16Hex(packets[5:9]) + swap16Hex(packets[10:14]), 16) # 注意这里使用 下位机的timestamp
                    # self.Timestamp_neural_signal = int(time.time() * 1000)
                    # current index 
                    temp_packet_index = int(packets[0:2] ,16) # index of 3 packets list
                    # current signal
                    self.overflowSignal[1] = int(packets[15:17] ,16) 
                    # current recording channels
                    self.spike_raw_channel[0] = int(packets[22:24] ,16)
                    self.spike_raw_channel[1] = int(packets[20:22] ,16)
                    self.spike_raw_channel[2] = int(packets[27:29] ,16)
                    self.spike_raw_channel[3] = int(packets[25:27] ,16)

                    self.spike_FIFO_mode2.append([self.Timestamp_neural_signal, temp_packet_index, self.spike_raw_channel, (packets[30:] + ' ')]) # timestamp + packet_index + channel_index + raw data
                    # process data
                    self.spike_raw_packets_process_mode2()

                    # file saving
                    if(self.save_file_mode2_flag):
                        self.Mode2RawCounter += 1
                    pass

                    """ ESA packets: mode 3 """
                elif(packets_type == 7 and packet_length == 112): 
                    self.sensor_fs = 1250 / 3
                    self.Timestamp_recorder_counter = int(swap16Hex(packets[5:9]) + swap16Hex(packets[10:14]), 16)
                    self.Timestamp_neural_signal = self.Timestamp_recorder_counter # int(time.time() * 1000)

                    self.overflowSignal[1] = int(packets[15:17] ,16) # current signal
                    self.sensor_update_flag = int(packets[17:19] ,16)# sensor signal
                    self.mode_3_packets_process(packets[20:] + ' ')

                    # file saving
                    if(self.save_file_mode3_flag):
                        self.Mode3RawCounter += 1
                    pass
                
                elif(packets_type == 8 and packet_length == 124): # single channel Raw data recording
                    self.Timestamp_recorder_counter = int(swap16Hex(packets[5:9]) + swap16Hex(packets[10:14]), 16) # timestamp
                    self.Timestamp_neural_signal = self.Timestamp_recorder_counter

                    self.spike_channel_index_mode1_3 = int(packets[0:2] ,16) # channel index of current packets
                    self.mode3_raw_data_process(packets[20:] + ' ')

                    pass

                    """ for timestamp alignment """
                elif(packets_type == 4): # empty payload
                    # battery
                    idle_message = np.array(packets.split(' ')) # 取所有个 short
                    battery_a =  int(swap16Hex(idle_message[2]) ,16)
                    battery_b = int(swap16Hex(idle_message[3]) ,16)
                    battery_c = int(swap16Hex(idle_message[4]) ,16)
                    self.EmptyGUIUpdate.emit([battery_a, battery_b, battery_c])
                    pass

                elif(packets_type == 3): # timestamp payload
                    timestamp_message = np.array(packets.split(' ')) # 取所有个 short
                    _ = int(swap16Hex(timestamp_message[5][0:2]) ,16)
                    _ = int(swap16Hex(timestamp_message[5][2:4]) ,16)
                    pass
    
    def data_file_saving_control(self):
        # mode 0 
         ###### video recording ######
        if(self.save_file_lfp_flag):
            self.save_lfp_file(self.lfp_file_addr)
        elif(self.LFPRawCounter > 0):
            self.save_lfp_file(self.lfp_file_addr, manual_save=True)
        # mode 3
        if(self.save_file_mode3_flag):
            self.save_spike_mode3_file(self.mode3_file_addr)
        elif(self.Mode3RawCounter > 0):
            self.save_spike_mode3_file(self.mode3_file_addr, manual_save=True)
        
        # mode 1
        if(self.save_file_mode1_flag):
            self.save_spike_mode1_file(self.mode1_file_addr)
        elif(self.SPIKERawCounter > 0):
            self.save_spike_mode1_file(self.mode1_file_addr, manual_save=True)
        # mode 2
        if(self.save_file_mode2_flag):
            self.save_spike_mode2_file(self.mode2_file_addr)
        elif(self.Mode2RawCounter > 0):
            self.save_spike_mode2_file(self.mode2_file_addr, manual_save=True)
        pass
##############################################################
############################################################## Data processing
##############################################################
##############################################################

    def mode_3_packets_process(self, mode_3_data_buffer):
        # spilt
        mode_3_data_buffer = np.array(mode_3_data_buffer.split(' '))[0:-1]
        # 1. raw data 
        for channel_num in range(16):
            # lfp data
            temp_channel = mode_3_data_buffer[self.raw_data_index_base_mode3 + channel_num * self.raw_data_per_packet_mode3] 
            temp_channel_DAC_lfp = list(map(lambda x:self.DAC(swap16Hex(x), raw=False), temp_channel)) # 注意 对于 mode3 需要翻转一下
            self.lfpdata_GUI[channel_num].extend(temp_channel_DAC_lfp) 
            # ESA data
            temp_channel = mode_3_data_buffer[self.raw_data_index_base_mode3 + (channel_num + 16) * self.raw_data_per_packet_mode3] 
            temp_channel_DAC_ESA = list(map(lambda x:self.DAC(swap16Hex(x), raw=False), temp_channel)) # 注意 对于 mode3 需要翻转一下
            self.ESAdata_GUI[channel_num].extend(temp_channel_DAC_ESA) 
            
            # save to file
            if(self.save_file_mode3_flag):
                self.ESA_data["Channel_{}".format(channel_num)].extend(temp_channel_DAC_lfp)
                self.ESA_data["ESA_Channel_{}".format(channel_num)].extend(temp_channel_DAC_ESA)
            
        self.lfptimestamp_GUI.append(self.Timestamp_neural_signal)
           # save to file
        if(self.save_file_mode3_flag):
            self.ESA_data["TimeStamp"].append(self.Timestamp_neural_signal)
            self.sensors_data["UpdateFlag"].append(self.sensor_update_flag)
        # 3. sensor data
        temp_sensor_data = mode_3_data_buffer[self.sensor_index]
        # sensor data
        temp_sensor_data[0:3] = np.array(list(map(lambda x:self.LSM6DS3_accelData_in_g(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[0:3])))
        temp_sensor_data[3:6] = np.array(list(map(lambda x:self.LSM6DS3_gyroData_in_dps(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[3:6])))
        # LC data
        temp_sensor_data[6:] = np.array(list(map(lambda x:self.DAC(swap16Hex(x)), temp_sensor_data[6:])))
        
        for i in range(9):
            temp_sensor = list(temp_sensor_data[np.arange(0 + i, len(temp_sensor_data) ,9)])
            # for GUI
            self.sensordata_GUI[i].extend(temp_sensor)
            # save to file
            if(self.save_file_mode3_flag):
                self.sensors_data[self.sensor_name[i]].extend(temp_sensor)

        temp_raster_data = mode_3_data_buffer[-3:] #TODO 这里由于 下位机的处理速度，目前没有改功能
        for raster_time, spike_data in enumerate(temp_raster_data):
            spike_data = format(self.DAC(swap16Hex(spike_data)) ,'#018b')[2:] # 保留 前16位
            for channel_num ,spike_num in enumerate(spike_data):
                self.spikerasterdata_GUI[15 - channel_num].append(int(spike_num))
                 # for file saving
                if(int(spike_num) and self.save_file_mode3_flag):
                    self.ESA_data["AP_timestamp"].append(raster_time * 0.864 + self.Timestamp_neural_signal) # TODO raster bin size TBD
                    self.ESA_data["Electrode"].append(15 - channel_num)
        pass

    def mode3_raw_data_process(self, spike_data_buffer):
        # spilt
        spike_data_buffer = np.array(spike_data_buffer.split(' '))[0:-1]
        # 1. raw data + timestamp
        temp_channel = spike_data_buffer 
        temp_channel_DAC = list(map(lambda x:self.DAC(swap16Hex(x), raw=False), temp_channel)) #注意： mode3 中所有的原始数据在下位机上就已经做了前后8字节的对调,所以这里需要再对调一次
        # 2. give to GUI buffer
        self.spikedata_GUI.extend(temp_channel_DAC)
        self.spiketimestamp_GUI.append(self.Timestamp_neural_signal)
        # print(len(temp_channel_DAC), self.Timestamp_neural_signal)
        # 3. save to file
        if(self.save_file_mode3_flag):
            self.ESA_data["Raw_data"].extend(temp_channel_DAC)
            self.ESA_data["Raw_timestamp"].append(self.Timestamp_neural_signal)
            self.ESA_data["Raw_channel"].append(self.spike_channel_index_mode1_3) 
            self.ESA_data["Raw_packet_sizes"].append(len(temp_channel_DAC))
         

    def spike_sensor_packets_process_mode2(self, sensor_data):
        # spilt
        temp_sensor_data = np.array(sensor_data.split(' '))[0:-1]
        # sensor data
        temp_sensor_data[0:3] = np.array(list(map(lambda x:self.LSM6DS3_accelData_in_g(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[0:3])))
        temp_sensor_data[3:6] = np.array(list(map(lambda x:self.LSM6DS3_gyroData_in_dps(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[3:6])))
        # LC data
        temp_sensor_data[6:] = np.array(list(map(lambda x:self.DAC(swap16Hex(x)), temp_sensor_data[6:])))
        for i in range(9):
            temp_sensor = list(temp_sensor_data[np.arange(0 + i, len(temp_sensor_data) ,9)])
            # for GUI
            self.sensordata_GUI[i].extend(temp_sensor)
        pass

    def spike_raw_packets_process_mode2(self):
        if(len(self.spike_FIFO_mode2) >= self.spike_maxlen_mode2):
            index_temp = list(np.arange(0, self.spike_maxlen_mode2, 1))
            timestamp_temp = [] # 10
            packetIndex_temp = []
            FIFO_list_temp = []  # 看前10个包的数据
            # get pop times
            for i in range(self.spike_maxlen_mode2): 
                FIFO_temp = self.spike_FIFO_mode2.popleft()
                FIFO_list_temp.append(FIFO_temp)
                timestamp_temp.append(FIFO_temp[0])
                packetIndex_temp.append(FIFO_temp[1])

            ## sort acording to timestamp and packet index
            index_temp = sorted(index_temp, key=lambda x: (timestamp_temp[x], packetIndex_temp[x]))
            timestamp_temp = np.array(timestamp_temp)[index_temp]
            packetIndex_temp = np.array(packetIndex_temp)[index_temp]
            FIFO_list_temp = np.array(FIFO_list_temp, dtype=object)[index_temp]
            # remove duplicate value
            _, non_duplicate_index =np.unique(np.array([timestamp_temp, packetIndex_temp]),return_index=True, axis=1)
            FIFO_list_temp = FIFO_list_temp[non_duplicate_index]
            timestamp_temp = timestamp_temp[non_duplicate_index]
            packetIndex_temp = packetIndex_temp[non_duplicate_index]

            current_timestamp = np.unique(timestamp_temp)[0]
            temp_pop_times = np.sum(timestamp_temp == current_timestamp)

            for i in range(temp_pop_times): 
                temp_mode2 = FIFO_list_temp[i]
                # packet index and timestamp
                temp_i_timestamp = temp_mode2[0]
                temp_i_packetIndex = temp_mode2[1] # 0~2
                # spilt raw data
                temp_raw_mode2 = np.array(temp_mode2[3].split(' '))[0:-1]
                emp_channel_DAC = list(map(lambda x:self.DAC(x, raw=False), temp_raw_mode2))
                # raw data
                for i, channel_num in enumerate(temp_mode2[2]): # channel index: 4 channels : 30 points per packet per channel
                    self.spikedata_mode2_GUI[channel_num].extend(emp_channel_DAC[30 * i:30 * (i + 1)])
                    # file saving
                    if(self.save_file_mode2_flag):
                        self.AP_LFP_data["Channel_{}".format(channel_num)].extend(emp_channel_DAC[30 * i:30 * (i + 1)])
            
                # give to GUI buffer for timestamp
                self.spiketimestamp_mode2_GUI.append(current_timestamp) # timestamp
                # file saving
                if(self.save_file_mode2_flag):
                    self.AP_LFP_data["TimeStamp"].append(current_timestamp) # timestamp

            # append back to fifo
            for i in range(len(non_duplicate_index) - temp_pop_times):
                self.spike_FIFO_mode2.appendleft(FIFO_list_temp[len(non_duplicate_index) - i - 1])
        pass

    def lfp_packets_process(self, lfp_data_buffer):
        # spilt
        lfp_data_buffer = np.array(lfp_data_buffer.split(' '))[0:-1]
        # 1. raw data 
        for channel_num in range(16):
            temp_channel = lfp_data_buffer[self.raw_data_index_base + channel_num * self.raw_data_per_packet_channel]
            temp_channel_DAC = list(map(lambda x:self.DAC(x, raw=False), temp_channel))
            self.lfpdata_GUI[channel_num].extend(temp_channel_DAC)
            # save to file
            if(self.save_file_lfp_flag):
                self.raw_data["Channel_{}".format(channel_num)].extend(temp_channel_DAC)
        
        # 2. timestamp
        self.lfptimestamp_GUI.append(self.Timestamp_neural_signal)
            # save to file
        if(self.save_file_lfp_flag):
            self.raw_data["TimeStamp"].append(self.Timestamp_neural_signal)
            self.sensors_data["UpdateFlag"].append(self.sensor_update_flag)
        
        # 3. sensor data
        temp_sensor_data = lfp_data_buffer[self.sensor_index]
        # IMU data
        temp_sensor_data[0:3] = np.array(list(map(lambda x:self.LSM6DS3_accelData_in_g(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[0:3])))
        temp_sensor_data[3:6] = np.array(list(map(lambda x:self.LSM6DS3_gyroData_in_dps(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[3:6])))
        # LC data
        temp_sensor_data[6:] = np.array(list(map(lambda x:self.DAC(swap16Hex(x)), temp_sensor_data[6:])))
        
        for i in range(9):
            temp_sensor = list(temp_sensor_data[np.arange(0 + i, len(temp_sensor_data) ,9)])
            # for GUI
            self.sensordata_GUI[i].extend(temp_sensor)
            # save to file
            if(self.save_file_lfp_flag):
                self.sensors_data[self.sensor_name[i]].extend(temp_sensor)

    def spike_packets_process(self, spike_data_buffer):
        # spilt
        spike_data_buffer = np.array(spike_data_buffer.split(' '))[0:-1]
        # 1. raw data + timestamp
        temp_channel = spike_data_buffer[9:-5] 
        temp_channel_DAC = list(map(lambda x:self.DAC(x, raw=False), temp_channel))
        # 2. give to GUI buffer
        self.spikedata_GUI.extend(temp_channel_DAC)
        self.spiketimestamp_GUI.append(self.Timestamp_neural_signal)
        # 3. save to file
        if(self.save_file_mode1_flag):
            self.AP_data["Raw_data"].extend(temp_channel_DAC)
            self.AP_data["Raw_timestamp"].append(self.Timestamp_neural_signal)
            self.AP_data["Raw_channel"].append(self.spike_channel_index_mode1_3) 
            self.sensors_data["UpdateFlag"].append(self.sensor_update_flag)
            # Log
            if(len(temp_channel_DAC) != 90):
                print("spike data length error", len(temp_channel_DAC))
            
        # 4. sensor data
        temp_sensor_data = spike_data_buffer[self.sensor_index]
        # sensor data
        temp_sensor_data[0:3] = np.array(list(map(lambda x:self.LSM6DS3_accelData_in_g(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[0:3])), dtype=np.float32)
        temp_sensor_data[3:6] = np.array(list(map(lambda x:self.LSM6DS3_gyroData_in_dps(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[3:6])), dtype=np.float32)
        # LC data
        temp_sensor_data[6:] = np.array(list(map(lambda x:self.DAC(swap16Hex(x)), temp_sensor_data[6:])), dtype=np.float32)
        for i in range(9):
            temp_sensor = list(temp_sensor_data[np.arange(0 + i, len(temp_sensor_data) ,9)])
            # for GUI
            self.sensordata_GUI[i].extend(temp_sensor)
            # for file
            if(self.save_file_mode1_flag):
                self.sensors_data[self.sensor_name[i]].extend(temp_sensor)
        
        # 5. raster data
        temp_raster_data = spike_data_buffer[-5:]
        for raster_time, spike_data in enumerate(temp_raster_data):
            spike_data = format(self.DAC(swap16Hex(spike_data)) ,'#018b')[2:] # 保留 前16位
            for channel_num ,spike_num in enumerate(spike_data):
                self.spikerasterdata_GUI[15 - channel_num].append(int(spike_num))
                # for file saving
                if(int(spike_num) and self.save_file_mode1_flag):
                    self.AP_data["AP_timestamp"].append(raster_time * 0.864 + self.Timestamp_neural_signal) # 一个 raster bin 大概为0.864ms
                    self.AP_data["Electrode"].append(15 - channel_num)


##############################################################
############################################################## Data Saving
##############################################################
##############################################################
    def save_lfp_file(self, addr, manual_save=False):
        """ save data to a file"""
        if(self.LFPRawCounter % 500 == 0): # print file collection progress
            print("file preparing", round(self.LFPRawCounter/self.file_size_lfp * 100, 2) , "%", "have run ", round(self.Timestamp_recorder_counter / 1000 / 60, 2), "min")

        if(self.LFPRawCounter >= self.file_size_lfp or manual_save): 
            self.LFPRawCounter = 0
            # 1. detect if there exist one or mutiple miss packets when save raw data to a structured file
            timestamp_files = np.array(self.raw_data["TimeStamp"])
            timestamp_diff = np.diff(timestamp_files)
            # recording the missed packets number
            miss_packets = np.argwhere((timestamp_diff > self.LFP_max_interval) | (timestamp_diff <= 0)).flatten() # the interval exceed the set value
            self.raw_data["MissPacketsIndex"] = miss_packets
            # number
            miss_packets_num = np.ceil(timestamp_diff[miss_packets] / self.LFP_max_interval)
            miss_packets_num = np.sum(miss_packets_num.flatten())
            self.raw_data["MissPackets"] = miss_packets_num

            # 2. save the file
            now_time=datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')

            # LFP 16 channels
            lfp_channels = [self.raw_data[f"Channel_{i}"] for i in range(16)]
            # 插值填补丢包（每包4点/通道，间隔阈值 LFP_max_interval）
            lfp_channels_filled = _interpolate_missing_packets_by_min(
                lfp_channels,
                self.raw_data["TimeStamp"],
                self.raw_data_per_packet_channel,
                self.LFP_max_interval
            )
            lfp_labels = [f"Ch{i}" for i in range(16)]
            lfp_fs = [1250] * 16  # approximate 1.25kHz
            lfp_filename = addr[0:-4] + str(now_time) + "lfp.edf"
            # 将第保存数据时刻数据包的时间戳写入注释，不再保存为独立通道
            End_ts = float(time.time() * 1000) # ms

            lfp_annotations = []
            lfp_annotations.append((0.0, 0.0, f"EndTimestamp(ms)={End_ts}"))
            self.edf_writer.enqueue_write(lfp_filename, lfp_channels_filled, lfp_labels, lfp_fs, dimension='uV', annotations=lfp_annotations)
            # print(len(lfp_channels_filled), len(lfp_channels_filled[0]), len(lfp_channels_filled[1]), lfp_channels_filled[0][-1])
            # Sensors 9 channels（加入插值以标记丢包，每包1点/通道，阈值 LFP_max_interval）
            sensor_keys = self.sensor_name  # list of 9 labels
            sensor_channels = [self.sensors_data[k] for k in sensor_keys]
            sensor_channels_filled = _interpolate_missing_packets_by_min(
                sensor_channels,
                self.raw_data["TimeStamp"],
                1,
                self.LFP_max_interval
            )
            sensor_fs = [self.sensor_fs] * len(sensor_channels_filled)
            sensor_filename = addr[0:-4] + str(now_time) + "sensor.edf"
            # 注释写入结束时间戳
            sensor_annotations = []
            End_ts_sens = End_ts
            sensor_annotations.append((0.0, 0.0, f"EndTimestamp(ms)={End_ts_sens}"))
            self.edf_writer.enqueue_write(sensor_filename, sensor_channels_filled, sensor_keys, sensor_fs, dimension='unit', annotations=sensor_annotations)
            
            
            # 3. reinit the temp array
            self.raw_data = get_raw_data_container()
            self.sensors_data = get_events_data_container()

            # 3.5 camera
            self.CameraGUIUpdate.emit([]) 
            # 4. resample detection
            if(sum(self.overflowSignal) == 1): #  重新开始sample
                self.sample_times += 1
                self.overflowSignal[0] = self.overflowSignal[1]
                print("sample begin!")

    def save_spike_mode3_file(self, addr, manual_save=False):
        """ save data to a file"""
        if(self.Mode3RawCounter % 500 == 0): # print file collection progress
            print("file preparing", round(self.Mode3RawCounter/self.file_size_mode3 * 100, 2) , "%", "have run ", round(self.Timestamp_recorder_counter / 1000 / 60, 2), "min")

        if(self.Mode3RawCounter >= self.file_size_mode3 or manual_save): 
            self.Mode3RawCounter = 0
            # 1. detect if there exist one or mutiple miss packets when save raw data to a structured file
            timestamp_files = np.array(self.ESA_data["TimeStamp"])
            timestamp_diff = np.diff(timestamp_files)
            # recording the missed packets number
            miss_packets = np.argwhere((timestamp_diff > self.mode3_max_interval) | (timestamp_diff <= 0)).flatten() # the interval exceed the set value
            self.ESA_data["MissPacketsIndex"] = miss_packets
            # number
            miss_packets_num = np.ceil(timestamp_diff[miss_packets] / self.mode3_max_interval)
            miss_packets_num = np.sum(miss_packets_num.flatten())
            self.ESA_data["MissPackets"] = miss_packets_num

            # 2. save the file
            now_time=datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
          
            # Combine LFP and ESA into one EDF with 32 channels
            lfp_channels = [self.ESA_data[f"Channel_{i}"] for i in range(16)]
            esa_channels = [self.ESA_data[f"ESA_Channel_{i}"] for i in range(16)]
            all_channels = lfp_channels + esa_channels
            # 插值填补丢包（每包3点/通道，间隔阈值 mode3_max_interval）
            all_channels_filled = _interpolate_missing_packets_by_min(
                all_channels,
                self.ESA_data["TimeStamp"],
                self.raw_data_per_packet_mode3,
                self.mode3_max_interval
            )
            labels = [f"Ch{i}" for i in range(16)] + [f"ESA{i}" for i in range(16)]
            fs = [1250] * len(all_channels)
            mode3_filename = addr[0:-4] + str(now_time) + "LFP&ESA.edf"
            # 注释结束起始时间戳
            End_ts_m3 = float(time.time() * 1000) # ms
            mode3_annotations = []
            mode3_annotations.append((0.0, 0.0, f"EndTimestamp(ms)={End_ts_m3}"))
            # 异步写入，避免一次性写入引起GUI卡顿
            self.edf_writer.enqueue_write(mode3_filename, all_channels_filled, labels, fs, dimension='uV', annotations=mode3_annotations)

            # Sensors（加入插值以标记丢包，每包1点/通道，阈值 mode3_max_interval）
            sensor_keys = self.sensor_name
            sensor_channels = [self.sensors_data[k] for k in sensor_keys]
            sensor_channels_filled = _interpolate_missing_packets_by_min(
                sensor_channels,
                self.ESA_data["TimeStamp"],
                1,
                self.mode3_max_interval
            )
            sensor_fs = [self.sensor_fs] * len(sensor_channels_filled)
            sensor_filename = addr[0:-4] + str(now_time) + "sensor.edf"
            # 注释写入结束时间戳
            sensor_annotations = []
            End_ts_m3_sens = End_ts_m3
            sensor_annotations.append((0.0, 0.0, f"EndTimestamp(ms)={End_ts_m3_sens}"))
            self.edf_writer.enqueue_write(sensor_filename, sensor_channels_filled, sensor_keys, sensor_fs, dimension='unit', annotations=sensor_annotations)

            # New: ESA Raw two-channel EDF (RawData + RawChannel broadcast) at 12.5kHz
            raw_samples = self.ESA_data.get("Raw_data", [])
            raw_timestamps = self.ESA_data.get("Raw_timestamp", [])
            raw_sizes = self.ESA_data.get("Raw_packet_sizes", [])
            raw_ch_list = self.ESA_data.get("Raw_channel", [])
            if len(raw_samples) > 0 and len(raw_timestamps) > 0:
                # Interpolate missing packets in raw data
                raw_filled = _interpolate_missing_packets_by_min_variable(
                    raw_samples,
                    raw_timestamps,
                    raw_sizes,
                    self.mode3_raw_max_interval
                )
                # Broadcast per-packet channel index to per-sample array
                ch_broadcast = _broadcast_channel_to_samples_by_variable(
                    raw_ch_list,
                    raw_sizes,
                    raw_timestamps,
                    self.mode3_raw_max_interval,
                    filler_value=-10000
                )
                labels = ["RawData", "RawChannel"]
                fs = [12500, 12500]
                dims = ["uV", "index"]
                mode3_raw_filename = addr[0:-4] + str(now_time) + "mode3_raw.edf"
                raw_annotations = []
                raw_annotations.append((0.0, 0.0, f"EndTimestamp(ms)={End_ts_m3}"))
                self.edf_writer.enqueue_write(mode3_raw_filename, [raw_filled, ch_broadcast], labels, fs, dimension=dims, annotations=raw_annotations)
            
            # 3. reinit the temp array
            self.ESA_data = get_mode3_data_container()
            self.sensors_data = get_events_data_container()

            # 3.5 camera
            self.CameraGUIUpdate.emit([]) 

            # 4. resample detection
            if(sum(self.overflowSignal) == 1): #  重新开始sample
                self.sample_times += 1
                self.overflowSignal[0] = self.overflowSignal[1]
                print("sample begin!")
           
    def save_spike_mode1_file(self, addr, manual_save=False):
        if(self.SPIKERawCounter % 500 == 0):
            print("file preparing",  round(self.SPIKERawCounter/self.file_size_mode1 * 100, 2) , "%" ,"have run ", round(self.Timestamp_recorder_counter / 1000 / 60, 2), "min")
        
        """ save data to a file"""
        if(self.SPIKERawCounter == self.file_size_mode1 or manual_save):
            self.SPIKERawCounter = 0
            # 1. detect if there exist one or mutiple miss packets when save raw data to a structured file
            timestamp_files = np.array(self.AP_data["Raw_timestamp"])
            timestamp_diff = np.diff(timestamp_files)
            # recording the missed packets number   
            miss_packets = np.argwhere((timestamp_diff > self.Spike_max_interval) | (timestamp_diff <= 0)).flatten() # the interval exceed the set value
            self.AP_data["MissPacketsIndex"] = miss_packets
            # number
            miss_packets_num = np.ceil(timestamp_diff[miss_packets] / self.Spike_max_interval)
            miss_packets_num = np.sum(miss_packets_num.flatten())
            self.AP_data["MissPackets"] = miss_packets_num # 100000
            # 2. save the file
            now_time=datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')

            # Single-channel spike raw data at ~20.833kHz
            raw_samples = [self.AP_data["Raw_data"]]
            # 插值填补丢包（每包90点，间隔阈值 Spike_max_interval）
            raw_samples_filled = _interpolate_missing_packets_by_min(
                raw_samples,
                self.AP_data["Raw_timestamp"],
                90,
                self.Spike_max_interval
            )
            labels = ["Raw"]
            fs = [20833]
            mode1_filename = addr[0:-4] + str(now_time) + "mode1.edf"
            # Build annotations from AP events and start timestamp
            annotations = []
            ap_ts = self.AP_data.get("AP_timestamp", [])
            electrodes = self.AP_data.get("Electrode", [])
            n_ann = min(len(ap_ts), len(electrodes))
            for i in range(n_ann):
                onset_sec = float(ap_ts[i]) / 1000.0
                desc = f"Spike@Ch{electrodes[i]}"
                annotations.append((onset_sec, 0.0, desc))
            # jiesh时间戳注释
            End_ts_m1 = float(time.time() * 1000) # ms
            annotations.insert(0, (0.0, 0.0, f"EndTimestamp(ms)={End_ts_m1}"))
            self.edf_writer.enqueue_write(mode1_filename, raw_samples_filled, labels, fs, dimension='uV', annotations=annotations)

            # Sensors（加入插值以标记丢包，每包1点/通道，阈值 Spike_max_interval）
            sensor_keys = self.sensor_name
            sensor_channels = [self.sensors_data[k] for k in sensor_keys]
            sensor_channels_filled = _interpolate_missing_packets_by_min(
                sensor_channels,
                self.AP_data["Raw_timestamp"],
                1,
                self.Spike_max_interval
            )
            sensor_fs = [self.sensor_fs] * len(sensor_channels_filled)
            sensor_filename = addr[0:-4] + str(now_time) + "sensor.edf"
            # 注释写入结束时间戳
            sensor_annotations = []
            End_ts_m1_sens = End_ts_m1
            sensor_annotations.append((0.0, 0.0, f"EndTimestamp(ms)={End_ts_m1_sens}"))
            self.edf_writer.enqueue_write(sensor_filename, sensor_channels_filled, sensor_keys, sensor_fs, dimension='unit', annotations=sensor_annotations)
           
            # 3. reinit the temp array
            self.AP_data = spike_data_container()
            self.sensors_data = get_events_data_container()
            # 4. resample detection
            if(sum(self.overflowSignal) == 1): #  重新开始sample
                self.sample_times += 1
                self.overflowSignal[0] = self.overflowSignal[1]
                print("sample begin!")
        pass

    def save_spike_mode2_file(self, addr, manual_save=False):
        if(self.Mode2RawCounter % 500 == 0):
            print("file preparing", round(self.Mode2RawCounter/self.file_size_mode2 * 100, 2) , "%")
        """ save data to a file"""
        if(self.Mode2RawCounter == self.file_size_mode2 or manual_save):
            self.Mode2RawCounter = 0
            # 1. detect if there exist one or mutiple miss packets when save raw data to a structured file  
            timestamp_files = np.array(self.AP_LFP_data["TimeStamp"])       
            timestamp_diff = np.diff(timestamp_files)
            # recording the missed packets number
            miss_packets = np.argwhere((timestamp_diff > self.mode2_max_interval) | (timestamp_diff <= 0)).flatten() # the interval exceed the set value
            self.AP_LFP_data["MissPacketsIndex"] = miss_packets
            # number
            miss_packets_num = np.ceil(timestamp_diff[miss_packets] / self.mode2_max_interval)
            miss_packets_num = np.sum(miss_packets_num.flatten())
            self.AP_LFP_data["MissPackets"] = miss_packets_num # 100000

            # 2. save the file  
            now_time=datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')

            # Collect only non-empty channels to avoid header mismatch
            channels = []
            labels = []
            for i in range(16):
                data_i = self.AP_LFP_data[f"Channel_{i}"]
                if len(data_i) > 0:
                    channels.append(data_i)
                    labels.append(f"Ch{i}")
            if len(channels) == 0:
                raise RuntimeError("No Mode2 channel data to save")
            # 插值填补丢包（每包30点/通道，间隔阈值 mode2_max_interval）
            channels_filled = _interpolate_missing_packets_by_min(
                channels,
                self.AP_LFP_data["TimeStamp"],
                30,
                self.mode2_max_interval
            )
            fs = [20833] * len(channels_filled)
            mode2_filename = addr[0:-4] + str(now_time) + "AP_LFP_Raw_data.edf"
            # 注释写入起始时间戳
            mode2_annotations = []
            End_ts_m2 = float(time.time() * 1000) # ms
            mode2_annotations.append((0.0, 0.0, f"EndTimestamp(ms)={End_ts_m2}"))
            self.edf_writer.enqueue_write(mode2_filename, channels_filled, labels, fs, dimension='uV', annotations=mode2_annotations)

            # 3. reinit the temp array
            self.AP_LFP_data = get_raw_data_container()   

            # 4. resample detection 
            if(sum(self.overflowSignal) == 1): #  重新开始sample
                self.sample_times += 1
                self.overflowSignal[0] = self.overflowSignal[1]
                print("sample begin!")
        pass


##############################################################
############################################################## GUI Data real update
##############################################################
##############################################################

    def GUIUpate_enable(self):
        """ GUI update """ 
        if(len(self.lfptimestamp_GUI) >= self.GUIUpdateInterval): # mode 0 & 3
            self.GUIUpdate.emit([[0], self.lfptimestamp_GUI, self.lfpdata_GUI, self.sensordata_GUI, self.spikerasterdata_GUI, self.ESAdata_GUI]) # mode 0
            self.lfptimestamp_GUI = []
            self.lfpdata_GUI = [[] for _ in range(16)]
            self.sensordata_GUI = [[] for _ in range(9)]
            self.spikerasterdata_GUI = [[] for _ in range(16)]
            self.ESAdata_GUI = [[] for _ in range(16)]
        elif(len(self.spiketimestamp_GUI) >= self.GUIUpdateInterval): # mode 1
            self.GUIUpdate.emit([[1, self.spike_channel_index_mode1_3], self.spiketimestamp_GUI, self.spikedata_GUI, self.sensordata_GUI, self.spikerasterdata_GUI]) # mode 1
            self.spiketimestamp_GUI = []
            self.spikedata_GUI = []
            self.spikerasterdata_GUI = [[] for _ in range(16)]
            self.sensordata_GUI = [[] for _ in range(9)]
        elif(len(self.spiketimestamp_mode2_GUI) >= self.GUIUpdateInterval // 5):  # mode 2
            self.GUIUpdate.emit([[2], self.spiketimestamp_mode2_GUI, self.spikedata_mode2_GUI, self.sensordata_GUI]) # mode 2
            self.spiketimestamp_mode2_GUI = []
            self.sensordata_GUI= [[] for _ in range(9)]
            self.spikedata_mode2_GUI = [[] for _ in range(16)]
      
    def LSM6DS3_accelData_in_g(self, x): # 2g range
        return float((x * 0.061 * (2 >> 1)) / 1000 )
    
    def LSM6DS3_gyroData_in_dps(self, x): # 500 range
        gyro_range_divisor = 500 / 125
        return float((x * 4.375 * gyro_range_divisor) / 1000)

    def DAC(self ,x ,raw=True, two_complement=False): 
        if raw:
            if(two_complement):
                if (int(x, 16) < int('8000', 16)): # positive value
                    return int(x, 16)
                else: # negative value
                    a = int(x, 16) 
                    return a - 2**(len(x) * 4)
            else:
                return int(x ,16) # n
        else:
            return (float(int(x ,16) * self.DAC_resolution) - 1.225) / 192 * 1000 * 1000  # uV 放大 192 倍 use unsigned offset 


    def flush(self):
        self.port.flushInput()

    def calc_SpikeThreshold(self ,x):
        """的数据计算一次threshold"""
        x = np.array(x ,dtype=np.float32)
        return 4 * np.median(np.abs(x) / 0.6745)

    def run(self): # re-write the run method of Qthread
        #  asyncio.run(self.serial_main_run())
        self.read_data()

