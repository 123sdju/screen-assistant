# 配置和数据文件

桌面端始终在 EXE 同目录读写 `config.json`。开发模式下文件位于 `desktop/config.json`，也可通过 `SCREEN_ASSISTANT_HOME` 或 `SCREEN_ASSISTANT_CONFIG` 覆盖。

模型连接包含 `base_url`、URL 模式、接口格式、明文 `api_key`、模型名、请求总超时、`max_tokens` 和 `reasoning_effort`。URL 模式包括：

- 自动识别：识别标准 Chat Completions/Responses 后缀；根地址优先尝试 Chat，并在端点不存在或供应商明确要求 Responses 时回退。
- API 根地址：把填写值作为根地址，根据接口格式追加 `/chat/completions` 或 `/responses`。
- 完整端点 URL：HTTP 请求严格使用填写的完整地址，不追加、删除或重排路径和查询参数。自定义后缀无法自动判断响应协议，因此必须明确选择 Chat Completions 或 Responses。

自动识别模式可直接粘贴以 `/chat/completions`、`/v1/chat/completions` 或 `/v1/responses` 结尾的完整端点，桌面端会拆分根地址，避免重复拼接路径。

思考强度为空时请求不发送该字段；可选值为 `none`、`minimal`、`low`、`medium`、`high`、`xhigh` 和 `max`，实际支持范围由模型供应商决定。Chat Completions 使用顶层 `reasoning_effort`，Responses 使用 `reasoning.effort`。请求总超时同时覆盖思考和输出阶段，不提供非标准的“仅思考超时”。

LAN Gateway 默认监听 `0.0.0.0:18765`。`lan.advertise_address` 默认留空，由桌面端优先从 WLAN、物理以太网中自动选择配对地址，并降低 VPN、VirtualBox、Hyper-V 和 WSL 网卡优先级。多网卡环境可在“设置 → 对外配对 IPv4”填写电脑当前局域网 IPv4。禁止填写 `127.0.0.1`、`0.0.0.0` 和链路本地地址。

网关同时提供浏览器 Web 端：`/` 和 `/web` 都会返回 Web 客户端页面。桌面二维码使用带 `code` 和 `desktop_id` 查询参数的 Web 链接；浏览器打开后会自动填写地址和配对码并开始配对。Android App 继续兼容旧版 JSON 二维码。Web 和 Android 都可使用 SSE 结果流、历史、遥控、配置编辑、专注模式和结果字体调整。完整流程见 [Web 端说明](web.md)。

当 `extra_body_enabled=false` 时，请求不携带该参数；启用时 `extra_body` 必须是 JSON Object，并原样传给 OpenAI 兼容 SDK。

当模型连接已经设置 `reasoning_effort` 时，配置组的 `extra_body` 不得再次包含同名字段。需要供应商自定义值时，应把模型思考强度设为“自动”，再通过 `extra_body` 原样传递。

历史目录默认是 EXE 所在目录，数据实际保存到：

```text
<历史目录>\data\history.db
<历史目录>\data\screenshots\<task-id>\
```

清空历史目录输入框后，任务只保留在当前进程内存中，截图使用系统临时目录并在任务结束后删除。
