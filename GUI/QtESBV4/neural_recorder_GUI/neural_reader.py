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
import threading
import binascii
import numpy as np
import logging
# import json
import multiprocessing
# from multiprocessing import Process, freeze_support
import collections as coll
from PyQt6.QtCore import QThread, pyqtSignal, QObject
import re
import queue as _pyqueue
try:
    from pyedflib import EdfWriter, FILETYPE_EDFPLUS
    EDF_AVAILABLE = True
except Exception:
    EDF_AVAILABLE = False

def save_process_main(queue):
    mode0_raw = get_raw_data_container()
    mode0_sensors = get_events_data_container()
    mode3_raw = get_mode3_data_container()
    mode3_sensors = get_events_data_container()

    write_q: "_pyqueue.Queue" = _pyqueue.Queue()

    def writer_loop():
        while True:
            task = write_q.get()
            if task is None:
                break
            try:
                mode = task.get("mode")
                if mode == 0:
                    _process_mode0_save(task)
                elif mode == 1:
                    _process_mode1_save(task)
                elif mode == 2:
                    _process_mode2_save(task)
                elif mode == 3:
                    _process_mode3_save(task)
            except Exception as e:
                logging.error(f"Save Process Writer Error: {e}", exc_info=True)
                print(f"Save Process Writer Error: {e}")

    writer_thread = threading.Thread(target=writer_loop, daemon=True)
    writer_thread.start()

    def _calc_start_time(end_timestamp_ms: float, timestamps_ms: list, tail_ms: float):
        if not timestamps_ms:
            return datetime.datetime.fromtimestamp(end_timestamp_ms / 1000.0)
        try:
            duration_ms = float(timestamps_ms[-1]) - float(timestamps_ms[0]) + float(tail_ms)
        except Exception:
            duration_ms = float(tail_ms)
        start_timestamp_ms = float(end_timestamp_ms) - float(duration_ms)
        return datetime.datetime.fromtimestamp(start_timestamp_ms / 1000.0)

    def _finalize_miss_packets(raw_dict: dict, max_interval: float, ts_key: str = "TimeStamp"):
        try:
            timestamp_files = np.asarray(raw_dict.get(ts_key, []), dtype=np.float64)
            if timestamp_files.size <= 1:
                raw_dict["MissPacketsIndex"] = np.asarray([], dtype=np.int64)
                raw_dict["MissPackets"] = 0
                return
            timestamp_diff = np.diff(timestamp_files)
            miss_packets = np.argwhere((timestamp_diff > max_interval) | (timestamp_diff <= 0)).flatten()
            raw_dict["MissPacketsIndex"] = miss_packets
            if miss_packets.size == 0:
                raw_dict["MissPackets"] = 0
                return
            miss_packets_num = np.ceil(timestamp_diff[miss_packets] / float(max_interval))
            raw_dict["MissPackets"] = float(np.sum(miss_packets_num.flatten()))
        except Exception:
            raw_dict["MissPacketsIndex"] = []
            raw_dict["MissPackets"] = 0

    while True:
        msg = queue.get()
        if msg is None:
            break

        try:
            msg_type = msg.get("type")
        except Exception:
            msg_type = None

        if msg_type == "shutdown":
            break

        if msg_type == "append_chunk":
            mode = int(msg.get("mode", -1))
            if mode == 0:
                timestamps = msg.get("timestamps", [])
                channels = msg.get("channels", [])
                sensors = msg.get("sensors", {})
                update_flags = msg.get("update_flags", [])

                mode0_raw["TimeStamp"].extend(timestamps)
                for i in range(min(16, len(channels))):
                    mode0_raw[f"Channel_{i}"].extend(channels[i])
                for k, v in sensors.items():
                    if k in mode0_sensors:
                        mode0_sensors[k].extend(v)
                mode0_sensors["UpdateFlag"].extend(update_flags)
                
                # Check for potential memory overflow (e.g. > 2 hours of data without flush)
                if len(mode0_raw["TimeStamp"]) > 9000000: # ~2 hours at 1250Hz
                     logging.warning(f"Memory Warning: Mode 0 buffer size {len(mode0_raw['TimeStamp'])} samples. Flush may be missing.")

            elif mode == 3:
                timestamps = msg.get("timestamps", [])
                lfp_channels = msg.get("lfp_channels", [])
                esa_channels = msg.get("esa_channels", [])
                sensors = msg.get("sensors", {})
                update_flags = msg.get("update_flags", [])

                mode3_raw["TimeStamp"].extend(timestamps)
                for i in range(min(16, len(lfp_channels))):
                    mode3_raw[f"Channel_{i}"].extend(lfp_channels[i])
                for i in range(min(16, len(esa_channels))):
                    mode3_raw[f"ESA_Channel_{i}"].extend(esa_channels[i])
                for k, v in sensors.items():
                    if k in mode3_sensors:
                        mode3_sensors[k].extend(v)
                mode3_sensors["UpdateFlag"].extend(update_flags)
                
                if len(mode3_raw["TimeStamp"]) > 9000000:
                     logging.warning(f"Memory Warning: Mode 3 buffer size {len(mode3_raw['TimeStamp'])} samples.")
            continue

        if msg_type == "append_mode3_raw":
            timestamps = msg.get("timestamps", [])
            raw_samples = msg.get("raw_samples", [])
            raw_channels = msg.get("raw_channels", [])
            raw_sizes = msg.get("raw_sizes", [])
            raw_alignment = msg.get("raw_alignment", [])

            mode3_raw["Raw_data"].extend(raw_samples)
            mode3_raw["Raw_timestamp"].extend(timestamps)
            mode3_raw["Raw_channel"].extend(raw_channels)
            mode3_raw["Raw_packet_sizes"].extend(raw_sizes)
            mode3_raw["Raw_alignment"].extend(raw_alignment)
            continue

        if msg_type == "flush":
            mode = int(msg.get("mode", -1))
            addr = msg.get("addr", "")
            end_timestamp = float(msg.get("end_timestamp", time.time() * 1000))
            params = msg.get("params", {})

            if mode == 0:
                raw_snapshot = mode0_raw
                sensors_snapshot = mode0_sensors
                mode0_raw = get_raw_data_container()
                mode0_sensors = get_events_data_container()

                _finalize_miss_packets(raw_snapshot, float(params.get("LFP_max_interval", 5)))
                start_time = _calc_start_time(end_timestamp, raw_snapshot.get("TimeStamp", []), 3.2)

                write_q.put({
                    "mode": 0,
                    "raw_data": raw_snapshot,
                    "sensors_data": sensors_snapshot,
                    "addr": addr,
                    "start_time": start_time,
                    "end_timestamp": end_timestamp,
                    "params": {
                        "LFP_max_interval": params.get("LFP_max_interval", 5),
                        "raw_data_per_packet_channel": params.get("raw_data_per_packet_channel", 4),
                        "sensor_name": params.get("sensor_name", []),
                        "sensor_fs": params.get("sensor_fs", 0),
                    },
                })

            elif mode == 3:
                raw_snapshot = mode3_raw
                sensors_snapshot = mode3_sensors
                mode3_raw = get_mode3_data_container()
                mode3_sensors = get_events_data_container()

                _finalize_miss_packets(raw_snapshot, float(params.get("mode3_max_interval", 4)))
                start_time = _calc_start_time(end_timestamp, raw_snapshot.get("TimeStamp", []), 2.4)

                write_q.put({
                    "mode": 3,
                    "raw_data": raw_snapshot,
                    "sensors_data": sensors_snapshot,
                    "addr": addr,
                    "start_time": start_time,
                    "end_timestamp": end_timestamp,
                    "params": {
                        "mode3_max_interval": params.get("mode3_max_interval", 4),
                        "raw_data_per_packet_mode3": params.get("raw_data_per_packet_mode3", 3),
                        "sensor_name": params.get("sensor_name", []),
                        "sensor_fs": params.get("sensor_fs", 0),
                        "mode3_raw_max_interval": params.get("mode3_raw_max_interval", 15),
                    },
                })
            continue

        if isinstance(msg, dict) and "mode" in msg and "raw_data" in msg:
            write_q.put(msg)
            continue

    try:
        write_q.put(None)
        writer_thread.join(timeout=2.0)
    except Exception:
        pass

