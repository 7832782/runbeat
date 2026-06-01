#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tab 1 - BPM 识别标签页

功能:
    1. 选择 BPM 检测方法: mixxx（高精度，需额外安装）或 librosa（纯 Python 回退）
    2. 批量分析 audio_input/ 中的所有音频文件
    3. 以表格展示结果: 文件名 / BPM / 检测方法 / 置信度
    4. 双击 BPM 单元格可手动修正数值（自动保存到 data/song_bpm_list.json）
    5. 自动加载 file_mapping.json，将临时文件名还原为原始文件名显示

使用流程:
    先在 Tab 0（准备音频）中导入文件 → 切换到本标签页 → 点击"开始识别BPM"

依赖:
    modules/batch_bpm_detector.py → BatchBPMDetector
    data/file_mapping.json（可选，用于文件名还原）
"""

import os
import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QMessageBox, QComboBox, QSpinBox, QTableWidget,
    QTableWidgetItem, QDoubleSpinBox, QAbstractItemView, QHeaderView
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


class BPMDetectorTab(QWidget):
    """BPM识别标签页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 输入设置（使用默认路径）
        input_group = QGroupBox("输入设置")
        input_layout = QVBoxLayout()

        project_dir = os.path.dirname(os.path.dirname(__file__))
        default_input = os.path.join(project_dir, 'audio_input')
        path_label = QLabel(f"音频文件夹: {default_input}")
        path_label.setStyleSheet("color: #999;")
        input_layout.addWidget(path_label)

        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        # 参数设置
        params_group = QGroupBox("识别参数")
        params_layout = QHBoxLayout()

        # 检测方法选择
        params_layout.addWidget(QLabel("检测方法:"))
        self.method_combo = QComboBox()
        self.method_combo.addItem("mixxx (精准)", "mixxx")
        self.method_combo.addItem("librosa (快速)", "librosa")
        self.method_combo.currentIndexChanged.connect(self.on_method_changed)
        params_layout.addWidget(self.method_combo)

        params_layout.addSpacing(20)

        # librosa参数（默认隐藏）
        self.num_samples_label = QLabel("采样次数:")
        params_layout.addWidget(self.num_samples_label)
        self.num_samples = QSpinBox()
        self.num_samples.setRange(1, 10)
        self.num_samples.setValue(3)
        params_layout.addWidget(self.num_samples)

        self.sample_duration_label = QLabel("采样时长(秒):")
        params_layout.addWidget(self.sample_duration_label)
        self.sample_duration = QSpinBox()
        self.sample_duration.setRange(5, 60)
        self.sample_duration.setValue(30)
        params_layout.addWidget(self.sample_duration)

        # 默认选择mixxx，隐藏采样参数
        self.num_samples_label.setVisible(False)
        self.num_samples.setVisible(False)
        self.sample_duration_label.setVisible(False)
        self.sample_duration.setVisible(False)

        params_layout.addStretch()
        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

        # 操作按钮
        btn_layout = QHBoxLayout()

        self.analyze_btn = QPushButton("开始识别BPM")
        self.analyze_btn.clicked.connect(self.start_analysis)
        btn_layout.addWidget(self.analyze_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 结果显示
        result_group = QGroupBox("识别结果 (双击BPM可手动修改)")
        result_layout = QVBoxLayout()

        # 使用表格显示结果，支持编辑BPM
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(4)
        self.result_table.setHorizontalHeaderLabels(["文件名", "BPM", "方法", "置信度"])
        self.result_table.setMinimumHeight(200)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.result_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.result_table.itemChanged.connect(self.on_bpm_changed)
        # 表头铺满设置
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        result_layout.addWidget(self.result_table)

        result_group.setLayout(result_layout)
        layout.addWidget(result_group)

        layout.addStretch()

        # 存储当前结果数据
        self.current_results = []
        self._is_saving = False  # 防止递归保存

    def on_method_changed(self, index):
        """检测方法改变时更新UI"""
        method = self.method_combo.currentData()
        if method == "librosa":
            self.num_samples_label.setVisible(True)
            self.num_samples.setVisible(True)
            self.sample_duration_label.setVisible(True)
            self.sample_duration.setVisible(True)
        else:  # mixxx
            self.num_samples_label.setVisible(False)
            self.num_samples.setVisible(False)
            self.sample_duration_label.setVisible(False)
            self.sample_duration.setVisible(False)

    def start_analysis(self):
        # 使用默认路径
        project_dir = os.path.dirname(os.path.dirname(__file__))
        input_folder = os.path.join(project_dir, 'audio_input')

        if not os.path.exists(input_folder) or not os.listdir(input_folder):
            QMessageBox.warning(self, "警告", "请先导入音频文件（使用'0. 准备音频'标签页）")
            return

        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText("识别中...")
        self.result_table.setRowCount(0)
        self.current_results = []
        self.bpm_modified = False

        if self.parent_window:
            self.parent_window.log_message(f"[BPM识别] 开始分析文件夹: {input_folder}")

        output_file = os.path.join(project_dir, "data", "song_bpm_list.json")
        method = self.method_combo.currentData()
        detector_kwargs = {"method": method}
        if method == "librosa":
            detector_kwargs["num_samples"] = self.num_samples.value()
            detector_kwargs["sample_duration"] = self.sample_duration.value()

        self.bpm_worker = WorkerThread(
            self._run_bpm_detection, input_folder, output_file, method, detector_kwargs
        )
        self.bpm_worker.finished.connect(self._on_bpm_finished)
        self.bpm_worker.start()

    @staticmethod
    def _run_bpm_detection(input_folder, output_file, method, detector_kwargs):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'modules'))
        from batch_bpm_detector import BatchBPMDetector
        detector = BatchBPMDetector(output_file=output_file, **detector_kwargs)
        return detector.analyze_folder(input_folder, verbose=False)

    def _on_bpm_finished(self, success, message):
        self.analyze_btn.setEnabled(True)
        self.analyze_btn.setText("开始识别BPM")

        if not success:
            QMessageBox.critical(self, "错误", f"BPM识别失败: {message}")
            if self.parent_window:
                self.parent_window.log_message(f"[BPM识别] 错误: {message}")
            return

        results = self.bpm_worker.result if self.bpm_worker else []
        self.current_results = results
        self.bpm_modified = False
        method = self.method_combo.currentData()

        # 加载文件映射，转换文件名
        file_mapping = self._load_file_mapping()

        # 使用表格显示结果
        self.result_table.setRowCount(len(results))
        for row, result in enumerate(results):
            # 使用原始文件名显示
            display_name = result.file_name
            temp_name = result.file_name
            if temp_name in file_mapping:
                display_name = file_mapping[temp_name]['original_name']

            # 文件名（不可编辑）
            name_item = QTableWidgetItem(display_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.result_table.setItem(row, 0, name_item)

            # BPM（可编辑）
            bpm_item = QTableWidgetItem(f"{result.original_bpm:.1f}")
            bpm_item.setData(Qt.ItemDataRole.UserRole, row)  # 存储行索引
            self.result_table.setItem(row, 1, bpm_item)

            # 方法（不可编辑）
            method_item = QTableWidgetItem(result.method)
            method_item.setFlags(method_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.result_table.setItem(row, 2, method_item)

            # 置信度（不可编辑）
            conf_item = QTableWidgetItem(f"{result.confidence:.0%}")
            conf_item.setFlags(conf_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.result_table.setItem(row, 3, conf_item)

        # 表头已设置为自动铺满，无需手动调整列宽

        if self.parent_window:
            self.parent_window.log_message(f"[BPM识别] 完成，识别了 {len(results)} 首歌曲 (方法: {method})")
            self.parent_window.update_song_list()

        QMessageBox.information(self, "完成", f"成功识别 {len(results)} 首歌曲的BPM\n方法: {method}\n\n提示：双击BPM数值可以手动修改")

    def on_bpm_changed(self, item):
        """BPM数值被修改时调用 - 实时保存"""
        if item.column() != 1:  # 只处理BPM列
            return

        # 防止递归保存
        if self._is_saving:
            return

        try:
            new_bpm = float(item.text())
            row = item.row()

            if 40 <= new_bpm <= 300:  # 合理的BPM范围
                # 更新数据
                self.current_results[row].original_bpm = new_bpm

                # 实时保存
                self._save_to_json()

                if self.parent_window:
                    file_name = self.current_results[row].file_name
                    self.parent_window.log_message(f"[BPM识别] 已修改并保存: {file_name} BPM -> {new_bpm:.1f}")
                    self.parent_window.update_song_list()
            else:
                # 恢复原来的值
                item.setText(f"{self.current_results[row].original_bpm:.1f}")
                QMessageBox.warning(self, "警告", "BPM必须在40-300之间")
        except ValueError:
            # 恢复原来的值
            row = item.row()
            item.setText(f"{self.current_results[row].original_bpm:.1f}")
            QMessageBox.warning(self, "警告", "请输入有效的数字")

    def _save_to_json(self):
        """保存当前结果到JSON文件"""
        if not self.current_results:
            return

        self._is_saving = True
        try:
            project_dir = os.path.dirname(os.path.dirname(__file__))
            output_file = os.path.join(project_dir, "data", "song_bpm_list.json")

            # 构建保存数据
            data = []
            for result in self.current_results:
                data.append({
                    "file_name": result.file_name,
                    "file_path": result.file_path,
                    "original_bpm": result.original_bpm,
                    "method": result.method,
                    "confidence": result.confidence
                })

            # 保存到JSON
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            print(f"保存失败: {e}")
        finally:
            self._is_saving = False

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
                self.parent_window.log_message(f"[BPM识别] 加载文件映射失败: {e}")
        return {}
