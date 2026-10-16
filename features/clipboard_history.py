"""
剪贴板历史
功能：
1. 监听系统剪贴板变化
2. 记录文本和图片历史
3. 右键菜单快速粘贴
4. 持久化存储（JSON）
"""

import json
import os
from pathlib import Path
from typing import List, Optional, Any, Dict
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, QSettings, Signal, QUrl
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QListWidget, QListWidgetItem,
    QAbstractItemView, QApplication
)
from PySide6.QtGui import QClipboard


class ClipboardHistoryItem:
    """剪贴板历史条目"""

    def __init__(self, data: Any, item_type: str, timestamp: datetime = None):
        self.data = data  # 原始数据（文本字符串或 QImage）
        self.type = item_type  # "text" 或 "image"
        self.timestamp = timestamp or datetime.now()
        self.formatted_time = self.timestamp.strftime("%m-%d %H:%M")

        # 预处理显示用的预览
        if item_type == "text":
            self.display_text = data[:50] + ("..." if len(data) > 50 else "")
            self.preview = data
        elif item_type == "image":
            if isinstance(data, QImage):
                self.preview = QPixmap.fromImage(data.scaled(60, 60, Qt.SmoothTransformation))
            elif isinstance(data, QPixmap):
                self.preview = data.scaled(60, 60, Qt.SmoothTransformation)
            else:
                self.preview = QPixmap(60, 60)
            self.display_text = f"图片 ({self.timestamp.strftime('%m-%d %H:%M')})"


class ClipboardHistoryModel(QObject):
    """剪贴板历史模型 - 提供数据给 UI"""

    history_changed = Signal()  # 历史列表变化信号
    item_copied = Signal(str)  # 复制信号（携带文本）

    def __init__(self, max_size: int = 50, parent=None):
        super().__init__(parent)
        self._max_size = max_size
        self._history: List[ClipboardHistoryItem] = []
        self._last_text: Optional[str] = None
        self._last_image: Optional[QImage] = None

        # 从配置加载已保存的历史
        self._load_saved_history()

        # 启动剪贴板监听定时器
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_clipboard)
        self._timer.start(500)  # 500ms 检查一次

    def _load_saved_history(self) -> None:
        """从配置文件加载已保存的历史"""
        settings = QSettings("DesktopPet", "ClipboardHistory")
        data = settings.value("history")
        if data:
            try:
                history_data = json.loads(data)
                for item in history_data:
                    if item.get("type") == "text":
                        self._history.append(ClipboardHistoryItem(item["data"], "text"))
                    elif item.get("type") == "image":
                        # 图片需要特殊处理，这里暂时跳过或存储路径
                        pass
                # 只保留最近 max_size 条
                self._history = self._history[-self._max_size:]
                self.history_changed.emit()
            except Exception as e:
                print(f"加载剪贴板历史失败: {e}")

    def _save_history(self) -> None:
        """保存历史到配置文件"""
        settings = QSettings("DesktopPet", "ClipboardHistory")
        save_data = []
        for item in self._history[-self._max_size:]:
            if item.type == "text":
                save_data.append({
                    "type": "text",
                    "data": item.data
                })
        settings.setValue("history", json.dumps(save_data, ensure_ascii=False))

    def _check_clipboard(self) -> None:
        """检查剪贴板是否有变化"""
        clipboard = QApplication.clipboard()

        # 检查文本变化
        current_text = clipboard.text()
        if current_text != self._last_text or not self._history:
            # 排除空文本
            if current_text.strip():
                self._add_text(current_text)
            self._last_text = current_text

        # 检查图片变化
        image = clipboard.image()
        if not image.isNull():
            if self._last_image is None or not self._images_equal(image, self._last_image):
                self._add_image(image)
            self._last_image = image

    def _images_equal(self, img1: QImage, img2: QImage) -> bool:
        """检查两张图片是否相等"""
        if img1.size() != img2.size():
            return False
        # 简单比较：转换为字节对比
        return img1.save("/tmp/img1.png") and img2.save("/tmp/img2.png")  # 简化处理

    def _add_text(self, text: str) -> None:
        """添加文本历史"""
        # 检查是否已存在完全相同的文本
        for item in self._history:
            if item.type == "text" and item.data == text:
                # 更新时间戳
                item.timestamp = datetime.now()
                item.formatted_time = item.timestamp.strftime("%m-%d %H:%M")
                item.display_text = item.data[:50] + ("..." if len(item.data) > 50 else "")
                self.history_changed.emit()
                return

        # 添加新条目
        new_item = ClipboardHistoryItem(text, "text")
        self._history.insert(0, new_item)  # 插入到最前

        # 超出限制删除最旧的
        if len(self._history) > self._max_size:
            self._history = self._history[:self._max_size]

        self.history_changed.emit()
        self._save_history()

    def _add_image(self, image: QImage) -> None:
        """添加图片历史"""
        # 检查是否已存在相同的图片（按哈希）
        img_hash = image.save("/tmp/clipboard_check.png")  # 简化：实际应比较尺寸+内容
        # 这里只做基本去重：如果最近 10 条都是图片且时间相近则跳过
        recent_images = [i for i in self._history[-10:] if i.type == "image"]
        if recent_images:
            # 简单判断：如果最后一条是图片且时间相差不超过 5分钟则跳过
            last_time = recent_images[-1].timestamp
            from datetime import timedelta
            if datetime.now() - last_time < timedelta(minutes=5):
                return

        new_item = ClipboardHistoryItem(image, "image")
        self._history.insert(0, new_item)

        # 超出限制删除最旧的
        if len(self._history) > self._max_size:
            self._history = self._history[:self._max_size]

        self.history_changed.emit()
        self._save_history()

    def get_history(self) -> List[ClipboardHistoryItem]:
        """获取历史列表"""
        return self._history

    def clear_history(self) -> None:
        """清空历史"""
        self._history = []
        self.history_changed.emit()
        self._save_history()

    def copy_to_clipboard(self, item: ClipboardHistoryItem, target_type: str = "text") -> None:
        """将历史条目复制回系统剪贴板"""
        clipboard = QApplication.clipboard()
        if item.type == "text":
            clipboard.setText(item.data)
        elif item.type == "image":
            clipboard.setImage(item.data)


