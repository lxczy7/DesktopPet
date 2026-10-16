# 从 openpets 借鉴的功能清单

来源项目：`openpets-4.0.1`（Electron + TypeScript 的桌面宠物开源项目）
（Electron + TypeScript 的桌面宠物平台，代码不能直接用，但设计范式很适合移植）

---

## 一、本轮已落地（4 项）

| 功能 | 借鉴自 openpets | 实现位置 |
|---|---|---|
| **宠物大小可调（滑块实时预览）** | 宠物窗口尺寸配置思路 | `features/settings_dialog.py` + `core/pet_window.py: apply_pet_size` |
| **视线跟随鼠标** | `pet-window-gaze.ts`（按鼠标方位切朝向帧，100ms tick，移动时暂停） | `core/pet_window.py: _gaze_tick` + `paintEvent` 水平镜像 |
| **拖拽松手自由落体 + 落地弹跳** | `pet-motion-engine.ts` 的 physics（`vy += 2.2`，落地 `vy = -vy*bounce`） | `core/pet_window.py: _start_fall / _physics_tick` |
| **双击原地起跳** | reaction 系统里的 `jumping` / `success` 反应 | `core/pet_window.py: _start_jump` |

另外落地了一个"插件式"实用功能（参考 openpets 官方 `water-reminder` / `day-routine` 插件）：

| 功能 | 说明 |
|---|---|
| **健康提醒** | 喝水（45min）/ 久坐（60min），免打扰时段 22:00-8:00，气泡 + 托盘通知不弹窗 | `features/reminders.py` |

---

## 二、后续可做（按性价比排序）

### ⭐⭐⭐ 强烈推荐

**1. 宠物状态 / 陪伴养成**（借鉴 `openpets.virtual-pet` 插件）
- 记录：陪伴天数、互动次数、今日喂食/玩耍记录
- 右键菜单 → "宠物状态"：一个小面板显示"已经陪你 12 天啦 / 今天互动 8 次"
- 增加情感联结，用户更舍不得卸载。实现量小（本地 JSON 存计数即可）。

**2. 番茄钟 / 专注模式**（借鉴 `openpets.focus-buddy`，605 行）
- 右键 → "专注 25 分钟"，期间宠物进入"陪你工作"状态（打瞌睡/看书），
  结束时跳起来庆祝；可自定义 25/45/60 分钟
- 对写论文/备课场景非常实用。

**3. 整点报时 / 日程提醒**（借鉴 `openpets.reminders`）
- 整点报时（可关）、自定义提醒时间点（如"15:30 开会"）
- 复用现有 reminders 服务的调度框架，扩展成本低。

### ⭐⭐ 值得做

**4. 快捷启动器**（借鉴 `openpets.launch-buddy`，155 行）
- 右键 → "快捷启动"，注册常打开的文件夹/项目/程序
- 点一下就打开，比翻开始菜单快。对宣哥（多项目并行）实用。

**5. 更多动作帧 + 反应系统**（借鉴 `reaction-animation-mapping.ts`）
- 现在只有 idle/walk/sit/lie/interact 六种；openpets 有 9 种状态 + 11 种 reaction
- 可扩展：挥手（打招呼时）、转圈、打瞌睡、胜利跳
- 需要 ImageGen 生成新素材（约 4-6 张垫图帧），代码侧加状态即可。

**6. 宠物跟随鼠标跑**（借鉴 `motionSetFollowCursor`）
- 可选开关（默认关）：宠物会慢悠悠跟着鼠标跑
- 因为可能打扰工作，建议做成"点一下宠物它才跟着你"的一次性行为。

### ⭐ 锦上添花

**7. 多宠物 / 宠物画廊**（借鉴 `pet-pool` + 宠物包格式）
- 支持多个宠物形象，右键切换
- 需要成体系的素材包设计，工作量较大。

**8. 静音/音频**（借鉴 `ctx.audio`）
- 宠物动作配轻音效（走路、跳跃、提醒）
- 需要音效素材。

**9. AI 对话层**（借鉴 openpets 的 MCP / agent 集成）
- 接本地大模型（宣哥已有 vLLM 部署的 Qwen3.6），让宠物能真正聊天
- 技术可行（vLLM OpenAI 兼容接口），但是个大工程。

---

## 三、openpets 里"看看就好"的部分

这些是它的平台化设计，对单机小工具偏重，不必照搬：

- **插件 SDK v3**（沙箱 JS 运行时 + 权限模型 + 配额）
- **本地 IPC + MCP 服务端**（给 Claude Code / Cursor 等编码 agent 用）
- **团队/远程控制协议**（`team-service`、`remote-control`）
- **语音助手**（STT/TTS 实时对话，`voice-*` 系列十几个文件）
- **React/Tailwind 控制中心**（那种玻璃拟物 UI 风格倒是可以参考做设置面板美化）
