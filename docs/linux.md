# Linux 桌面版

Linux 首版提供 PySide6 桌面界面、整屏/区域/多图截图、AI 流式请求、本地历史、LAN Gateway、配对和 App 控制。发布产物为 `ScreenAssistant-Linux-x86_64.tar.gz`。

## 运行

解压后赋予执行权限并启动：

```bash
tar -xzf ScreenAssistant-Linux-x86_64.tar.gz
chmod +x ScreenAssistant
./ScreenAssistant
```

推荐 Ubuntu 24.04 或相近的 x86_64 桌面发行版。运行库通常需要 `libegl1`、`libxkbcommon-x11-0` 和 `libxcb-cursor0`。Pillow 截图后端在 X11 下需要 `scrot` 或 `gnome-screenshot`；Wayland 下能否截图取决于桌面环境的门户和截图工具策略。

## 平台差异

- 区域截图在 Linux 使用全屏半透明选区，拖动鼠标选择，Esc 取消。
- 全局快捷键使用非 root 的桌面输入监听。X11 通常可用；严格 Wayland 会话可能由合成器禁止全局监听，此时软件的按钮和 App 遥控仍可使用。
- Linux 首版不提供代码回放。该功能要求可靠拦截并替换其他应用的键盘输入，在 Wayland/X11 间无法同时做到免 root、行为一致且安全。
- 托盘图标是否显示取决于桌面环境是否启用 StatusNotifier/AppIndicator 支持。

## 本地构建

```bash
sudo apt-get install python3-venv libegl1 libxkbcommon-x11-0 libxcb-cursor0 scrot
bash scripts/build-linux.sh
```

产物位于 `release/linux/ScreenAssistant-Linux-x86_64.tar.gz`。推送 `v*` 标签后，Release 工作流会同时构建 Windows、Linux 和 Android 产物并生成统一 SHA-256 文件。
