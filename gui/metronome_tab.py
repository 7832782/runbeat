#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tab 3 - 节拍器生成标签页

功能:
    1. 设置节拍器参数: BPM、时长、拍号、强/弱拍频率
    2. 检测变速后歌曲的总时长（自动遍历 shifted_songs/ 文件夹）
    3. 生成建议时长（总时长 + 每首歌 5 秒空余）
    4. 生成节拍器 WAV 文件到 audio_output/metronome/metronome_{bpm}.wav

音色说明:
    - 强拍（每小节第 1 拍）: 默认 1000Hz，音量 0.8，用于节拍对齐参考
    - 弱拍（其余拍）: 默认 800Hz，音量 0.5
    - 使用指数衰减正弦波模拟自然的"嗒"声

依赖:
    modules/metronome_generator.py → MetronomeGenerator, MetronomeConfig
"""

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QMessageBox, QSpinBox, QComboBox, QDoubleSpinBox
)
from PyQt6.QtCore import QThread, pyqtSignal


class WorkerThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, task_func, *args, **kwargs):
        super().__init__()
        self.task_func = task_func
        self.args = args
        self.kwargs = kwargs
        self.result = None
        self.error_msg = None

    def run(self):
        try:
            self.result = self.task_func(*self.args, **self.kwargs)
            self.finished.emit(True, "")
        except Exception as e:
            self.error_msg = str(e)
            self.finished.emit(False, str(e))


class MetronomeTab(QWidget):
    """节拍器生成标签页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 参数设置
        params_group = QGroupBox("节拍器参数")
        params_layout = QVBoxLayout()

        # BPM设置
        bpm_layout = QHBoxLayout()
        bpm_layout.addWidget(QLabel("目标BPM:"))
        self.bpm_spin = QSpinBox()
        self.bpm_spin.setRange(60, 300)
        self.bpm_spin.setValue(180)
        bpm_layout.addWidget(self.bpm_spin)
        bpm_layout.addStretch()
        params_layout.addLayout(bpm_layout)

        # 时长设置
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("时长(秒):"))
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(5, 36000)
        self.duration_spin.setValue(30)
        duration_layout.addWidget(self.duration_spin)
        duration_layout.addStretch()
        params_layout.addLayout(duration_layout)

        # 拍号设置
        beat_layout = QHBoxLayout()
        beat_layout.addWidget(QLabel("每小节拍数:"))
        self.beats_spin = QSpinBox()
        self.beats_spin.setRange(2, 8)
        self.beats_spin.setValue(4)
        beat_layout.addWidget(self.beats_spin)
        beat_layout.addStretch()
        params_layout.addLayout(beat_layout)

        # 音色类型选择
        click_type_layout = QHBoxLayout()
        click_type_layout.addWidget(QLabel("拍声音色:"))
        self.click_type_combo = QComboBox()
        self.click_type_map = {
            "节拍器拍": 0,
            "砰 (短)": 1,
            "砰 (长)": 2,
            "牛铃": 3,
            "共鸣噪音": 4,
            "咔嚓噪音": 5,
            "滴 (短)": 6,
            "滴 (长)": 7,
        }
        self.click_type_combo.addItems(list(self.click_type_map.keys()))
        self.click_type_combo.setCurrentText("节拍器拍")
        click_type_layout.addWidget(self.click_type_combo)
        click_type_layout.addStretch()
        params_layout.addLayout(click_type_layout)

        # MIDI 音高设置
        pitch_layout = QHBoxLayout()
        pitch_layout.addWidget(QLabel("强拍 MIDI 音高:"))
        self.strong_pitch = QSpinBox()
        self.strong_pitch.setRange(18, 116)
        self.strong_pitch.setValue(84)
        pitch_layout.addWidget(self.strong_pitch)

        pitch_layout.addWidget(QLabel("弱拍 MIDI 音高:"))
        self.weak_pitch = QSpinBox()
        self.weak_pitch.setRange(18, 116)
        self.weak_pitch.setValue(80)
        pitch_layout.addWidget(self.weak_pitch)
        pitch_layout.addStretch()
        params_layout.addLayout(pitch_layout)

        # Swing 设置
        swing_layout = QHBoxLayout()
        swing_layout.addWidget(QLabel("摇摆量 (-1 到 1):"))
        self.swing_spin = QDoubleSpinBox()
        self.swing_spin.setRange(-1.0, 1.0)
        self.swing_spin.setValue(0.0)
        self.swing_spin.setSingleStep(0.1)
        swing_layout.addWidget(self.swing_spin)
        swing_layout.addStretch()
        params_layout.addLayout(swing_layout)

        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

        # 歌曲时长检测
        songs_group = QGroupBox("歌曲时长检测")
        songs_layout = QVBoxLayout()

        songs_btn_layout = QHBoxLayout()
        self.detect_songs_btn = QPushButton("检测歌曲时长")
        self.detect_songs_btn.clicked.connect(self.detect_songs_duration)
        songs_btn_layout.addWidget(self.detect_songs_btn)

        self.apply_duration_btn = QPushButton("应用建议时长")
        self.apply_duration_btn.clicked.connect(self.apply_recommended_duration)
        self.apply_duration_btn.setEnabled(False)  # 初始不可用，检测后才可用
        songs_btn_layout.addWidget(self.apply_duration_btn)

        songs_btn_layout.addStretch()
        songs_layout.addLayout(songs_btn_layout)

        self.songs_info_label = QLabel("未检测歌曲")
        self.songs_info_label.setWordWrap(True)
        songs_layout.addWidget(self.songs_info_label)

        songs_group.setLayout(songs_layout)
        layout.addWidget(songs_group)

        # 存储建议时长
        self.recommended_duration = 30

        # 生成按钮
        btn_layout = QHBoxLayout()

        self.generate_btn = QPushButton("生成节拍器")
        self.generate_btn.clicked.connect(self.generate_metronome)
        btn_layout.addWidget(self.generate_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 预览信息
        info_group = QGroupBox("节拍器信息")
        info_layout = QVBoxLayout()

        self.info_label = QLabel("点击生成按钮创建节拍器音频")
        self.info_label.setWordWrap(True)
        info_layout.addWidget(self.info_label)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        layout.addStretch()

    def detect_songs_duration(self):
        """检测变速后歌曲的总时长"""
        try:
            from pydub import AudioSegment

            project_dir = os.path.dirname(os.path.dirname(__file__))
            shifted_dir = os.path.join(project_dir, "audio_output", "shifted_songs")

            if not os.path.exists(shifted_dir):
                QMessageBox.warning(self, "警告", f"未找到歌曲目录: {shifted_dir}\n请先进行变速处理")
                return

            # 查找所有音频文件
            audio_files = []
            for ext in ['*.mp3', '*.wav', '*.flac', '*.m4a']:
                audio_files.extend(Path(shifted_dir).glob(ext))

            if not audio_files:
                QMessageBox.warning(self, "警告", f"在 {shifted_dir} 中未找到音频文件\n请先进行变速处理")
                return

            # 计算总时长
            total_duration_ms = 0
            song_count = len(audio_files)

            for file_path in audio_files:
                try:
                    audio = AudioSegment.from_file(str(file_path))
                    total_duration_ms += len(audio)
                except Exception as e:
                    if self.parent_window:
                        self.parent_window.log_message(f"[检测] 无法读取 {file_path.name}: {e}")

            total_duration_sec = total_duration_ms / 1000
            # 每首歌加5秒空余
            extra_duration = song_count * 5
            self.recommended_duration = int(total_duration_sec + extra_duration)

            # 更新UI
            info_text = f"检测到 {song_count} 首歌曲\n总时长: {total_duration_sec:.1f}秒\n每首+5秒空余: +{extra_duration}秒\n建议节拍器时长: {self.recommended_duration}秒"
            self.songs_info_label.setText(info_text)

            # 启用应用按钮
            self.apply_duration_btn.setEnabled(True)

            if self.parent_window:
                self.parent_window.log_message(f"[歌曲检测] {song_count}首, 总时长{total_duration_sec:.1f}s, 建议节拍器{self.recommended_duration}s")

            QMessageBox.information(self, "检测完成", f"检测到 {song_count} 首歌曲\n建议节拍器时长: {self.recommended_duration}秒\n点击'应用建议时长'按钮使用此时长")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"检测失败: {str(e)}")

    def apply_recommended_duration(self):
        """应用建议的节拍器时长"""
        self.duration_spin.setValue(min(self.recommended_duration, 36000))  # 最大36000秒(10小时)
        if self.parent_window:
            self.parent_window.log_message(f"[节拍器] 已应用建议时长: {self.recommended_duration}秒")

    def generate_metronome(self):
        bpm = self.bpm_spin.value()
        duration = self.duration_spin.value()
        beats_per_measure = self.beats_spin.value()
        click_type_name = self.click_type_combo.currentText()
        click_type = self.click_type_map[click_type_name]
        strong_pitch = self.strong_pitch.value()
        weak_pitch = self.weak_pitch.value()
        swing = self.swing_spin.value()

        project_dir = os.path.dirname(os.path.dirname(__file__))
        metronome_dir = os.path.join(project_dir, "audio_output", "metronome")
        os.makedirs(metronome_dir, exist_ok=True)
        output_path = os.path.join(metronome_dir, f"metronome_{bpm}.wav")

        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("生成中...")

        self.metro_worker = WorkerThread(
            self._run_metronome_generation,
            bpm, duration, beats_per_measure, click_type, strong_pitch, weak_pitch, swing, output_path
        )
        self.metro_worker.finished.connect(self._on_metronome_finished)
        self.metro_worker.start()

    @staticmethod
    def _run_metronome_generation(bpm, duration, beats_per_measure, click_type, strong_pitch, weak_pitch, swing, output_path):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'modules'))
        from metronome_generator import MetronomeGenerator, MetronomeConfig, ClickType
        config = MetronomeConfig(
            bpm=bpm, duration=duration, beats_per_measure=beats_per_measure,
            click_type=ClickType(click_type), strong_pitch=strong_pitch, weak_pitch=weak_pitch,
            swing=swing
        )
        generator = MetronomeGenerator(config)
        audio, sr = generator.generate(output_path)
        return {
            'output_path': output_path,
            'info': generator.get_info()
        }

    def _on_metronome_finished(self, success, message):
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("生成节拍器")

        if not success:
            QMessageBox.critical(self, "错误", f"生成失败: {message}")
            return

        result = self.metro_worker.result if self.metro_worker else {}
        output_path = result.get('output_path', '')
        info = result.get('info', {})
        info_text = f"""
节拍器已生成!
文件: {output_path}
BPM: {info.get('bpm', '')}
时长: {info.get('duration', '')}秒
总拍数: {info.get('total_beats', '')}
拍号: {info.get('beats_per_measure', '')}/4
        """.strip()
        self.info_label.setText(info_text)

        if self.parent_window:
            self.parent_window.log_message(f"[节拍器] 已生成: {output_path}")

        QMessageBox.information(self, "完成", "节拍器音频已生成!")
