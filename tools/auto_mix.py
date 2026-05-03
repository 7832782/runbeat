#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Audacity 自动混音脚本

根据 RunBeat 导出的对齐信息 CSV 文件，自动在 Audacity 中导入并排列音频轨道。

使用方法：
    1. 在 RunBeat 中导出对齐信息（生成 CSV 文件）
    2. 打开 Audacity 并启用 mod-script-pipe
    3. 运行: python auto_mix.py

依赖：
    - Audacity (已安装 mod-script-pipe 模块)
    - FFmpeg
    - pipeclient.py

作者: RunBeat Project
"""

import csv
import os
import subprocess
import tempfile
import glob
import sys

# 添加 tools 目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeclient import PipeClient


# ===================== 配置区域 =====================
# 自动查找最新的对齐信息 CSV 文件
def find_latest_csv():
    """查找 data 文件夹中最新的 alignment_detail CSV 文件"""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(project_dir, 'data')
    csv_pattern = os.path.join(data_dir, 'alignment_detail_*.csv')
    csv_files = glob.glob(csv_pattern)
    if not csv_files:
        return None
    # 按修改时间排序，返回最新的
    return max(csv_files, key=os.path.getmtime)

# 路径配置（相对于项目根目录）
METRONOME_FOLDER = os.path.join("audio_output", "metronome")    # 节拍器文件夹
SONGS_FOLDER = os.path.join("audio_output", "shifted_songs")     # 变速后的歌曲文件夹
OUTPUT_PATH = "final_mix.wav"                                     # 最终导出的文件名
# =======================================================================


def to_audacity_path(path):
    """将路径转换为 Audacity 可识别的格式（绝对路径，使用正斜杠）"""
    abs_path = os.path.abspath(path)
    return abs_path.replace('\\', '/')


def parse_csv(csv_path):
    """解析 CSV 文件，提取参数和音频列表"""
    header_params = {}
    audio_list = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # 解析 # 开头的头部参数
            if line.startswith('#'):
                content = line.lstrip('#').strip()
                if ',' in content:
                    key, val = content.split(',', 1)
                    header_params[key.strip()] = val.strip()
            # 解析表头（跳过）
            elif line.startswith('序号'):
                continue
            # 解析音频数据行
            else:
                parts = line.split(',')
                if len(parts) >= 4:
                    audio_list.append({
                        'filename': parts[1].strip(),  # 去除前后空格
                        'start_play': float(parts[3])  # 开始播放(s)
                    })
    
    return header_params, audio_list


def create_silence_audio(duration_sec, output_path, sample_rate=44100):
    """使用 FFmpeg 创建指定时长的静音音频"""
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi',
        '-i', f'anullsrc=r={sample_rate}:cl=mono',
        '-t', str(duration_sec),
        '-acodec', 'pcm_s16le',
        '-ar', str(sample_rate),
        output_path
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"创建静音失败: {e}")
        return False


def concat_audio_with_silence(audio_path, silence_duration, output_path):
    """将静音和原音频拼接在一起 - 使用 adelay 保持原始音频完整性"""
    # 使用 adelay 过滤器添加延迟（静音），保持原始音频不变
    # 格式: adelay=delays_in_ms:all=1
    delay_ms = int(silence_duration * 1000)
    
    cmd = [
        'ffmpeg', '-y',
        '-i', audio_path,
        '-af', f'adelay={delay_ms}|{delay_ms}:all=1',
        '-acodec', 'pcm_s16le',
        output_path
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"添加静音失败: {e}")
        print(f"FFmpeg stderr: {e.stderr}")
        return False


def main():
    # 获取项目根目录
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 1. 查找并解析 CSV
    print("正在查找最新的对齐信息文件...")
    csv_path = find_latest_csv()
    if not csv_path:
        print("❌ 错误：未找到 alignment_detail_*.csv 文件")
        print("   请先在 RunBeat 中导出对齐信息")
        return
    print(f"使用 CSV 文件: {csv_path}")
    
    header_params, audio_list = parse_csv(csv_path)
    first_beat_time = float(header_params['第一首歌首拍(s)'])
    metronome_vol = float(header_params['节拍器音量(dB)'])
    target_loudness = float(header_params['目标响度(dBFS)'])
    print(f"解析完成：共 {len(audio_list)} 个音频，节拍器首拍时间 {first_beat_time}s")

    # 2. 连接 Audacity
    print("\n正在连接 Audacity...")
    print("   请确保 Audacity 已打开且 mod-script-pipe 已启用")
    try:
        client = PipeClient()
        print("✅ 已连接 Audacity")
    except SystemExit as e:
        print(f"❌ 连接失败！")
        print(f"   请确保 Audacity 已打开且 mod-script-pipe 已启用")
        print(f"   错误信息: {e}")
        return

    # 3. 新建工程
    client.write("New:")
    print("已新建工程")

    # 创建临时文件夹存放处理后的音频
    temp_folder = tempfile.mkdtemp(prefix="audacity_mix_")
    print(f"临时文件夹: {temp_folder}")

    # 构建完整路径
    metronome_folder = os.path.join(project_dir, METRONOME_FOLDER)
    songs_folder = os.path.join(project_dir, SONGS_FOLDER)

    # 4. 处理节拍器
    metronome_path = os.path.join(metronome_folder, "metronome_180.wav")
    if os.path.exists(metronome_path):
        print(f"\n正在处理节拍器: {metronome_path}")
        
        # 在节拍器前添加静音，让它从 first_beat_time 开始
        processed_metronome = os.path.join(temp_folder, "metronome_processed.wav")
        if concat_audio_with_silence(metronome_path, first_beat_time, processed_metronome):
            # 导入处理后的节拍器
            client.write(f'Import2: Filename="{to_audacity_path(processed_metronome)}"')
            
            # 调整节拍器音量
            client.write("SelectAll:")
            client.write(f"Amplify: dB={metronome_vol}")
            print(f"✅ 节拍器已处理（前导静音 {first_beat_time}s），音量调整为 {metronome_vol}dB")
        else:
            print(f"⚠️  节拍器处理失败，尝试直接导入")
            client.write(f'Import2: Filename="{to_audacity_path(metronome_path)}"')
    else:
        print(f"⚠️  警告：未找到节拍器文件 {metronome_path}")

    # 5. 逐个处理并导入音频
    print(f"\n开始处理 {len(audio_list)} 个音频文件...")
    for idx, audio in enumerate(audio_list, 1):
        audio_path = os.path.join(songs_folder, audio['filename'])
        if not os.path.exists(audio_path):
            print(f"⚠️  警告：未找到音频 {audio_path}，跳过")
            continue
        
        start_time = audio['start_play']
        print(f"正在处理 [{idx}/{len(audio_list)}]: {audio['filename']} (目标位置 {start_time:.3f}s)")
        
        # 在音频前添加静音
        processed_audio = os.path.join(temp_folder, f"processed_{idx}.wav")
        if concat_audio_with_silence(audio_path, start_time, processed_audio):
            # 导入处理后的音频
            client.write(f'Import2: Filename="{to_audacity_path(processed_audio)}"')
            print(f"✅ {audio['filename']} 已处理并导入（前导静音 {start_time:.3f}s）")
        else:
            print(f"⚠️  处理失败，尝试直接导入原文件")
            client.write(f'Import2: Filename="{to_audacity_path(audio_path)}"')

    print("\n" + "="*60)
    print("🎉 全部完成！")
    print("="*60)
    print(f"\n请在 Audacity 中：")
    print("  1. 检查各轨道对齐情况")
    print("  2. 如需调整，可手动编辑")
    print(f"  3. 导出最终混音到: {OUTPUT_PATH}")
    print(f"\n临时文件保存在: {temp_folder}")
    print("你可以手动删除这个文件夹。")


if __name__ == "__main__":
    main()
