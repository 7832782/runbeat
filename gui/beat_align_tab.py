#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
首拍对齐标签页

功能：
1. 显示变速后音频列表
2. 自动检测每首歌的首拍
3. 显示前15秒波形图
4. 支持鼠标/键盘微调首拍位置
5. 保存时间戳供混音使用
6. 播放预览功能
"""

import os
import sys
import json
import re
import numpy as np
from pathlib import Path
from typing import List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox,
    QGroupBox, QDoubleSpinBox, QSplitter, QSlider,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPoint
from PyQt6.QtGui import QKeyEvent, QPainter, QColor, QPen, QBrush, QFont, QMouseEvent, QPolygon

import sounddevice as sd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'modules'))
from beat_detector import FirstBeatDetector, BeatAlignmentManager


def natural_sort_key(s) -> List:
    """自然排序键函数 - 正确处理数字顺序"""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]


class BeatDetectThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, file_paths):
        super().__init__()
        self.file_paths = file_paths

    def run(self):
        self.results = {}
        total = len(self.file_paths)
        for i, file_path in enumerate(self.file_paths):
            try:
                result = FirstBeatDetector().detect(file_path)
                self.results[file_path] = {
                    'first_beat_time': result.first_beat_time,
                    'confidence': result.confidence,
                    'file_name': result.file_name
                }
                self.progress.emit(i + 1, total, result.file_name)
            except Exception as e:
                self.error.emit(f"{file_path}: {e}")
        self.finished.emit(len(self.results))


class AudioLoader(QThread):
    """后台加载音频文件"""
    loaded = pyqtSignal(np.ndarray, int)  # 音频数据, 采样率
    error = pyqtSignal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        try:
            import librosa
            # 加载完整音频用于显示和浏览
            audio_data, sample_rate = librosa.load(self.file_path, sr=None, mono=True)
            self.loaded.emit(audio_data, sample_rate)
        except Exception as e:
            self.error.emit(str(e))


class AudioPlayer(QThread):
    """音频播放线程 - 完全参考mp3.py实现"""
    position_changed = pyqtSignal(float)  # 当前播放位置（秒）
    finished_signal = pyqtSignal()

    def __init__(self, audio_data, sample_rate):
        super().__init__()
        self.audio_data = audio_data
        self.sample_rate = sample_rate
        self.chunk_size = 2048
        self.is_playing = False
        self.is_paused = False
        self.current_frame = 0
        self.seek_position = None
        self.volume = 1.0

    def run(self):
        self.is_playing = True

        # 创建输出流
        def callback(outdata, frames, time_info, status):
            if status:
                print(f"音频状态: {status}")

            if self.is_paused or not self.is_playing:
                outdata[:] = np.zeros((frames, 1))
                return

            # 处理跳转请求
            if self.seek_position is not None:
                self.current_frame = int(self.seek_position * self.sample_rate)
                self.seek_position = None

            # 计算要播放的帧数
            remaining = len(self.audio_data) - self.current_frame
            if remaining <= 0:
                outdata[:] = np.zeros((frames, 1))
                return

            to_play = min(frames, remaining)
            chunk = self.audio_data[self.current_frame:self.current_frame + to_play]

            # 应用音量
            chunk = chunk * self.volume

            # 填充输出缓冲区
            outdata[:to_play, 0] = chunk
            if to_play < frames:
                outdata[to_play:, 0] = 0

            # 更新当前位置
            self.current_frame += to_play
            current_time = self.current_frame / self.sample_rate
            self.position_changed.emit(current_time)

        # 启动音频流
        try:
            with sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype=np.float32,
                blocksize=self.chunk_size,
                callback=callback
            ):
                # 等待播放完成或停止
                while self.is_playing:
                    self.msleep(10)
                    if self.current_frame >= len(self.audio_data):
                        break
        except Exception as e:
            print(f"音频播放错误: {e}")

        self.finished_signal.emit()

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def stop(self):
        self.is_playing = False

    def seek(self, position_seconds):
        """跳转到指定位置（秒）"""
        self.seek_position = max(0, min(position_seconds, len(self.audio_data) / self.sample_rate))

    def set_volume(self, volume):
        """设置音量 (0.0 - 1.0)"""
        self.volume = max(0.0, min(1.0, volume))


class WaveformWidget(QWidget):
    """波形显示组件 - 参考mp3.py实现拖拽平移和滚轮缩放"""
    beat_position_changed = pyqtSignal(float)  # 首拍位置改变信号
    play_position_changed = pyqtSignal(float)  # 播放位置改变信号
    view_position_changed = pyqtSignal(float)  # 视图位置改变信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_tab = parent

        # 数据
        self.audio_data = None
        self.sample_rate = 44100
        self.duration = 0
        self.first_beat_time = 0.0  # 首拍位置
        self.play_position = 0.0  # 播放位置

        # 视图参数 - 只显示一部分波形
        self.view_start_time = 0.0  # 视图开始时间（秒）
        self.view_duration = 15.0   # 视图显示时长（秒），默认15秒

        # 交互状态 - 参考mp3.py
        self.is_dragging_beat = False
        self.is_dragging_play = False
        self.is_dragging_view = False  # 是否正在拖拽视图（平移）
        self.last_mouse_x = 0
        self.last_mouse_y = 0

        # 显示参数 - 完全参考mp3.py深色主题
        self.waveform_color = QColor(0, 120, 215)  # mp3.py蓝色
        self.background_color = QColor(40, 40, 40)  # mp3.py深色背景
        self.beat_line_color = QColor(244, 67, 54)  # 红色（保留，这是额外功能）
        self.playhead_color = QColor(255, 255, 0)  # mp3.py黄色
        self.playhead_width = 2  # mp3.py播放头线宽
        self.grid_color = QColor(80, 80, 80)  # mp3.py网格颜色
        self.text_color = QColor(200, 200, 200)  # mp3.py文字颜色

        # 拖拽检测宽度（mp3.py风格，不绘制矩形条）
        self.drag_bar_width = 20  # 拖拽检测宽度（像素）

        self.setMinimumHeight(250)
        self.setMouseTracking(True)

    def set_audio_data(self, audio_data, sample_rate):
        """设置音频数据"""
        self.audio_data = audio_data
        self.sample_rate = sample_rate
        self.duration = len(audio_data) / sample_rate
        # 重置视图到开始
        self.view_start_time = 0.0
        self.update()

    def set_view_position(self, start_time: float):
        """设置视图开始位置"""
        if self.duration <= 0:
            return
        # 确保视图不超出音频范围
        max_start = max(0, self.duration - self.view_duration)
        self.view_start_time = max(0, min(start_time, max_start))
        self.update()
        self.view_position_changed.emit(self.view_start_time)

    def set_first_beat(self, time: float):
        """设置首拍位置"""
        self.first_beat_time = max(0, min(time, self.duration))
        self.update()
        self.beat_position_changed.emit(self.first_beat_time)

    def set_play_position(self, position: float):
        """更新播放位置"""
        self.play_position = max(0, min(position, self.duration))
        self.update()

    def _clamp_view(self):
        """限制视图范围 - 允许视图超出音频范围以查看全曲任意位置"""
        # 只限制起始时间不小于0，允许超出音频结束
        self.view_start_time = max(0, self.view_start_time)

    def time_to_x(self, time_sec: float, width: int) -> int:
        """将时间转换为X坐标（基于当前视图）"""
        if self.view_duration <= 0:
            return 0
        ratio = (time_sec - self.view_start_time) / self.view_duration
        return int(ratio * width)

    def x_to_time(self, x: int, width: int) -> float:
        """将X坐标转换为时间（基于当前视图）"""
        if width <= 0 or self.view_duration <= 0:
            return 0
        ratio = x / width
        return self.view_start_time + ratio * self.view_duration

    def paintEvent(self, event):
        """绘制波形 - 完全参考mp3.py结构"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()

        # 绘制背景
        painter.fillRect(0, 0, width, height, self.background_color)

        if self.audio_data is None or len(self.audio_data) == 0:
            # 显示提示文字 - mp3.py风格
            painter.setPen(self.text_color)
            painter.setFont(QFont("Microsoft YaHei", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "选择歌曲加载波形")
            painter.end()
            return

        # 绘制网格和时间刻度 - mp3.py风格
        self._draw_grid_and_time(painter, width, height)

        # 绘制波形（只绘制视图范围内的部分）
        self._draw_waveform(painter, width, height)

        # 绘制首拍线（红色实线）- 这是额外功能，mp3.py没有
        self._draw_beat_line(painter, width, height)

        # 绘制播放头（黄色虚线+三角形）- mp3.py风格
        self._draw_playhead(painter, width, height)

        # 绘制视图信息 - mp3.py风格
        # self._draw_view_info(painter, width, height)

        painter.end()

    def _draw_grid_and_time(self, painter, width, height):
        """绘制网格和时间刻度 - 完全参考mp3.py"""
        view_end = min(self.view_start_time + self.view_duration, self.duration)

        # 绘制垂直网格线
        painter.setPen(QPen(self.grid_color, 1, Qt.PenStyle.DotLine))
        painter.setFont(QFont("Microsoft YaHei", 9))

        # 计算时间刻度间隔 - mp3.py逻辑
        if self.view_duration <= 5:
            interval = 0.5  # 0.5秒一格
        elif self.view_duration <= 15:
            interval = 1.0  # 1秒一格
        elif self.view_duration <= 30:
            interval = 2.0  # 2秒一格
        else:
            interval = 5.0  # 5秒一格

        # 绘制网格线和时间标签
        start_grid = int(self.view_start_time / interval) * interval
        t = start_grid
        while t <= view_end:
            x = self.time_to_x(t, width)
            if 0 <= x <= width:
                # 绘制网格线 - mp3.py风格，留出上下边距
                painter.drawLine(x, 20, x, height - 30)

                # 绘制时间标签 - mp3.py风格 MM:SS
                painter.setPen(self.text_color)
                time_str = f"{int(t // 60):02d}:{int(t % 60):02d}"
                painter.drawText(x - 20, height - 15, 40, 20, Qt.AlignmentFlag.AlignCenter, time_str)
                painter.setPen(QPen(self.grid_color, 1, Qt.PenStyle.DotLine))
            t += interval

        # 绘制水平中线 - mp3.py风格
        center_y = height // 2
        painter.setPen(QPen(self.grid_color, 1, Qt.PenStyle.SolidLine))
        painter.drawLine(0, center_y, width, center_y)

    def _draw_waveform(self, painter, width, height):
        """绘制音频波形 - 完全参考mp3.py"""
        if self.duration <= 0:
            return

        view_end = self.view_start_time + self.view_duration

        # 计算视图对应的样本范围
        start_sample = int(self.view_start_time * self.sample_rate)
        end_sample = int(view_end * self.sample_rate)
        start_sample = max(0, start_sample)
        end_sample = min(len(self.audio_data), end_sample)

        if start_sample >= end_sample:
            return

        # 计算每像素对应的样本数
        view_samples = end_sample - start_sample
        samples_per_pixel = max(1, view_samples // width)

        center_y = height // 2
        max_amplitude = np.max(np.abs(self.audio_data)) or 1

        painter.setPen(self.waveform_color)

        for x in range(width):
            sample_start = start_sample + x * samples_per_pixel
            sample_end = min(sample_start + samples_per_pixel, end_sample)

            if sample_start < len(self.audio_data) and sample_start < end_sample:
                chunk = self.audio_data[sample_start:sample_end]
                if len(chunk) > 0:
                    max_val = np.max(chunk)
                    min_val = np.min(chunk)

                    # 归一化并映射到像素高度 - mp3.py风格，留出上下边距
                    top = center_y - int((max_val / max_amplitude) * (height // 2 - 25))
                    bottom = center_y - int((min_val / max_amplitude) * (height // 2 - 25))

                    painter.drawLine(x, top, x, bottom)

    def _draw_view_info(self, painter, width, height):
        """绘制视图信息 - 完全参考mp3.py"""
        view_end = min(self.view_start_time + self.view_duration, self.duration)
        info_text = f"视图: {self.view_start_time:.1f}s - {view_end:.1f}s / 总时长: {self.duration:.1f}s"

        painter.setPen(self.text_color)
        painter.setFont(QFont("Microsoft YaHei", 9))
        painter.drawText(10, 20, 400, 20, Qt.AlignmentFlag.AlignLeft, info_text)

        # 绘制提示文字 - mp3.py风格
        hint_text = "拖拽波形移动视图 | 拖拽黄/红线调整位置 | 双击跳转 | 滚轮缩放"
        painter.drawText(width - 380, 20, 370, 20, Qt.AlignmentFlag.AlignRight, hint_text)

    def _get_beat_line_x(self, width):
        """获取首拍线X坐标（基于当前视图）"""
        return self.time_to_x(self.first_beat_time, width)

    def _get_playhead_x(self, width):
        """获取播放头X坐标（基于当前视图）"""
        return self.time_to_x(self.play_position, width)

    def _is_line_visible(self, time_sec):
        """检查某时间是否在视图范围内"""
        return self.view_start_time <= time_sec <= self.view_start_time + self.view_duration

    def _draw_beat_line(self, painter, width, height):
        """绘制首拍标记线（红色实线）+ 半透明矩形拖拽区域"""
        # 只在线可见时绘制
        if not self._is_line_visible(self.first_beat_time):
            return

        x = self._get_beat_line_x(width)

        # 绘制半透明矩形条（拖拽区域）- 20px宽，红色
        bar_x = x - self.drag_bar_width // 2
        bar_color = QColor(self.beat_line_color)
        bar_color.setAlpha(40)  # 半透明
        painter.fillRect(bar_x, 20, self.drag_bar_width, height - 50, bar_color)

        # 绘制红色实线
        pen = QPen(self.beat_line_color)
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.drawLine(x, 20, x, height - 30)

        # 绘制标签
        painter.setPen(self.beat_line_color)
        painter.setFont(QFont("Microsoft YaHei", 9))
        painter.drawText(x + 5, 15, f"首拍: {self.first_beat_time:.3f}s")

    def _draw_playhead(self, painter, width, height):
        """绘制播放头指示线 - 黄色虚线+半透明矩形拖拽区域"""
        # 检查播放头是否在视图范围内
        if self.play_position < self.view_start_time or self.play_position > self.view_start_time + self.view_duration:
            return

        x = self._get_playhead_x(width)

        # 绘制半透明矩形条（拖拽区域）- 20px宽
        bar_x = x - self.drag_bar_width // 2
        bar_color = QColor(self.playhead_color)
        bar_color.setAlpha(40)  # 半透明
        painter.fillRect(bar_x, 20, self.drag_bar_width, height - 50, bar_color)

        # 绘制黄色虚线
        pen = QPen(self.playhead_color)
        pen.setWidth(self.playhead_width)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(x, 20, x, height - 30)

    def _draw_left_indicator(self, painter, color, height):
        """绘制左侧指示器（线在当前视图左侧）"""
        painter.setPen(color)
        painter.setBrush(QBrush(color))
        # 绘制小三角形指向右侧
        triangle_size = 10
        y_center = height // 2
        polygon = QPolygon([
            QPoint(0, y_center - triangle_size),
            QPoint(triangle_size, y_center),
            QPoint(0, y_center + triangle_size)
        ])
        painter.drawPolygon(polygon)

    def _draw_right_indicator(self, painter, color, width, height):
        """绘制右侧指示器（线在当前视图右侧）"""
        painter.setPen(color)
        painter.setBrush(QBrush(color))
        # 绘制小三角形指向左侧
        triangle_size = 10
        y_center = height // 2
        polygon = QPolygon([
            QPoint(width - 1, y_center - triangle_size),
            QPoint(width - 1 - triangle_size, y_center),
            QPoint(width - 1, y_center + triangle_size)
        ])
        painter.drawPolygon(polygon)

    def _is_in_beat_drag_area(self, x, width):
        """检查是否在首拍线拖拽区域内"""
        beat_x = self._get_beat_line_x(width)
        return abs(x - beat_x) <= self.drag_bar_width // 2

    def _is_in_play_drag_area(self, x, width):
        """检查是否在播放头拖拽区域内"""
        play_x = self._get_playhead_x(width)
        return abs(x - play_x) <= self.drag_bar_width // 2

    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下 - 参考mp3.py实现"""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        x = int(event.position().x())
        y = int(event.position().y())
        width = self.width()
        height = self.height()

        if self.duration <= 0:
            return

        self.last_mouse_x = x
        self.last_mouse_y = y

        # 检查是否点击在首拍线（红色）附近 - 优先
        if self._is_in_beat_drag_area(x, width):
            self.is_dragging_beat = True
            return

        # 检查是否点击在播放头（黄色）附近
        if self._is_in_play_drag_area(x, width):
            self.is_dragging_play = True
            return

        # 否则开始拖拽视图（平移）
        self.is_dragging_view = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动 - 参考mp3.py实现"""
        x = int(event.position().x())
        y = int(event.position().y())
        width = self.width()
        height = self.height()

        if self.is_dragging_beat:
            # 拖拽首拍线
            position = self.x_to_time(x, width)
            position = max(0, min(position, self.duration))
            self.set_first_beat(position)

        elif self.is_dragging_play:
            # 拖拽播放头
            position = self.x_to_time(x, width)
            position = max(0, min(position, self.duration))
            self.play_position = position
            self.play_position_changed.emit(position)
            self.update()

        elif self.is_dragging_view:
            # 拖拽视图（平移）
            dx = self.last_mouse_x - x  # 鼠标向左移动，视图向右滚动
            time_shift = (dx / width) * self.view_duration
            new_start = self.view_start_time + time_shift
            self.set_view_position(new_start)

        else:
            # 鼠标悬停效果 - 检查是否在可拖拽元素上
            if self._is_in_beat_drag_area(x, width):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif self._is_in_play_drag_area(x, width):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.OpenHandCursor)

        self.last_mouse_x = x
        self.last_mouse_y = y

    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放 - 参考mp3.py实现"""
        if event.button() == Qt.MouseButton.LeftButton:
            x = int(event.position().x())
            y = int(event.position().y())

            if self.is_dragging_beat:
                self.is_dragging_beat = False
            elif self.is_dragging_play:
                self.is_dragging_play = False
            elif self.is_dragging_view:
                self.is_dragging_view = False
                self.setCursor(Qt.CursorShape.OpenHandCursor)
                # 点击空白处不做任何操作，避免误触

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """双击跳转 - 左键双击跳转黄色虚线(播放位置)，右键双击跳转红色虚线(首拍位置)"""
        x = int(event.position().x())
        width = self.width()

        if event.button() == Qt.MouseButton.LeftButton:
            # 左键双击跳转播放位置（黄色虚线）
            new_time = self.x_to_time(x, width)
            new_time = max(0, min(new_time, self.duration))
            self.play_position = new_time
            self.play_position_changed.emit(new_time)
            self.update()

        elif event.button() == Qt.MouseButton.RightButton:
            # 右键双击跳转首拍位置（红色虚线）
            new_time = self.x_to_time(x, width)
            new_time = max(0, min(new_time, self.duration))
            self.set_first_beat(new_time)

    def wheelEvent(self, event):
        """鼠标滚轮缩放视图 - 参考mp3.py实现"""
        delta = event.angleDelta().y()
        # 向上滚(delta>0) = 放大 = 减小时间窗口
        zoom_factor = 0.9 if delta > 0 else 1.1

        # 限制缩放范围
        new_duration = self.view_duration * zoom_factor
        new_duration = max(5.0, min(new_duration, self.duration))  # 最小5秒，最大全时长

        if new_duration != self.view_duration:
            # 以鼠标位置为中心缩放
            width = self.width()
            mouse_x = int(event.position().x())
            mouse_time = self.x_to_time(mouse_x, width)

            self.view_duration = new_duration
            new_start = mouse_time - (mouse_x / width) * self.view_duration
            self.view_start_time = new_start
            self._clamp_view()
            self.update()
            self.view_position_changed.emit(self.view_start_time)

    def keyPressEvent(self, event: QKeyEvent):
        """键盘事件 - 左右方向键微调首拍"""
        step = 0.01  # 10ms步进

        if event.key() == Qt.Key.Key_Left:
            self.set_first_beat(self.first_beat_time - step)
        elif event.key() == Qt.Key.Key_Right:
            self.set_first_beat(self.first_beat_time + step)
        else:
            super().keyPressEvent(event)


class BeatAlignTab(QWidget):
    """首拍对齐标签页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.alignment_manager = BeatAlignmentManager()
        self.current_results = {}
        self.detect_thread = None
        self.current_audio_file = None
        self.full_audio_data = None  # 完整音频数据用于播放
        self.full_sample_rate = 44100
        self.play_start_position = 0.0  # 播放起始位置（用户拖拽后的位置）

        # 播放器
        self.player = None
        # 音频加载器
        self.audio_loader = None

        self.init_ui()
        # 自动加载默认文件夹
        self.auto_find_folder()

    def init_ui(self):
        layout = QHBoxLayout(self)

        # 左侧面板 - 歌曲列表
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        # 文件夹选择
        folder_group = QGroupBox("音频文件夹")
        folder_layout = QHBoxLayout()

        self.folder_path = QLabel("未选择")
        folder_layout.addWidget(self.folder_path)

        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_folder)
        folder_layout.addWidget(browse_btn)

        auto_btn = QPushButton("自动查找")
        auto_btn.clicked.connect(self.auto_find_folder)
        folder_layout.addWidget(auto_btn)

        folder_group.setLayout(folder_layout)
        left_layout.addWidget(folder_group)

        # 歌曲列表
        list_group = QGroupBox("歌曲列表（变速后的音频）")
        list_layout = QVBoxLayout()

        self.songs_table = QTableWidget()
        self.songs_table.setColumnCount(2)
        self.songs_table.setHorizontalHeaderLabels(["歌曲名", "首拍(s)"])
        self.songs_table.setMinimumHeight(150)
        # 表头铺满设置
        self.songs_table.horizontalHeader().setStretchLastSection(True)
        self.songs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.songs_table.currentCellChanged.connect(self.on_song_selected_from_table)
        list_layout.addWidget(self.songs_table)

        # 批量检测按钮（检测后自动保存）
        detect_btn = QPushButton("自动检测并保存所有首拍")
        detect_btn.clicked.connect(self.detect_all_beats)
        list_layout.addWidget(detect_btn)

        list_group.setLayout(list_layout)
        left_layout.addWidget(list_group)

        # 右侧面板 - 波形和微调
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # 波形图
        wave_group = QGroupBox("波形预览 - 点击或拖动红线调整首拍，黄线调整播放位置")
        wave_layout = QVBoxLayout()

        self.waveform = WaveformWidget(self)
        self.waveform.beat_position_changed.connect(self.on_beat_position_changed)
        self.waveform.play_position_changed.connect(self.on_play_position_changed)
        self.waveform.view_position_changed.connect(self.on_view_position_changed)
        wave_layout.addWidget(self.waveform)

        # 视图位置条（用于浏览全曲波形）
        view_layout = QHBoxLayout()
        view_layout.addWidget(QLabel("视图位置:"))
        self.view_position_slider = QSlider(Qt.Orientation.Horizontal)
        self.view_position_slider.setRange(0, 1000)  # 0-1000表示0%-100%
        self.view_position_slider.setValue(0)
        self.view_position_slider.valueChanged.connect(self.on_view_slider_changed)
        view_layout.addWidget(self.view_position_slider)
        self.view_time_label = QLabel("0.0s")
        view_layout.addWidget(self.view_time_label)
        wave_layout.addLayout(view_layout)

        # 播放控制
        play_control_layout = QHBoxLayout()

        self.play_btn = QPushButton("▶ 播放")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self.toggle_playback)
        play_control_layout.addWidget(self.play_btn)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_playback)
        play_control_layout.addWidget(self.stop_btn)

        # 音量滑块
        play_control_layout.addWidget(QLabel("音量:"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        play_control_layout.addWidget(self.volume_slider)

        self.play_time_label = QLabel("00:00 / 00:00")
        play_control_layout.addWidget(self.play_time_label)

        play_control_layout.addStretch()
        wave_layout.addLayout(play_control_layout)

        wave_group.setLayout(wave_layout)
        right_layout.addWidget(wave_group)

        # 微调控制
        control_group = QGroupBox("首拍时间微调")
        control_layout = QHBoxLayout()

        control_layout.addWidget(QLabel("首拍时间:"))

        self.beat_time_spin = QDoubleSpinBox()
        self.beat_time_spin.setRange(0, 15)
        self.beat_time_spin.setDecimals(3)
        self.beat_time_spin.setSingleStep(0.01)
        self.beat_time_spin.valueChanged.connect(self.on_spin_value_changed)
        control_layout.addWidget(self.beat_time_spin)

        control_layout.addWidget(QLabel("秒"))

        # 微调按钮
        left_btn = QPushButton("← -10ms")
        left_btn.clicked.connect(lambda: self.adjust_beat(-0.01))
        control_layout.addWidget(left_btn)

        right_btn = QPushButton("+10ms →")
        right_btn.clicked.connect(lambda: self.adjust_beat(0.01))
        control_layout.addWidget(right_btn)

        left_big_btn = QPushButton("← -100ms")
        left_big_btn.clicked.connect(lambda: self.adjust_beat(-0.1))
        control_layout.addWidget(left_big_btn)

        right_big_btn = QPushButton("+100ms →")
        right_big_btn.clicked.connect(lambda: self.adjust_beat(0.1))
        control_layout.addWidget(right_big_btn)

        control_layout.addStretch()
        control_group.setLayout(control_layout)
        right_layout.addWidget(control_group)

        # 信息标签
        self.info_label = QLabel("选择歌曲开始调整首拍")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.info_label)

        # 使用分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([300, 600])

        layout.addWidget(splitter)

        # 设置焦点策略以接收键盘事件
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def browse_folder(self):
        """浏览文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择变速后的音频文件夹")
        if folder:
            self.load_folder(folder)

    def auto_find_folder(self):
        """自动查找 shifted_songs 文件夹"""
        project_dir = os.path.dirname(os.path.dirname(__file__))
        folder = os.path.join(project_dir, "audio_output", "shifted_songs")
        if os.path.exists(folder):
            self.load_folder(folder)
        else:
            QMessageBox.warning(self, "警告", "未找到 shifted_songs 文件夹")

    def load_folder(self, folder: str):
        """加载文件夹中的音频"""
        self.folder_path.setText(folder)
        self.songs_table.setRowCount(0)
        self.current_results = {}
        self.file_paths = []  # 存储文件路径

        # 加载文件映射（原始文件名）
        self.file_mapping = self._load_file_mapping()
        # 加载BPM列表（获取变速后的文件名映射）
        self.bpm_list = self._load_bpm_list()
        # 加载已保存的首拍信息
        self.alignment_manager = BeatAlignmentManager()

        # 查找所有音频文件
        audio_files = []
        for ext in ['.wav', '.mp3', '.flac']:
            audio_files.extend(Path(folder).glob(f'*{ext}'))

        audio_files = sorted(audio_files, key=natural_sort_key)

        for row, file_path in enumerate(audio_files):
            self.songs_table.insertRow(row)
            self.file_paths.append(str(file_path))

            # 使用原始文件名显示
            display_name = self._get_display_name(file_path.name)
            name_item = QTableWidgetItem(display_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.songs_table.setItem(row, 0, name_item)

            # 首拍时间（如果有保存的）
            first_beat = self.alignment_manager.get_first_beat(str(file_path))
            if first_beat is not None:
                first_beat_text = f"{first_beat:.3f}"
            else:
                first_beat_text = "未检测"
            beat_item = QTableWidgetItem(first_beat_text)
            beat_item.setFlags(beat_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.songs_table.setItem(row, 1, beat_item)

        if self.parent_window and hasattr(self.parent_window, 'log_text'):
            self.parent_window.log_message(f"[首拍对齐] 加载了 {len(audio_files)} 首歌曲")

    def _load_bpm_list(self) -> list:
        """加载BPM列表"""
        try:
            project_dir = os.path.dirname(os.path.dirname(__file__))
            bpm_file = os.path.join(project_dir, 'data', 'song_bpm_list.json')
            if os.path.exists(bpm_file):
                with open(bpm_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            if self.parent_window and hasattr(self.parent_window, 'log_text'):
                self.parent_window.log_message(f"[首拍对齐] 加载BPM列表失败: {e}")
        return []

    def _get_display_name(self, shifted_name: str) -> str:
        """根据变速后的文件名获取原始文件名显示"""
        # 尝试从file_mapping直接查找（如果文件名没变）
        if shifted_name in self.file_mapping:
            return self.file_mapping[shifted_name]['original_name']

        # 解析变速后的文件名，提取索引
        stem = Path(shifted_name).stem  # "1_90bpm"
        parts = stem.split('_')
        if len(parts) >= 1:
            idx = parts[0]  # "1"
            # 在file_mapping中查找对应索引的文件
            for temp_name, mapping in self.file_mapping.items():
                temp_stem = Path(temp_name).stem  # "1"
                if temp_stem == idx:
                    # 找到对应的原始文件名
                    original_name = mapping['original_name']
                    # 移除扩展名，添加BPM信息
                    original_stem = Path(original_name).stem
                    return f"{original_stem} ({stem})"

        # 如果找不到映射，返回原始文件名
        return shifted_name

    def _load_file_mapping(self) -> dict:
        """加载文件映射"""
        try:
            project_dir = os.path.dirname(os.path.dirname(__file__))
            mapping_file = os.path.join(project_dir, 'data', 'file_mapping.json')
            if os.path.exists(mapping_file):
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            if self.parent_window and hasattr(self.parent_window, 'log_text'):
                self.parent_window.log_message(f"[首拍对齐] 加载文件映射失败: {e}")
        return {}

    def on_song_selected_from_table(self, current_row: int, current_column: int, previous_row: int, previous_column: int):
        """从表格选择歌曲时加载波形和音频"""
        if current_row < 0 or current_row >= len(self.file_paths):
            return

        file_path = self.file_paths[current_row]
        self.current_audio_file = file_path
        self.current_row = current_row

        # 停止当前播放并重置播放位置
        if self.player:
            self.player.stop()
            self.player.wait()
            self.player = None
        self.play_start_position = 0.0

        # 检查是否已有检测结果
        if file_path in self.current_results:
            first_beat = self.current_results[file_path]['first_beat_time']
        else:
            # 尝试从 alignment_manager 加载
            first_beat = self.alignment_manager.get_first_beat(file_path) or 0.0

        # 加载完整音频数据用于播放
        try:
            import librosa
            self.full_audio_data, self.full_sample_rate = librosa.load(
                file_path, sr=None, mono=True
            )
            self.play_btn.setEnabled(True)
            self.play_btn.setText("▶ 播放")
        except Exception as e:
            print(f"加载音频失败: {e}")
            self.full_audio_data = None
            self.play_btn.setEnabled(False)

        # 加载前15秒用于显示
        self.audio_loader = AudioLoader(file_path)
        self.audio_loader.loaded.connect(self._on_audio_loaded)
        self.audio_loader.error.connect(self._on_load_error)
        self.audio_loader.start()

        self.waveform.set_first_beat(first_beat)
        self.beat_time_spin.setValue(first_beat)
        self.info_label.setText(f"当前: {Path(file_path).name}")

    def _on_audio_loaded(self, audio_data, sample_rate):
        """音频加载完成"""
        self.waveform.set_audio_data(audio_data, sample_rate)
        self.update_play_time_label()
        self.update_view_time_label()
        self.stop_btn.setEnabled(True)

    def _on_load_error(self, error_msg):
        """音频加载失败"""
        print(f"加载音频失败: {error_msg}")
        self.stop_btn.setEnabled(False)

    def toggle_playback(self):
        """切换播放/暂停"""
        if self.player is None:
            self.start_playback()
        elif self.player.is_paused:
            self.resume_playback()
        else:
            self.pause_playback()

    def start_playback(self):
        """开始播放"""
        if self.full_audio_data is None:
            return

        try:
            # 停止之前的播放
            if self.player is not None:
                self.player.stop()
                self.player.wait()

            # 创建新的播放器
            self.player = AudioPlayer(self.full_audio_data, self.full_sample_rate)
            self.player.position_changed.connect(self._on_player_position_changed)
            self.player.finished_signal.connect(self._on_playback_finished)

            # 设置音量
            self.player.set_volume(self.volume_slider.value() / 100.0)

            # 使用保存的播放起始位置
            start_pos = self.play_start_position
            if start_pos > 0:
                self.player.seek(start_pos)

            self.player.start()
            self.play_btn.setText("⏸ 暂停")

        except Exception as e:
            print(f"播放失败: {e}")
            self.play_btn.setText("▶ 播放")

    def pause_playback(self):
        """暂停播放"""
        if self.player:
            self.player.pause()
            self.play_btn.setText("▶ 继续")

    def resume_playback(self):
        """继续播放"""
        if self.player:
            # 如果播放位置被拖拽过，跳转到新位置
            current_pos = self.player.current_frame / self.player.sample_rate
            if abs(current_pos - self.play_start_position) > 0.01:  # 位置变化超过10ms
                self.player.seek(self.play_start_position)
            self.player.resume()
            self.play_btn.setText("⏸ 暂停")

    def stop_playback(self):
        """停止播放"""
        if self.player:
            self.player.stop()
            self.player.wait()
            self.player = None
        self.play_btn.setText("▶ 播放")
        self.play_start_position = 0.0
        self.waveform.set_play_position(0)
        self.update_play_time_label()

    def _on_player_position_changed(self, position: float):
        """播放器位置改变"""
        self.waveform.set_play_position(position)
        self.update_play_time_label()

    def _on_playback_finished(self):
        """播放结束"""
        self.play_btn.setText("▶ 播放")
        self.player = None
        self.play_start_position = 0.0

    def on_play_position_changed(self, position_sec: float):
        """波形图播放位置改变（用户拖拽）"""
        # 保存播放起始位置
        self.play_start_position = position_sec
        # 如果正在播放，跳转到新位置
        if self.player and not self.player.is_paused:
            self.player.seek(position_sec)
        self.update_play_time_label()

    def on_volume_changed(self, value):
        """音量改变"""
        if self.player:
            self.player.set_volume(value / 100.0)

    def on_view_slider_changed(self, value):
        """视图位置条改变 - 允许查看全曲任意位置"""
        if self.waveform and self.waveform.duration > 0:
            # value范围是0-1000，转换为时间（0到音频结束）
            ratio = value / 1000.0
            # 最大起始时间可以是音频结束（允许视图超出音频）
            max_start = self.waveform.duration
            start_time = ratio * max_start
            self.waveform.set_view_position(start_time)
            self.update_view_time_label()

    def on_view_position_changed(self, start_time: float):
        """波形图视图位置改变（由波形图内部触发）"""
        # 更新滑块位置
        if self.waveform and self.waveform.duration > 0:
            # 使用音频时长作为最大值，允许视图超出音频
            max_start = self.waveform.duration
            if max_start > 0:
                ratio = start_time / max_start
                self.view_position_slider.blockSignals(True)
                self.view_position_slider.setValue(int(ratio * 1000))
                self.view_position_slider.blockSignals(False)
        self.update_view_time_label()

    def update_view_time_label(self):
        """更新视图时间标签"""
        if self.waveform:
            start = self.waveform.view_start_time
            duration = self.waveform.view_duration
            end = start + duration
            self.view_time_label.setText(f"{start:.1f}s - {end:.1f}s (窗口: {duration:.1f}s)")
        else:
            self.view_time_label.setText("0.0s")

    def update_play_time_label(self):
        """更新播放时间标签"""
        current_sec = self.waveform.play_position if self.waveform else 0
        duration_sec = 0
        if self.full_audio_data is not None:
            duration_sec = len(self.full_audio_data) / self.full_sample_rate
        current_str = self._format_time(current_sec)
        total_str = self._format_time(duration_sec)
        self.play_time_label.setText(f"{current_str} / {total_str}")

    def _format_time(self, seconds):
        """格式化时间为 mm:ss"""
        minutes = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{minutes:02d}:{secs:02d}"

    def detect_all_beats(self):
        count = self.songs_table.rowCount()
        if count == 0:
            QMessageBox.warning(self, "警告", "没有可检测的歌曲")
            return

        file_paths = self.file_paths.copy()

        self.detect_thread = BeatDetectThread(file_paths)
        self.detect_thread.progress.connect(self._on_detect_progress)
        self.detect_thread.error.connect(self._on_detect_error)
        self.detect_thread.finished.connect(self._on_detect_finished)
        self.detect_thread.start()

        if self.parent_window:
            self.parent_window.log_message(f"[首拍检测] 开始检测 {count} 首歌曲...")

    def _on_detect_progress(self, current, total, file_name):
        if self.parent_window and hasattr(self.parent_window, 'log_text'):
            self.parent_window.log_message(f"[首拍检测] {current}/{total}: {file_name}")

    def _on_detect_error(self, error_msg):
        if self.parent_window and hasattr(self.parent_window, 'log_text'):
            self.parent_window.log_message(f"[首拍检测] 错误: {error_msg}")

    def _on_detect_finished(self, count):
        # 保存所有结果
        for file_path, result in self.detect_thread.results.items():
            self.current_results[file_path] = result
            self.alignment_manager.set_first_beat(file_path, result['first_beat_time'])

        # 更新表格中的首拍显示
        for row, file_path in enumerate(self.file_paths):
            if file_path in self.current_results:
                first_beat = self.current_results[file_path]['first_beat_time']
                self.songs_table.item(row, 1).setText(f"{first_beat:.3f}")

        if self.parent_window:
            self.parent_window.log_message(f"[首拍检测] 完成，已检测 {count} 首歌曲并保存")

        QMessageBox.information(self, "完成", f"首拍检测完成！\n已检测 {count} 首歌曲\n结果已自动保存")

        # 刷新当前显示
        current_row = self.songs_table.currentRow()
        if current_row >= 0:
            self.on_song_selected_from_table(current_row, 0, -1, 0)

    def on_beat_position_changed(self, time: float):
        """波形图首拍位置改变 - 实时保存"""
        self.beat_time_spin.blockSignals(True)
        self.beat_time_spin.setValue(time)
        self.beat_time_spin.blockSignals(False)

        # 更新当前结果并实时保存
        current_row = self.songs_table.currentRow()
        if current_row >= 0 and current_row < len(self.file_paths):
            file_path = self.file_paths[current_row]
            if file_path not in self.current_results:
                self.current_results[file_path] = {}
            self.current_results[file_path]['first_beat_time'] = time

            # 实时保存到 alignment_manager
            self.alignment_manager.set_first_beat(file_path, time)

            # 实时更新表格显示
            self.songs_table.item(current_row, 1).setText(f"{time:.3f}")

    def on_spin_value_changed(self, value: float):
        """微调框值改变"""
        self.waveform.set_first_beat(value)

    def adjust_beat(self, delta: float):
        """微调首拍时间"""
        new_time = self.beat_time_spin.value() + delta
        self.beat_time_spin.setValue(new_time)

    def keyPressEvent(self, event: QKeyEvent):
        """键盘事件"""
        step = 0.01
        if event.key() == Qt.Key.Key_Left:
            self.adjust_beat(-step)
        elif event.key() == Qt.Key.Key_Right:
            self.adjust_beat(step)
        else:
            super().keyPressEvent(event)
