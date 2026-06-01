#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tab 5 - 混音标签页

功能:
    1. 设置混音参数: 目标响度（dBFS）、节拍器 BPM、节拍器音量
    2. 导出对齐信息 CSV（data/alignment_detail_{timestamp}.csv）
       包含: 每首歌的首拍时间、开始播放时间、结束时间、节拍器重拍标记
       可用 tools/auto_mix.py 在 Audacity 中导入此 CSV
    3. 执行混音: 首拍对齐 + 响度归一化 + 可选节拍器叠加
       输出: audio_output/final_mix/running_mix.wav

首拍对齐策略:
    - 第一首歌从 0 秒开始，其首拍作为节拍器参考起点
    - 后续歌曲的首拍对齐到节拍器的下一个重拍（每 4 拍 = 1 小节）
    - 自动检测重叠：如果下一首歌会与当前歌曲重叠，自动推迟到下下个重拍

依赖:
    modules/audio_mixer.py → AudioMixer, MixConfig
    modules/beat_detector.py → BeatAlignmentManager
"""

import os
import re
from typing import List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QMessageBox, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QFileDialog
)
from PyQt6.QtCore import QThread, pyqtSignal


def natural_sort_key(s) -> List:
    """自然排序键函数 - 正确处理数字顺序"""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]


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


class MixingTab(QWidget):
    """混音标签页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 输入设置
        input_group = QGroupBox("输入设置")
        input_layout = QVBoxLayout()

        # 输入文件夹（使用默认路径）
        project_dir = os.path.dirname(os.path.dirname(__file__))
        default_input = os.path.join(project_dir, 'audio_output', 'shifted_songs')
        path_label = QLabel(f"音频文件夹: {default_input}")
        path_label.setStyleSheet("color: #999;")
        input_layout.addWidget(path_label)

        # 输出文件
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("输出文件:"))
        self.output_file = QLineEdit()
        self.output_file.setPlaceholderText("running_mix.wav...")
        output_layout.addWidget(self.output_file)

        out_browse_btn = QPushButton("浏览...")
        out_browse_btn.clicked.connect(self.browse_output)
        output_layout.addWidget(out_browse_btn)
        input_layout.addLayout(output_layout)

        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        # 混音参数
        params_group = QGroupBox("混音参数")
        params_layout = QVBoxLayout()

        # 目标响度
        loudness_layout = QHBoxLayout()
        loudness_layout.addWidget(QLabel("目标响度(dBFS):"))
        self.loudness_spin = QDoubleSpinBox()
        self.loudness_spin.setRange(-24, -6)
        self.loudness_spin.setValue(-12)
        self.loudness_spin.setSingleStep(1)
        loudness_layout.addWidget(self.loudness_spin)
        loudness_layout.addStretch()
        params_layout.addLayout(loudness_layout)

        # 节拍器BPM（用于对齐计算）
        bpm_layout = QHBoxLayout()
        bpm_layout.addWidget(QLabel("节拍器BPM:"))
        self.metronome_bpm_spin = QSpinBox()
        self.metronome_bpm_spin.setRange(60, 300)
        self.metronome_bpm_spin.setValue(180)
        bpm_layout.addWidget(self.metronome_bpm_spin)
        bpm_layout.addStretch()
        params_layout.addLayout(bpm_layout)

        # 节拍器设置
        metronome_group = QGroupBox("节拍器叠加")
        metronome_layout = QVBoxLayout()

        # 启用节拍器
        self.use_metronome_check = QCheckBox("叠加节拍器")
        self.use_metronome_check.setChecked(True)
        metronome_layout.addWidget(self.use_metronome_check)

        # 节拍器文件夹（使用默认路径）
        project_dir = os.path.dirname(os.path.dirname(__file__))
        default_metronome = os.path.join(project_dir, 'audio_output', 'metronome')
        metro_path_label = QLabel(f"节拍器文件夹: {default_metronome}")
        metro_path_label.setStyleSheet("color: #999;")
        metronome_layout.addWidget(metro_path_label)

        # 节拍器音量
        metro_vol_layout = QHBoxLayout()
        metro_vol_layout.addWidget(QLabel("节拍器音量(dB):"))
        self.metronome_vol_spin = QDoubleSpinBox()
        self.metronome_vol_spin.setRange(-30, 0)
        self.metronome_vol_spin.setValue(0)
        self.metronome_vol_spin.setSingleStep(1)
        metro_vol_layout.addWidget(self.metronome_vol_spin)
        metro_vol_layout.addWidget(QLabel("(负值表示比音乐小)"))
        metro_vol_layout.addStretch()
        metronome_layout.addLayout(metro_vol_layout)

        metronome_group.setLayout(metronome_layout)
        layout.addWidget(metronome_group)

        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

        # 混音按钮
        btn_layout = QHBoxLayout()

        self.export_btn = QPushButton("导出对齐信息")
        self.export_btn.setToolTip("导出Audacity标签文件到data文件夹")
        self.export_btn.clicked.connect(self.export_alignment_info)
        btn_layout.addWidget(self.export_btn)

        btn_layout.addStretch()

        self.mix_btn = QPushButton("开始混音")
        self.mix_btn.clicked.connect(self.start_mixing)
        btn_layout.addWidget(self.mix_btn)

        layout.addLayout(btn_layout)

        layout.addStretch()

    def browse_output(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存混音文件", "running_mix.wav", "WAV files (*.wav)"
        )
        if file_path:
            self.output_file.setText(file_path)

    def find_metronome_file(self):
        """自动查找节拍器文件"""
        project_dir = os.path.dirname(os.path.dirname(__file__))
        metronome_dir = os.path.join(project_dir, "audio_output", "metronome")
        possible_names = ['metronome_180.wav', 'metronome_180.mp3', 'metronome.wav', 'metronome.mp3', 'click.wav', 'click.mp3']
        for name in possible_names:
            path = os.path.join(metronome_dir, name)
            if os.path.exists(path):
                return path
        return None

    def start_mixing(self):
        # 使用默认路径
        project_dir = os.path.dirname(os.path.dirname(__file__))
        input_folder = os.path.join(project_dir, 'audio_output', 'shifted_songs')

        if not os.path.exists(input_folder) or not os.listdir(input_folder):
            QMessageBox.warning(self, "警告", "请先完成变速处理")
            return

        output_file = self.output_file.text()
        if not output_file:
            output_file = os.path.join(project_dir, "audio_output", "final_mix", "running_mix.wav")

        # 自动查找节拍器文件
        metro_path = None
        if self.use_metronome_check.isChecked():
            metro_path = self.find_metronome_file()
            if not metro_path:
                QMessageBox.warning(self, "警告", "未找到节拍器文件，请先生成节拍器")
                return

        mix_params = {
            'input_folder': input_folder,
            'output_file': output_file,
            'target_loudness': self.loudness_spin.value(),
            'use_beat_alignment': True,  # 默认启用首拍对齐
            'metronome_bpm': self.metronome_bpm_spin.value(),
            'metronome_path': metro_path if self.use_metronome_check.isChecked() else None,
            'metronome_volume': self.metronome_vol_spin.value(),
        }

        self.mix_btn.setEnabled(False)
        self.mix_btn.setText("混音中...")

        self.mixer_worker = WorkerThread(self._run_mixing, mix_params)
        self.mixer_worker.finished.connect(self._on_mixing_finished)
        self.mixer_worker.start()

    @staticmethod
    def _run_mixing(params):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'modules'))
        from audio_mixer import AudioMixer, MixConfig
        config = MixConfig(
            target_loudness=params['target_loudness'],
            use_beat_alignment=params['use_beat_alignment'],
            metronome_bpm=params['metronome_bpm'],
            metronome_path=params['metronome_path'],
            metronome_volume=params['metronome_volume'],
        )
        mixer = AudioMixer(config)
        # 始终使用首拍对齐
        return mixer.mix_with_beat_alignment(params['input_folder'], params['output_file'])

    def _on_mixing_finished(self, success, message):
        self.mix_btn.setEnabled(True)
        self.mix_btn.setText("开始混音")

        if not success:
            QMessageBox.critical(self, "错误", f"混音失败: {message}")
            return

        success_result = self.mixer_worker.result if self.mixer_worker else False
        output_file = self.output_file.text()
        if not output_file:
            project_dir = os.path.dirname(os.path.dirname(__file__))
            output_file = os.path.join(project_dir, "audio_output", "final_mix", "running_mix.wav")

        if success_result:
            if self.parent_window:
                self.parent_window.log_message(f"[混音] 完成: {output_file}")
            QMessageBox.information(self, "完成", f"混音完成!\n输出: {output_file}")
            # 询问是否清理缓存
            self.ask_clear_cache()
        else:
            QMessageBox.warning(self, "警告", "混音失败")

    def ask_clear_cache(self):
        """混音完成后询问是否清理缓存"""
        reply = QMessageBox.question(
            self, "清理缓存",
            "混音已完成！\n\n"
            "是否清理中间文件缓存？\n\n"
            "将清理：\n"
            "- audio_input（输入音频）\n"
            "- audio_output/metronome（节拍器文件）\n"
            "- audio_output/shifted_songs（变速后的歌曲）\n"
            "- data（BPM数据等）\n\n"
            "注意：final_mix（混音结果）不会被清理",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # 调用准备音频标签页的清理功能
            if self.parent_window and hasattr(self.parent_window, 'prepare_tab'):
                self.parent_window.prepare_tab.clear_cache(silent=True)
                if self.parent_window:
                    self.parent_window.log_message("[混音] 已清理缓存")
            else:
                if self.parent_window:
                    self.parent_window.log_message("[混音] 无法访问清理功能")

    def export_alignment_info(self):
        """导出对齐信息到Audacity标签文件"""
        # 获取shifted_songs文件夹中的歌曲
        project_dir = os.path.dirname(os.path.dirname(__file__))
        input_folder = os.path.join(project_dir, 'audio_output', 'shifted_songs')

        if not os.path.exists(input_folder):
            QMessageBox.warning(self, "警告", "未找到变速后的音频文件夹")
            return

        # 获取所有音频文件
        from pathlib import Path
        audio_files = []
        for ext in ['.wav', '.mp3', '.flac']:
            audio_files.extend(Path(input_folder).glob(f'*{ext}'))
        audio_files = sorted([str(f) for f in audio_files], key=natural_sort_key)

        if not audio_files:
            QMessageBox.warning(self, "警告", "没有可导出的歌曲")
            return

        # 导入首拍对齐管理器
        try:
            import sys
            project_dir = os.path.dirname(os.path.dirname(__file__))
            if project_dir not in sys.path:
                sys.path.insert(0, project_dir)
            from modules.beat_detector import BeatAlignmentManager
            alignment_manager = BeatAlignmentManager()
        except ImportError as e:
            QMessageBox.critical(self, "错误", f"无法加载首拍对齐模块: {e}")
            return

        # 检查是否所有歌曲都有首拍信息
        missing_beats = []
        for file_path in audio_files:
            first_beat = alignment_manager.get_first_beat(file_path)
            if first_beat is None:
                missing_beats.append(os.path.basename(file_path))

        if missing_beats:
            reply = QMessageBox.question(
                self, "确认导出",
                f"以下歌曲缺少首拍信息:\n{chr(10).join(missing_beats[:5])}{'...' if len(missing_beats) > 5 else ''}\n\n是否继续导出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        try:
            import numpy as np
            import librosa
            from datetime import datetime

            # 获取data文件夹路径
            data_dir = os.path.join(project_dir, 'data')
            os.makedirs(data_dir, exist_ok=True)

            # 生成文件名（带时间戳）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_file = os.path.join(data_dir, f'alignment_detail_{timestamp}.csv')

            # 获取当前参数
            metronome_bpm = self.metronome_bpm_spin.value()
            target_loudness = self.loudness_spin.value()
            metronome_volume = self.metronome_vol_spin.value()
            use_metronome = self.use_metronome_check.isChecked()

            # 计算对齐信息
            labels = []
            beat_duration_ms = 60000 / metronome_bpm
            measure_duration_ms = beat_duration_ms * 4  # 4拍一小节

            first_song_first_beat_ms = 0.0
            current_measure = 0
            prev_song_end_ms = 0.0  # 用于检查重叠

            for idx, file_path in enumerate(audio_files):
                file_name = os.path.basename(file_path)

                # 获取首拍时间
                first_beat_sec = alignment_manager.get_first_beat(file_path) or 0.0
                first_beat_ms = first_beat_sec * 1000

                # 获取音频时长
                try:
                    audio_data, sr = librosa.load(file_path, sr=None, mono=True)
                    duration_ms = len(audio_data) / sr * 1000
                except:
                    duration_ms = 0

                if idx == 0:
                    # 第一首歌
                    song_start_ms = 0
                    first_song_first_beat_ms = first_beat_ms
                    target_beat_time_ms = first_beat_ms
                    labels.append({
                        'start': song_start_ms / 1000,
                        'end': (song_start_ms + duration_ms) / 1000,
                        'label': f"{idx+1}. {file_name}"
                    })
                else:
                    # 后续歌曲：首拍对齐到节拍器的下一个重拍，且不能与前一首歌重叠
                    target_beat_time_ms = first_song_first_beat_ms + (current_measure * measure_duration_ms)
                    song_start_ms = target_beat_time_ms - first_beat_ms

                    # 确保不与上一首歌重叠：开始时间必须 >= 上一首歌的结束时间
                    if song_start_ms < prev_song_end_ms:
                        # 需要往后找下一个重拍，直到不重叠
                        while song_start_ms < prev_song_end_ms:
                            current_measure += 1  # 往后推一个小节
                            target_beat_time_ms = first_song_first_beat_ms + (current_measure * measure_duration_ms)
                            song_start_ms = target_beat_time_ms - first_beat_ms

                    labels.append({
                        'start': song_start_ms / 1000,
                        'end': (song_start_ms + duration_ms) / 1000,
                        'label': f"{idx+1}. {file_name}"
                    })

                # 计算当前歌曲结束时间，用于检查下一首歌是否重叠
                song_end_ms = song_start_ms + duration_ms
                prev_song_end_ms = song_end_ms  # 更新上一首歌的结束时间

                # 计算下一首应该对齐到哪个重拍
                elapsed_from_metronome_start = song_end_ms - first_song_first_beat_ms
                current_beat = int(np.ceil(elapsed_from_metronome_start / beat_duration_ms))
                next_measure_beat = ((current_beat // 4) + 1) * 4
                current_measure = next_measure_beat / 4

            # 计算总时长
            total_duration_sec = labels[-1]['end'] if labels else 0

            # 生成节拍器重拍标记（每4拍一个重拍）
            metronome_labels = []
            measure_duration_sec = measure_duration_ms / 1000
            measure_num = 0
            t = first_song_first_beat_ms / 1000  # 从第一首歌首拍开始
            while t <= total_duration_sec + 1:  # 多生成1秒
                metronome_labels.append({
                    'time': t,
                    'label': f"▼ 重拍 {measure_num + 1}"
                })
                t += measure_duration_sec
                measure_num += 1

            # 写入CSV文件
            with open(csv_file, 'w', encoding='utf-8') as f:
                # 写入参数信息
                f.write("# 混音参数\n")
                f.write(f"# BPM,{metronome_bpm}\n")
                f.write(f"# 目标响度(dBFS),{target_loudness}\n")
                f.write(f"# 节拍器叠加,{'是' if use_metronome else '否'}\n")
                if use_metronome:
                    f.write(f"# 节拍器音量(dB),{metronome_volume}\n")
                f.write(f"# 第一首歌首拍(s),{first_song_first_beat_ms/1000:.3f}\n")
                f.write(f"# 重拍数量,{len(metronome_labels)}\n")
                f.write("#\n")
                f.write("序号,文件名,首拍时间(s),开始播放(s),结束时间(s),时长(s)\n")

                for idx, label in enumerate(labels):
                    file_path = audio_files[idx]
                    first_beat_sec = alignment_manager.get_first_beat(file_path) or 0.0
                    duration = label['end'] - label['start']

                    f.write(f"{idx+1},{label['label'][3:]},{first_beat_sec:.3f},"
                           f"{label['start']:.3f},{label['end']:.3f},{duration:.3f}\n")

            # 显示成功消息
            msg = f"对齐信息已导出到:\n{csv_file}\n\n"
            msg += "混音参数:\n"
            msg += f"  BPM: {metronome_bpm}\n"
            msg += f"  目标响度: {target_loudness} dBFS\n"
            msg += f"  节拍器叠加: {'启用' if use_metronome else '禁用'}\n"
            if use_metronome:
                msg += f"  节拍器音量: {metronome_volume} dB\n"
            msg += f"  重拍数量: {len(metronome_labels)}\n"
            msg += f"  第一首歌首拍: {first_song_first_beat_ms/1000:.3f}s\n\n"
            msg += "歌曲预览:\n"
            for i, label in enumerate(labels[:3]):
                msg += f"  {label['label']}: {label['start']:.2f}s - {label['end']:.2f}s\n"
            if len(labels) > 3:
                msg += f"  ... 共 {len(labels)} 首歌曲\n"

            QMessageBox.information(self, "导出成功", msg)

            if self.parent_window:
                self.parent_window.log_message(f"[混音] 已导出对齐信息到: {csv_file}")

        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出时出错:\n{str(e)}")
            if self.parent_window:
                self.parent_window.log_message(f"[混音] 导出失败: {e}")
