import cv2
import time
import os
import datetime
import threading
import numpy as np
from typing import Dict, Tuple, Optional

def get_available_cameras():
    """检测可用的摄像头"""
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
                    print(f"发现摄像头 {i}: {width}x{height}, FPS: {fps}")
                
                cap.release()
            
        except Exception as e:
            print(f"检测摄像头 {i} 时出错: {e}")
            continue
    
    return available_cameras

class CameraModule:
    def __init__(self):
        self.camera = None
        self.is_camera_open = False
        self.is_recording = False
        self.recording_thread = None
        self.video_writer = None
        self.frame = None
        self.frame_processed = False  # 添加帧处理标记
        
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
        """设置视频压缩配置
        
        Args:
            codec (str): 编码器类型 ('h264', 'h265', 'xvid')
            quality (str): 质量等级 ('low', 'medium', 'high', 'lossless')
            resolution_scale (float): 分辨率缩放因子 (0.1-1.0)
            fps_limit (int): 帧率限制
            crf (int): 恒定质量因子 (仅H.264/H.265)
            preset (str): 编码预设 (仅H.264/H.265)
        """
        for key, value in kwargs.items():
            if key in self.compression_config:
                self.compression_config[key] = value
                print(f"压缩配置已更新: {key} = {value}")
            else:
                print(f"未知的压缩配置参数: {key}")
    
    def get_compression_info(self) -> Dict:
        """获取当前压缩配置信息"""
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
        """根据当前配置获取最优的编码器设置"""
        codec = self.compression_config['codec']
        quality = self.compression_config['quality']
        
        if codec not in self.codec_configs:
            print(f"不支持的编码器: {codec}，回退到XVID")
            codec = 'xvid'
        
        codec_config = self.codec_configs[codec]
        fourcc_str = codec_config['fourcc']
        
        # 获取质量设置
        quality_settings = codec_config['quality_settings'].get(quality, 
                                                               codec_config['quality_settings']['medium'])
        
        return fourcc_str, quality_settings
        
    def open_camera(self, camera_id=0):
        """打开摄像头"""
        if not self.is_camera_open:
            try:
                # 尝试不同的后端
                backends = [cv2.CAP_ANY, cv2.CAP_DSHOW]
                
                for backend in backends:
                    print(f"尝试使用后端 {backend} 打开摄像头...")
                    self.camera = cv2.VideoCapture(camera_id, backend)
                    
                    # 检查摄像头是否成功打开
                    if self.camera.isOpened():
                        # 尝试读取一帧，确认摄像头工作正常
                        ret, test_frame = self.camera.read()
                        if ret:
                            print(f"成功使用后端 {backend} 打开摄像头")
                            
                            # 设置分辨率为480p (640x480)
                            print("(width, height)" ,self.camera.get(cv2.CAP_PROP_FRAME_WIDTH), self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
                            # self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                            # self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                            
                            # 设置缓冲区大小为1，减少延迟
                            self.camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                            
                            self.is_camera_open = True
                            return True
                        else:
                            print(f"使用后端 {backend} 打开摄像头成功，但无法读取帧")
                            self.camera.release()
                    else:
                        print(f"使用后端 {backend} 无法打开摄像头")
                
                # 如果所有后端都失败，尝试降低分辨率
                print("尝试使用较低分辨率打开摄像头...")
                self.camera = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
                if self.camera.isOpened():
                    # 设置较低的分辨率
                    self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                    self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                    
                    # 测试是否可以读取帧
                    ret, test_frame = self.camera.read()
                    if ret:
                        print("成功使用较低分辨率打开摄像头")
                        self.is_camera_open = True
                        return True
                
                print("无法打开摄像头，请检查摄像头连接或驱动程序")
                return False
                
            except Exception as e:
                print(f"打开摄像头时出错: {e}")
                return False
        return True
        
    def close_camera(self):
        """关闭摄像头"""
        if self.is_camera_open:
            if self.is_recording:
                self.stop_recording()
                
            if self.camera:
                self.camera.release()
                
            self.is_camera_open = False
            self.frame = None
    
    def get_frame(self):
        """获取当前帧并添加时间戳"""
        if not self.is_camera_open:
            return None
        
        # 尝试多次读取帧，以应对偶尔的读取失败
        max_attempts = 3
        for attempt in range(max_attempts):
            ret, frame = self.camera.read()
            if ret:
                break
            print(f"读取帧失败，尝试 {attempt+1}/{max_attempts}")
            time.sleep(0.01)  # 减少等待时间，提高响应速度
        
        if not ret:
            print("多次尝试读取帧均失败，请检查摄像头连接")
            return None
            
        # 添加时间戳 - 确保每次都获取最新时间
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # 增加毫秒显示
        cv2.putText(
            frame, 
            current_time, 
            (10, 30), 
            cv2.FONT_HERSHEY_SIMPLEX, 
            0.8, 
            (255, 255, 255), 
            2, 
            cv2.LINE_AA
        )
        
        with self.lock:
            self.frame = frame.copy()
            self.frame_processed = False  # 新帧未处理
            
        return frame
    
    def start_recording(self, save_path=None):
        """开始录制视频"""
        if not self.is_camera_open or self.is_recording:
            return False
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 获取编码器设置
        fourcc_str, quality_settings = self._get_optimal_codec_settings()
        codec = self.compression_config['codec']
        extension = self.codec_configs[codec]['extension']
        
        if save_path is None:
            # 创建保存目录
            save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
            os.makedirs(save_dir, exist_ok=True)
            
            # 生成文件名，使用正确的扩展名
            save_path = os.path.join(save_dir, f"video_{timestamp}{extension}")
        else:
            # 移除原扩展名并添加新的扩展名
            base_path = os.path.splitext(save_path)[0]
            save_path = f"{base_path}_{timestamp}{extension}"
        
        # 获取摄像头原始参数
        original_width = int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH))
        original_height = int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        original_fps = self.camera.get(cv2.CAP_PROP_FPS)
        
        # 应用分辨率缩放
        scale = self.compression_config['resolution_scale']
        width = int(original_width * scale)
        height = int(original_height * scale)
        
        # 确保分辨率为偶数（某些编码器要求）
        width = width if width % 2 == 0 else width - 1
        height = height if height % 2 == 0 else height - 1
        
        # 应用帧率限制
        fps = self.compression_config['fps_limit'] if self.compression_config['fps_limit'] else original_fps
        if fps <= 0 or fps > 100:
            fps = 30.0  # 默认帧率
        
        print(f"录制配置: 编码器={codec}, 质量={self.compression_config['quality']}")
        print(f"分辨率: {original_width}x{original_height} -> {width}x{height}")
        print(f"帧率: {original_fps} -> {fps}")
        print(f"保存路径: {save_path}")
        
        # 创建视频写入器
        try:
            fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
            self.video_writer = cv2.VideoWriter(save_path, fourcc, fps, (width, height))
            
            if not self.video_writer.isOpened():
                print(f"无法创建视频写入器，尝试使用备用编码器")
                # 回退到XVID编码器
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
                save_path = os.path.splitext(save_path)[0] + '.avi'
                self.video_writer = cv2.VideoWriter(save_path, fourcc, fps, (width, height))
                
            if not self.video_writer.isOpened():
                print("无法创建视频写入器")
                return False
                
        except Exception as e:
            print(f"创建视频写入器时出错: {e}")
            return False
        
        # 存储录制参数供录制线程使用
        self.recording_params = {
            'target_width': width,
            'target_height': height,
            'original_width': original_width,
            'original_height': original_height,
            'scale': scale
        }
        
        # 保存录制文件路径，用于后续统计
        self.current_recording_path = save_path
        
        self.is_recording = True
        
        # 启动录制线程
        self.recording_thread = threading.Thread(target=self._record_video)
        self.recording_thread.daemon = True
        self.recording_thread.start()
        
        return True
    
    def _record_video(self):
        """录制视频的线程函数"""
        # 计算基于摄像头帧率的休眠时间
        fps = self.camera.get(cv2.CAP_PROP_FPS)
        if fps <= 0 or fps > 100:
            fps = 30.0
        
        sleep_time = 0.01  # 根据帧率调整休眠时间;设置为2倍的刷新率来减少丢帧的风险
         
        while self.is_recording and self.is_camera_open:
            with self.lock:
                if self.frame is not None and not self.frame_processed:
                    frame_to_write = self.frame.copy()
                    
                    # 如果需要缩放分辨率
                    if hasattr(self, 'recording_params') and self.recording_params['scale'] != 1.0:
                        target_width = self.recording_params['target_width']
                        target_height = self.recording_params['target_height']
                        frame_to_write = cv2.resize(frame_to_write, (target_width, target_height), interpolation=cv2.INTER_AREA)
                    
                    self.video_writer.write(frame_to_write)
                    self.frame_processed = True  # 标记为已处理
            
            # 根据摄像头帧率休眠，避免过度循环
            time.sleep(sleep_time)
    
    def stop_recording(self):
        """停止录制视频"""
        if self.is_recording:
            self.is_recording = False
            
            # 保存当前录制的文件路径
            current_file_path = None
            if hasattr(self, 'current_recording_path'):
                current_file_path = self.current_recording_path
            
            # 等待录制线程结束
            if self.recording_thread and self.recording_thread.is_alive():
                self.recording_thread.join(timeout=5.0)
            
            # 释放视频写入器
            if self.video_writer:
                self.video_writer.release()
                self.video_writer = None
            
            # 显示压缩统计信息
            if current_file_path and os.path.exists(current_file_path):
                print(f"\n录制完成: {os.path.basename(current_file_path)}")
                stats = self._get_quick_stats(current_file_path)
                if stats:
                    print(f"文件大小: {stats['file_size_mb']:.2f} MB")
                    print(f"录制时长: {stats['duration_seconds']:.1f} 秒")
                    print(f"分辨率: {stats['resolution']}")
                    print(f"帧率: {stats['fps']:.1f} fps")
                    print(f"码率: {stats['bitrate_kbps']:.1f} kbps")
            
            # 清理录制参数
            if hasattr(self, 'recording_params'):
                delattr(self, 'recording_params')
            if hasattr(self, 'current_recording_path'):
                delattr(self, 'current_recording_path')
            
            return True
        return False
    
    def _get_quick_stats(self, file_path: str) -> Dict:
        """获取视频文件的基本统计信息（内部使用）"""
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
            print(f"获取视频统计信息时出错: {e}")
            return {}
    
    def get_compression_stats(self, file_path: str = None) -> Dict:
        """获取视频文件的详细压缩统计信息
        
        Args:
            file_path: 视频文件路径，如果为None则使用最近录制的文件
        """
        if file_path is None:
            if hasattr(self, 'current_recording_path'):
                file_path = self.current_recording_path
            else:
                return {'error': '没有可用的录制文件'}
        
        stats = self._get_quick_stats(file_path)
        if not stats:
            return {'error': '无法获取文件统计信息'}
        
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