#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块5: 首拍识别与对齐管理 (beat_detector.py)

功能:
    1. 自动检测音频文件的第一个重拍（首拍）位置
    2. 持久化管理多首歌曲的首拍时间戳
    3. 为混音模块提供对齐计算（歌曲首拍 → 节拍器重拍）

输入:
    变速后的音频文件路径

输出:
    data/beat_alignments.json — 持久化的首拍时间戳存储

检测算法:
    1. 加载音频前 15 秒（preview_duration，可配置）
    2. 使用 librosa.onset.onset_detect() 检测音符开始点（onset）
    3. 使用 librosa.beat.beat_track() 检测节拍位置（beat）
    4. 综合判断第一个重拍:
       - 找到第一个 onset 和与其最接近的 beat
       - 如果两者在 100ms 内，取平均值（说明是可靠的重拍）
       - 否则回退到第一个 onset
    5. 置信度评估: 基于首拍位置的 onset 强度与全局最大强度的比值

类和数据结构:
    BeatDetectionResult      dataclass — 单首歌曲的检测结果
    FirstBeatDetector        首拍检测器 — 分析音频，返回首拍时间
    BeatAlignmentManager     对齐管理器 — JSON 持久化存储，支持读写删

在混音中的作用:
    混音模块通过 BeatAlignmentManager 获取每首歌的首拍时间戳，
    计算歌曲应该在什么时间开始播放，使其首拍精确对齐到节拍器的重拍位置。
