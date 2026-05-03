#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块2: 目标BPM节拍器生成

功能: 根据用户输入的目标BPM，生成标准节拍器音频

输入:
    - 目标BPM (如180)
    - 节拍器音色 (可选，默认短促脉冲音)
    - 时长 (默认30秒)
    - 拍号 (默认4/4拍，支持自定义强拍)

输出:
    - metronome_{bpm}.wav (文件名包含目标BPM)

特性:
    - 节拍器声音为短促的脉冲音，避免干扰音乐
    - 支持自定义强拍（第一拍）音色区分
    - 支持自定义频率、音量、衰减时间
"""

import os
import argparse
import numpy as np
import soundfile as sf
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class MetronomeConfig:
    """节拍器配置数据类"""
    bpm: int = 180                    # 目标BPM
    duration: float = 30.0            # 总时长(秒)
    beats_per_measure: int = 4        # 每小节拍数 (拍号分子)
    sample_rate: int = 44100          # 采样率
    
    # 强拍(第一拍)音色参数
    strong_freq: float = 1000.0       # 强拍频率(Hz)
    strong_duration: float = 0.05     # 强拍持续时间(秒)
    strong_volume: float = 0.8        # 强拍音量 (0-1)
    
    # 弱拍音色参数
    weak_freq: float = 800.0          # 弱拍频率(Hz)
    weak_duration: float = 0.05       # 弱拍持续时间(秒)
    weak_volume: float = 0.5          # 弱拍音量 (0-1)


class MetronomeGenerator:
    """
    节拍器生成器
    
    生成指定BPM的节拍器音频，支持强拍/弱拍区分。
    """
    
    def __init__(self, config: Optional[MetronomeConfig] = None):
        """
        初始化节拍器生成器
        
        Args:
            config: 节拍器配置，使用默认配置如果为None
        """
        self.config = config or MetronomeConfig()
    
    def _generate_click(
        self,
        frequency: float,
        duration: float,
        volume: float,
        sample_rate: int
    ) -> np.ndarray:
        """
        生成单个节拍声音（指数衰减正弦波）
        
        使用指数衰减的正弦波模拟"嗒"声，听起来更自然
        
        Args:
            frequency: 声音频率(Hz)
            duration: 声音持续时间(秒)
            volume: 音量 (0-1)
            sample_rate: 采样率
            
        Returns:
            音频样本数组
        """
        num_samples = int(duration * sample_rate)
        t = np.linspace(0, duration, num_samples, endpoint=False)
        
        # 生成正弦波
        sine_wave = np.sin(2 * np.pi * frequency * t)
        
        # 应用指数衰减包络（让声音自然衰减）
        # 衰减系数: 声音在duration结束时衰减到约1%
        decay = np.exp(-5 * t / duration)
        
        # 应用音量和衰减
        click = sine_wave * decay * volume
        
        return click
    
    def generate(
        self,
        output_path: Optional[str] = None
    ) -> Tuple[np.ndarray, int]:
        """
        生成节拍器音频
        
        Args:
            output_path: 输出文件路径，为None时不保存文件
            
        Returns:
            (音频数组, 采样率)
        """
        config = self.config
        
        # 计算总样本数
        total_samples = int(config.duration * config.sample_rate)
        
        # 初始化静音音频
        audio = np.zeros(total_samples, dtype=np.float32)
        
        # 计算每拍的间隔（样本数）
        beat_interval_samples = int(60.0 / config.bpm * config.sample_rate)
        
        # 生成强拍和弱拍声音
        strong_click = self._generate_click(
            config.strong_freq,
            config.strong_duration,
            config.strong_volume,
            config.sample_rate
        )
        weak_click = self._generate_click(
            config.weak_freq,
            config.weak_duration,
            config.weak_volume,
            config.sample_rate
        )
        
        # 在音频中放置节拍
        beat_count = 0
        for pos in range(0, total_samples, beat_interval_samples):
            # 判断是强拍还是弱拍
            is_strong_beat = (beat_count % config.beats_per_measure) == 0
            click = strong_click if is_strong_beat else weak_click
            
            # 确保不超出音频边界
            end_pos = min(pos + len(click), total_samples)
            click_length = end_pos - pos
            
            # 叠加节拍声音
            audio[pos:end_pos] += click[:click_length]
            
            beat_count += 1
        
        # 防止削波（归一化到 [-1, 1] 范围内）
        max_amplitude = np.max(np.abs(audio))
        if max_amplitude > 1.0:
            audio = audio / max_amplitude * 0.95
        
        # 保存文件
        if output_path:
            sf.write(output_path, audio, config.sample_rate)
            print(f"[INFO] 节拍器已保存: {output_path}")
            print(f"       BPM: {config.bpm}, 时长: {config.duration}s, 拍号: {config.beats_per_measure}/4")
        
        return audio, config.sample_rate
    
    def get_info(self) -> dict:
        """获取节拍器信息"""
        return {
            "bpm": self.config.bpm,
            "duration": self.config.duration,
            "beats_per_measure": self.config.beats_per_measure,
            "sample_rate": self.config.sample_rate,
            "total_beats": int(self.config.duration / (60.0 / self.config.bpm)),
            "strong_freq": self.config.strong_freq,
            "weak_freq": self.config.weak_freq
        }


def main():
    """
    模块2主函数 - 测试入口
    
    使用示例:
        python metronome_generator.py --bpm 180
        python metronome_generator.py --bpm 180 --duration 60
        python metronome_generator.py --bpm 180 --strong-freq 1200 --weak-freq 800
    """
    parser = argparse.ArgumentParser(
        description="节拍器生成工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 生成180BPM的节拍器（默认30秒）
  python metronome_generator.py --bpm 180
  
  # 生成60秒长的节拍器
  python metronome_generator.py --bpm 180 --duration 60
  
  # 自定义音色频率
  python metronome_generator.py --bpm 180 --strong-freq 1200 --weak-freq 600
  
  # 自定义输出路径
  python metronome_generator.py --bpm 180 -o ./output/my_metronome.wav
        """
    )
    
    # 获取脚本所在目录，用于计算默认路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    
    parser.add_argument(
        "--bpm",
        type=int,
        required=True,
        help="目标BPM (必须指定)"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="节拍器时长(秒) (默认: 30)"
    )
    parser.add_argument(
        "--beats-per-measure",
        type=int,
        default=4,
        help="每小节拍数 (默认: 4)"
    )
    parser.add_argument(
        "--strong-freq",
        type=float,
        default=1000.0,
        help="强拍频率(Hz) (默认: 1000)"
    )
    parser.add_argument(
        "--weak-freq",
        type=float,
        default=800.0,
        help="弱拍频率(Hz) (默认: 800)"
    )
    parser.add_argument(
        "--strong-volume",
        type=float,
        default=0.8,
        help="强拍音量 (0-1, 默认: 0.8)"
    )
    parser.add_argument(
        "--weak-volume",
        type=float,
        default=0.5,
        help="弱拍音量 (0-1, 默认: 0.5)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="输出文件路径 (默认: 项目根目录下的 metronome_{bpm}.wav)"
    )
    
    args = parser.parse_args()
    
    # 确定输出路径
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        output_path = os.path.join(project_dir, "audio_output", "metronome", f"metronome_{args.bpm}.wav")
    
    # 确保输出目录存在
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    print("[RunBeat] 节拍器生成模块")
    print("=" * 60)
    
    # 创建配置
    config = MetronomeConfig(
        bpm=args.bpm,
        duration=args.duration,
        beats_per_measure=args.beats_per_measure,
        strong_freq=args.strong_freq,
        weak_freq=args.weak_freq,
        strong_volume=args.strong_volume,
        weak_volume=args.weak_volume
    )
    
    # 生成节拍器
    generator = MetronomeGenerator(config)
    
    print(f"[CONFIG] BPM: {config.bpm}")
    print(f"[CONFIG] 时长: {config.duration}s")
    print(f"[CONFIG] 拍号: {config.beats_per_measure}/4")
    print(f"[CONFIG] 强拍: {config.strong_freq}Hz, 音量{config.strong_volume}")
    print(f"[CONFIG] 弱拍: {config.weak_freq}Hz, 音量{config.weak_volume}")
    print("-" * 60)
    
    audio, sr = generator.generate(output_path)
    
    # 打印信息
    info = generator.get_info()
    print(f"[INFO] 总拍数: {info['total_beats']}")
    print(f"[INFO] 音频长度: {len(audio)/sr:.2f}s")
    
    print("=" * 60)
    print(f"[DONE] 节拍器已生成: {output_path}")
    
    return 0


if __name__ == "__main__":
    exit(main())
