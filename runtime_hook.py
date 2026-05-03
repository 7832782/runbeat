#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyInstaller 运行时钩子

解决打包后的路径问题
"""

import os
import sys


def runtime_hook():
    """设置运行时路径"""
    # 获取可执行文件所在目录
    if getattr(sys, 'frozen', False):
        # 打包后的环境
        base_dir = os.path.dirname(sys.executable)
    else:
        # 开发环境
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 设置工作目录
    os.chdir(base_dir)
    
    # 添加模块搜索路径
    sys.path.insert(0, base_dir)
    
    # 设置环境变量
    os.environ['RUNBEAT_BASE_DIR'] = base_dir


# 执行钩子
runtime_hook()