"""

import os
import json
import numpy as np
import librosa
import soundfile as sf
from typing import Optional, Tuple, List
from dataclasses import dataclass


@dataclass
class BeatDetectionResult:
    """首拍检测结果"""
    file_path: str
    file_name: str
    first_beat_time: float  # 首拍时间戳（秒）
    confidence: float       # 检测置信度
    onset_times: List[float]  # 所有 onset 时间点
    beat_times: List[float]   # 所有节拍时间点


class FirstBeatDetector:
    """
    首拍检测器
    
    自动识别音频的第一个重拍位置
    """
    
    def __init__(self, preview_duration: float = 15.0):
        """
        初始化检测器
        
        Args:
            preview_duration: 预览时长（秒），只分析前N秒
        """
        self.preview_duration = preview_duration
    
    def detect(self, audio_path: str) -> BeatDetectionResult:
        """
        检测音频的首拍位置
        
        策略：
        1. 加载音频前N秒
        2. 使用 onset detection 找到所有 onset 点
        3. 使用 beat tracking 找到节拍位置
        4. 综合判断找到第一个重拍
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            首拍检测结果
        """
        # 加载音频（只加载前preview_duration秒）
        y, sr = librosa.load(audio_path, sr=None, mono=True, 
                             duration=self.preview_duration)
        
        # 1. Onset detection - 检测音符开始点
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onset_frames = librosa.onset.onset_detect(
            onset_envelope=onset_env, 
            sr=sr,
            wait=3,  # 等待几帧，避免过密检测
            pre_avg=3,
            post_avg=3,
            pre_max=3,
            post_max=3
        )
        onset_times = librosa.frames_to_time(onset_frames, sr=sr)
        
        # 2. Beat tracking - 检测节拍位置
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        
        # 3. 找到第一个重拍
        # 策略：取第一个 onset 和第一个 beat 的加权平均
        # 如果 onset 和 beat 很接近，认为那是重拍
        first_beat_time = self._find_first_strong_beat(
            onset_times, beat_times, onset_env, sr
        )
        
        # 计算置信度（基于 onset 强度）
        confidence = self._calculate_confidence(
            first_beat_time, onset_times, onset_env, sr
        )
        
        return BeatDetectionResult(
            file_path=audio_path,
            file_name=os.path.basename(audio_path),
            first_beat_time=round(first_beat_time, 3),
            confidence=round(confidence, 2),
            onset_times=onset_times.tolist(),
            beat_times=beat_times.tolist()
        )
    
    def _find_first_strong_beat(
        self, 
        onset_times: np.ndarray, 
        beat_times: np.ndarray,
        onset_env: np.ndarray,
        sr: int
    ) -> float:
        """
        找到第一个重拍位置
        
        策略：
        - 如果有 onset 和 beat 重合或接近，优先选择
        - 否则选择第一个较强的 onset
        - 如果都没有，选择 0（音频开头）
        """
        if len(onset_times) == 0:
            return 0.0
        
        # 找到第一个 onset
        first_onset = onset_times[0]
        
        # 找与第一个 onset 最接近的 beat
        if len(beat_times) > 0:
            closest_beat_idx = np.argmin(np.abs(beat_times - first_onset))
            closest_beat = beat_times[closest_beat_idx]
            
            # 如果 beat 和 onset 在 100ms 内，认为是重拍
            if abs(closest_beat - first_onset) < 0.1:
                # 取 weighted average，权重偏向更强的那个
                return (first_onset + closest_beat) / 2
        
        # 否则返回第一个 onset
        return first_onset
    
    def _calculate_confidence(
        self, 
        first_beat_time: float,
        onset_times: np.ndarray,
        onset_env: np.ndarray,
        sr: int
    ) -> float:
        """计算首拍检测的置信度"""
        if len(onset_times) == 0:
            return 0.0
        
        # 将时间转换为帧
        first_beat_frame = librosa.time_to_frames(first_beat_time, sr=sr)
        
        if first_beat_frame < len(onset_env):
            # 基于 onset 强度计算置信度
            onset_strength = onset_env[first_beat_frame]
            max_strength = np.max(onset_env)
            
            if max_strength > 0:
                return min(1.0, onset_strength / max_strength * 1.5)
        
        return 0.5


class BeatAlignmentManager:
    """
    节拍对齐管理器
    
    管理多首歌曲的首拍时间戳，支持混音对齐
    """
    
    def __init__(self, json_path: str = None):
        if json_path is None:
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            json_path = os.path.join(project_dir, "data", "beat_alignments.json")
        self.json_path = json_path
        self.alignments = {}
        self._load()
    
    def _load(self):
        """加载已保存的对齐数据"""
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    self.alignments = json.load(f)
            except:
                self.alignments = {}
    
    def save(self):
        """保存对齐数据"""
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(self.alignments, f, ensure_ascii=False, indent=2)
    
    def set_first_beat(self, file_path: str, first_beat_time: float):
        """设置歌曲的首拍时间戳"""
        self.alignments[file_path] = {
            'first_beat_time': first_beat_time,
            'file_name': os.path.basename(file_path)
        }
        self.save()
    
    def get_first_beat(self, file_path: str) -> Optional[float]:
        """获取歌曲的首拍时间戳"""
        if file_path in self.alignments:
            return self.alignments[file_path]['first_beat_time']
        return None

    def get_metronome_first_beat(self) -> Optional[float]:
        """获取节拍器的首拍时间戳"""
        return self.get_first_beat('__metronome__')

    def set_metronome_first_beat(self, first_beat_time: float):
        """设置节拍器的首拍时间戳"""
        self.set_first_beat('__metronome__', first_beat_time)
    
    def calculate_aligned_start_time(
        self, 
        file_path: str, 
        metronome_bpm: int,
        prev_song_end_beat: int = 0
    ) -> float:
        """
        计算歌曲在混音中的对齐开始时间
        
        Args:
            file_path: 歌曲路径
            metronome_bpm: 节拍器BPM
            prev_song_end_beat: 上一首歌结束时的节拍数
            
        Returns:
            对齐后的开始时间（秒）
        """
        first_beat = self.get_first_beat(file_path)
        if first_beat is None:
            first_beat = 0.0
        
        # 计算目标首拍位置（对应节拍器的第N个重拍）
        beat_duration = 60.0 / metronome_bpm
        target_first_beat_time = prev_song_end_beat * beat_duration
        
        # 歌曲需要从什么时间开始播放，才能让它的首拍对齐到目标位置
        song_start_time = target_first_beat_time - first_beat
        
        return max(0, song_start_time)


if __name__ == "__main__":
    # 测试
    import argparse
    
    parser = argparse.ArgumentParser(description="首拍检测工具")
    parser.add_argument("--input", "-i", required=True, help="音频文件路径")
    args = parser.parse_args()
    
    detector = FirstBeatDetector()
    result = detector.detect(args.input)
    
    print(f"文件: {result.file_name}")
    print(f"首拍时间: {result.first_beat_time:.3f}秒")
    print(f"置信度: {result.confidence:.2f}")
    print(f"检测到 {len(result.onset_times)} 个 onset")
    print(f"检测到 {len(result.beat_times)} 个 beat")
