# AIMP Now Playing → OBS

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078d6.svg)]()
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776ab.svg)]()

实时读取 AIMP 正在播放的歌曲信息，提供**桌面悬浮窗**与 **OBS 浏览器源**两种展示方式：封面、歌名、进度、实时歌词，支持多主题与深度自定义。

## 功能特性

- 🎵 实时获取 AIMP 播放状态、曲目信息、封面与进度（使用官方 Remote API，无需插件，支持点击/拖拽进度条跳转）
- 🎨 紧凑现代化双主题界面：支持深色 / 亮色一键切换（带圆形涟漪过渡与 Windows 原生标题栏深浅色同步）、顶部悬浮胶囊导航、60+ FPS 原生 GDI 滑入淡入切页、封面呼吸光晕、7 柱峰值保持频谱与流光进度条
- 🖥 桌面悬浮窗：无边框置顶、半透明、等比缩放、跨显示器拖动、全局快捷键锁定、开关淡入淡出动效，**不占用任务栏图标**
- 📺 OBS 浏览器源：8 套主题、九宫格定位、实时 16:9 微缩预览、自定义颜色/字体/控件显隐，改样式实时同步
- 📝 歌词：同步 LRC 逐行高亮，中日翻译双行显示，平滑滚动切换，支持本机字体搜索选择
- 💾 设置自动保存（含深/亮外观模式），重启不丢失
- 🎭 演示模式：顶部一键开启，让 GUI、悬浮窗与 OBS 覆盖页全部显示示例数据
- 🔔 最小化到托盘：点最小化收进右下角通知区，不占任务栏（悬浮窗保持正常显示且不留任务栏图标），单击恢复、右键可退出
- 📦 单文件 exe 发布，无需安装 Python

## 截图

![主界面（深色模式）](screenshot-gui.png)

![主界面（亮色模式）](screenshot-gui-light.png)

![覆盖页样式与实时预览](screenshot-settings.png)

![桌面悬浮窗](screenshot-floating.png)

![OBS 覆盖页](screenshot-overlay.png)

## 快速开始

### 直接使用 exe

从 Releases 下载 `AIMPNowPlaying.exe`，双击运行即可。首次启动需要几秒解压内置运行时。

### 从源码运行

仅支持 Windows，需要 Python 3.10+。

```powershell
python -m pip install -r requirements.txt
python main.py
```

只运行后台服务（无 GUI）：

```powershell
python main.py --headless
```

## OBS 集成

1. OBS 中添加“浏览器（Browser）”源
2. URL 填 `http://127.0.0.1:8765/`
3. 宽度建议 `460`，高度 `240`，按需调整

浏览器打开 `http://127.0.0.1:8765/preview` 可并排预览全部主题（模拟数据）。

### 主题

| 主题 | 说明 |
| --- | --- |
| `modern` | 默认深色卡片 |
| `glass` | 毛玻璃 + 青紫渐变 |
| `minimal` | 透明无边框极简 |
| `neon` | 霓虹发光 |
| `spotify` | Spotify 风格 |
| `light` | 白色卡片 |
| `bar` | 横向紧凑条（16:9 底部） |
| `center` | 竖屏居中（9:16） |

### 常用参数

```text
http://127.0.0.1:8765/?theme=neon&pos=bottom-right&width=460
```

| 参数 | 作用 |
| --- | --- |
| `theme` | 选择主题 |
| `pos` | 九宫格定位：`bottom-left` / `center` / `top-right` 等 |
| `coverside` | 封面位置：`left` / `right` / `top` |
| `bg` / `panel` | 页面/面板背景色 |
| `accent` / `accent2` | 强调色与进度条渐变终点 |
| `text` / `dim` | 主文字 / 次要文字颜色 |
| `width` / `fontsize` / `margin` | 宽度、字号、边距 |
| `lyricfont` | 歌词字体（本机字体名） |
| `cover` / `title` / `state` / `progress` / `lyrics` | 隐藏对应控件（`off`） |
| `hide` | 停止播放时隐藏面板（`stopped`） |
| `demo` | 模拟数据预览（`1`） |

