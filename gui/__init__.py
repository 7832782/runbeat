"""
RunBeat GUI 图形界面包 (GUI)

基于 PyQt6 的桌面应用界面，按标签页组织为 7 个子模块：

prepare_audio_tab.py  Tab 0 - 准备音频
    拖拽导入音频文件、排序、删除、一键导入到 audio_input/

workflow_tab.py  Tab - 一键工作流
    串联所有步骤：BPM识别 → 变速 → 节拍器 → 首拍对齐 → 混音

bpm_detector_tab.py  Tab 1 - BPM 识别
    选择检测方法（mixxx/librosa），批量分析，支持手动修改 BPM

tempo_shift_tab.py  Tab 2 - 变速处理
    设置目标 BPM，严格/非严格模式，预览变速后 BPM

metronome_tab.py  Tab 3 - 节拍器生成
    设置 BPM/时长/拍号/音色，自动检测歌曲总时长推荐节拍器长度

beat_align_tab.py  Tab 4 - 首拍对齐
    波形可视化预览 + 自动首拍检测 + 鼠标/键盘微调 + 音频播放

mixing_tab.py  Tab 5 - 混音
    响度归一化 + 首拍对齐 + 节拍器叠加 + 导出对齐信息 CSV

main_window.py  主窗口
    QMainWindow 容器，QTabWidget 管理所有标签页，日志面板，状态栏
"""

from .main_window import MainWindow
from .workflow_tab import WorkflowTab

__all__ = ['MainWindow', 'WorkflowTab']
