#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RunBeat GUI 启动脚本

RunBeat 是一个跑步音乐BPM适配工具，通过 BPM 识别 → 变速处理 → 首拍对齐 → 混音
的完整流程，将任意音乐转换为适合跑步节奏的音频。

使用方法:
    python run_gui.py

依赖:
    - PyQt6: 图形界面框架
    - librosa: 音频分析
    - pydub: 音频处理
    - soundfile / sounddevice: 音频I/O
    - mixxx-analyzer: 高精度BPM检测(可选)
"""

import sys
import os

# 将 gui/ 子目录添加到 Python 搜索路径中，
# 使得可以直接 import gui 包下的模块（如 main_window）
current_dir = os.path.dirname(os.path.abspath(__file__))
gui_dir = os.path.join(current_dir, 'gui')
sys.path.insert(0, gui_dir)

try:
    from main_window import main
    main()
except ImportError as e:
    print(f"错误: 无法导入GUI模块 - {e}")
    print("请确保已安装PyQt6: pip install PyQt6")
    sys.exit(1)
except Exception as e:
    print(f"错误: {e}")
    sys.exit(1)