## 手机查看

同一 Wi-Fi 下，用 iPhone Safari 打开：

```text
http://电脑IP:8765/m
```

（`/mobile` 为同义路径。）页面竖屏/横屏自适应，显示封面、歌名、进度与歌词（支持 Enhanced LRC 逐字加粗），带与浏览器源一致的**歌词滚动动画**与**平滑进度条**，每 1.2 秒自动刷新。

**全屏使用**：iOS 不允许网页隐藏 Safari 地址栏；点击“分享 → 添加到主屏幕”后，从主屏幕图标打开即为独立全屏（已内置 PWA manifest 与图标）。页面使用动态视口高度（`100dvh`）自动填满屏幕。

**界面主题**：左下角 ◐ 按钮可切换主题，选择会记在本机。内含 Modern / Glass / Neon / Spotify / Light / Vinyl（黑胶暖调）/ Bloom（封面虚化沉浸）共 7 套；也可用 `http://电脑IP:8765/m?theme=vinyl` 直接指定。电脑端覆盖页的强调色仍可轻微染色手机界面。

**播放控制**：角落里的半透明 ⏯ 小按钮可展开播放控制（上一首 / 播放暂停 / 停止 / 下一首）。

**设备认证（默认关闭）**：

- 手机连接默认关闭，只有在 GUI 顶部「手机」标签页中启用后，设备才能连接
- 首次连接会出现在“待审核设备”中（顶部「手机」标签会亮起红点角标），点击“同意”后手机才能读取信息与发送播放控制；也可“拒绝”或稍后“移除”
- 从旧版本升级后，原先已授权的手机需要在电脑端**重新点一次“同意”**（设备密钥迁移会重置授权状态）
- `--headless` 模式下手机连接强制关闭

启动（局域网模式）：

```powershell
python main.py --host 0.0.0.0
```

> 安全：手机页面支持播放控制；`/api/config` 的写入仅允许本机（127.0.0.1），局域网设备无法修改样式。手机端读取状态/封面/歌词/控制均需已授权设备 token；token 由设备密钥（secret）换取，仅知道设备 ID 无法取回 token。关闭手机连接后服务会重新绑定回 `127.0.0.1`。

## 桌面悬浮窗

点击主界面右上角「悬浮窗」按钮打开，支持开关淡入淡出动效，且通过 `WS_EX_TOOLWINDOW` 保持不占用任务栏图标。

- 拖动：按住窗口任意位置拖动，支持跨显示器
- 缩放：`Ctrl + 鼠标滚轮` 等比缩放（40% ~ 250%）
- 锁定/解锁拖动：全局快捷键 `Ctrl + Shift + L`，切换时右下角短暂显示 🔒/🔓
- 右键菜单：播放控制（播放/暂停、上一首、下一首、停止）、外观（主题/透明度/缩放/歌词字号动画）、交互（锁定）、关闭

## 最小化到托盘

点主界面的最小化按钮后，程序不会留在任务栏，而是收进右下角通知区：

- 单击或双击托盘图标：平滑淡入恢复主窗口
- 右键托盘图标：菜单（显示主窗口 / 退出）
- 首次最小化会弹一个**静音**提示气泡（`NIIF_NOSOUND`，不播放提示音）
- 收进托盘期间程序照常运行：OBS 浏览器源、手机页面、桌面悬浮窗（保持置顶且不留任务栏图标）、导出文件都不中断

> Windows 11 默认把新出现的托盘图标收进通知区的折叠面板（`^`）；想让它常驻，可在「设置 → 个性化 → 任务栏 → 其他系统托盘图标」里打开。任务栏管理器重启（资源管理器崩溃恢复）后图标会自动重新注册。

## 配置

### 命令行参数

```text
--host 127.0.0.1     服务监听地址
--port 8765          服务端口
--refresh 300        状态刷新间隔（毫秒）
--export 目录        导出文件目录
--headless           无 GUI 模式
--version            显示版本号
```

### 设置保存

