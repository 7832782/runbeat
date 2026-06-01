"""
RunBeat 工具包 (Tools)

本包包含与外部工具集成的辅助脚本：

pipeclient.py  Audacity mod-script-pipe 客户端
    原作者: Steve Daulton (GPLv2)
    功能: 通过命名管道与 Audacity 通信，发送脚本命令并接收响应
    平台: Windows（\\.\pipe\ToSrvPipe / FromSrvPipe）
          Unix（/tmp/audacity_script_pipe.to.{uid} / from.{uid}）

auto_mix.py  Audacity 自动混音编排脚本
    输入: data/alignment_detail_*.csv（RunBeat 导出的对齐信息）
    输出: 在 Audacity 中自动创建多轨道工程
    流程: 解析 CSV → 用 ffmpeg adelay 为每首歌添加前导静音 →
          通过 pipeclient 导入 Audacity → 用户手动检查并导出
    依赖: Audacity（启用 mod-script-pipe）、FFmpeg
"""

from .pipeclient import PipeClient

__all__ = ['PipeClient']
