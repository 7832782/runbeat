#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyInstaller 运行时钩子 (Runtime Hook)

当 RunBeat 被 PyInstaller 打包成 .exe 后，程序的文件系统和模块路径
与开发环境不同。此钩子在程序启动时被 PyInstaller 调用，用于：
1. 识别当前运行环境（开发 vs 打包后）
2. 设置正确的工作目录到可执行文件所在目录
3. 添加模块搜索路径，确保打包后的模块能被找到
4. 设置 RUNBEAT_BASE_DIR 环境变量供其他模块使用
"""

import os
import sys


def runtime_hook():
    """设置运行时路径，适配开发环境和打包后环境"""
    # sys.frozen 是 PyInstaller 设置的标志：
    # - 打包后：sys.frozen = True，此时 sys.executable 指向 .exe 文件路径
    # - 开发环境：sys.frozen 不存在或为 False
    if getattr(sys, 'frozen', False):
        # 打包后的环境：工作目录 = 可执行文件所在目录
        base_dir = os.path.dirname(sys.executable)
    else:
        # 开发环境：工作目录 = 当前脚本所在目录
        base_dir = os.path.dirname(os.path.abspath(__file__))

    # 切换到正确的根目录，确保相对路径（如 audio_input/, data/）正常工作
    os.chdir(base_dir)

    # 将根目录加入搜索路径，确保模块导入不受打包路径影响
    sys.path.insert(0, base_dir)

    # 设置环境变量，方便其他模块在需要时获取根目录
    os.environ['RUNBEAT_BASE_DIR'] = base_dir


# 模块被导入时立即执行钩子
runtime_hook()
