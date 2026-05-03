#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作流自动化标签页

一键完成整个流程：
BPM识别 -> 变速处理 -> 混音
"""

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional, List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QDoubleSpinBox, QProgressBar,
    QFileDialog, QGroupBox, QTextEdit, QMessageBox, QCheckBox, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'modules'))


def natural_sort_key(s) -> List:
    """自然排序键函数 - 正确处理数字顺序"""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]


class WorkflowThread(QThread):
    """工作流后台线程"""
    progress = pyqtSignal(str, int)  # 消息, 进度百分比
    step_completed = pyqtSignal(str, bool)  # 步骤名称, 是否成功
    finished = pyqtSignal(bool, str)
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.is_running = True
    
    def run(self):
        try:
            total_steps = 5  # 5步：BPM、变速、节拍器、首拍对齐、混音
            current_step = 0

            # 步骤1: BPM识别
            if self.is_running:
                self.progress.emit("开始BPM识别...", 0)
                success = self._step1_bpm_detection()
                current_step += 1
                self.step_completed.emit("BPM识别", success)
                if not success:
                    self.finished.emit(False, "BPM识别失败")
                    return
                self.progress.emit("", int(current_step / total_steps * 100))

            # 步骤2: 变速处理
            if self.is_running:
                self.progress.emit("开始变速处理...", int(current_step / total_steps * 100))
                success = self._step2_tempo_shifting()
                current_step += 1
                self.step_completed.emit("变速处理", success)
                if not success:
                    self.finished.emit(False, "变速处理失败")
                    return
                self.progress.emit("", int(current_step / total_steps * 100))

            # 步骤3: 节拍器生成
            if self.is_running:
                self.progress.emit("开始生成节拍器...", int(current_step / total_steps * 100))
                success = self._step3_generate_metronome()
                current_step += 1
                self.step_completed.emit("节拍器生成", success)
                if not success:
                    self.finished.emit(False, "节拍器生成失败")
                    return
                self.progress.emit("", int(current_step / total_steps * 100))

            # 步骤4: 首拍对齐
            if self.is_running:
                self.progress.emit("开始首拍对齐...", int(current_step / total_steps * 100))
                success = self._step4_beat_alignment()
                current_step += 1
                self.step_completed.emit("首拍对齐", success)
                if not success:
                    self.finished.emit(False, "首拍对齐失败")
                    return
                self.progress.emit("", int(current_step / total_steps * 100))

            # 步骤5: 混音
            if self.is_running:
                self.progress.emit("开始混音...", int(current_step / total_steps * 100))
                success = self._step5_mixing()
                current_step += 1
                self.step_completed.emit("混音", success)
                if not success:
                    self.finished.emit(False, "混音失败")
                    return
                self.progress.emit("", 100)

            self.finished.emit(True, "工作流完成!")

        except Exception as e:
            self.finished.emit(False, f"工作流异常: {str(e)}")
    
    def _step1_bpm_detection(self) -> bool:
        """步骤1: BPM识别"""
        try:
            from batch_bpm_detector import BatchBPMDetector

            detector = BatchBPMDetector(
                output_file=self.config['json_output'],
                method=self.config.get('method', 'librosa'),
            )

            # 使用临时文件夹进行BPM识别
            results = detector.analyze_folder(
                self.config['temp_input_folder'],
                verbose=False
            )

            # 加载文件映射
            mapping_file = self.config['file_mapping']
            with open(mapping_file, 'r', encoding='utf-8') as f:
                file_mapping = json.load(f)

            # 更新BPM结果，使用原始文件名
            for result in results:
                temp_name = result.file_name
                if temp_name in file_mapping:
                    original_info = file_mapping[temp_name]
                    result.file_name = original_info['original_name']
                    result.file_path = original_info['original_path']

            # 重新保存更新后的结果
            from dataclasses import asdict
            data = [asdict(r) for r in results]
            with open(self.config['json_output'], 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self.progress.emit(f"BPM识别完成，共 {len(results)} 首", -1)
            return len(results) > 0

        except Exception as e:
            self.progress.emit(f"BPM识别错误: {str(e)}", -1)
            return False
    
    def _step2_tempo_shifting(self) -> bool:
        """步骤2: 变速处理"""
        try:
            from tempo_shifter import TempoShifter
            import json

            # 加载文件映射
            mapping_file = self.config['file_mapping']
            with open(mapping_file, 'r', encoding='utf-8') as f:
                file_mapping = json.load(f)

            # 创建反向映射: 原始文件名 -> 临时文件名
            reverse_mapping = {v['original_name']: k for k, v in file_mapping.items()}

            shifter = TempoShifter(
                target_bpm=self.config['target_bpm'],
                method="librosa"
            )

            # 读取BPM结果
            with open(self.config['json_output'], 'r', encoding='utf-8') as f:
                bpm_data = json.load(f)

            # 处理每首歌曲
            success_count = 0
            output_dir = os.path.join(self.config['output_folder'], 'shifted_songs')
            os.makedirs(output_dir, exist_ok=True)

            for song in bpm_data:
                original_name = song['file_name']
                original_bpm = song['original_bpm']

                # 找到对应的临时文件
                temp_name = reverse_mapping.get(original_name)
                if not temp_name:
                    self.progress.emit(f"  未找到映射: {original_name}", -1)
                    continue

                temp_path = os.path.join(self.config['temp_input_folder'], temp_name)
                if not os.path.exists(temp_path):
                    self.progress.emit(f"  文件不存在: {temp_path}", -1)
                    continue

                # 生成输出文件名（使用原始文件名）
                name_without_ext = os.path.splitext(original_name)[0]
                output_name = f"{name_without_ext}_{self.config['target_bpm']}bpm.wav"

                # 变速处理
                try:
                    result = shifter.process_file(temp_path, original_bpm, output_dir, output_name,
                                                  strict_mode=self.config.get('strict_mode', True))
                    if result.success:
                        success_count += 1
                        # 检测输出文件时长
                        try:
                            import soundfile as sf
                            output_path = os.path.join(output_dir, output_name)
                            info = sf.info(output_path)
                            duration = info.duration
                            self.progress.emit(f"  已变速: {original_name} ({duration:.1f}秒)", -1)
                        except:
                            self.progress.emit(f"  已变速: {original_name}", -1)
                    else:
                        self.progress.emit(f"  变速失败: {original_name}", -1)
                except Exception as e:
                    self.progress.emit(f"  变速错误 {original_name}: {e}", -1)

            self.progress.emit(f"变速处理完成，共 {success_count}/{len(bpm_data)} 首", -1)
            return success_count > 0

        except Exception as e:
            self.progress.emit(f"变速处理错误: {str(e)}", -1)
            return False
    
    def _step3_generate_metronome(self) -> bool:
        """步骤3: 生成节拍器"""
        try:
            from metronome_generator import MetronomeGenerator, MetronomeConfig

            metronome_dir = os.path.join(self.config['output_folder'], 'metronome')
            os.makedirs(metronome_dir, exist_ok=True)

            metronome_bpm = self.config.get('metronome_bpm', 180)
            output_path = os.path.join(metronome_dir, f'metronome_{metronome_bpm}.wav')

            # 如果已存在则跳过
            if os.path.exists(output_path):
                self.progress.emit(f"节拍器已存在: {output_path}", -1)
                return True

            config = MetronomeConfig(
                bpm=metronome_bpm,
                duration=3600,  # 1小时
                beats_per_measure=4
            )

            generator = MetronomeGenerator(config)
            generator.generate(output_path)

            self.progress.emit(f"节拍器生成完成: {metronome_bpm}BPM", -1)
            return True

        except Exception as e:
            self.progress.emit(f"节拍器生成错误: {str(e)}", -1)
            return False

    def _step4_beat_alignment(self) -> bool:
        """步骤4: 首拍对齐检测"""
        try:
            from beat_detector import FirstBeatDetector, BeatAlignmentManager

            shifted_dir = os.path.join(self.config['output_folder'], 'shifted_songs')
            if not os.path.exists(shifted_dir):
                self.progress.emit("未找到变速后的音频文件夹", -1)
                return False

            detector = FirstBeatDetector()
            alignment_manager = BeatAlignmentManager()

            audio_files = []
            for ext in ['.wav', '.mp3', '.flac']:
                audio_files.extend(Path(shifted_dir).glob(f'*{ext}'))

            success_count = 0
            for file_path in sorted(audio_files, key=natural_sort_key):
                try:
                    result = detector.detect(str(file_path))
                    alignment_manager.set_first_beat(str(file_path), result.first_beat_time)
                    success_count += 1
                    self.progress.emit(f"  首拍检测: {file_path.name} @ {result.first_beat_time:.3f}s", -1)
                except Exception as e:
                    self.progress.emit(f"  首拍检测失败: {file_path.name}: {e}", -1)

            self.progress.emit(f"首拍对齐完成，共 {success_count} 首", -1)
            return success_count > 0

        except Exception as e:
            self.progress.emit(f"首拍对齐错误: {str(e)}", -1)
            return False

    def _step5_mixing(self) -> bool:
        """步骤5: 混音"""
        try:
            from audio_mixer import AudioMixer, MixConfig

            config = MixConfig(
                target_loudness=self.config['loudness'],
                metronome_bpm=self.config.get('metronome_bpm', 180),
                metronome_path=self._get_metronome_path(),
                metronome_volume=self.config.get('metronome_volume', -12)
            )

            mixer = AudioMixer(config)
            shifted_dir = os.path.join(self.config['output_folder'], 'shifted_songs')
            return mixer.mix_with_beat_alignment(
                shifted_dir,
                self.config['mix_output']
            )

        except Exception as e:
            self.progress.emit(f"混音错误: {str(e)}", -1)
            return False

    def _get_metronome_path(self) -> Optional[str]:
        """获取节拍器文件路径"""
        metronome_dir = os.path.join(self.config['output_folder'], 'metronome')
        metronome_bpm = self.config.get('metronome_bpm', 180)

        possible_names = [
            f'metronome_{metronome_bpm}.wav',
            f'metronome_{metronome_bpm}.mp3',
            'metronome.wav',
            'metronome.mp3'
        ]

        for name in possible_names:
            path = os.path.join(metronome_dir, name)
            if os.path.exists(path):
                return path
        return None

    def stop(self):
        self.is_running = False

    def _step0_prepare_files(self) -> bool:
        """步骤0: 准备文件 - 拷贝并重命名为数字编号"""
        try:
            import shutil
            from pathlib import Path

            original_folder = self.config['input_folder']
            temp_folder = self.config['temp_input_folder']
            mapping_file = self.config['file_mapping']

            # 确保临时目录存在且为空
            if os.path.exists(temp_folder):
                shutil.rmtree(temp_folder)
            os.makedirs(temp_folder, exist_ok=True)

            # 获取所有音频文件
            audio_extensions = {'.mp3', '.wav', '.flac', '.m4a', '.ogg', '.aac', '.wma'}
            audio_files = []
            for f in os.listdir(original_folder):
                if Path(f).suffix.lower() in audio_extensions:
                    audio_files.append(f)

            audio_files.sort(key=natural_sort_key)

            if not audio_files:
                self.progress.emit("未找到音频文件", -1)
                return False

            # 创建映射关系
            file_mapping = {}
            for idx, original_name in enumerate(audio_files, start=1):
                original_path = os.path.join(original_folder, original_name)
                ext = Path(original_name).suffix
                temp_name = f"{idx}{ext}"
                temp_path = os.path.join(temp_folder, temp_name)

                # 拷贝文件
                shutil.copy2(original_path, temp_path)

                # 保存映射
                file_mapping[temp_name] = {
                    'original_name': original_name,
                    'original_path': original_path,
                    'temp_path': temp_path,
                    'index': idx
                }

                self.progress.emit(f"  已准备: {original_name} -> {temp_name}", -1)

            # 保存映射到JSON
            with open(mapping_file, 'w', encoding='utf-8') as f:
                json.dump(file_mapping, f, ensure_ascii=False, indent=2)

            self.progress.emit(f"文件准备完成，共 {len(audio_files)} 首", -1)
            return True

        except Exception as e:
            self.progress.emit(f"文件准备错误: {str(e)}", -1)
            return False


class WorkflowTab(QWidget):
    """工作流标签页"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.workflow_thread = None
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # 输入设置（使用默认路径）
        input_group = QGroupBox("输入设置")
        input_layout = QVBoxLayout()

        # 输入路径（可编辑）
        input_path_layout = QHBoxLayout()
        input_path_layout.addWidget(QLabel("输入文件夹:"))
        self.input_path_edit = QLineEdit()
        self.input_path_edit.setPlaceholderText("选择或输入音频文件夹路径...")
        input_path_layout.addWidget(self.input_path_edit)

        browse_input_btn = QPushButton("浏览...")
        browse_input_btn.clicked.connect(self.browse_input)
        input_path_layout.addWidget(browse_input_btn)

        auto_input_btn = QPushButton("自动查找")
        auto_input_btn.clicked.connect(self.auto_find_input)
        input_path_layout.addWidget(auto_input_btn)

        input_layout.addLayout(input_path_layout)

        # 输出路径（可编辑）
        output_path_layout = QHBoxLayout()
        output_path_layout.addWidget(QLabel("输出文件夹:"))
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("选择或输入输出文件夹路径...")
        output_path_layout.addWidget(self.output_path_edit)

        browse_output_btn = QPushButton("浏览...")
        browse_output_btn.clicked.connect(self.browse_output)
        output_path_layout.addWidget(browse_output_btn)

        auto_output_btn = QPushButton("自动查找")
        auto_output_btn.clicked.connect(self.auto_find_output)
        output_path_layout.addWidget(auto_output_btn)

        input_layout.addLayout(output_path_layout)

        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        # 初始化路径显示
        self.update_path_display()
        
        # 参数设置（简化版）
        params_group = QGroupBox("处理参数")
        params_layout = QVBoxLayout()

        # 第一行参数
        row1_layout = QHBoxLayout()

        row1_layout.addWidget(QLabel("音频目标BPM:"))
        self.target_bpm = QSpinBox()
        self.target_bpm.setRange(60, 300)
        self.target_bpm.setValue(90)
        row1_layout.addWidget(self.target_bpm)

        row1_layout.addWidget(QLabel("节拍器BPM:"))
        self.metronome_bpm = QSpinBox()
        self.metronome_bpm.setRange(60, 300)
        self.metronome_bpm.setValue(180)
        row1_layout.addWidget(self.metronome_bpm)

        row1_layout.addStretch()
        params_layout.addLayout(row1_layout)

        # 第二行参数
        row2_layout = QHBoxLayout()

        row2_layout.addWidget(QLabel("目标响度(dBFS):"))
        self.loudness = QDoubleSpinBox()
        self.loudness.setRange(-24, -6)
        self.loudness.setValue(-12)
        row2_layout.addWidget(self.loudness)

        row2_layout.addWidget(QLabel("节拍器音量(dB):"))
        self.metronome_volume = QDoubleSpinBox()
        self.metronome_volume.setRange(-30, 0)
        self.metronome_volume.setValue(0)  # 默认0dB
        self.metronome_volume.setSingleStep(1)
        row2_layout.addWidget(self.metronome_volume)
        row2_layout.addWidget(QLabel("(负值表示比音乐小)"))

        row2_layout.addStretch()
        params_layout.addLayout(row2_layout)

        # 第三行 - BPM检测方法
        row3_layout = QHBoxLayout()

        row3_layout.addWidget(QLabel("BPM检测方法:"))
        self.method_combo = QComboBox()
        self.method_combo.addItem("mixxx (精准)", "mixxx")
        self.method_combo.addItem("librosa (快速)", "librosa")
        self.method_combo.setFixedWidth(140)
        row3_layout.addWidget(self.method_combo)

        row3_layout.addStretch()
        params_layout.addLayout(row3_layout)

        # 第四行 - 严格模式
        row4_layout = QHBoxLayout()

        self.strict_mode_check = QCheckBox("严格模式（所有歌曲变速到目标BPM）")
        self.strict_mode_check.setChecked(False)  # 默认不勾选
        row4_layout.addWidget(self.strict_mode_check)

        row4_layout.addStretch()
        params_layout.addLayout(row4_layout)
        
        params_group.setLayout(params_layout)
        layout.addWidget(params_group)
        
        # 进度区域
        progress_group = QGroupBox("执行进度")
        progress_layout = QVBoxLayout()

        # 步骤状态（5步：BPM识别、变速处理、节拍器生成、首拍对齐、混音）
        steps_layout = QHBoxLayout()

        self.step1_label = QLabel("1.BPM识别: 等待中")
        steps_layout.addWidget(self.step1_label)

        steps_layout.addWidget(QLabel("→"))

        self.step2_label = QLabel("2.变速处理: 等待中")
        steps_layout.addWidget(self.step2_label)

        steps_layout.addWidget(QLabel("→"))

        self.step3_label = QLabel("3.节拍器生成: 等待中")
        steps_layout.addWidget(self.step3_label)

        steps_layout.addWidget(QLabel("→"))

        self.step4_label = QLabel("4.首拍对齐: 等待中")
        steps_layout.addWidget(self.step4_label)

        steps_layout.addWidget(QLabel("→"))

        self.step5_label = QLabel("5.混音: 等待中")
        steps_layout.addWidget(self.step5_label)

        steps_layout.addStretch()
        progress_layout.addLayout(steps_layout)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)
        
        # 控制按钮
        btn_layout = QHBoxLayout()

        self.start_btn = QPushButton("开始")
        self.start_btn.clicked.connect(self.start_workflow)
        btn_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self.stop_workflow)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()

    def log(self, message: str):
        """添加日志到主日志区域"""
        if self.parent_window:
            self.parent_window.log_message(message)

    def reset_steps(self):
        """重置步骤状态"""
        self.step1_label.setText("1.BPM识别: 等待中")
        self.step1_label.setStyleSheet("color: #999;")
        self.step2_label.setText("2.变速处理: 等待中")
        self.step2_label.setStyleSheet("color: #999;")
        self.step3_label.setText("3.节拍器生成: 等待中")
        self.step3_label.setStyleSheet("color: #999;")
        self.step4_label.setText("4.首拍对齐: 等待中")
        self.step4_label.setStyleSheet("color: #999;")
        self.step5_label.setText("5.混音: 等待中")
        self.step5_label.setStyleSheet("color: #999;")
        self.progress_bar.setValue(0)

    def start_workflow(self):
        # 使用自定义路径或默认路径
        project_dir = os.path.dirname(os.path.dirname(__file__))
        input_folder = self.input_path_edit.text() or self.get_default_input_path()
        output_folder = self.output_path_edit.text() or self.get_default_output_path()

        if not os.path.exists(input_folder) or not os.listdir(input_folder):
            QMessageBox.warning(self, "警告", "请先导入音频文件（使用'0. 准备音频'标签页）")
            return

        # 重置状态
        self.reset_steps()

        # 准备配置（简化版）
        # 数据文件夹固定不可修改
        data_folder = os.path.join(project_dir, 'data')
        config = {
            'input_folder': input_folder,
            'temp_input_folder': input_folder,
            'output_folder': output_folder,
            'file_mapping': os.path.join(data_folder, 'file_mapping.json'),
            'json_output': os.path.join(data_folder, 'song_bpm_list.json'),
            'mix_output': os.path.join(output_folder, 'final_mix', 'running_mix.wav'),
            'target_bpm': self.target_bpm.value(),
            'metronome_bpm': self.metronome_bpm.value(),
            'metronome_volume': self.metronome_volume.value(),
            'method': self.method_combo.currentData(),
            'loudness': self.loudness.value(),
            'strict_mode': self.strict_mode_check.isChecked()
        }
        
        # 创建工作线程
        self.workflow_thread = WorkflowThread(config)
        self.workflow_thread.progress.connect(self.on_progress)
        self.workflow_thread.step_completed.connect(self.on_step_completed)
        self.workflow_thread.finished.connect(self.on_finished)
        
        # 更新UI
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        # 启动
        self.workflow_thread.start()
        self.log("[工作流] 开始执行...")
    
    def stop_workflow(self):
        if self.workflow_thread:
            self.workflow_thread.stop()
            self.log("[工作流] 用户停止")

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def get_default_input_path(self):
        """获取默认输入路径"""
        project_dir = os.path.dirname(os.path.dirname(__file__))
        return os.path.join(project_dir, 'audio_input')

    def get_default_output_path(self):
        """获取默认输出路径"""
        project_dir = os.path.dirname(os.path.dirname(__file__))
        return os.path.join(project_dir, 'audio_output')

    def update_path_display(self):
        """更新路径显示"""
        if not self.input_path_edit.text():
            self.input_path_edit.setText(self.get_default_input_path())
        if not self.output_path_edit.text():
            self.output_path_edit.setText(self.get_default_output_path())

    def browse_input(self):
        """浏览选择输入文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择音频文件夹")
        if folder:
            self.input_path_edit.setText(folder)
            self.log(f"[工作流] 已选择音频文件夹: {folder}")

    def auto_find_input(self):
        """自动查找默认输入文件夹"""
        default_path = self.get_default_input_path()
        self.input_path_edit.setText(default_path)
        self.log(f"[工作流] 已恢复默认音频文件夹: {default_path}")

    def browse_output(self):
        """浏览选择输出文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if folder:
            self.output_path_edit.setText(folder)
            self.log(f"[工作流] 已选择输出文件夹: {folder}")

    def auto_find_output(self):
        """自动查找默认输出文件夹"""
        default_path = self.get_default_output_path()
        self.output_path_edit.setText(default_path)
        self.log(f"[工作流] 已恢复默认输出文件夹: {default_path}")
    
    def clear_cache(self):
        """手动清理缓存文件"""
        reply = QMessageBox.question(
            self, "确认清理", 
            "确定要清理以下缓存目录吗？\n\n"
            "- audio_input\n"
            "- audio_output/final_mix\n"
            "- audio_output/metronome\n"
            "- audio_output/shifted_songs\n"
            "- data\n\n"
            "此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        try:
            project_dir = os.path.dirname(os.path.dirname(__file__))
            
            cache_dirs = [
                os.path.join(project_dir, 'audio_input'),
                os.path.join(project_dir, 'audio_output', 'final_mix'),
                os.path.join(project_dir, 'audio_output', 'metronome'),
                os.path.join(project_dir, 'audio_output', 'shifted_songs'),
                os.path.join(project_dir, 'data'),
            ]
            
            cleared_count = 0
            for dir_path in cache_dirs:
                if os.path.exists(dir_path):
                    for item in os.listdir(dir_path):
                        item_path = os.path.join(dir_path, item)
                        try:
                            if os.path.isfile(item_path):
                                os.remove(item_path)
                                cleared_count += 1
                            elif os.path.isdir(item_path):
                                shutil.rmtree(item_path)
                                cleared_count += 1
                        except Exception as e:
                            self.log(f"  清理失败 {item}: {e}")
                    self.log(f"已清理: {os.path.basename(dir_path)}")
            
            self.log(f"[缓存清理] 完成，共清理 {cleared_count} 项")
            QMessageBox.information(self, "完成", f"缓存清理完成！\n共清理 {cleared_count} 项")
            
        except Exception as e:
            self.log(f"[缓存清理] 错误: {e}")
            QMessageBox.critical(self, "错误", f"缓存清理失败: {e}")
    
    def on_progress(self, message: str, progress: int):
        """进度更新"""
        if message:
            self.log(message)
        if progress >= 0:
            self.progress_bar.setValue(progress)
    
    def on_step_completed(self, step: str, success: bool):
        """步骤完成"""
        status = "完成" if success else "失败"

        if step == "准备文件":
            self.step0_label.setText(f"0.准备文件: {status}")
        elif step == "BPM识别":
            self.step1_label.setText(f"1.BPM识别: {status}")
        elif step == "变速处理":
            self.step2_label.setText(f"2.变速处理: {status}")
        elif step == "混音":
            self.step3_label.setText(f"3.混音: {status}")

        self.log(f"[工作流] {step} {status}")
    
    def on_finished(self, success: bool, message: str):
        """工作流完成"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        self.log(f"[工作流] {message}")

        if success:
            QMessageBox.information(self, "完成", message)
            # 询问是否清理缓存
            self.ask_clear_cache()
        else:
            QMessageBox.critical(self, "错误", message)

    def ask_clear_cache(self):
        """工作流完成后询问是否清理缓存"""
        reply = QMessageBox.question(
            self, "清理缓存",
            "工作流已完成！\n\n"
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
                self.log("[工作流] 已清理缓存")
            else:
                self.log("[工作流] 无法访问清理功能")
