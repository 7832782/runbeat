#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RunBeat GUI 主窗口 (MainWindow)

基于 PyQt6 的桌面应用主界面，负责：
1. 创建 QTabWidget 容器，按顺序加载 7 个功能标签页（Tab 0-5 + 一键工作流）
2. 提供通用日志面板（QTextEdit）和状态栏
3. 管理全局样式（Fusion 主题 + Microsoft YaHei 字体）
4. 协调跨标签页通信（如 BPM 识别完成后自动刷新变速标签页的歌曲列表）

标签页加载策略:
    每个标签页通过 try/except 导入，即使某个模块缺失也不会导致整个应用崩溃

类:
    WorkerThread  通用后台工作线程，避免阻塞 UI
    MainWindow    QMainWindow 主窗口

完整工作流:
    Tab 0 准备音频 → Tab 1 BPM识别 → Tab 2 变速处理
    → Tab 3 节拍器生成 → Tab 4 首拍对齐 → Tab 5 混音
    或使用"一键工作流"标签页自动串联所有步骤
"""

import sys
import os

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTabWidget, QGroupBox, QTextEdit, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

# 添加模块路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'modules'))

# 导入各个标签页
try:
    from prepare_audio_tab import PrepareAudioTab
except ImportError:
    PrepareAudioTab = None

try:
    from workflow_tab import WorkflowTab
except ImportError:
    WorkflowTab = None

try:
    from bpm_detector_tab import BPMDetectorTab
except ImportError:
    BPMDetectorTab = None

try:
    from tempo_shift_tab import TempoShiftTab
except ImportError:
    TempoShiftTab = None

try:
    from metronome_tab import MetronomeTab
except ImportError:
    MetronomeTab = None

try:
    from beat_align_tab import BeatAlignTab
except ImportError:
    BeatAlignTab = None

try:
    from mixing_tab import MixingTab
except ImportError:
    MixingTab = None


class WorkerThread(QThread):
    """通用工作线程"""
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


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RunBeat - 跑步音乐BPM适配工具")
        self.setMinimumSize(900, 700)

        self.init_ui()
        self.setup_styles()

    def init_ui(self):
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)

        # 标题
        title_label = QLabel("RunBeat - 跑步音乐BPM适配工具")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))
        main_layout.addWidget(title_label)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(2)
        main_layout.addWidget(line)

        # 创建分割器
        from PyQt6.QtWidgets import QSplitter
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 标签页
        self.tabs = QTabWidget()

        # 添加各个标签页
        # 0. 准备音频
        if PrepareAudioTab:
            self.prepare_tab = PrepareAudioTab(self)
            self.tabs.addTab(self.prepare_tab, "0. 准备音频")

        # 一键工作流
        if WorkflowTab:
            self.workflow_tab = WorkflowTab(self)
            self.tabs.addTab(self.workflow_tab, "一键工作流")

        # 1. BPM识别
        if BPMDetectorTab:
            self.bpm_tab = BPMDetectorTab(self)
            self.tabs.addTab(self.bpm_tab, "1. BPM识别")

        # 2. 变速处理
        if TempoShiftTab:
            self.tempo_tab = TempoShiftTab(self)
            self.tabs.addTab(self.tempo_tab, "2. 变速处理")

        # 3. 节拍器
        if MetronomeTab:
            self.metronome_tab = MetronomeTab(self)
            self.tabs.addTab(self.metronome_tab, "3. 节拍器")

        # 4. 首拍对齐
        if BeatAlignTab:
            self.beat_align_tab = BeatAlignTab(self)
            self.tabs.addTab(self.beat_align_tab, "4. 首拍对齐")

        # 5. 混音
        if MixingTab:
            self.mixer_tab = MixingTab(self)
            self.tabs.addTab(self.mixer_tab, "5. 混音")

        splitter.addWidget(self.tabs)

        # 日志区域
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setPlaceholderText("运行日志将显示在这里...")
        log_layout.addWidget(self.log_text)

        log_group.setLayout(log_layout)
        splitter.addWidget(log_group)

        # 设置分割器比例
        splitter.setSizes([500, 150])

        main_layout.addWidget(splitter)

        # 状态栏
        self.statusBar().showMessage("就绪")

        # 欢迎信息
        self.log_message("[系统] RunBeat 已启动")
        self.log_message("[系统] 请按顺序使用各个标签页完成音乐制作")

    def setup_styles(self):
        """设置样式表 - 使用系统默认样式，只做最小化调整"""
        # 只设置标签页样式，其他使用系统默认
        self.setStyleSheet("""
            QTabBar::tab {
                padding: 10px 20px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #2196F3;
                color: white;
            }
        """)

    def log_message(self, message: str):
        """添加日志消息"""
        self.log_text.append(message)
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def update_song_list(self):
        """更新歌曲列表（从BPM识别后）"""
        # 自动切换到变速处理标签页并加载歌曲
        import json
        project_dir = os.path.dirname(os.path.dirname(__file__))
        json_path = os.path.join(project_dir, "data", "song_bpm_list.json")
        if os.path.exists(json_path) and hasattr(self, 'tempo_tab'):
            self.tempo_tab.json_path.setText(json_path)
            self.tempo_tab.load_songs()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # 设置应用字体
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
