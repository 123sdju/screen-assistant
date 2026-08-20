# Screen Assistant

[English](README.md)

Screen Assistant 是一套不需要独立业务服务器的 Windows/Linux 截图 AI 助手，以及 Android/Web 局域网遥控客户端。桌面客户端负责截图、模型调用、本地历史和局域网网关；Android App 或浏览器 Web 端用于遥控、查看流式结果、修改模型与配置组，以及控制同一电脑下其他客户端的结果翻页。

项目不需要 PostgreSQL、账号系统、计费服务或单独部署的后端。

## 主要功能

- 整屏截图、区域截图和多图缓冲，并可在桌面端预览。
- 支持 Chat Completions 与 Responses 两类 OpenAI 兼容接口，可填写 API 根地址或完整端点 URL。
- “完整端点 URL”模式严格使用任意自定义地址，不修改路径或查询参数。
- 每个模型可设置思考强度；选择“自动”时请求不发送该字段。
- 可选发送 `extra_body` JSON Object，并原样传递给兼容服务。
- 可录制全局快捷键，实时显示冲突，按 Esc 取消录制。
- 按键驱动代码回放，修复编辑器自动缩进叠加，并自动切换英文输入布局。
- 可选长按快速回放，以固定速度加小幅随机波动连续输出。
- App 支持 mDNS 自动发现、二维码扫码和手动局域网地址配对。
- 通过 SSE 同步思考流、结果流、任务状态、配置变化和缓冲变化。
- App 结果正文支持 `0.8×–1.8×` 字体缩放，导航栏、状态栏和配置界面保持系统字体。
- App 中 Markdown 代码块在横竖屏均占满可用宽度并自动换行，无需左右滑动阅读长单行。
- 电脑全局快捷键可控制所有当前停留在结果页的在线 App 翻页和调整字体。
- 一部 App 可控制连接到同一电脑的其他 App 上下翻页。
- Android App 和浏览器 Web 端都支持可持久化的“专注模式”，只保留当前结果和必要状态。
- App 可新增、编辑、删除模型连接和任务配置组。
- 已有 API Key 不会通过局域网回显，App 只能保持、替换或清除。
- 可在浏览器打开 `http://<电脑局域网IP>:18765` 或 `/web`，使用二维码链接或手动地址连接，不必安装 Android App。

## 下载与安装

从 [GitHub Releases](../../releases/latest) 下载：

- `ScreenAssistant-Windows-x64.exe`：Windows 便携客户端。
- `ScreenAssistant-Linux-x86_64.tar.gz`：Linux x86_64 便携客户端。
- `ScreenAssistant-Android.apk`：Android ARM 安装包。
- `SHA256SUMS.txt`：两个安装文件的 SHA-256 校验值。

将桌面程序放在独立、可写的目录中运行。由于社区构建尚未进行商业代码签名，Windows 可能显示 SmartScreen 提示；Linux 安装方式和平台差异见 [Linux 桌面版](docs/linux.md)。Android 端需要允许当前浏览器或文件管理器安装未知来源 APK。

协议功能发生变化时，电脑端和 App 应使用相同版本。

## 首次使用

1. 在桌面软件的“模型连接”中填写 URL、URL 模式、接口格式、API Key、模型名、可选思考强度和请求总超时。“完整端点 URL”模式支持任意路径并原样保留查询参数。
2. 在“配置组”中设置 System Prompt、用户提示词和可选 `extra_body`。
3. 打开“局域网与配对”，生成六位配对码和二维码。
4. 确保手机和电脑连接同一个可信局域网。
5. App 可自动发现电脑、扫描二维码，或手动输入 `http://<电脑局域网IP>:18765`；Web 端可直接打开二维码链接，或访问 `http://<电脑局域网IP>:18765`（也支持 `/web`）后手动输入地址和配对码。
6. Windows 防火墙提示时，仅允许专用网络访问。

手机中的 `127.0.0.1` 和 `localhost` 指向手机自身，不能用于连接电脑。应填写电脑真实的局域网 IPv4，例如 `192.168.1.10`。

自动发现使用 DNS-SD 服务类型 `_screenasst._tcp.local`；局域网阻止组播时仍可使用二维码或手动 IP 配对。

## 安全和本地数据

- 桌面端在 EXE 同目录生成 `config.json`，其中可能包含明文 API Key。
- `config.json`、Token、数据库、截图、日志、缓存、虚拟环境、签名文件和构建产物均被 `.gitignore` 排除。
- 每部 App 使用独立 Bearer Token，可在桌面端单独撤销。
- App 读取模型设置时只能看到 Key 是否已配置，不会获得已有 Key 内容。
- 截图只保留在电脑端，不通过 App API 传输。
- 清空历史目录设置后，不创建 SQLite 历史库，任务截图只进入临时目录。
- 网关只适用于可信局域网，请勿把 `18765` 端口直接暴露到公网。

更多安全说明见 [SECURITY.md](SECURITY.md)。

## 代码回放

回放只提取 Markdown 代码块，不会回放普通中文说明。

普通模式下，每完成一次物理按键的按下和释放，就输出一个代码字符。快速模式下，长按任意非修饰键会按照设定字符速度和有限随机波动连续推进。

每次换行后，回放引擎会先覆盖目标编辑器自动产生的缩进，再按源码输入真实缩进。代码全部输出后，键盘仍保持拦截且不再输出，必须按 Esc 或点击“关闭代码回放”手动退出。

## 目录结构

```text
screen-assistant/
├─ desktop/   PySide6 桌面界面、任务引擎、历史和 LAN Gateway
├─ mobile/    Flutter Android App
├─ docs/      架构、配置和局域网协议
└─ scripts/   环境设置、测试、构建和 Release 打包脚本
```

二维码依赖 `mobile_scanner` 以 BSD-3-Clause 许可证保留在 `mobile/third_party/mobile_scanner`。

## 开发环境

要求：

- Windows 10/11，或 x86_64 Linux 桌面系统。
- Python 3.11 或更高版本。
- Flutter stable 3.29 或更高版本。
- Android SDK 和 JDK 17。
- PowerShell 5.1 或更高版本。

```powershell
git clone <repository-url>
cd screen-assistant

.\scripts\setup-desktop.ps1
.\scripts\run-desktop.ps1
```

如果 Flutter 不在 `PATH`，可将 `SCREEN_ASSISTANT_FLUTTER` 设置为 Flutter SDK 目录。脚本同时支持标准的 `ANDROID_HOME` 和 `JAVA_HOME` 环境变量。

运行全部检查：

```powershell
.\scripts\test.ps1
```

构建并整理 Release：

```powershell
.\scripts\build-desktop.ps1
.\scripts\build-apk.ps1
.\scripts\package-release.ps1 -Version 1.1.0
```

Linux 下执行：

```bash
bash scripts/build-linux.sh
```

构建输出不会进入 Git：

- `desktop/dist/ScreenAssistant.exe`
- `mobile/build/app/outputs/flutter-apk/app-release.apk`
- `release/linux/ScreenAssistant-Linux-x86_64.tar.gz`
- `release/v1.1.0/`

## 文档

- [架构说明](docs/architecture.md)
- [配置和本地数据](docs/configuration.md)
- [局域网协议](docs/protocol.md)
- [Linux 桌面版](docs/linux.md)
- [v1.1.0 手动测试清单](docs/manual-test-v1.1.0.md)
- [版本记录](CHANGELOG.md)

## 许可证

本项目使用 [MIT License](LICENSE)。第三方组件继续使用各自的许可证。