def _process_mode0_save(task):
    raw_data = task['raw_data']
    sensors_data = task['sensors_data']
    addr = task['addr']
    start_time = task['start_time'] # datetime object
    params = task['params']
    
    # Extract params
    LFP_max_interval = params['LFP_max_interval']
    raw_data_per_packet_channel = params['raw_data_per_packet_channel']
    sensor_name = params['sensor_name']
    sensor_fs = params['sensor_fs']
    
    now_str = start_time.strftime('%Y-%m-%d-%H-%M-%S')
    
    # LFP 16 channels
    lfp_channels = [raw_data[f"Channel_{i}"] for i in range(16)]
    lfp_channels_filled = _interpolate_missing_packets_by_min(
        lfp_channels,
        raw_data["TimeStamp"],
        raw_data_per_packet_channel,
        LFP_max_interval
    )
    lfp_labels = [f"Ch{i}" for i in range(16)]
    lfp_fs = [1250] * 16
    lfp_filename = addr[0:-4] + str(now_str) + "lfp.edf"
    
    End_ts = task.get('end_timestamp', 0.0)
    lfp_annotations = [(0.0, 0.0, f"EndTimestamp(ms)={End_ts}")]
    
    _safe_write_edf(lfp_filename, lfp_channels_filled, lfp_labels, lfp_fs, 
                    dimension='uV', annotations=lfp_annotations, starttime=start_time)
    
    # Sensors
    sensor_channels = [sensors_data[k] for k in sensor_name]
    sensor_channels_filled = _interpolate_missing_packets_by_min(
        sensor_channels,
        raw_data["TimeStamp"],
        1,
        LFP_max_interval
    )
    sensor_fs_list = [sensor_fs] * len(sensor_channels_filled)
    sensor_filename = addr[0:-4] + str(now_str) + "sensor.edf"
    sensor_annotations = [(0.0, 0.0, f"EndTimestamp(ms)={End_ts}")]
    
    _safe_write_edf(sensor_filename, sensor_channels_filled, sensor_name, sensor_fs_list, 
                    dimension='unit', annotations=sensor_annotations, starttime=start_time)

