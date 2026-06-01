#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RunBeat PyInstaller 打包脚本（完整版）

使用 PyInstaller 将 RunBeat 打包成独立的 Windows 可执行文件（onedir 模式）。

功能:
    1. 清理旧构建文件（build/, dist/, *.spec）
    2. 自动检测并安装 PyInstaller
    3. 执行打包（--onedir 模式，包含所有数据目录和隐藏导入）
    4. 复制额外文件（README.md, requirements.txt）
    5. 创建启动批处理文件（启动 RunBeat.bat）

使用方法:
    python build_exe.py

打包完成后:
    可执行文件: dist/RunBeat/RunBeat.exe
    运行方式: 双击"启动 RunBeat.bat"或直接运行 RunBeat.exe

注意:
    - 首次运行可能需要等待解压（PyInstaller 会将文件解压到临时目录）
    - 目标电脑需安装 FFmpeg（用于音频格式转换）
    - 完整版包含所有 hidden-imports，打包体积较大但兼容性更好
"""

import os
import sys
import shutil
import subprocess


def clean_build():
    """清理之前的构建文件"""
    print("清理之前的构建文件...")
    dirs_to_remove = ['build', 'dist']
    for dir_name in dirs_to_remove:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"  已删除: {dir_name}/")
    
    # 删除 .spec 文件
    for file in os.listdir('.'):
        if file.endswith('.spec'):
            os.remove(file)
            print(f"  已删除: {file}")


def install_pyinstaller():
    """检查并安装 PyInstaller"""
    try:
        import PyInstaller
        print("PyInstaller 已安装")
        return True
    except ImportError:
        print("正在安装 PyInstaller...")
        try:
            subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'], check=True)
            print("PyInstaller 安装完成")
            return True
        except subprocess.CalledProcessError as e:
            print(f"安装失败: {e}")
            return False


def build_exe():
    """使用 PyInstaller 打包"""
    print("\n开始打包 RunBeat...")
    
    # PyInstaller 命令参数
    cmd = [
        'pyinstaller',
        '--name=RunBeat',
        '--windowed',  # 使用 GUI 模式，不显示控制台
        '--onefile',   # 打包成单个文件（可选，如果要单文件）
        # '--onedir',  # 打包成目录（推荐，启动更快）
        '--onedir',
        
        # 添加数据文件
        '--add-data=audio_input;audio_input',
        '--add-data=audio_output;audio_output',
        '--add-data=data;data',
        '--add-data=tools;tools',
        
        # 隐藏导入（PyQt6 需要）
        '--hidden-import=PyQt6.sip',
        '--hidden-import=PyQt6.QtCore',
        '--hidden-import=PyQt6.QtGui',
        '--hidden-import=PyQt6.QtWidgets',
        
        # 其他隐藏导入
        '--hidden-import=numpy',
        '--hidden-import=librosa',
        '--hidden-import=soundfile',
        '--hidden-import=sounddevice',
        '--hidden-import=pydub',
        
        # 图标（如果有的话）
        # '--icon=assets/icon.ico',
        
        # 运行时钩子
        '--runtime-hook=runtime_hook.py',
        
        # 主程序入口
        'run_gui.py'
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print("\n✅ 打包成功！")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 打包失败: {e}")
        return False


def copy_additional_files():
    """复制额外文件到输出目录"""
    dist_dir = os.path.join('dist', 'RunBeat')
    
    if not os.path.exists(dist_dir):
        print(f"错误: 找不到输出目录 {dist_dir}")
        return False
    
    print("\n复制额外文件...")
    
    # 创建必要的目录
    dirs_to_create = [
        os.path.join(dist_dir, 'audio_input'),
        os.path.join(dist_dir, 'audio_output', 'metronome'),
        os.path.join(dist_dir, 'audio_output', 'shifted_songs'),
        os.path.join(dist_dir, 'audio_output', 'final_mix'),
        os.path.join(dist_dir, 'data'),
    ]
    
    for dir_path in dirs_to_create:
        os.makedirs(dir_path, exist_ok=True)
        print(f"  创建目录: {dir_path}")
    
    # 复制 README
    if os.path.exists('README.md'):
        shutil.copy('README.md', dist_dir)
        print(f"  复制: README.md")
    
    # 复制 requirements.txt
    if os.path.exists('requirements.txt'):
        shutil.copy('requirements.txt', dist_dir)
        print(f"  复制: requirements.txt")
    
    return True


def create_batch_file():
    """创建启动批处理文件"""
    dist_dir = os.path.join('dist', 'RunBeat')
    batch_path = os.path.join(dist_dir, '启动 RunBeat.bat')
    
    with open(batch_path, 'w', encoding='utf-8') as f:
        f.write('@echo off\n')
        f.write('chcp 65001 >nul\n')  # 设置 UTF-8 编码
        f.write('echo 正在启动 RunBeat...\n')
        f.write('start "" "RunBeat.exe"\n')
    
    print(f"  创建: 启动 RunBeat.bat")


def main():
    """主函数"""
    print("=" * 60)
    print("RunBeat 打包工具")
    print("=" * 60)
    
    # 检查是否在正确的目录
    if not os.path.exists('run_gui.py'):
        print("错误: 请在 runbeat 项目根目录运行此脚本")
        print("当前目录:", os.getcwd())
        return 1
    
    # 清理旧构建
    clean_build()
    
    # 安装 PyInstaller
    if not install_pyinstaller():
        return 1
    
    # 打包
    if not build_exe():
        return 1
    
    # 复制额外文件
    if not copy_additional_files():
        return 1
    
    # 创建启动脚本
    create_batch_file()
    
    print("\n" + "=" * 60)
    print("打包完成！")
    print("=" * 60)
    print(f"\n输出目录: dist/RunBeat/")
    print(f"可执行文件: dist/RunBeat/RunBeat.exe")
    print(f"\n使用方法:")
    print(f"  1. 将整个 dist/RunBeat/ 文件夹复制到目标位置")
    print(f"  2. 运行 '启动 RunBeat.bat' 或直接运行 RunBeat.exe")
    print(f"\n注意:")
    print(f"  - 首次运行可能需要等待解压")
    print(f"  - 确保目标电脑已安装 FFmpeg")
    print("=" * 60)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
