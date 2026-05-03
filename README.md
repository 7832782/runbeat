# RunBeat - 智能跑步音乐生成系统

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 项目简介

RunBeat 是一个基于Python的智能跑步音乐生成系统，将任意音频自动处理为匹配用户目标步频（BPM）的跑步音乐。该系统结合了数字信号处理、音乐信息检索（MIR）和音频处理技术，实现从BPM识别到最终混音的完整音频处理流程。

**核心功能**：

- 🎵 **BPM识别**：基于Mixxx DJ引擎的高精度节拍检测
- 🏃 **变速不变调**：使用Phase Vocoder技术保持音调
- 🎚️ **智能混音**：自动响度归一化与节拍对齐
- 🎯 **首拍对齐**：可视化波形编辑与播放预览
- 🔗 **Audacity集成**：支持专业音频编辑软件协作

## 演示截图

> 建议添加GUI界面截图，展示：
>
> - 主界面概览
> - 波形编辑界面
> - 处理流程示意

## 功能特性

## 功能特性

- **BPM识别**: 批量识别音频文件的原生BPM，支持librosa和mixxx两种算法
- **变速处理**: 将音频变速到目标BPM，支持严格/非严格模式
- **节拍器生成**: 生成指定BPM的节拍器音频
- **首拍对齐**: 可视化调整歌曲首拍位置，支持与节拍器对齐
- **混音导出**: 将多首歌曲拼接混音，导出最终跑步音乐
- **Audacity集成**: 支持导出对齐信息，可在Audacity中进一步编辑

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行GUI

```bash
python run_gui.py
```

### 3. 使用流程

#### 3.1. 使用一键工作流（推荐）

1. **准备音频**: 在"0. 准备音频"标签页导入音频、调整音频顺序
2. **一键执行**: 在"一键工作流"标签页点击"开始执行"
3. **等待完成**: 系统自动完成BPM识别、变速、节拍器生成、首拍对齐、混音
4. **查看结果**: 在 `audio_output/final_mix/` 目录查看最终混音文件

#### 3.2. 手动流程

如需精细控制每个步骤，可按以下顺序手动操作：

1. **准备音频**: 在"0. 准备音频"标签页导入音频、调整音频顺序
2. **BPM识别**: 在"1. BPM识别"标签页识别歌曲BPM
   - 支持 Mixxx 和 Librosa 两种引擎
   - 可手动修正识别结果
3. **变速处理**: 在"2. 变速处理"标签页将歌曲变速到目标BPM
   - 使用 SoundTouch 实现变速不变调
   - 支持批量处理
4. **节拍器**: 在"3. 节拍器"标签页生成节拍器
   - 设置目标BPM和跑步距离
   - 自动计算所需节拍数
5. **首拍对齐**: 在"4. 首拍对齐"标签页调整歌曲首拍位置
   - 可视化波形编辑
   - 双击黄线跳转播放
   - 右键双击红线对齐首拍
6. **混音**: 在"5. 混音"标签页导出最终音频
   - 支持多轨道混音
   - 自动防止歌曲重叠

## 目录结构

```
runbeat/
├── README.md                    # 项目说明
├── requirements.txt             # Python依赖
├── run_gui.py                   # GUI启动脚本
├── screenshots/                 # 演示截图
└── tools/                       # 工具脚本
    ├── auto_mix.py             # Audacity自动混音脚本
    └── pipeclient.py           # Audacity管道客户端
├── audio_input/                 # 音频输入文件夹
├── audio_output/                # 音频输出文件夹
│   ├── metronome/              # 节拍器输出
│   ├── shifted_songs/          # 变速后音频
│   └── final_mix/              # 最终混音
├── data/                        # 数据文件
│   ├── song_bpm_list.json      # BPM识别结果
│   ├── file_mapping.json       # 文件名映射
│   └── beat_alignments.json    # 首拍对齐数据
├── modules/                     # 核心模块
│   ├── batch_bpm_detector.py   # BPM识别
│   ├── tempo_shifter.py        # 变速处理
│   ├── metronome_generator.py  # 节拍器生成
│   ├── audio_mixer.py          # 音频混音
│   └── beat_detector.py        # 首拍检测
└── gui/                         # GUI界面
    ├── main_window.py          # 主窗口
    ├── bpm_detector_tab.py     # BPM识别标签页
    ├── tempo_shift_tab.py      # 变速处理标签页
    ├── metronome_tab.py        # 节拍器标签页
    ├── beat_align_tab.py       # 首拍对齐标签页
    ├── mixing_tab.py           # 混音标签页
    ├── prepare_audio_tab.py    # 准备音频标签页
    └── workflow_tab.py         # 一键工作流标签页
```

## 依赖说明

- **librosa**: BPM识别、音频分析
- **pydub**: 音频剪辑、拼接、混音
- **soundfile**: 音频读写
- **sounddevice**: 音频播放
- **PyQt6**: 图形界面
- **mixxx-analyzer**: 高精度BPM识别

## 注意事项

- 需要安装 ffmpeg 以支持多种音频格式
- Windows 用户可能需要额外配置 soundstretch
- 首拍对齐功能需要音频播放支持

## 技术栈

- **Python 3.9+**: 核心开发语言
- **PyQt6**: 跨平台图形用户界面
- **Librosa**: 音频分析、BPM检测（备选方案）

## AI 辅助开发说明

本项目在开发过程中充分利用了大语言模型（LLM）作为开发助手，体现了 AI 辅助编程的实践。

## 系统要求

- Python 3.9 或更高版本
- FFmpeg（必需，用于音频格式支持）
- Windows/Mac/Linux 均可运行

## 自动化脚本

项目根目录提供 `auto_mix.py` 脚本，可与Audacity集成实现自动混音：

```bash
python auto_mix.py
```

该脚本会读取对齐信息，自动在Audacity中导入并排列音频轨道。

关于Audacity的脚本使用，请参考[Scripting - Audacity Manual](https://manual.audacityteam.org/man/scripting.html)

## 贡献指南

欢迎提交Issue和Pull Request！

## 许可证

本项目采用 [MIT License](LICENSE) 开源许可证。

## 致谢

- [Librosa](https://librosa.org/) - 音频分析库
- [Mixxx](https://mixxx.org/) - DJ软件及BPM分析引擎
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) - GUI框架