def _process_mode3_save(task):
    esa_data = task['raw_data']
    sensors_data = task['sensors_data']
    addr = task['addr']
    start_time = task['start_time']
    params = task['params']
    
    mode3_max_interval = params['mode3_max_interval']
    raw_data_per_packet_mode3 = params['raw_data_per_packet_mode3']
    sensor_name = params['sensor_name']
    sensor_fs = params['sensor_fs']
    mode3_raw_max_interval = params['mode3_raw_max_interval']
    
    now_str = start_time.strftime('%Y-%m-%d-%H-%M-%S')
    
    # LFP & ESA
    lfp_channels = [esa_data[f"Channel_{i}"] for i in range(16)]
    esa_channels = [esa_data[f"ESA_Channel_{i}"] for i in range(16)]
    
    all_channels = lfp_channels + esa_channels
    
    all_channels_filled = _interpolate_missing_packets_by_min(
        all_channels,
        esa_data["TimeStamp"],
        raw_data_per_packet_mode3,
        mode3_max_interval
    )
    labels = [f"Ch{i}" for i in range(16)] + [f"ESA{i}" for i in range(16)]
    fs = [1250] * len(all_channels)
    dims = ['uV'] * 32
    mode3_filename = addr[0:-4] + str(now_str) + "LFP&ESA.edf"
    
    End_ts = task.get('end_timestamp', 0.0)
    mode3_annotations = [(0.0, 0.0, f"EndTimestamp(ms)={End_ts}")]
    
    _safe_write_edf(mode3_filename, all_channels_filled, labels, fs, 
                    dimension=dims, annotations=mode3_annotations, starttime=start_time)
    
    # Sensors
    sensor_channels = [sensors_data[k] for k in sensor_name]
    sensor_channels_filled = _interpolate_missing_packets_by_min(
        sensor_channels,
        esa_data["TimeStamp"],
        1,
        mode3_max_interval
    )
    sensor_fs_list = [sensor_fs] * len(sensor_channels_filled)
    sensor_filename = addr[0:-4] + str(now_str) + "sensor.edf"
    sensor_annotations = [(0.0, 0.0, f"EndTimestamp(ms)={End_ts}")]
    
    _safe_write_edf(sensor_filename, sensor_channels_filled, sensor_name, sensor_fs_list, 
                    dimension='unit', annotations=sensor_annotations, starttime=start_time)
    
    # Raw Data
    raw_samples = esa_data.get("Raw_data", [])
    raw_timestamps = esa_data.get("Raw_timestamp", [])
    raw_sizes = esa_data.get("Raw_packet_sizes", [])
    raw_ch_list = esa_data.get("Raw_channel", [])
    raw_alignment = esa_data.get("Raw_alignment", [])
    
    if len(raw_samples) > 0 and len(raw_timestamps) > 0:
        raw_filled = _interpolate_missing_packets_by_min_variable(
            raw_samples, raw_timestamps, raw_sizes, mode3_raw_max_interval
        )
        ch_broadcast = _broadcast_channel_to_samples_by_variable(
            raw_ch_list, raw_sizes, raw_timestamps, mode3_raw_max_interval, filler_value=-10000
        )
        alignment_filled = _interpolate_missing_packets_by_min_variable(
            raw_alignment, raw_timestamps, raw_sizes, mode3_raw_max_interval
        )
        
        labels = ["RawData", "RawChannel", "Alignment"]
        fs = [12500, 12500, 12500]
        dims = ["uV", "index", "unit"]
        mode3_raw_filename = addr[0:-4] + str(now_str) + "mode3_raw.edf"
        raw_annotations = [(0.0, 0.0, f"EndTimestamp(ms)={End_ts}")]
        
        _safe_write_edf(mode3_raw_filename, [raw_filled, ch_broadcast, alignment_filled], labels, fs, 
                        dimension=dims, annotations=raw_annotations, starttime=start_time)

def _process_mode1_save(task):
    ap_data = task['raw_data']
    sensors_data = task['sensors_data']
    addr = task['addr']
    start_time = task['start_time']
    params = task['params']
    
    Spike_max_interval = params['Spike_max_interval']
    sensor_name = params['sensor_name']
    sensor_fs = params['sensor_fs']
    
    now_str = start_time.strftime('%Y-%m-%d-%H-%M-%S')
    
    # Raw Data
    raw_samples = [ap_data["Raw_data"]]
    raw_samples_filled = _interpolate_missing_packets_by_min(
        raw_samples,
        ap_data["Raw_timestamp"],
        90,
        Spike_max_interval
    )
    labels = ["Raw"]
    fs = [20833]
    mode1_filename = addr[0:-4] + str(now_str) + "mode1.edf"
    
    annotations = []
    ap_ts = ap_data.get("AP_timestamp", [])
    electrodes = ap_data.get("Electrode", [])
    n_ann = min(len(ap_ts), len(electrodes))
    for i in range(n_ann):
        onset_sec = float(ap_ts[i]) / 1000.0
        desc = f"Spike@Ch{electrodes[i]}"
        annotations.append((onset_sec, 0.0, desc))
    
    End_ts = task.get('end_timestamp', 0.0)
    annotations.insert(0, (0.0, 0.0, f"EndTimestamp(ms)={End_ts}"))
    
    _safe_write_edf(mode1_filename, raw_samples_filled, labels, fs, 
                    dimension='uV', annotations=annotations, starttime=start_time)
    
    # Sensors
    sensor_channels = [sensors_data[k] for k in sensor_name]
    sensor_channels_filled = _interpolate_missing_packets_by_min(
        sensor_channels,
        ap_data["Raw_timestamp"],
        1,
        Spike_max_interval
    )
    sensor_fs_list = [sensor_fs] * len(sensor_channels_filled)
    sensor_filename = addr[0:-4] + str(now_str) + "sensor.edf"
    sensor_annotations = [(0.0, 0.0, f"EndTimestamp(ms)={End_ts}")]
    
    _safe_write_edf(sensor_filename, sensor_channels_filled, sensor_name, sensor_fs_list, 
                    dimension='unit', annotations=sensor_annotations, starttime=start_time)

