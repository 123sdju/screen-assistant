# v1.2.1 手动测试清单

使用同一版本的本地构建或 GitHub Release 产物：

- `release/v1.2.1/ScreenAssistant-Windows-x64.exe`
- `release/v1.2.1/ScreenAssistant-Linux-x86_64.tar.gz`
- `release/v1.2.1/ScreenAssistant-Android.apk`

## 默认设置

- 新建配置或删除模型的 `max_tokens` 后重新读取，确认默认值为 `8192`，界面显示“Max Output Tokens（含思考）”。
- 已有显式 `max_tokens`（例如 `2048`）的模型重新读取后仍保持原值。
- 点击桌面端“恢复默认快捷键”，确认按功能顺序显示：`F1` 整屏截图、`F2` 多图截图、`F3` 区域截图、`F4` 提交缓冲、`F5` 截图并提交、`F6` 清空缓冲、`F7` 切换配置组、`F8` 回放、`F9`/`F10` App/Web 翻页、`F11`/`F12` App/Web 字体调整。
- 逐项录制、清空并保存快捷键，确认冲突提示和 Esc 取消行为仍然有效。

## 模型兼容性

- 使用支持 `max_completion_tokens` 的 Chat Completions 供应商执行连接测试和截图任务。
- 使用只接受旧 `max_tokens` 字段的兼容服务，确认客户端自动回退且任务不会重复显示成功。
- 设置 Responses 思考强度，确认支持 `reasoning.summary` 的服务可以正常输出；服务拒绝该可选字段时，客户端会重试不带 summary 的请求。
- 让模型返回不完整、错误或没有可见回答的响应，确认任务显示失败，不会误写成成功历史。
- 设置模型思考强度后，在 `extra_body` 中分别加入 `reasoning_effort` 或 `reasoning`，确认保存被阻止并提示重复配置。

## 多图截图与客户端常亮

- 在桌面、Android App 和 Web 端分别执行“多图截图”，确认每次追加一张整屏截图，最多保留 8 张并可提交。
- Android App 保持前台打开时确认屏幕不会自动熄灭。
- Web 页面打开时确认浏览器支持的 Screen Wake Lock 或媒体保活会被申请；切到后台再回到前台后重新尝试申请。浏览器不支持时应仅提示，不影响结果查看和遥控。

## 连接恢复与回归

- Android App 或 Web 端进入当前结果页，验证思考流、结果流、历史、配置、遥控、专注模式和字体调整。
- 中断局域网或 SSE 后，确认 Android App 提示手动重新连接，不会无限后台重试；Web 短暂断开仍可自动恢复。
- 撤销设备 Token，确认客户端提示重新配对，旧连接事件不能覆盖新连接。
- 回归整屏、区域、多图截图、截图提交、历史、代码回放、托盘和完全退出。
- Linux 在 X11 验证全局快捷键；严格 Wayland 下若合成器阻止监听，确认按钮、Web 和 App 遥控仍可用且程序不崩溃。

本清单用于 GitHub `v1.2.1` 发布验收。
