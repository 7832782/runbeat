#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tab 0 - 准备音频标签页

RunBeat 工作流的第一步，负责将用户选择的音频文件导入到内部工作目录。

功能:
    1. 拖拽导入: 支持将文件从资源管理器直接拖入列表（过滤非音频文件）
    2. 文件对话框导入: 点击按钮选择文件（支持多选）
    3. 列表排序: 内部拖拽调整歌曲顺序（通过 DragDropMode.InternalMove）
    4. 删除/清空: 支持删除单首或清空全部
    5. 准备完成: 将列表中的文件按序号复制到 audio_input/（重命名为 1.mp3, 2.mp3...）
       同时生成 data/file_mapping.json 保存原始文件名映射
    6. 清理缓存: 清空 audio_input/、metronome/、shifted_songs/、data/（保留 final_mix/）

类:
    AudioListItem        自定义 QListWidgetItem，存储文件路径和原始名称
    DroppableListWidget   支持外部拖拽导入和内部拖拽排序的列表组件
    PrepareAudioTab        标签页主控件

支持音频格式:
    .mp3 / .wav / .flac / .m4a / .ogg / .aac / .wma
"""

import os
import shutil
import json
from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QGroupBox, QAbstractItemView, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction


class AudioListItem(QListWidgetItem):
    """自定义音频列表项"""
    
    def __init__(self, file_path: str, original_name: str = None):
        super().__init__()
        self.file_path = file_path
        self.original_name = original_name or os.path.basename(file_path)
        self.index = 0
        self.update_display()
    
    def update_display(self):
        """更新显示文本"""
        self.setText(f"{self.index}. {self.original_name}")


class DroppableListWidget(QListWidget):
    """支持外部拖拽的列表组件"""
    
    files_dropped = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        
        # 设置样式
        self.setStyleSheet("""
            QListWidget {
                border: 2px dashed #666;
                border-radius: 8px;
                background-color: #2d2d2d;
                padding: 5px;
            }
            QListWidget:hover {
                border-color: #4CAF50;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #444;
            }
            QListWidget::item:selected {
                background-color: #4CAF50;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #3d3d3d;
            }
        """)
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("""
                QListWidget {
                    border: 2px dashed #4CAF50;
                    border-radius: 8px;
                    background-color: #363636;
                    padding: 5px;
                }
                QListWidget::item {
                    padding: 8px;
                    border-bottom: 1px solid #444;
                }
                QListWidget::item:selected {
                    background-color: #4CAF50;
                    color: white;
                }
            """)
        else:
            super().dragEnterEvent(event)
    
    def dragLeaveEvent(self, event):
        self.setStyleSheet("""
            QListWidget {
                border: 2px dashed #666;
                border-radius: 8px;
                background-color: #2d2d2d;
                padding: 5px;
            }
            QListWidget:hover {
                border-color: #4CAF50;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #444;
            }
            QListWidget::item:selected {
                background-color: #4CAF50;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #3d3d3d;
            }
        """)
        super().dragLeaveEvent(event)
    
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)
    
    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            # 外部文件拖拽
            files = []
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if self._is_audio_file(file_path):
                    files.append(file_path)
            
            if files:
                self.files_dropped.emit(files)
            
            # 恢复样式
            self.setStyleSheet("""
                QListWidget {
                    border: 2px dashed #666;
                    border-radius: 8px;
                    background-color: #2d2d2d;
                    padding: 5px;
                }
                QListWidget:hover {
                    border-color: #4CAF50;
                }
                QListWidget::item {
                    padding: 8px;
                    border-bottom: 1px solid #444;
                }
                QListWidget::item:selected {
                    background-color: #4CAF50;
                    color: white;
                }
                QListWidget::item:hover {
                    background-color: #3d3d3d;
                }
            """)
            event.acceptProposedAction()
        else:
            # 内部拖拽排序
            super().dropEvent(event)
    
    def _is_audio_file(self, file_path: str) -> bool:
        """检查是否为音频文件"""
        audio_extensions = {'.mp3', '.wav', '.flac', '.m4a', '.ogg', '.aac', '.wma'}
        return Path(file_path).suffix.lower() in audio_extensions


class PrepareAudioTab(QWidget):
    """准备音频标签页"""
    
    audio_list_changed = pyqtSignal()  # 音频列表变化信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.audio_files: List[AudioListItem] = []
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)

        # 音频列表（支持拖拽导入和排序）
        list_group = QGroupBox("音频列表（拖拽文件导入，拖拽项目排序）")
        list_layout = QVBoxLayout()

        self.audio_list = DroppableListWidget()
        self.audio_list.files_dropped.connect(self.add_files)
        self.audio_list.model().rowsMoved.connect(self.on_order_changed)
        self.audio_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.audio_list.customContextMenuRequested.connect(self.show_context_menu)
        list_layout.addWidget(self.audio_list)

        # 操作按钮行（导入、删除、清空、清理缓存、准备完成）
        btn_layout = QHBoxLayout()

        self.import_btn = QPushButton("导入音频")
        self.import_btn.setMinimumHeight(35)
        self.import_btn.clicked.connect(self.import_files)
        btn_layout.addWidget(self.import_btn)

        self.remove_btn = QPushButton("删除选中")
        self.remove_btn.setMinimumHeight(35)
        self.remove_btn.clicked.connect(self.remove_selected)
        btn_layout.addWidget(self.remove_btn)

        self.clear_btn = QPushButton("清空列表")
        self.clear_btn.setMinimumHeight(35)
        self.clear_btn.clicked.connect(self.clear_list)
        btn_layout.addWidget(self.clear_btn)

        self.clear_cache_btn = QPushButton("清理缓存")
        self.clear_cache_btn.setMinimumHeight(35)
        self.clear_cache_btn.clicked.connect(self.clear_cache)
        btn_layout.addWidget(self.clear_cache_btn)

        # 准备完成按钮放在清理缓存旁边
        self.prepare_btn = QPushButton("准备完成")
        self.prepare_btn.setMinimumHeight(35)
        self.prepare_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.prepare_btn.clicked.connect(self.prepare_files)
        btn_layout.addWidget(self.prepare_btn)

        btn_layout.addStretch()

        self.count_label = QLabel("共 0 首")
        btn_layout.addWidget(self.count_label)

        list_layout.addLayout(btn_layout)
        list_group.setLayout(list_layout)
        layout.addWidget(list_group)

        layout.addStretch()
    
    def import_files(self):
        """通过对话框导入文件"""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择音频文件",
            "",
            "音频文件 (*.mp3 *.wav *.flac *.m4a *.ogg *.aac *.wma);;所有文件 (*.*)"
        )
        if files:
            self.add_files(files)
    
    def add_files(self, file_paths: List[str]):
        """添加文件到列表"""
        added_count = 0
        for file_path in file_paths:
            # 检查是否已存在
            exists = any(item.file_path == file_path for item in self.audio_files)
            if not exists:
                item = AudioListItem(file_path)
                self.audio_files.append(item)
                self.audio_list.addItem(item)
                added_count += 1
        
        if added_count > 0:
            self.update_indices()
            self.log(f"已添加 {added_count} 首音频")
            self.audio_list_changed.emit()
    
    def update_indices(self):
        """更新所有项的序号显示"""
        for i, item in enumerate(self.audio_files, start=1):
            item.index = i
            item.update_display()
        self.count_label.setText(f"共 {len(self.audio_files)} 首")
    
    def on_order_changed(self):
        """列表顺序改变时更新"""
        # 重新获取列表中的项
        self.audio_files = []
        for i in range(self.audio_list.count()):
            item = self.audio_list.item(i)
            if isinstance(item, AudioListItem):
                self.audio_files.append(item)
        self.update_indices()
        self.audio_list_changed.emit()
    
    def remove_selected(self):
        """删除选中项"""
        current_row = self.audio_list.currentRow()
        if current_row >= 0:
            item = self.audio_list.takeItem(current_row)
            if item in self.audio_files:
                self.audio_files.remove(item)
            self.update_indices()
            self.log(f"已删除: {item.original_name}")
            self.audio_list_changed.emit()
    
    def clear_list(self):
        """清空列表"""
        if not self.audio_files:
            return
        
        reply = QMessageBox.question(
            self, "确认清空", 
            f"确定要清空所有 {len(self.audio_files)} 首音频吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.audio_list.clear()
            self.audio_files.clear()
            self.update_indices()
            self.log("列表已清空")
            self.audio_list_changed.emit()
    
    def show_context_menu(self, position):
        """显示右键菜单"""
        menu = QMenu()
        
        remove_action = QAction("❌ 删除", self)
        remove_action.triggered.connect(self.remove_selected)
        menu.addAction(remove_action)
        
        menu.addSeparator()
        
        clear_action = QAction("🗑️ 清空全部", self)
        clear_action.triggered.connect(self.clear_list)
        menu.addAction(clear_action)
        
        menu.exec(self.audio_list.mapToGlobal(position))
    
    def prepare_files(self):
        """准备文件：拷贝到 audio_input 并生成映射"""
        if not self.audio_files:
            QMessageBox.warning(self, "警告", "请先导入音频文件")
            return
        
        try:
            project_dir = os.path.dirname(os.path.dirname(__file__))
            temp_folder = os.path.join(project_dir, 'audio_input')
            mapping_file = os.path.join(project_dir, 'data', 'file_mapping.json')
            
            # 确保目录存在
            os.makedirs(temp_folder, exist_ok=True)
            os.makedirs(os.path.dirname(mapping_file), exist_ok=True)
            
            # 清空临时目录
            for item in os.listdir(temp_folder):
                item_path = os.path.join(temp_folder, item)
                try:
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                except:
                    pass
            
            # 创建映射并拷贝文件
            file_mapping = {}
            for item in self.audio_files:
                idx = item.index
                original_path = item.file_path
                ext = Path(original_path).suffix
                temp_name = f"{idx}{ext}"
                temp_path = os.path.join(temp_folder, temp_name)
                
                # 拷贝文件
                shutil.copy2(original_path, temp_path)
                
                # 保存映射
                file_mapping[temp_name] = {
                    'original_name': item.original_name,
                    'original_path': original_path,
                    'temp_path': temp_path,
                    'index': idx
                }
            
            # 保存映射到JSON
            with open(mapping_file, 'w', encoding='utf-8') as f:
                json.dump(file_mapping, f, ensure_ascii=False, indent=2)
            
            self.log(f"准备完成！共 {len(self.audio_files)} 首音频已导入")
            QMessageBox.information(
                self, "完成", 
                f"音频准备完成！\n共导入 {len(self.audio_files)} 首歌曲\n\n"
                f"文件已保存到: {temp_folder}\n"
                f"映射已保存到: {mapping_file}"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"准备文件失败: {e}")
            self.log(f"准备文件错误: {e}")
    
    def log(self, message: str):
        """添加日志"""
        if self.parent_window:
            self.parent_window.log_message(f"[准备音频] {message}")
    
    def get_audio_count(self) -> int:
        """获取音频数量"""
        return len(self.audio_files)

    def get_audio_list(self) -> List[dict]:
        """获取音频列表信息"""
        return [
            {
                'index': item.index,
                'original_name': item.original_name,
                'file_path': item.file_path
            }
            for item in self.audio_files
        ]

    def clear_cache(self, silent: bool = False):
        """清理缓存文件

        Args:
            silent: 如果为True，不显示确认对话框（用于工作流完成后的自动询问）
        """
        if not silent:
            reply = QMessageBox.question(
                self, "确认清理",
                "确定要清理以下缓存目录吗？\n\n"
                "- audio_input\n"
                "- audio_output/metronome\n"
                "- audio_output/shifted_songs\n"
                "- data\n\n"
                "注意：final_mix（混音结果）不会被清理\n"
                "此操作不可恢复！",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            import shutil
            project_dir = os.path.dirname(os.path.dirname(__file__))

            # 注意：不再清理 final_mix，保护混音结果
            cache_dirs = [
                os.path.join(project_dir, 'audio_input'),
                os.path.join(project_dir, 'audio_output', 'metronome'),
                os.path.join(project_dir, 'audio_output', 'shifted_songs'),
                os.path.join(project_dir, 'data'),
            ]

            cleared_count = 0
            for dir_path in cache_dirs:
                if os.path.exists(dir_path):
                    for item in os.listdir(dir_path):
                        item_path = os.path.join(dir_path, item)
                        try:
                            if os.path.isfile(item_path):
                                os.remove(item_path)
                                cleared_count += 1
                            elif os.path.isdir(item_path):
                                shutil.rmtree(item_path)
                                cleared_count += 1
                        except Exception as e:
                            self.log(f"  清理失败 {item}: {e}")
                    self.log(f"已清理: {os.path.basename(dir_path)}")

            self.log(f"[缓存清理] 完成，共清理 {cleared_count} 项")
            if not silent:
                QMessageBox.information(self, "完成", f"缓存清理完成！\n共清理 {cleared_count} 项")
            return True

        except Exception as e:
            self.log(f"[缓存清理] 错误: {e}")
            return False