class ClipboardHistoryDialog(QDialog):
    """剪贴板历史对话框"""

    def __init__(self, parent=None, model: ClipboardHistoryModel = None):
        super().__init__(parent)
        self._model = model or ClipboardHistoryModel()
        self.setWindowTitle("剪贴板历史")
        self.resize(400, 500)
        self.setModal(False)

        layout = QVBoxLayout(self)

        # 历史列表
        self._list_widget = QListWidget()
        self._list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list_widget.setFlow(QListWidget.LeftToRight)
        self._list_widget.setViewMode(QAbstractItemView.IconMode)
        self._list_widget.setIconSize((80, 80))

        # 实际应该显示自定义的委托项，这里简化：使用 listWidget 列表模式
        self._list_widget.setSelectionMode(QAbstractItemView.ListMode)
        layout.addWidget(self._list_widget)

        # 按钮栏
        from PySide6.QtWidgets import QHBoxLayout, QPushButton
        button_layout = QHBoxLayout()

        clear_btn = QPushButton("清空历史")
        clear_btn.clicked.connect(self._clear_history)
        button_layout.addWidget(clear_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        # 连接信号
        self._model.history_changed.connect(self._update_list)
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)

        # 初始化列表
        self._update_list()

    def _update_list(self) -> None:
        """更新列表显示"""
        self._list_widget.clear()
        for item in self._model.get_history():
            from PySide6.QtWidgets import QListWidgetItem as QListWidgetItem
            from PySide6.QtGui import QIcon

            # 创建自定义的列表项
            lst_item = QListWidgetItem(self._list_widget)

            if item.type == "text":
                lst_item.setText(f"{item.formatted_time}: {item.display_text}")
                lst_item.setToolTip(item.data)
                # 图标暂时使用文本图标
                lst_item.setIcon(QApplication.style().standardIcon(QStyle.SP_FileIcon))
            elif item.type == "image":
                lst_item.setText(item.display_text)
                if item.preview and not item.preview.isNull():
                    lst_item.setIcon(item.preview)
                else:
                    lst_item.setIcon(QApplication.style().standardIcon(QStyle.SP_FileIcon))
                lst_item.setToolTip("图片历史项")

            # 设置数据到列表项
            lst_item.setData(256, item)  # Qt.UserRole = 256

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        """双击项目：复制到剪贴板"""
        data = item.data(256)  # 获取 Qt.UserRole 的数据
        if data:
            ClipboardHistoryModel.copy_to_clipboard(None, data)


def main():
    """测试入口"""
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)

    model = ClipboardHistoryModel(max_size=30)
    dialog = ClipboardHistoryDialog(model=model)
    dialog.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()