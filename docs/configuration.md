# 配置和数据文件

桌面端始终在 EXE 同目录读写 `config.json`。开发模式下文件位于 `desktop/config.json`，也可通过 `SCREEN_ASSISTANT_HOME` 或 `SCREEN_ASSISTANT_CONFIG` 覆盖。

模型连接包含 `base_url`、明文 `api_key`、模型名、请求总超时、`max_tokens` 和 `reasoning_effort`。思考强度为空时请求不发送该字段；可选值为 `none`、`minimal`、`low`、`medium`、`high`、`xhigh` 和 `max`，实际支持范围由模型供应商决定。请求总超时同时覆盖思考和输出阶段，不提供非标准的“仅思考超时”。

LAN Gateway 默认监听 `0.0.0.0:18765`。`lan.advertise_address` 默认留空，由桌面端优先从 WLAN、物理以太网中自动选择配对地址，并降低 VPN、VirtualBox、Hyper-V 和 WSL 网卡优先级。多网卡环境可在“设置 → 对外配对 IPv4”填写电脑当前局域网 IPv4。禁止填写 `127.0.0.1`、`0.0.0.0` 和链路本地地址。

当 `extra_body_enabled=false` 时，请求不携带该参数；启用时 `extra_body` 必须是 JSON Object，并原样传给 OpenAI 兼容 SDK。

当模型连接已经设置 `reasoning_effort` 时，配置组的 `extra_body` 不得再次包含同名字段。需要供应商自定义值时，应把模型思考强度设为“自动”，再通过 `extra_body` 原样传递。

历史目录默认是 EXE 所在目录，数据实际保存到：

```text
<历史目录>\data\history.db
<历史目录>\data\screenshots\<task-id>\
```

清空历史目录输入框后，任务只保留在当前进程内存中，截图使用系统临时目录并在任务结束后删除。
