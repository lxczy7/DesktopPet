# -*- coding: utf-8 -*-
"""生成"截图编辑器能力演示图"（无头渲染，不需要真实屏幕）。

用途：给宣哥/学生展示编辑器各工具效果，或做文档配图。
产物：generated-images/编辑器功能演示_<日期>.png

用法：
  QT_QPA_FONTDIR="C:/Windows/Fonts" PYTHONPATH=. .venv/Scripts/python.exe utils/make_editor_demo.py
（QT_QPA_FONTDIR 指向系统字体目录，保证中文正常渲染）
"""
import os
import sys
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

import features.screenshot_tool as st  # noqa: E402
from features.screenshot_tool import EditorDialog  # noqa: E402


def build_source() -> QPixmap:
    """造一张"论文截图"风格的测试底图"""
    pm = QPixmap(820, 520)
    p = QPainter(pm)
    p.fillRect(0, 0, 820, 520, QColor(252, 251, 248))
    p.setPen(QColor(25, 25, 30))
    p.setFont(QFont("Microsoft YaHei", 16))
    p.drawText(32, 62, "III-C  损失函数 Loss")
    p.setFont(QFont("Microsoft YaHei", 12))
    p.setPen(QColor(60, 60, 70))
    for i, t in enumerate(["1.  L_CE：像素交叉熵，基础分类损失；",
                           "2.  L_Dice：Dice 损失，针对类别不均衡；",
                           "3.  消融表明 L_CE 占主导，Dice 作为辅助。"]):
        p.drawText(32, 116 + i * 36, t)
    p.setPen(QColor(200, 200, 205))
    p.drawRect(32, 230, 756, 250)
    p.setPen(QColor(120, 120, 130))
    p.setFont(QFont("Microsoft YaHei", 11))
    p.drawText(48, 268, "预测掩膜 / 真实标注 / 误差热力图")
    p.drawText(48, 300, "mIoU 0.7412    F1 0.8203    OA 0.9156")
    p.end()
    return pm


def main() -> None:
    pm = build_source()
    dlg = EditorDialog(pm)
    dlg.show()
    app.processEvents()
    dlg._zoom_100()
    app.processEvents()
    view = dlg._view

    def vp(sx, sy):
        """图片(场景)坐标 -> view 视口坐标，消除居中滚动偏移"""
        pt = view.mapFromScene(QPointF(sx, sy))
        return float(pt.x()), float(pt.y())

    def fire(kind, sx, sy, btns=Qt.MouseButton.LeftButton, btn=Qt.MouseButton.LeftButton):
        x, y = vp(sx, sy)
        e = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), btn, btns,
                        Qt.KeyboardModifier.NoModifier)
        {QMouseEvent.Type.MouseButtonPress: view.mousePressEvent,
         QMouseEvent.Type.MouseMove: view.mouseMoveEvent,
         QMouseEvent.Type.MouseButtonRelease: view.mouseReleaseEvent}[kind](e)

    def drag(x1, y1, x2, y2, n=10):
        fire(QMouseEvent.Type.MouseButtonPress, x1, y1)
        for i in range(1, n + 1):
            fire(QMouseEvent.Type.MouseMove, x1 + (x2 - x1) * i / n,
                 y1 + (y2 - y1) * i / n, btns=Qt.MouseButton.LeftButton)
        fire(QMouseEvent.Type.MouseButtonRelease, x2, y2, btns=Qt.MouseButton.NoButton)

    # 画笔下划线
    dlg._apply_tool("freehand")
    dlg._set_color("#ff9500")
    dlg._set_width(0)
    drag(30, 72, 210, 72, 12)
    # 矩形框选
    dlg._apply_tool("rect")
    dlg._set_color("#e62828")
    dlg._set_width(1)
    drag(232, 92, 440, 132)
    # 箭头指示
    dlg._apply_tool("arrow")
    dlg._set_color("#0a84ff")
    drag(636, 300, 470, 268)
    # 文字标注
    st.QInputDialog.getText = staticmethod(lambda *a, **k: ("这两项要一起看", True))
    dlg._apply_tool("text")
    dlg._set_color("#111111")
    fire(QMouseEvent.Type.MouseButtonPress, 400, 175)
    fire(QMouseEvent.Type.MouseButtonRelease, 400, 175, btns=Qt.MouseButton.NoButton)
    # 椭圆圈指标
    dlg._apply_tool("ellipse")
    dlg._set_color("#30d158")
    dlg._set_width(1)
    drag(44, 282, 356, 320)
    # 马赛克涂抹（盖住第 3 行文字右半，效果最直观）
    dlg._apply_tool("mosaic")
    for i in range(8):
        x = 330 + i * 26
        fire(QMouseEvent.Type.MouseButtonPress, x, 184)
        fire(QMouseEvent.Type.MouseMove, x, 184, btns=Qt.MouseButton.LeftButton)
        fire(QMouseEvent.Type.MouseButtonRelease, x, 184, btns=Qt.MouseButton.NoButton)

    out = dlg.render_result()
    dst = BASE / "generated-images" / f"编辑器功能演示_{date.today().isoformat()}.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(str(dst), "PNG")
    print(f"已生成: {dst}  ({out.width()}x{out.height()})")


if __name__ == "__main__":
    main()