所有设置自动保存到 `%APPDATA%\AIMP-OBS-NowPlaying\settings.json`，命令行参数优先于已保存设置；可用环境变量 `AIMP_SETTINGS_PATH` 指定自定义位置。

### 导出文件

运行时会更新 `export/` 目录（默认在程序所在目录）：

- `nowplaying.json` — 完整 JSON 状态
- `nowplaying.txt` — 简单文本（标题/歌手/时间）
- `cover.png` — 当前封面
- `lyrics.lrc` — 当前歌词

## 从源码构建与测试

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
.\build_exe.ps1
```

GitHub Actions 会在 Windows 上自动执行测试并构建 exe。

## 技术栈

- Python 3.10+，`ctypes` 直接调用 Win32 API
- AIMP Remote API（窗口消息 + 共享内存 + `WM_COPYDATA` 封面）
- CustomTkinter（主界面）、Tkinter Canvas（悬浮窗）
- Pillow（图片处理）、tinytag（音频标签/内嵌封面歌词）
- PyInstaller（单文件打包）

## 项目结构

```text
AIMP-OBS-NowPlaying/
├── main.py                 入口（GUI / --headless）
├── aimp_obs/
│   ├── aimp_api.py         AIMP Remote API 封装
│   ├── lyrics.py           LRC/内嵌歌词解析
│   ├── cover.py            封面提取与缓存
│   ├── state.py            状态汇总与导出
│   ├── overlay.py          OBS 覆盖页（HTML/CSS/JS）
│   ├── mobile.py           手机端页面与 PWA 清单
│   ├── devices.py          局域网设备审批与 token 管理
│   ├── server.py           本地 HTTP 服务
│   ├── theme.py            深/亮主题色板、矢量图标与 Win32 GDI 合成工具
│   ├── widgets.py          自定义动画组件（过渡幕布、频谱、进度条、歌词、预览等）
│   ├── gui.py              CustomTkinter 紧凑主界面
│   ├── floating.py         桌面悬浮窗
│   ├── tray.py             系统托盘图标（Win32 Shell_NotifyIconW）
│   ├── demo.py             演示模式模拟数据
│   ├── settings.py         设置持久化
│   └── paths.py            源码/exe 路径工具
├── tests/                  单元测试
├── assets/                 应用图标
├── .github/workflows/      CI 构建
└── LICENSE
```

## 常见问题

**提示“未检测到 AIMP”**：请先启动 AIMP；AIMP 重启后程序会自动重连。

**歌词不显示**：确认歌曲同目录存在同名 `.lrc`（例如 `歌手 - 歌名.lrc`），或音频内嵌歌词。

**端口被占用**：在设置中更换端口，或使用 `--port` 指定。

**封面不显示**：优先使用 AIMP 返回的封面，其次读取音频标签/同目录 `cover.jpg`、`folder.jpg`。

## 隐私

- 所有数据仅在本机处理，不会上传歌曲、歌词或封面
- 服务默认只监听 `127.0.0.1`；使用 `--host 0.0.0.0` 或启用手机连接时暴露到局域网，同一网络内设备需经审批并携带 token 才能读取状态/发送控制，覆盖页样式写入始终仅限本机

## 贡献

欢迎提交 Issue 和 Pull Request：

- 报告问题前请提供 AIMP 版本、Python 版本、复现步骤
- 代码风格跟随现有项目，提交前请运行 `python -m pytest`
- 重大变更请先开 Issue 讨论

## 许可证

本项目采用 **MIT**（见 [LICENSE](LICENSE)）。

主要依赖许可证：

- tinytag：MIT
- Pillow：HPND
- CustomTkinter：MIT
- PyInstaller：GPL-2.0-or-later（含分发例外）

> `assets/icon.ico` 为项目作者提供的 logo，随项目以 MIT 许可发布。

## 致谢

- [AIMP](https://www.aimp.ru/) 及其官方 Remote API / SDK
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)
- [Pillow](https://python-pillow.org/)
- [tinytag](https://github.com/tinytag/tinytag)
- [PyInstaller](https://pyinstaller.org/)
