#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tab 2 - 变速不变调处理标签页

功能:
    1. 加载 data/song_bpm_list.json，展示每首歌的原 BPM 和变速后 BPM
    2. 设置目标 BPM（跑步推荐 160-190）
    3. 严格模式: 所有歌曲变速到精确目标 BPM
       非严格模式: 找目标 BPM 的最接近因数（如 180 → 90 / 60），
       使变速比例最小化，减少音质损失
    4. 批量处理，输出到 audio_output/shifted_songs/
    5. 自动加载 file_mapping.json 显示原始文件名

变速比例计算:
    rate = 目标BPM / 原始BPM
    例: 原 120BPM → 目标 180BPM → rate = 1.5 (加速 50%)

依赖:
    modules/tempo_shifter.py → TempoShifter（librosa.effects.time_stretch 相位声码器）
"""

import os
import json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QMessageBox, QLineEdit, QSpinBox, QFileDialog,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal


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


class TempoShiftTab(QWidget):
    """变速处理标签页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # JSON文件选择
        json_group = QGroupBox("BPM数据文件")
        json_layout = QHBoxLayout()

        self.json_path = QLineEdit()
        self.json_path.setPlaceholderText("song_bpm_list.json 路径...")
        json_layout.addWidget(self.json_path)

        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_json)
        json_layout.addWidget(browse_btn)

        auto_btn = QPushButton("自动查找")
        auto_btn.clicked.connect(self.auto_find_json)
        json_layout.addWidget(auto_btn)

        json_group.setLayout(json_layout)
        layout.addWidget(json_group)

        # 参数设置
        params_group = QGroupBox("变速参数")
        params_layout = QVBoxLayout()

        # 目标BPM
        bpm_layout = QHBoxLayout()
        bpm_layout.addWidget(QLabel("目标BPM:"))
        self.target_bpm = QSpinBox()
        self.target_bpm.setRange(60, 300)
        self.target_bpm.setValue(180)
        bpm_layout.addWidget(self.target_bpm)
        bpm_layout.addStretch()
        params_layout.addLayout(bpm_layout)

        # 严格模式选项
        self.strict_mode_check = QCheckBox("严格模式（变速到精确的目标BPM）")
        self.strict_mode_check.setChecked(False)  # 默认不勾选（非严格模式）
        self.strict_mode_check.setToolTip(
            "严格模式：所有歌曲变速到精确的目标BPM\n"
            "非严格模式：变速到目标BPM的因数，使变化幅度最小\n"
            "例如：原BPM=95，目标BPM=180，非严格模式会变速到90（180/2）"
        )
        params_layout.addWidget(self.strict_mode_check)

        # 输出目录
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("输出目录:"))
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("audio_output...")
        output_layout.addWidget(self.output_path)

        out_browse_btn = QPushButton("浏览...")
        out_browse_btn.clicked.connect(self.browse_output)
        output_layout.addWidget(out_browse_btn)
        params_layout.addLayout(output_layout)

        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

        # 歌曲列表
        songs_group = QGroupBox("待处理歌曲")
        songs_layout = QVBoxLayout()

        self.songs_table = QTableWidget()
        self.songs_table.setColumnCount(3)
        self.songs_table.setHorizontalHeaderLabels(["歌曲名", "原BPM", "变速后BPM"])
        self.songs_table.setMinimumHeight(150)
        # 表头铺满设置
        self.songs_table.horizontalHeader().setStretchLastSection(True)
        self.songs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        songs_layout.addWidget(self.songs_table)

        load_btn = QPushButton("加载歌曲列表")
        load_btn.clicked.connect(self.load_songs)
        songs_layout.addWidget(load_btn)

        songs_group.setLayout(songs_layout)
        layout.addWidget(songs_group)

        # 处理按钮
        btn_layout = QHBoxLayout()

        self.process_btn = QPushButton("开始变速处理")
        self.process_btn.clicked.connect(self.start_processing)
        btn_layout.addWidget(self.process_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()

    def browse_json(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择JSON文件", "", "JSON files (*.json)"
        )
        if file_path:
            self.json_path.setText(file_path)

    def auto_find_json(self):
        project_dir = os.path.dirname(os.path.dirname(__file__))
        json_path = os.path.join(project_dir, "data", "song_bpm_list.json")
        if os.path.exists(json_path):
            self.json_path.setText(json_path)
            self.load_songs()
        else:
            QMessageBox.warning(self, "警告", "未找到 song_bpm_list.json")

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if folder:
            self.output_path.setText(folder)

    def load_songs(self):
        json_path = self.json_path.text()
        if not json_path or not os.path.exists(json_path):
            QMessageBox.warning(self, "警告", "请先选择有效的JSON文件")
            return

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                songs = json.load(f)

            # 加载文件映射
            file_mapping = self._load_file_mapping()

            # 清空表格
            self.songs_table.setRowCount(0)

            # 计算非严格模式下的实际目标BPM
            target_bpm = self.target_bpm.value()
            strict_mode = self.strict_mode_check.isChecked()

            for row, song in enumerate(songs):
                self.songs_table.insertRow(row)

                # 使用原始文件名显示
                temp_name = song['file_name']
                display_name = temp_name
                if temp_name in file_mapping:
                    display_name = file_mapping[temp_name]['original_name']

                # 歌曲名
                name_item = QTableWidgetItem(display_name)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.songs_table.setItem(row, 0, name_item)

                # 原BPM
                original_bpm = song['original_bpm']
                original_item = QTableWidgetItem(f"{original_bpm:.1f}")
                original_item.setFlags(original_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.songs_table.setItem(row, 1, original_item)

                # 变速后BPM（根据是否严格模式计算）
                if strict_mode:
                    shifted_bpm = target_bpm
                else:
                    # 非严格模式：找最优目标BPM
                    shifted_bpm = self._calculate_optimal_bpm(original_bpm, target_bpm)

                shifted_item = QTableWidgetItem(f"{shifted_bpm:.1f}")
                shifted_item.setFlags(shifted_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.songs_table.setItem(row, 2, shifted_item)

            if self.parent_window:
                self.parent_window.log_message(f"[变速处理] 加载了 {len(songs)} 首歌曲")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载失败: {str(e)}")

    def _calculate_optimal_bpm(self, original_bpm: float, target_bpm: int) -> float:
        """计算非严格模式下的最优目标BPM"""
        candidates = set()
        candidates.add(target_bpm)

        # 添加目标BPM的因数
        for divisor in range(2, 9):
            candidate = target_bpm / divisor
            if candidate >= 40:
                candidates.add(candidate)

        # 添加目标BPM的倍数
        candidates.add(target_bpm * 2)

        candidates = sorted(list(candidates))

        # 找变化幅度最小的
        best_candidate = target_bpm
        min_change_ratio = abs(original_bpm - target_bpm) / original_bpm

        for candidate in candidates:
            change_ratio = abs(original_bpm - candidate) / original_bpm
            if change_ratio < min_change_ratio:
                min_change_ratio = change_ratio
                best_candidate = candidate

        return best_candidate

    def _load_file_mapping(self) -> dict:
        """加载文件映射"""
        try:
            project_dir = os.path.dirname(os.path.dirname(__file__))
            mapping_file = os.path.join(project_dir, 'data', 'file_mapping.json')
            if os.path.exists(mapping_file):
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            if self.parent_window:
                self.parent_window.log_message(f"[变速处理] 加载文件映射失败: {e}")
        return {}

    def start_processing(self):
        json_path = self.json_path.text()
        if not json_path or not os.path.exists(json_path):
            QMessageBox.warning(self, "警告", "请选择有效的JSON文件")
            return

        output_dir = self.output_path.text()
        if not output_dir:
            project_dir = os.path.dirname(os.path.dirname(__file__))
            output_dir = os.path.join(project_dir, "audio_output", "shifted_songs")

        self.process_btn.setEnabled(False)
        self.process_btn.setText("处理中...")

        strict_mode = self.strict_mode_check.isChecked()

        self.tempo_worker = WorkerThread(
            self._run_tempo_shifting,
            json_path, output_dir, self.target_bpm.value(), strict_mode
        )
        self.tempo_worker.finished.connect(self._on_tempo_finished)
        self.tempo_worker.start()

    @staticmethod
    def _run_tempo_shifting(json_path, output_dir, target_bpm, strict_mode):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'modules'))
        from tempo_shifter import TempoShifter
        shifter = TempoShifter(target_bpm=target_bpm, method="librosa")
        return shifter.process_from_json(json_path, output_dir, strict_mode=strict_mode)

    def _on_tempo_finished(self, success, message):
        self.process_btn.setEnabled(True)
        self.process_btn.setText("开始变速处理")

        if not success:
            QMessageBox.critical(self, "错误", f"处理失败: {message}")
            return

        results = self.tempo_worker.result if self.tempo_worker else []
        success_count = sum(1 for r in results if r.success)

        if self.parent_window:
            self.parent_window.log_message(f"[变速处理] 完成: {success_count}/{len(results)} 成功")

        QMessageBox.information(
            self, "完成",
            f"处理完成!\n成功: {success_count}/{len(results)}"
        )
