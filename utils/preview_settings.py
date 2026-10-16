"""给设置面板截个图，确认新加的"宠物大小""健康提醒"两个区块显示正常"""
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from features.settings_dialog import SettingsDialog

dlg = SettingsDialog()
dlg.resize(520, 860)
dlg.show()
app.processEvents()
app.processEvents()

out = Path(tempfile.gettempdir()) / "settings_preview.png"
dlg.grab().save(str(out))
print("saved:", out, dlg.size().width(), "x", dlg.size().height())

# 顺便验证控件值都读到了
s = dlg.get_settings()
for k in ("pet.size", "reminders.enabled", "reminders.drink_minutes",
          "reminders.sit_minutes", "reminders.quiet_start_hour", "reminders.quiet_end_hour"):
    print(f"  {k} = {s.get(k)}")

dlg.close()
sys.exit(0)
