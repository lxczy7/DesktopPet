"""提醒服务验证：调度周期 / 开关 / 安静时段 / 触发内容"""
import sys
import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from features.reminders import ReminderService, DRINK_PHRASES, SIT_PHRASES
from config.settings_manager import settings

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(detail)) if detail else ""))


class FakePet:
    def __init__(self):
        self.spoken = []
        self.notified = []

    def speak(self, text):
        self.spoken.append(text)

    def notify(self, title, text):
        self.notified.append((title, text))


pet = FakePet()
svc = ReminderService(pet)

# ---------- 1. 正常启动 ----------
print("== 1. 调度启动 ==")
settings.set("reminders.enabled", True)
settings.set("reminders.drink_minutes", 30)
settings.set("reminders.sit_minutes", 40)
svc.reload()
check("1a. 喝水定时器已启动", svc._drink_timer.isActive())
check("1b. 久坐定时器已启动", svc._sit_timer.isActive())
check("1c. 喝水周期 = 30 分钟", svc._drink_timer.interval() == 30 * 60 * 1000,
      f"{svc._drink_timer.interval()} ms")
check("1d. 久坐周期 = 40 分钟", svc._sit_timer.interval() == 40 * 60 * 1000,
      f"{svc._sit_timer.interval()} ms")

# ---------- 2. 关闭提醒 ----------
print("== 2. 开关 ==")
settings.set("reminders.enabled", False)
svc.reload()
check("2a. 关闭后两个定时器都停止", not svc._drink_timer.isActive() and not svc._sit_timer.isActive())

settings.set("reminders.enabled", True)
svc.reload()

# ---------- 3. 间隔下限保护 ----------
print("== 3. 间隔下限 ==")
settings.set("reminders.drink_minutes", 1)   # 太小，应被抬到 5 分钟
svc.reload()
check("3a. 过小间隔被抬升到 5 分钟", svc._drink_timer.interval() == 5 * 60 * 1000,
      f"{svc._drink_timer.interval()} ms")

# ---------- 4. 安静时段 ----------
print("== 4. 安静时段 ==")
settings.set("reminders.quiet_start_hour", 22)
settings.set("reminders.quiet_end_hour", 8)

# 直接测判定函数（注入不同小时）
import features.reminders as rm
orig_dt = rm.datetime


class FakeDT(orig_dt.datetime):
    _hour = 12

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 16, cls._hour, 0, 0)


rm.datetime = type("M", (), {"datetime": FakeDT})

FakeDT._hour = 12
check("4a. 中午 12 点 -> 不安静", svc._in_quiet_hours() is False)
FakeDT._hour = 23
check("4b. 深夜 23 点 -> 安静（跨零点）", svc._in_quiet_hours() is True)
FakeDT._hour = 3
check("4c. 凌晨 3 点 -> 安静", svc._in_quiet_hours() is True)
FakeDT._hour = 7
check("4d. 早上 7 点 -> 安静（边界内）", svc._in_quiet_hours() is True)
FakeDT._hour = 8
check("4e. 早上 8 点 -> 解除安静（边界外）", svc._in_quiet_hours() is False)
FakeDT._hour = 21
check("4f. 晚 21 点 -> 不安静", svc._in_quiet_hours() is False)

# 安静时段不触发
FakeDT._hour = 23
pet.spoken.clear()
svc._fire(DRINK_PHRASES, "💧 喝水提醒")
check("4g. 安静时段内不打扰", len(pet.spoken) == 0)

# 非安静时段正常触发
FakeDT._hour = 12
pet.spoken.clear()
pet.notified.clear()
svc._fire(DRINK_PHRASES, "💧 喝水提醒")
check("4h. 正常时段触发：气泡", len(pet.spoken) == 1 and pet.spoken[0] in DRINK_PHRASES, pet.spoken)
check("4i. 正常时段触发：托盘通知", len(pet.notified) == 1 and pet.notified[0][0] == "💧 喝水提醒")

# ---------- 5. 停止 ----------
print("== 5. 停止 ==")
svc.stop()
check("5a. stop 后全部停止", not svc._drink_timer.isActive() and not svc._sit_timer.isActive())

# 恢复 datetime 与配置
rm.datetime = orig_dt
settings.set("reminders.enabled", True)
settings.set("reminders.drink_minutes", 45)
settings.set("reminders.sit_minutes", 60)
settings.set("reminders.quiet_start_hour", 22)
settings.set("reminders.quiet_end_hour", 8)

passed = sum(1 for _, ok in RESULTS if ok)
print(f"\n===== {passed}/{len(RESULTS)} PASS =====")
if passed != len(RESULTS):
    for n, ok in RESULTS:
        if not ok:
            print("  FAILED:", n)
    sys.exit(1)
sys.exit(0)
