import cv2
import time
import os
import datetime
import threading
import multiprocessing as mp
import queue
import numpy as np
from typing import Dict, Tuple, Optional
from path_utils import get_recordings_directory

def get_available_cameras():
    """Detect available cameras"""
    available_cameras = []
    
    # 检测前10个摄像头索引
    for i in range(10):
        try:
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                # 尝试读取一帧来确认摄像头工作正常
                ret, frame = cap.read()
                if ret:
                    # 获取摄像头信息
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    
                    camera_info = {
                        'id': i,
                        'name': f"Camera {i}",
                        'resolution': f"{width}x{height}",
                        'fps': fps if fps > 0 else 30.0
                    }
                    available_cameras.append(camera_info)
                    print(f"Camera {i} detected: {width}x{height}, FPS: {fps}")
                
                cap.release()
            
        except Exception as e:
            print(f"Error detecting camera {i}: {e}")
            continue
    
    return available_cameras

def _camera_capture_worker(cmd_q: "mp.Queue", frame_q: "mp.Queue", status_q: "mp.Queue"):
    camera = None
    camera_id = 0
    is_open = False
    is_recording = False
    video_writer = None
    recording_params = None
    current_recording_path = None
    stop_event = threading.Event()
    frame_lock = threading.Lock()
    shared = {"frame": None, "last_ok": 0.0}

    def capture_loop():
        while not stop_event.is_set():
            if camera is None or (hasattr(camera, "isOpened") and not camera.isOpened()):
                time.sleep(0.01)
                continue
            ret, frm = camera.read()
            if ret:
                with frame_lock:
                    shared["frame"] = frm
                    shared["last_ok"] = time.perf_counter()
            else:
                time.sleep(0.001)

    capture_thread = None
    pending_record_start = None
    next_write_ts = None
    last_preview_ts = 0.0

    def try_put_latest_frame(payload: bytes):
        try:
            while True:
                frame_q.get_nowait()
        except Exception:
            pass
        try:
            frame_q.put_nowait(payload)
        except Exception:
            pass

    def overlay_timestamp(bgr_frame: np.ndarray, ts: float):
        try:
            dt = datetime.datetime.fromtimestamp(ts)
            text = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            cv2.putText(
                bgr_frame,
                text,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
        except Exception:
            print("error: put text on frame")
            pass

    def open_writer(save_path: str, fourcc_str: str, fps: float, scale: float, frame_shape):
        nonlocal video_writer, recording_params, current_recording_path
        h0, w0 = int(frame_shape[0]), int(frame_shape[1])
        scale = float(scale) if scale else 1.0
        w = int(w0 * scale)
        h = int(h0 * scale)
        w = w if w % 2 == 0 else w - 1
        h = h if h % 2 == 0 else h - 1
        try:
            fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
            vw = cv2.VideoWriter(save_path, fourcc, float(fps), (w, h))
            if not vw.isOpened():
                vw.release()
                raise RuntimeError("VideoWriter open failed")
            video_writer = vw
            recording_params = {"w": w, "h": h, "scale": scale, "fps": float(fps)}
            current_recording_path = save_path
            return True, save_path
        except Exception:
            try:
                fallback_path = os.path.splitext(save_path)[0] + ".avi"
                fourcc = cv2.VideoWriter_fourcc(*"XVID")
                vw = cv2.VideoWriter(fallback_path, fourcc, float(fps), (w, h))
                if not vw.isOpened():
                    vw.release()
                    return False, save_path
                video_writer = vw
                recording_params = {"w": w, "h": h, "scale": scale, "fps": float(fps)}
                current_recording_path = fallback_path
                return True, fallback_path
            except Exception:
                return False, save_path

    try:
        while True:
            try:
                cmd = cmd_q.get(timeout=0.02)
            except queue.Empty:
                cmd = None

            if cmd:
                cmd_type = cmd.get("type")
                if cmd_type == "open":
                    camera_id = int(cmd.get("camera_id", 0))
                    try:
                        backends = [cv2.CAP_ANY, cv2.CAP_DSHOW]
                        opened = False
                        for backend in backends:
                            cap = cv2.VideoCapture(camera_id, backend)
                            if cap.isOpened():
                                ret, _ = cap.read()
                                if ret:
                                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                                    camera = cap
                                    opened = True
                                    break
                                cap.release()
                            else:
                                cap.release()
                        if not opened:
                            cap = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
                            if cap.isOpened():
                                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                                ret, _ = cap.read()
                                if ret:
                                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                                    camera = cap
                                    opened = True
                                else:
                                    cap.release()
                            else:
                                cap.release()

                        if opened:
                            is_open = True
                            stop_event.clear()
                            capture_thread = threading.Thread(target=capture_loop, daemon=True)
                            capture_thread.start()
                            status_q.put(("opened", True, f"camera {camera_id} opened"))
                        else:
                            status_q.put(("opened", False, f"camera {camera_id} open failed"))
                    except Exception as e:
                        status_q.put(("opened", False, str(e)))

                elif cmd_type == "close":
                    break

                elif cmd_type == "start_recording":
                    if not is_open:
                        status_q.put(("recording_started", False, "camera not open", None))
                    else:
                        pending_record_start = cmd

                elif cmd_type == "stop_recording":
                    if is_recording:
                        is_recording = False
                        next_write_ts = None
                        if video_writer is not None:
                            try:
                                video_writer.release()
                            except Exception:
                                pass
                        video_writer = None
                        recording_params = None
                        status_q.put(("recording_stopped", True, current_recording_path))
                        current_recording_path = None
                    else:
                        status_q.put(("recording_stopped", True, None))

            if not is_open:
                continue

            now_perf = time.perf_counter()

            with frame_lock:
                latest = shared["frame"]
            if latest is None:
                continue

            if pending_record_start and not is_recording:
                save_path = pending_record_start.get("save_path")
                fourcc_str = pending_record_start.get("fourcc", "mp4v")
                fps = float(pending_record_start.get("fps", 30.0))
                scale = float(pending_record_start.get("scale", 1.0))
                ok, actual_path = open_writer(save_path, fourcc_str, fps, scale, latest.shape)
                if ok:
                    is_recording = True
                    next_write_ts = now_perf
                    status_q.put(("recording_started", True, "ok", actual_path))
                else:
                    status_q.put(("recording_started", False, "writer open failed", save_path))
                pending_record_start = None

            preview_rate = 10.0 if is_recording else 15.0
            if now_perf - last_preview_ts >= (1.0 / preview_rate):
                preview = latest.copy()
                overlay_timestamp(preview, time.time())
                jpeg_quality = 70 if is_recording else 80
                ok, buf = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
                if ok:
                    try_put_latest_frame(buf.tobytes())
                last_preview_ts = now_perf

            if is_recording and video_writer is not None and recording_params is not None:
                fps = float(recording_params.get("fps", 30.0))
                if fps <= 0:
                    fps = 30.0
                if next_write_ts is None:
                    next_write_ts = now_perf
                if now_perf >= next_write_ts:
                    out = latest
                    if recording_params.get("scale", 1.0) != 1.0:
                        out = cv2.resize(out, (int(recording_params["w"]), int(recording_params["h"])), interpolation=cv2.INTER_AREA)
                    else:
                        if out.shape[1] != int(recording_params["w"]) or out.shape[0] != int(recording_params["h"]):
                            out = cv2.resize(out, (int(recording_params["w"]), int(recording_params["h"])), interpolation=cv2.INTER_AREA)
                    out = out.copy()
                    overlay_timestamp(out, time.time())
                    try:
                        video_writer.write(out)
                    except Exception:
                        pass
                    next_write_ts += 1.0 / fps
                else:
                    time.sleep(min(0.002, max(0.0, next_write_ts - now_perf)))

    finally:
        stop_event.set()
        try:
            if capture_thread is not None and capture_thread.is_alive():
                capture_thread.join(timeout=1.0)
        except Exception:
            pass
        try:
            if video_writer is not None:
                video_writer.release()
        except Exception:
            pass
        try:
            if camera is not None:
                camera.release()
        except Exception:
            pass
        try:
            status_q.put(("closed", True, None))
        except Exception:
            pass

class CameraModule:
    def __init__(self):
        self.camera = None
        self.is_camera_open = False
        self.is_recording = False
        self.frame = None
        self.frame_processed = False
        self._process = None
        self._cmd_q = None
        self._frame_q = None
        self._status_q = None
        self._consumer_stop = threading.Event()
        self._consumer_thread = None
        self._mp_ctx = mp.get_context("spawn")
        
        # 视频压缩配置
        self.compression_config = {
            'codec': 'h264',  # 默认使用H.264编码器
            'quality': 'medium',  # 质量等级: low, medium, high, lossless
            'crf': 23,  # 恒定质量因子 (0-51, 越小质量越高)
            'preset': 'medium',  # 编码预设: ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow
            'format': 'mp4',  # 输出格式
            'resolution_scale': 1.0,  # 分辨率缩放因子
            'fps_limit': None  # 帧率限制，None表示使用摄像头原始帧率
        }
        
        # 支持的编码器配置
        self.codec_configs = {
            'h264': {
                'fourcc': 'mp4v',  # 使用mp4v作为fourcc，更兼容
                'extension': '.mp4',
                'quality_settings': {
                    'lossless': {'crf': 0},
                    'high': {'crf': 18},
                    'medium': {'crf': 23},
                    'low': {'crf': 28}
                }
            },
            'h265': {
                'fourcc': 'HEVC',
                'extension': '.mp4',
                'quality_settings': {
                    'lossless': {'crf': 0},
                    'high': {'crf': 20},
                    'medium': {'crf': 25},
                    'low': {'crf': 30}
                }
            },
            'xvid': {
                'fourcc': 'XVID',
                'extension': '.avi',
                'quality_settings': {
                    'high': {'bitrate': 5000},
                    'medium': {'bitrate': 3000},
                    'low': {'bitrate': 1500}
                }
            }
        }
        self.lock = threading.Lock()
    
    def set_compression_config(self, **kwargs):
        """Set video compression config
        
        Args:
            codec (str): Codec type ('h264', 'h265', 'xvid')
            quality (str): Quality level ('low', 'medium', 'high', 'lossless')
            resolution_scale (float): Resolution scale factor (0.1-1.0)
            fps_limit (int): FPS limit
            crf (int): Constant Rate Factor (H.264/H.265 only)
            preset (str): Encoder preset (H.264/H.265 only)
        """
        for key, value in kwargs.items():
            if key in self.compression_config:
                self.compression_config[key] = value
                print(f"Compression config updated: {key} = {value}")
            else:
                print(f"Unknown compression config key: {key}")
    
    def get_compression_info(self) -> Dict:
        """Get current compression config info"""
        codec = self.compression_config['codec']
        quality = self.compression_config['quality']
        
        info = {
            'codec': codec,
            'quality': quality,
            'format': self.codec_configs[codec]['extension'],
            'resolution_scale': self.compression_config['resolution_scale'],
            'fps_limit': self.compression_config['fps_limit']
        }
        
        if codec in ['h264', 'h265']:
            info['crf'] = self.compression_config['crf']
            info['preset'] = self.compression_config['preset']
        
        return info
    
    def _get_optimal_codec_settings(self) -> Tuple[str, Dict]:
        """Get optimal encoder settings for current config"""
        codec = self.compression_config['codec']
        quality = self.compression_config['quality']
        
        if codec not in self.codec_configs:
            print(f"Unsupported codec: {codec}; falling back to XVID")
            codec = 'xvid'
        
        codec_config = self.codec_configs[codec]
        fourcc_str = codec_config['fourcc']
        
        # 获取质量设置
        quality_settings = codec_config['quality_settings'].get(quality, 
                                                               codec_config['quality_settings']['medium'])
        
        return fourcc_str, quality_settings
        
    def open_camera(self, camera_id=0):
        """Open camera"""
        if self.is_camera_open:
            return True
        try:
            self._cmd_q = self._mp_ctx.Queue()
            self._frame_q = self._mp_ctx.Queue(maxsize=2)
            self._status_q = self._mp_ctx.Queue()
            self._process = self._mp_ctx.Process(
                target=_camera_capture_worker,
                args=(self._cmd_q, self._frame_q, self._status_q),
                daemon=True,
            )
            self._process.start()
            self._cmd_q.put({"type": "open", "camera_id": int(camera_id)})
            ok = False
            msg = ""
            try:
                evt, success, msg = self._status_q.get(timeout=3.0)
                ok = bool(success) if evt == "opened" else False
            except Exception:
                ok = False

            if not ok:
                self.close_camera()
                return False

            self.is_camera_open = True
            self._consumer_stop.clear()
            self._consumer_thread = threading.Thread(target=self._consume_frames, daemon=True)
            self._consumer_thread.start()
            return True
        except Exception:
            self.close_camera()
            return False
        
    def close_camera(self):
        """Close camera"""
        if self.is_recording:
            try:
                self.stop_recording()
            except Exception:
                pass

        self._consumer_stop.set()
        try:
            if self._consumer_thread is not None and self._consumer_thread.is_alive():
                self._consumer_thread.join(timeout=1.0)
        except Exception:
            pass
        self._consumer_thread = None

        if self._cmd_q is not None:
            try:
                self._cmd_q.put({"type": "close"})
            except Exception:
                pass

        if self._process is not None:
            try:
                self._process.join(timeout=2.0)
            except Exception:
                pass
            try:
                if self._process.is_alive():
                    self._process.terminate()
            except Exception:
                pass
        self._process = None
        self._cmd_q = None
        self._frame_q = None
        self._status_q = None
        self.is_camera_open = False
        with self.lock:
            self.frame = None
            self.frame_processed = False
    
    def get_frame(self):
        """Get latest frame"""
        if not self.is_camera_open:
            return None
        with self.lock:
            if self.frame is None:
                return None
            return self.frame.copy()

    def _consume_frames(self):
        while not self._consumer_stop.is_set():
            if self._frame_q is None:
                time.sleep(0.05)
                continue
            try:
                payload = self._frame_q.get(timeout=0.2)
            except Exception:
                continue
            try:
                arr = np.frombuffer(payload, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is None:
                    continue
                with self.lock:
                    self.frame = img
                    self.frame_processed = False
            except Exception:
                continue
    
    def start_recording(self, save_path=None):
        """Start recording"""
        if not self.is_camera_open or self.is_recording:
            return False
        if self._cmd_q is None or self._status_q is None:
            return False

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fourcc_str, _ = self._get_optimal_codec_settings()
        codec = self.compression_config['codec']
        extension = self.codec_configs[codec]['extension']

        if save_path is None:
            save_dir = get_recordings_directory()
            save_path = os.path.join(save_dir, f"video_{timestamp}{extension}")
        else:
            base_path = os.path.splitext(save_path)[0]
            save_path = f"{base_path}_{timestamp}{extension}"

        fps_limit = self.compression_config.get('fps_limit', None)
        fps = float(fps_limit) if fps_limit else 30.0
        if fps <= 0:
            fps = 30.0
        scale = float(self.compression_config.get('resolution_scale', 1.0) or 1.0)

        try:
            self._cmd_q.put({
                "type": "start_recording",
                "save_path": save_path,
                "fourcc": fourcc_str,
                "fps": fps,
                "scale": scale,
            })
            evt, ok, _, actual_path = self._status_q.get(timeout=5.0)
            if evt == "recording_started" and ok:
                self.is_recording = True
                self.current_recording_path = actual_path
                return True
        except Exception:
            pass
        return False
    
    def stop_recording(self):
        """Stop recording"""
        if not self.is_recording:
            return False
        if self._cmd_q is None or self._status_q is None:
            self.is_recording = False
            return True

        current_file_path = getattr(self, "current_recording_path", None)
        try:
            self._cmd_q.put({"type": "stop_recording"})
            try:
                self._status_q.get(timeout=5.0)
            except Exception:
                pass
        except Exception:
            pass

        self.is_recording = False

        if current_file_path and os.path.exists(current_file_path):
            stats = self._get_quick_stats(current_file_path)
            if stats:
                print(f"\nRecording finished: {os.path.basename(current_file_path)}")
                print(f"File size: {stats['file_size_mb']:.2f} MB")
                print(f"Duration: {stats['duration_seconds']:.1f} s")
                print(f"Resolution: {stats['resolution']}")
                print(f"FPS: {stats['fps']:.1f} fps")
                print(f"Bitrate: {stats['bitrate_kbps']:.1f} kbps")
        return True
    
    def _get_quick_stats(self, file_path: str) -> Dict:
        """Get basic video stats (internal use)"""
        if not os.path.exists(file_path):
            return {}
        
        try:
            file_size = os.path.getsize(file_path)
            
            # 使用OpenCV获取视频信息
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                return {'file_size_mb': file_size / (1024 * 1024)}
            
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = frame_count / fps if fps > 0 else 0
            
            cap.release()
            
            return {
                'file_size_mb': file_size / (1024 * 1024),
                'duration_seconds': duration,
                'fps': fps,
                'resolution': f"{width}x{height}",
                'bitrate_kbps': (file_size * 8) / (duration * 1000) if duration > 0 else 0
            }
        except Exception as e:
            print(f"Error getting video stats: {e}")
            return {}
    
    def get_compression_stats(self, file_path: str = None) -> Dict:
        """Get detailed compression stats for a video file
        
        Args:
            file_path: Video file path; uses latest recording if None
        """
        if file_path is None:
            if hasattr(self, 'current_recording_path'):
                file_path = self.current_recording_path
            else:
                return {'error': 'No recording files available'}
        
        stats = self._get_quick_stats(file_path)
        if not stats:
            return {'error': 'Unable to get file stats'}
        
        # 添加详细的压缩信息
        try:
            file_size = os.path.getsize(file_path)
            frame_count = int(stats['fps'] * stats['duration_seconds']) if stats['duration_seconds'] > 0 else 0
            
            # 估算未压缩大小（假设24位RGB）
            resolution_parts = stats['resolution'].split('x')
            if len(resolution_parts) == 2:
                width, height = int(resolution_parts[0]), int(resolution_parts[1])
                uncompressed_size = frame_count * width * height * 3
                compression_ratio = uncompressed_size / file_size if file_size > 0 else 0
                stats['compression_ratio'] = compression_ratio
                stats['frame_count'] = frame_count
            
            # 添加编码器信息
            stats['codec'] = self.compression_config.get('codec', 'unknown')
            stats['quality'] = self.compression_config.get('quality', 'unknown')
            
        except Exception as e:
            stats['compression_error'] = str(e)
        
        return stats
