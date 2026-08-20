# LAN 协议 v1

默认地址为 `http://<电脑局域网IP>:18765`。浏览器 Web 页面由同一个桌面网关提供。除 `/`、`/web`、`/health` 和 `/v1/pair` 外，所有接口要求：

```http
Authorization: Bearer <device-token>
```

## 配对

`POST /v1/pair`

```json
{"code":"123456","device_id":"app-abc","device_name":"Pixel"}
```

成功返回独立设备 Token。桌面端二维码现在是直接打开 Web 端的链接：

```text
http://192.168.1.10:18765/web?code=123456&desktop_id=pc-abc
```

Android 端仍兼容旧版 JSON 二维码；Web 端打开链接后会自动填入地址和配对码。

## Web 客户端

- `GET /` 和 `GET /web`：返回桌面端内嵌的 Web 客户端页面，不需要 Bearer Token。页面中的静态脚本和样式通过 `/web/` 路径加载。
- Web 页面可以直接使用当前地址中的 `code` 查询参数配对，例如 `http://<电脑局域网IP>:18765/web?code=123456&desktop_id=<电脑ID>`。打开二维码链接时，当前来源地址会覆盖浏览器中保存的旧桌面地址。
- Web 首次配对调用 `POST /v1/pair`，请求中的 `device_id` 以 `web-` 前缀标识浏览器设备。返回的 Token 保存在该浏览器当前来源的本地存储中。
- 配对后，Web 使用与 Android App 相同的 Bearer Token 接口：先读取 `/v1/bootstrap`，再订阅 `/v1/events`，并按需访问任务、配置和遥控接口。
- Web 不提供截图下载接口；截图、API Key 原文和桌面端运行文件不会通过这些接口返回。
- 点击“移除连接”会清除浏览器中的地址和 Token。桌面端撤销设备后，接口返回 `401`，Web 必须重新配对。

完整的浏览器操作流程、功能说明和故障排查见 [Web 端说明](web.md)。

## 状态和任务

- `GET /v1/bootstrap`：电脑、安全配置摘要、缓冲数、忙碌状态、当前任务和历史摘要。
- `GET /v1/status`：轻量状态。
- `GET /v1/profiles`：仅返回配置组 ID 与名称。
- `GET /v1/settings`：返回可由 App 编辑的模型连接和任务配置组；只返回 `api_key_configured`，绝不返回已有 API Key。
- `PUT /v1/settings`：整体保存模型连接和任务配置组。每个模型用 `api_key_action=keep|replace|clear` 控制 Key，`replace` 时才提交 `api_key`。
- `GET /v1/tasks`：纯文本历史摘要。
- `GET /v1/tasks/{id}`：思考、结果、错误和时间，不返回截图路径。
- `GET /v1/events`：SSE。事件包括 `connected`、`buffer_changed`、`config_changed`、`task_snapshot`、`thinking_delta`、`result_delta`、`completed`、`failed`、`app_scroll`、`app_font_scale`、`command_completed` 和 `command_failed`。

## 遥控命令

`POST /v1/commands`

```json
{"command":"switch_profile","profile_id":"profile-id"}
```

允许的命令：`capture_fullscreen`、`submit_buffer`、`capture_and_submit`、`clear_buffer`、`switch_profile`、`scroll_apps_up`、`scroll_apps_down`。旧版 `scroll_desktop_up`、`scroll_desktop_down` 作为兼容别名保留，但同样只广播 App 翻页，不控制电脑界面。

翻页命令产生的 SSE 示例：

```json
{"event":"app_scroll","direction":"down","source_device_id":"app-controller"}
```

所有连接到同一电脑的 App 都会收到事件；`source_device_id` 对应的控制端忽略自身事件。只有当前停留在结果页的 App 执行滚动，不会强制其他页面切换，也不会在重连后补执行。

桌面字体快捷键产生的 SSE 示例：

```json
{"event":"app_font_scale","delta":0.1,"source_device_id":"desktop"}
```

符合条件的 App 将字体缩放增加或减少 `0.1`，限制在 `0.8–1.8` 并写入安全存储。

DNS-SD 自动发现使用 `_screenasst._tcp.local`。二维码和手动 IP 配对不依赖 mDNS。

设置保存成功后广播 `settings_changed`。桌面端在 GUI 主线程更新 `config.json` 和编辑界面，所有 App 随后重新读取脱敏设置。

接口返回 `202` 和 `command_id`。最终执行结果通过 SSE 通知；同一时刻到达的截图命令仍串行处理。模型正在思考或输出时提交新截图，会立即废弃旧任务并以新任务替换；旧任务不写入历史，迟到的流事件按 `task_id` 丢弃。
