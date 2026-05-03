#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RunBeat GUI 启动脚本

使用方法:
    python run_gui.py
"""

import sys
import os

# 确保可以导入gui模块
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
