#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RunBeat PyInstaller 打包脚本（简化版）

相比 build_exe.py 的简化版本，hidden-imports 更少，打包速度更快。

使用方法:
    1. 安装 PyInstaller: pip install pyinstaller
    2. 运行: python build_simple.py
    3. 等待打包完成

参数说明:
    --windowed    GUI 模式，不显示控制台窗口
    --onedir      打包为目录（启动更快，推荐）
    --clean       清理 PyInstaller 缓存
    --noconfirm   跳过确认提示，覆盖已有输出

输出:
    dist/RunBeat/ 文件夹，包含 RunBeat.exe 和所有依赖

与 build_exe.py 的区别:
    - hidden-imports 更少（仅 PyQt6.sip 和 numpy.core._dtype_ctypes）
    - 无运行时钩子
    - 无额外文件复制和批处理文件生成
    - 打包更快但可能缺少某些隐式依赖
"""

import os
import sys
import subprocess


def main():
    print("=" * 60)
    print("RunBeat 打包工具")
    print("=" * 60)
    
    # 检查 pyinstaller
    try:
        import PyInstaller
    except ImportError:
        print("正在安装 PyInstaller...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'], check=True)
    
    print("\n开始打包...")
    print("这可能需要几分钟时间，请耐心等待...\n")
    
    # 简单的打包命令
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name=RunBeat',
        '--windowed',
        '--onedir',
        '--clean',
        '--noconfirm',
        
        # 添加数据目录
        '--add-data=audio_input;audio_input',
        '--add-data=audio_output;audio_output', 
        '--add-data=data;data',
        '--add-data=tools;tools',
        
        # 隐藏导入
        '--hidden-import=PyQt6.sip',
        '--hidden-import=numpy.core._dtype_ctypes',
        
        # 主程序
        'run_gui.py'
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print("\n" + "=" * 60)
        print("✅ 打包成功！")
        print("=" * 60)
        print(f"\n输出位置: dist/RunBeat/")
        print(f"运行方式: 双击 dist/RunBeat/RunBeat.exe")
        print(f"\n提示:")
        print(f"  - 将整个 dist/RunBeat/ 文件夹复制到其他电脑即可使用")
        print(f"  - 确保目标电脑已安装 FFmpeg")
        print("=" * 60)
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 打包失败: {e}")
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