def _process_mode2_save(task):
    ap_lfp_data = task['raw_data']
    addr = task['addr']
    start_time = task['start_time']
    params = task['params']
    
    mode2_max_interval = params['mode2_max_interval']
    
    now_str = start_time.strftime('%Y-%m-%d-%H-%M-%S')
    
    channels = []
    labels = []
    for i in range(16):
        data_i = ap_lfp_data[f"Channel_{i}"]
        if len(data_i) > 0:
            channels.append(data_i)
            labels.append(f"Ch{i}")
            
    if len(channels) > 0:
        channels_filled = _interpolate_missing_packets_by_min(
            channels,
            ap_lfp_data["TimeStamp"],
            30,
            mode2_max_interval
        )
        fs = [20833] * len(channels_filled)
        mode2_filename = addr[0:-4] + str(now_str) + "AP_LFP_Raw_data.edf"
        
        End_ts = task.get('end_timestamp', 0.0)
        mode2_annotations = [(0.0, 0.0, f"EndTimestamp(ms)={End_ts}")]
        
        _safe_write_edf(mode2_filename, channels_filled, labels, fs, 
                        dimension='uV', annotations=mode2_annotations, starttime=start_time)

def _safe_write_edf(filename, channel_arrays, labels, sample_rates, physical_min=-10000.0, physical_max=10000.0, dimension='uV', annotations=None, starttime=None):
    """Write signals to an EDF/EDF+ file using pyedflib.
    Falls back by raising if pyedflib is unavailable so caller can handle.

    - channel_arrays: list of 1D arrays, one per channel
    - labels: list of string labels for channels
    - sample_rates: list of ints (same length as channel_arrays)
    - annotations: optional list of tuples (onset_seconds, duration_seconds, description)
    - starttime: datetime object for the file start time
    
    注意： edf 文件按 秒来对齐数据，所有每一个edf文件最后都会补充一段0值来对齐到下一秒，在后续数据处理过程中需要裁切一下
    """
    if not EDF_AVAILABLE:
        # raise RuntimeError('pyedflib is not available')
        print('pyedflib is not available')
        return

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
    if starttime is None:
        starttime = datetime.datetime.now()
        
    writer = EdfWriter(filename, n_channels=n_channels, file_type=FILETYPE_EDFPLUS)
    writer.setStartdatetime(starttime)
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
        "Raw_alignment": [], # Alignment signal
        
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
    ProgressUpdate = pyqtSignal(int, float, float) # mode, progress_percent, run_time_min

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
        self.alignment_counter = 0

        self.GUIUpdateInterval = 20 # packets num

        self.rssi = 0 # real-time rssi
        """ neural signal buffer """
        # mode 0 & 3
        self.lfptimestamp_GUI = []
        self.lfpdata_GUI = [[] for _ in range(16)]
        self.ESAdata_GUI = [[] for _ in range(16)]
        self.alignment_GUI = [] # Alignment signal buffer
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
        self._sensor_keys_no_flag = [k for k in self.sensors_data.keys() if k != "UpdateFlag"]
        self._mode0_pending = None
        self._mode3_pending = None
        self._mode3_raw_pending = None
        self._mode0_pending_packets = 0
        self._mode3_pending_packets = 0
        self._mode3_raw_pending_packets = 0
        self._save_chunk_packets_mode0 = 50
        self._save_chunk_packets_mode3 = 25
        self._save_chunk_packets_mode3_raw = 25
        self.save_queue = multiprocessing.Queue()
        self.save_process = multiprocessing.Process(target=save_process_main, args=(self.save_queue,), daemon=True)
        self.save_process.start()
        
        # Progress bucket trackers for non-continuous counters (trigger every 500 increment bucket)
        self._lfp_progress_bucket = -1
        self._mode3_progress_bucket = -1
        self._mode1_progress_bucket = -1
        self._mode2_progress_bucket = -1
        
        self.sensor_fs = 0
        self.file_duration_lfp = 1000 * 60 * 10 # minutes
        self.file_duration_mode1 = 1000 * 60 * 10
        self.file_duration_mode2 = 1000 * 60  * 10
        self.file_duration_mode3 = 1000 * 60 * 10 # minutes 考虑到一个trial block 最大 60分钟
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
        
        # Pre-allocate sensor buffer to avoid repeated creation
        self.temp_sensor_data_buffer = np.zeros(9, dtype=np.float32)

    def port_open(self):
        """ seiral ports opening """
        #### read parameters
        if not self.port.isOpen():
            self.port.open()
    
    def port_close(self):
        """ serial ports closing """
        self.port.close()
        try:
            if getattr(self, "save_queue", None) is not None:
                self.save_queue.put({"type": "shutdown"}, block=False)
        except Exception:
            pass

    def _save_put(self, msg):
        q = getattr(self, "save_queue", None)
        if q is None:
            return
        try:
            q.put(msg, block=False)
            return
        except Exception:
            pass
        try:
            q.put(msg, timeout=0.05)
        except Exception:
            return

    def _mode0_pending_init(self):
        self._mode0_pending = {
            "timestamps": [],
            "channels": [[] for _ in range(16)],
            "update_flags": [],
            "sensors": {k: [] for k in self._sensor_keys_no_flag},
        }
        self._mode0_pending_packets = 0

    def _mode3_pending_init(self):
        self._mode3_pending = {
            "timestamps": [],
            "lfp_channels": [[] for _ in range(16)],
            "esa_channels": [[] for _ in range(16)],
            "update_flags": [],
            "sensors": {k: [] for k in self._sensor_keys_no_flag},
        }
        self._mode3_pending_packets = 0

    def _mode3_raw_pending_init(self):
        self._mode3_raw_pending = {
            "timestamps": [],
            "raw_samples": [],
            "raw_channels": [],
            "raw_sizes": [],
            "raw_alignment": [],
        }
        self._mode3_raw_pending_packets = 0

    def _save_mode0_append(self, timestamp, ch16_lists, sensor_lists_9, update_flag):
        if self._mode0_pending is None:
            self._mode0_pending_init()
        self._mode0_pending["timestamps"].append(timestamp)
        for i in range(16):
            self._mode0_pending["channels"][i].extend(ch16_lists[i])
        for i, k in enumerate(self._sensor_keys_no_flag):
            self._mode0_pending["sensors"][k].extend(sensor_lists_9[i])
        self._mode0_pending["update_flags"].append(update_flag)
        self._mode0_pending_packets += 1
        if self._mode0_pending_packets >= self._save_chunk_packets_mode0:
            self._save_mode0_flush_pending()

    def _save_mode0_flush_pending(self):
        if not self._mode0_pending or self._mode0_pending_packets <= 0:
            return
        msg = {
            "type": "append_chunk",
            "mode": 0,
            "timestamps": self._mode0_pending["timestamps"],
            "channels": self._mode0_pending["channels"],
            "sensors": self._mode0_pending["sensors"],
            "update_flags": self._mode0_pending["update_flags"],
        }
        self._save_put(msg)
        self._mode0_pending_init()

    def _save_mode3_append(self, timestamp, lfp16_lists, esa16_lists, sensor_lists_9, update_flag):
        if self._mode3_pending is None:
            self._mode3_pending_init()
        self._mode3_pending["timestamps"].append(timestamp)
        for i in range(16):
            self._mode3_pending["lfp_channels"][i].extend(lfp16_lists[i])
            self._mode3_pending["esa_channels"][i].extend(esa16_lists[i])
        for i, k in enumerate(self._sensor_keys_no_flag):
            self._mode3_pending["sensors"][k].extend(sensor_lists_9[i])

        self._mode3_pending["update_flags"].append(update_flag)
        self._mode3_pending_packets += 1
        if self._mode3_pending_packets >= self._save_chunk_packets_mode3:
            self._save_mode3_flush_pending()

    def _save_mode3_flush_pending(self):
        if not self._mode3_pending or self._mode3_pending_packets <= 0:
            return
        msg = {
            "type": "append_chunk",
            "mode": 3,
            "timestamps": self._mode3_pending["timestamps"],
            "lfp_channels": self._mode3_pending["lfp_channels"],
            "esa_channels": self._mode3_pending["esa_channels"],
            "sensors": self._mode3_pending["sensors"],
            "update_flags": self._mode3_pending["update_flags"],
        }
        self._save_put(msg)
        self._mode3_pending_init()

    def _save_mode3_raw_append(self, timestamp, raw_samples, raw_channel, raw_alignment=None):
        if self._mode3_raw_pending is None:
            self._mode3_raw_pending_init()
        self._mode3_raw_pending["timestamps"].append(timestamp)
        self._mode3_raw_pending["raw_samples"].extend(raw_samples)
        self._mode3_raw_pending["raw_channels"].append(raw_channel)
        self._mode3_raw_pending["raw_sizes"].append(len(raw_samples))
        
        if raw_alignment:
            self._mode3_raw_pending["raw_alignment"].extend(raw_alignment)
        else:
            self._mode3_raw_pending["raw_alignment"].extend([0.0] * len(raw_samples))
            
        self._mode3_raw_pending_packets += 1
        if self._mode3_raw_pending_packets >= self._save_chunk_packets_mode3_raw:
            self._save_mode3_raw_flush_pending()

    def _save_mode3_raw_flush_pending(self):
        if not self._mode3_raw_pending or self._mode3_raw_pending_packets <= 0:
            return
        msg = {
            "type": "append_mode3_raw",
            "timestamps": self._mode3_raw_pending["timestamps"],
            "raw_samples": self._mode3_raw_pending["raw_samples"],
            "raw_channels": self._mode3_raw_pending["raw_channels"],
            "raw_sizes": self._mode3_raw_pending["raw_sizes"],
            "raw_alignment": self._mode3_raw_pending["raw_alignment"],
        }
        self._save_put(msg)
        self._mode3_raw_pending_init()
    
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
                try:
                    self.data_process_full(full_frame)
                except Exception as e:
                    logging.error(f"Error in data_process_full: {e}", exc_info=True)
                
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

    def trigger_alignment(self):
        """Trigger alignment signal (6ms duration)"""
        # Mode 3 Raw is 12.5kHz. 6ms = 0.006 * 12500 = 75 samples.
        self.alignment_counter = 75

    def mode_3_packets_process(self, mode_3_data_buffer):
        # spilt
        mode_3_data_buffer = np.array(mode_3_data_buffer.split(' '))[0:-1]
        # 1. raw data 
        save_lfp_channels = None
        save_esa_channels = None
        save_packet_sensors = None
        if self.save_file_mode3_flag:
            save_lfp_channels = [[] for _ in range(16)]
            save_esa_channels = [[] for _ in range(16)]
            save_packet_sensors = [[] for _ in range(9)]
        for channel_num in range(16):
            # lfp data
            temp_channel = mode_3_data_buffer[self.raw_data_index_base_mode3 + channel_num * self.raw_data_per_packet_mode3] 
            temp_channel_DAC_lfp = list(map(lambda x:self.DAC(swap16Hex(x), raw=False), temp_channel)) # 注意 对于 mode3 需要翻转一下
            self.lfpdata_GUI[channel_num].extend(temp_channel_DAC_lfp) 
            # ESA data
            temp_channel = mode_3_data_buffer[self.raw_data_index_base_mode3 + (channel_num + 16) * self.raw_data_per_packet_mode3] 
            temp_channel_DAC_ESA = list(map(lambda x:self.DAC(swap16Hex(x), raw=False), temp_channel)) # 注意 对于 mode3 需要翻转一下
            self.ESAdata_GUI[channel_num].extend(temp_channel_DAC_ESA) 
            if save_lfp_channels is not None and save_esa_channels is not None:
                save_lfp_channels[channel_num] = temp_channel_DAC_lfp
                save_esa_channels[channel_num] = temp_channel_DAC_ESA
        
        self.lfptimestamp_GUI.append(self.Timestamp_neural_signal)
          # 3. sensor data
        temp_sensor_data = mode_3_data_buffer[self.sensor_index]
        # Reuse pre-allocated buffer
        temp_sensor_data_float = self.temp_sensor_data_buffer
        
        # IMU data
        temp_sensor_data_float[0:3] = list(map(lambda x:self.LSM6DS3_accelData_in_g(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[0:3]))
        temp_sensor_data_float[3:6] = list(map(lambda x:self.LSM6DS3_gyroData_in_dps(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[3:6]))
        # LC data
        temp_sensor_data_float[6:] = list(map(lambda x:self.DAC(swap16Hex(x)), temp_sensor_data[6:]))
        # print(temp_sensor_data_float)
        for i in range(9):
            temp_sensor = list(temp_sensor_data_float[np.arange(0 + i, len(temp_sensor_data_float) ,9)])
            # for GUI
            self.sensordata_GUI[i].extend(temp_sensor)
            if save_packet_sensors is not None:
                save_packet_sensors[i] = temp_sensor

        temp_raster_data = mode_3_data_buffer[-3:] #TODO 这里由于 下位机的处理速度，目前没有改功能
        for raster_time, spike_data in enumerate(temp_raster_data):
            spike_data = format(self.DAC(swap16Hex(spike_data)) ,'#018b')[2:] # 保留 前16位
            for channel_num ,spike_num in enumerate(spike_data):
                self.spikerasterdata_GUI[15 - channel_num].append(int(spike_num))
                 # for file saving
                pass

        if self.save_file_mode3_flag and save_lfp_channels is not None and save_esa_channels is not None and save_packet_sensors is not None:
            self._save_mode3_append(self.Timestamp_neural_signal, save_lfp_channels, save_esa_channels, save_packet_sensors, self.sensor_update_flag)
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
        
        # alignment signal
        num_samples = len(temp_channel_DAC)
        
        # Optimize: Avoid loop for creating alignment signal
        ones_count = min(self.alignment_counter, num_samples)
        zeros_count = num_samples - ones_count
        
        current_alignment_vals = [1.0] * ones_count + [0.0] * zeros_count
        
        # Update counter
        if self.alignment_counter > 0:
            self.alignment_counter = max(0, self.alignment_counter - ones_count)
        
        self.alignment_GUI.extend(current_alignment_vals)
        
        # 3. save to file
        if self.save_file_mode3_flag:
            self._save_mode3_raw_append(self.Timestamp_neural_signal, temp_channel_DAC, self.spike_channel_index_mode1_3, current_alignment_vals)
         

    def spike_sensor_packets_process_mode2(self, sensor_data):
        # spilt
        temp_sensor_data = np.array(sensor_data.split(' '))[0:-1]
        # Reuse pre-allocated buffer
        temp_sensor_data_float = self.temp_sensor_data_buffer
        
        # IMU data
        temp_sensor_data_float[0:3] = list(map(lambda x:self.LSM6DS3_accelData_in_g(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[0:3]))
        temp_sensor_data_float[3:6] = list(map(lambda x:self.LSM6DS3_gyroData_in_dps(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[3:6]))
        # LC data
        temp_sensor_data_float[6:] = list(map(lambda x:self.DAC(swap16Hex(x)), temp_sensor_data[6:]))
        # print(temp_sensor_data_float)
        for i in range(9):
            temp_sensor = list(temp_sensor_data_float[np.arange(0 + i, len(temp_sensor_data_float) ,9)])
            # for GUI
            self.sensordata_GUI[i].extend(temp_sensor)
            # save to file
            if(self.save_file_lfp_flag):
                self.sensors_data[self.sensor_name[i]].extend(temp_sensor)
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
        save_packet_channels = None
        save_packet_sensors = None
        if self.save_file_lfp_flag:
            save_packet_channels = [[] for _ in range(16)]
            save_packet_sensors = [[] for _ in range(9)]
        for channel_num in range(16):
            temp_channel = lfp_data_buffer[self.raw_data_index_base + channel_num * self.raw_data_per_packet_channel]
            temp_channel_DAC = list(map(lambda x:self.DAC(x, raw=False), temp_channel))
            self.lfpdata_GUI[channel_num].extend(temp_channel_DAC)
            if save_packet_channels is not None:
                save_packet_channels[channel_num] = temp_channel_DAC
        
        # 2. timestamp
        self.lfptimestamp_GUI.append(self.Timestamp_neural_signal)
        
        # 3. sensor data
        temp_sensor_data = lfp_data_buffer[self.sensor_index]
        # Reuse pre-allocated buffer
        temp_sensor_data_float = self.temp_sensor_data_buffer
        
        # IMU data
        temp_sensor_data_float[0:3] = list(map(lambda x:self.LSM6DS3_accelData_in_g(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[0:3]))
        temp_sensor_data_float[3:6] = list(map(lambda x:self.LSM6DS3_gyroData_in_dps(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[3:6]))
        # LC data
        temp_sensor_data_float[6:] = list(map(lambda x:self.DAC(swap16Hex(x)), temp_sensor_data[6:]))
        # print(temp_sensor_data_float)
        for i in range(9):
            temp_sensor = list(temp_sensor_data_float[np.arange(0 + i, len(temp_sensor_data_float) ,9)])
            # for GUI
            self.sensordata_GUI[i].extend(temp_sensor)
            if save_packet_sensors is not None:
                save_packet_sensors[i] = temp_sensor

        if self.save_file_lfp_flag and save_packet_channels is not None and save_packet_sensors is not None:
            self._save_mode0_append(self.Timestamp_neural_signal, save_packet_channels, save_packet_sensors, self.sensor_update_flag)

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
            
         # 3. sensor data
        temp_sensor_data = spike_data_buffer[self.sensor_index]
        # Reuse pre-allocated buffer
        temp_sensor_data_float = self.temp_sensor_data_buffer
        
        # IMU data
        temp_sensor_data_float[0:3] = list(map(lambda x:self.LSM6DS3_accelData_in_g(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[0:3]))
        temp_sensor_data_float[3:6] = list(map(lambda x:self.LSM6DS3_gyroData_in_dps(self.DAC(swap16Hex(x), two_complement=True)), temp_sensor_data[3:6]))
        # LC data
        temp_sensor_data_float[6:] = list(map(lambda x:self.DAC(swap16Hex(x)), temp_sensor_data[6:]))
        # print(temp_sensor_data_float)
        for i in range(9):
            temp_sensor = list(temp_sensor_data_float[np.arange(0 + i, len(temp_sensor_data_float) ,9)])
            # for GUI
            self.sensordata_GUI[i].extend(temp_sensor)
            # save to file
            if(self.save_file_lfp_flag):
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
        curr_bucket = self.LFPRawCounter // 5000
        if(curr_bucket != self._lfp_progress_bucket):
            # print file collection progress once per 500-count bucket
            # print("Mode0 file preparing", round(self.LFPRawCounter/self.file_size_lfp * 100, 2) , "%", "have run ", round(self.Timestamp_recorder_counter / 1000 / 60, 2), "min")
            self.ProgressUpdate.emit(0, round(self.LFPRawCounter/self.file_size_lfp * 100, 2), round(self.Timestamp_recorder_counter / 1000 / 60, 2))
            self._lfp_progress_bucket = curr_bucket

        if(self.LFPRawCounter >= self.file_size_lfp or manual_save): 
            self.LFPRawCounter = 0
            self._lfp_progress_bucket = -1
            self.ProgressUpdate.emit(0, 0, round(self.Timestamp_recorder_counter / 1000 / 60, 2)) # Reset progress
            end_timestamp = float(time.time() * 1000)
            self._save_mode0_flush_pending()
            self._save_put({
                "type": "flush",
                "mode": 0,
                "addr": addr,
                "end_timestamp": end_timestamp,
                "params": {
                    "LFP_max_interval": self.LFP_max_interval,
                    "raw_data_per_packet_channel": self.raw_data_per_packet_channel,
                    "sensor_name": self.sensor_name,
                    "sensor_fs": int(1250/4),
                }, # self.sensor_fs = 1250 / 4 # 4个点对应 1个IMU 数据点
            })

            # 3.5 camera
            self.CameraGUIUpdate.emit([]) 
            # 4. resample detection
            if(sum(self.overflowSignal) == 1): #  重新开始sample
                self.sample_times += 1
                self.overflowSignal[0] = self.overflowSignal[1]
                print("sample begin!")

    def save_spike_mode3_file(self, addr, manual_save=False):
        """ save data to a file"""
        curr_bucket = self.Mode3RawCounter // 500
        if(curr_bucket != self._mode3_progress_bucket):
            # print file collection progress once per 500-count bucket
            # print("Mode3 file preparing", round(self.Mode3RawCounter/self.file_size_mode3 * 100, 2) , "%", "have run ", round(self.Timestamp_recorder_counter / 1000 / 60, 2), "min")
            self.ProgressUpdate.emit(3, round(self.Mode3RawCounter/self.file_size_mode3 * 100, 2), round(self.Timestamp_recorder_counter / 1000 / 60, 2))
            self._mode3_progress_bucket = curr_bucket

        if(self.Mode3RawCounter >= self.file_size_mode3 or manual_save): 
            self.Mode3RawCounter = 0
            self._mode3_progress_bucket = -1
            self.ProgressUpdate.emit(3, 0, round(self.Timestamp_recorder_counter / 1000 / 60, 2)) # Reset progress
            end_timestamp = float(time.time() * 1000)
            self._save_mode3_flush_pending()
            self._save_mode3_raw_flush_pending()
            self._save_put({
                "type": "flush",
                "mode": 3,
                "addr": addr,
                "end_timestamp": end_timestamp,
                "params": {
                    "mode3_max_interval": self.mode3_max_interval,
                    "raw_data_per_packet_mode3": self.raw_data_per_packet_mode3,
                    "sensor_name": self.sensor_name,
                    "sensor_fs": int(1250/3), #self.sensor_fs = 1250 / 3 
                    "mode3_raw_max_interval": self.mode3_raw_max_interval,
                },
            })

            # 3.5 camera
            self.CameraGUIUpdate.emit([]) 

            # 4. resample detection
            if(sum(self.overflowSignal) == 1): #  重新开始sample
                self.sample_times += 1
                self.overflowSignal[0] = self.overflowSignal[1]
                print("sample begin!")
           
    def save_spike_mode1_file(self, addr, manual_save=False):
        curr_bucket = self.SPIKERawCounter // 500
        if(curr_bucket != self._mode1_progress_bucket):
            # print("file preparing",  round(self.SPIKERawCounter/self.file_size_mode1 * 100, 2) , "%" ,"have run ", round(self.Timestamp_recorder_counter / 1000 / 60, 2), "min")
            self.ProgressUpdate.emit(1, round(self.SPIKERawCounter/self.file_size_mode1 * 100, 2), round(self.Timestamp_recorder_counter / 1000 / 60, 2))
            self._mode1_progress_bucket = curr_bucket
        
        """ save data to a file"""
        if(self.SPIKERawCounter == self.file_size_mode1 or manual_save):
            self.SPIKERawCounter = 0
            self._mode1_progress_bucket = -1
            self.ProgressUpdate.emit(1, 0, round(self.Timestamp_recorder_counter / 1000 / 60, 2)) # Reset progress
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
            # 2. save the file (Offload to process)
            end_timestamp = float(time.time() * 1000)
            
            # Calculate start_time from duration
            timestamps = self.AP_data.get("Raw_timestamp", [])
            if len(timestamps) > 0:
                # 4.32ms per packet for Mode 1 (20833Hz / 90 samples per packet)
                duration_ms = timestamps[-1] - timestamps[0] + 4.32 
            else:
                duration_ms = 0
            
            start_timestamp_ms = end_timestamp - duration_ms
            start_time = datetime.datetime.fromtimestamp(start_timestamp_ms / 1000.0)
            
            task = {
                'mode': 1,
                'raw_data': self.AP_data,
                'sensors_data': self.sensors_data,
                'addr': addr,
                'start_time': start_time,
                'end_timestamp': end_timestamp,
                'params': {
                    'Spike_max_interval': self.Spike_max_interval,
                    'sensor_name': self.sensor_name,
                    'sensor_fs': int(20833 / 90), #self.sensor_fs = 20833 / 90
                }
            }
            self._save_put(task)
            
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
        curr_bucket = self.Mode2RawCounter // 500
        if(curr_bucket != self._mode2_progress_bucket):
            # print("file preparing", round(self.Mode2RawCounter/self.file_size_mode2 * 100, 2) , "%")
            # Note: mode2 didn't print run time originally, but we can send it anyway or send -1 if not available/relevant
            self.ProgressUpdate.emit(2, round(self.Mode2RawCounter/self.file_size_mode2 * 100, 2), round(self.Timestamp_recorder_counter / 1000 / 60, 2))
            self._mode2_progress_bucket = curr_bucket
        """ save data to a file"""
        if(self.Mode2RawCounter == self.file_size_mode2 or manual_save):
            self.Mode2RawCounter = 0
            self._mode2_progress_bucket = -1
            self.ProgressUpdate.emit(2, 0, round(self.Timestamp_recorder_counter / 1000 / 60, 2)) # Reset progress
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

            # 2. save the file (Offload to process)
            end_timestamp = float(time.time() * 1000)
            
            # Calculate start_time from duration
            timestamps = self.AP_LFP_data.get("TimeStamp", [])
            if len(timestamps) > 0:
                # 1.44ms per packet for Mode 2 (20833Hz / 30 samples per packet)
                duration_ms = timestamps[-1] - timestamps[0] + 1.44 
            else:
                duration_ms = 0
            
            start_timestamp_ms = end_timestamp - duration_ms
            start_time = datetime.datetime.fromtimestamp(start_timestamp_ms / 1000.0)
            
            task = {
                'mode': 2,
                'raw_data': self.AP_LFP_data,
                'addr': addr,
                'start_time': start_time,
                'end_timestamp': end_timestamp,
                'params': {
                    'mode2_max_interval': self.mode2_max_interval
                }
            }
            self._save_put(task)
            
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
            # Create copies of data to emit to avoid race conditions when clearing buffers
            lfpdata_copy = [list(ch) for ch in self.lfpdata_GUI]
            sensordata_copy = [list(ch) for ch in self.sensordata_GUI]
            spikerasterdata_copy = [list(ch) for ch in self.spikerasterdata_GUI]
            esadata_copy = [list(ch) for ch in self.ESAdata_GUI]
            
            self.GUIUpdate.emit([[0], list(self.lfptimestamp_GUI), lfpdata_copy, sensordata_copy, spikerasterdata_copy, esadata_copy]) # mode 0
            
            # Clear existing buffers instead of creating new ones to prevent memory fragmentation
            self.lfptimestamp_GUI.clear()
            for ch in self.lfpdata_GUI: ch.clear()
            for ch in self.sensordata_GUI: ch.clear()
            for ch in self.spikerasterdata_GUI: ch.clear()
            for ch in self.ESAdata_GUI: ch.clear()
            
            
        elif(len(self.spiketimestamp_GUI) >= self.GUIUpdateInterval): # mode 1
            # Create copies
            spikedata_copy = list(self.spikedata_GUI)
            sensordata_copy = [list(ch) for ch in self.sensordata_GUI]
            spikerasterdata_copy = [list(ch) for ch in self.spikerasterdata_GUI]
            
            self.GUIUpdate.emit([[1, self.spike_channel_index_mode1_3], list(self.spiketimestamp_GUI), spikedata_copy, sensordata_copy, spikerasterdata_copy, list(self.alignment_GUI)]) # mode 1
            
            # Clear
            self.spiketimestamp_GUI.clear()
            self.spikedata_GUI.clear()
            for ch in self.spikerasterdata_GUI: ch.clear()
            for ch in self.sensordata_GUI: ch.clear()
            self.alignment_GUI.clear()
            
        elif(len(self.spiketimestamp_mode2_GUI) >= self.GUIUpdateInterval // 5):  # mode 2
            # Create copies
            spikedata_mode2_copy = [list(ch) for ch in self.spikedata_mode2_GUI]
            sensordata_copy = [list(ch) for ch in self.sensordata_GUI]
            
            self.GUIUpdate.emit([[2], list(self.spiketimestamp_mode2_GUI), spikedata_mode2_copy, sensordata_copy]) # mode 2
            
            # Clear
            self.spiketimestamp_mode2_GUI.clear()
            for ch in self.sensordata_GUI: ch.clear()
            for ch in self.spikedata_mode2_GUI: ch.clear()
      
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
