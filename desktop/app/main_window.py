from __future__ import annotations

import json
import shutil
import tempfile
import threading
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import qrcode
from PySide6.QtCore import QObject, QSize, Qt, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QSystemTrayIcon,
    QStyle,
    QTabWidget,
    QTextBrowser,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
    QMenu,
)

from app.ai_provider import OpenAICompatibleProvider
from app.capture import capture_fullscreen, capture_region, normalize_bbox
from app.code_replay import KeyDrivenReplayController
from app.config import (
    DEFAULT_SHORTCUTS,
    ConfigStore,
    normalize_base_url,
    normalize_reasoning_effort,
    normalize_remote_settings,
    parse_extra_body,
    public_remote_settings,
    validate_reasoning_extra_body,
)
from app.discovery import DiscoveryPublisher, is_usable_lan_ipv4, local_ipv4
from app.events import EventHub
from app.gateway import GatewayApi, GatewayServer
from app.global_hotkeys import GlobalHotkeyManager, validate_shortcuts
from app.history import HistoryStore
from app.pairing import PairingManager
from app.region_capture import RegionCaptureManager
from app.task_engine import TaskEngine
from app.shortcut_edit import ShortcutCaptureEdit


COMMANDS = {
    "capture_fullscreen",
    "submit_buffer",
    "capture_and_submit",
    "clear_buffer",
    "switch_profile",
    "scroll_desktop_up",
    "scroll_desktop_down",
    "scroll_apps_up",
    "scroll_apps_down",
}
HEAVY_COMMANDS = {"capture_fullscreen", "submit_buffer", "capture_and_submit", "clear_buffer"}
SHORTCUT_ACTIONS = (
    ("capture_fullscreen", "整屏截图"),
    ("capture_multi", "多图截图"),
    ("capture_region", "区域截图"),
    ("submit_buffer", "提交当前缓冲"),
    ("capture_and_submit", "截图并立即提交"),
    ("clear_buffer", "清空截图缓冲"),
    ("next_profile", "切换下一个配置组"),
    ("replay_result", "代码/文本回放"),
    ("scroll_apps_up", "App 向上翻页"),
    ("scroll_apps_down", "App 向下翻页"),
    ("increase_app_font", "App 字体增大"),
    ("decrease_app_font", "App 字体减小"),
)


class RemoteCommandBridge(QObject):
    requested = Signal(str, object, str, str)
    settings_requested = Signal(object, str, str)


class DesktopSignals(QObject):
    task_changed = Signal(object)
    status = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self, config: ConfigStore) -> None:
        super().__init__()
        self.config = config
        self.events = EventHub()
        self.history = HistoryStore(str(config.data["storage"].get("history_dir") or ""))
        self.signals = DesktopSignals()
        self.signals.task_changed.connect(self._render_task)
        self.signals.status.connect(self._show_status)
        self.tasks = TaskEngine(self.history, self.events, self.signals.task_changed.emit)
        self.pairing = PairingManager(config)
        self.command_bridge = RemoteCommandBridge()
        self.command_bridge.requested.connect(self._execute_remote_command)
        self.command_bridge.settings_requested.connect(self._execute_remote_settings)
        self._command_lock = threading.Lock()
        self._heavy_command_pending = False
        self.buffer: list[Path] = []
        self.capture_mode = "single"
        self._quitting = False
        self._gateway: GatewayServer | None = None
        self._discovery: DiscoveryPublisher | None = None
        self._pair_code = ""
        self._pair_expiry = 0
        self._lan_address = ""
        self._latest_result_markdown = ""
        self.hotkeys = GlobalHotkeyManager()
        self.hotkeys.activated.connect(self._hotkey_activated)
        self.hotkeys.conflict.connect(self._hotkey_registration_failed)
        self.replay = KeyDrivenReplayController()
        self.replay.started.connect(self._replay_started)
        self.replay.stopped.connect(self._replay_stopped)
        self.replay.finished.connect(self._replay_finished)
        self.replay.progress_updated.connect(self._replay_progress)
        self.replay.error_occurred.connect(self._replay_error)
        self.region_capture = RegionCaptureManager()
        self.region_capture.selection_finished.connect(self._region_selected)
        self.region_capture.selection_error.connect(self._show_error)
        self.region_capture.selection_cancelled.connect(lambda: self._show_status("已取消区域截图"))
        self.setWindowTitle("Screen Assistant")
        self.resize(1180, 780)
        self._build_ui()
        self._setup_tray()
        self._load_all_ui()
        self._register_hotkeys()
        self._start_gateway()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        header = QHBoxLayout()
        self.connection_label = QLabel("LAN Gateway 启动中...")
        self.buffer_label = QLabel("截图缓冲：0")
        self.busy_label = QLabel("就绪")
        header.addWidget(self.connection_label)
        header.addStretch()
        header.addWidget(self.buffer_label)
        header.addWidget(self.busy_label)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._task_tab(), "任务")
        self.tabs.addTab(self._models_tab(), "模型连接")
        self.tabs.addTab(self._profiles_tab(), "配置组")
        self.tabs.addTab(self._history_tab(), "历史")
        self.tabs.addTab(self._lan_tab(), "局域网与配对")
        self.tabs.addTab(self._settings_tab(), "设置")
        layout.addWidget(self.tabs)
        self.setCentralWidget(root)
        self.statusBar().showMessage("就绪")

    def _task_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        for label, callback in (
            ("整屏截图", lambda: self._safe_action(lambda: self.capture_to_buffer(False))),
            ("多图截图", lambda: self._safe_action(lambda: self.capture_to_buffer(True))),
            ("区域截图", self.start_region_capture),
            ("提交缓冲", lambda: self._safe_action(self.submit_buffer)),
            ("清空缓冲", lambda: self._safe_action(self.clear_buffer)),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        self.replay_button = QPushButton("开始按键回放")
        self.replay_button.clicked.connect(self.replay_current_result)
        controls.addWidget(self.replay_button)
        controls.addStretch()
        layout.addLayout(controls)
        replay_options = QHBoxLayout()
        replay_config = self.config.data["replay"]
        self.replay_fast_mode = QCheckBox("长按快速回放")
        self.replay_fast_mode.setChecked(bool(replay_config.get("fast_mode")))
        self.replay_speed = QSpinBox()
        self.replay_speed.setRange(3, 30)
        self.replay_speed.setSuffix(" 字符/秒")
        self.replay_speed.setValue(int(replay_config.get("chars_per_second") or 12))
        self.replay_jitter = QSpinBox()
        self.replay_jitter.setRange(0, 40)
        self.replay_jitter.setSuffix("%")
        self.replay_jitter.setValue(int(replay_config.get("jitter_percent") or 15))
        self.replay_fast_mode.toggled.connect(self._save_replay_options)
        self.replay_speed.valueChanged.connect(self._save_replay_options)
        self.replay_jitter.valueChanged.connect(self._save_replay_options)
        replay_options.addWidget(self.replay_fast_mode)
        replay_options.addWidget(QLabel("固定速度"))
        replay_options.addWidget(self.replay_speed)
        replay_options.addWidget(QLabel("随机浮动"))
        replay_options.addWidget(self.replay_jitter)
        replay_options.addStretch()
        layout.addLayout(replay_options)
        self.replay_status = QLabel("按键回放未启动：开始后，每按一次有效按键输出下一个字符，Esc停止")
        layout.addWidget(self.replay_status)
        buffer_splitter = QSplitter(Qt.Orientation.Horizontal)
        buffer_splitter.setMinimumHeight(190)
        buffer_splitter.setMaximumHeight(240)
        self.buffer_list = QListWidget()
        self.buffer_list.setViewMode(QListView.ViewMode.IconMode)
        self.buffer_list.setFlow(QListView.Flow.LeftToRight)
        self.buffer_list.setWrapping(False)
        self.buffer_list.setIconSize(QSize(150, 90))
        self.buffer_list.setGridSize(QSize(170, 125))
        self.buffer_list.setSpacing(6)
        self.buffer_list.currentRowChanged.connect(self._show_buffer_preview)
        self.buffer_preview = QLabel("截图缓冲为空")
        self.buffer_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.buffer_preview.setMinimumSize(360, 180)
        self.buffer_preview.setStyleSheet("QLabel { background: #171717; color: #bdbdbd; border: 1px solid #555; }")
        buffer_splitter.addWidget(self.buffer_list)
        buffer_splitter.addWidget(self.buffer_preview)
        buffer_splitter.setSizes([540, 600])
        layout.addWidget(buffer_splitter)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.thinking_view = QTextBrowser()
        self.result_view = QTextBrowser()
        self.thinking_view.setPlaceholderText("模型思考流")
        self.result_view.setPlaceholderText("模型最终结果")
        splitter.addWidget(self.thinking_view)
        splitter.addWidget(self.result_view)
        splitter.setSizes([430, 650])
        layout.addWidget(splitter)
        return page

    def _models_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        left = QVBoxLayout()
        self.model_list = QListWidget()
        self.model_list.currentRowChanged.connect(self._load_model_editor)
        left.addWidget(self.model_list)
        buttons = QHBoxLayout()
        add = QPushButton("新增")
        add.clicked.connect(self.add_model)
        delete = QPushButton("删除")
        delete.clicked.connect(self.delete_model)
        buttons.addWidget(add)
        buttons.addWidget(delete)
        left.addLayout(buttons)
        layout.addLayout(left, 1)
        form_box = QGroupBox("模型连接")
        form = QFormLayout(form_box)
        self.model_name = QLineEdit()
        self.model_base_url = QLineEdit()
        self.model_api_key = QLineEdit()
        self.model_model = QLineEdit()
        self.model_timeout = QSpinBox()
        self.model_timeout.setRange(5, 600)
        self.model_max_tokens = QSpinBox()
        self.model_max_tokens.setRange(1, 131072)
        self.model_reasoning_effort = QComboBox()
        for label, value in (
            ("自动（不发送）", ""),
            ("none", "none"),
            ("minimal", "minimal"),
            ("low", "low"),
            ("medium", "medium"),
            ("high", "high"),
            ("xhigh", "xhigh"),
            ("max", "max"),
        ):
            self.model_reasoning_effort.addItem(label, value)
        for label, widget in (
            ("名称", self.model_name), ("Base URL", self.model_base_url), ("API Key", self.model_api_key),
            ("模型名", self.model_model),
            ("请求总超时（思考 + 输出，秒）", self.model_timeout),
            ("Max Tokens", self.model_max_tokens),
            ("思考强度", self.model_reasoning_effort),
        ):
            form.addRow(label, widget)
        row = QHBoxLayout()
        save = QPushButton("保存模型连接")
        save.clicked.connect(self.save_model)
        test = QPushButton("测试连接")
        test.clicked.connect(self.test_model)
        row.addWidget(save)
        row.addWidget(test)
        form.addRow(row)
        layout.addWidget(form_box, 3)
        return page

    def _profiles_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        left = QVBoxLayout()
        self.profile_list = QListWidget()
        self.profile_list.currentRowChanged.connect(self._load_profile_editor)
        left.addWidget(self.profile_list)
        buttons = QHBoxLayout()
        add = QPushButton("新增")
        add.clicked.connect(self.add_profile)
        delete = QPushButton("删除")
        delete.clicked.connect(self.delete_profile)
        buttons.addWidget(add)
        buttons.addWidget(delete)
        left.addLayout(buttons)
        layout.addLayout(left, 1)
        box = QGroupBox("任务配置组")
        form = QFormLayout(box)
        self.profile_name = QLineEdit()
        self.profile_model = QComboBox()
        self.profile_system = QPlainTextEdit()
        self.profile_prompt = QPlainTextEdit()
        self.profile_extra_enabled = QCheckBox("发送 extra_body")
        self.profile_extra = QPlainTextEdit()
        self.profile_extra.setPlaceholderText('{\n  "enable_thinking": true\n}')
        form.addRow("名称", self.profile_name)
        form.addRow("模型连接", self.profile_model)
        form.addRow("System Prompt", self.profile_system)
        form.addRow("用户提示词", self.profile_prompt)
        form.addRow(self.profile_extra_enabled)
        form.addRow("extra_body JSON", self.profile_extra)
        row = QHBoxLayout()
        save = QPushButton("保存配置组")
        save.clicked.connect(self.save_profile)
        activate = QPushButton("设为当前配置")
        activate.clicked.connect(self.activate_selected_profile)
        row.addWidget(save)
        row.addWidget(activate)
        form.addRow(row)
        layout.addWidget(box, 3)
        return page

    def _history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_history)
        delete = QPushButton("删除所选")
        delete.clicked.connect(self.delete_selected_history)
        clear = QPushButton("清空历史")
        clear.clicked.connect(self.clear_history)
        controls.addWidget(refresh)
        controls.addWidget(delete)
        controls.addWidget(clear)
        controls.addStretch()
        layout.addLayout(controls)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.history_list = QListWidget()
        self.history_list.currentItemChanged.connect(self._show_history_item)
        self.history_view = QTextBrowser()
        splitter.addWidget(self.history_list)
        splitter.addWidget(self.history_view)
        splitter.setSizes([320, 800])
        layout.addWidget(splitter)
        return page

    def _lan_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        form_box = QGroupBox("连接信息")
        form = QFormLayout(form_box)
        self.lan_address_label = QLabel("-")
        self.pair_code_label = QLabel("点击生成配对码")
        self.pair_code_label.setStyleSheet("font-size: 28px; font-weight: bold")
        self.qr_label = QLabel()
        self.qr_label.setFixedSize(240, 240)
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        generate = QPushButton("生成新的二维码和配对码")
        generate.clicked.connect(self.generate_pairing)
        form.addRow("电脑地址", self.lan_address_label)
        form.addRow("六位配对码", self.pair_code_label)
        form.addRow(self.qr_label)
        form.addRow(generate)
        layout.addWidget(form_box, 2)
        devices_box = QGroupBox("已配对 App")
        devices_layout = QVBoxLayout(devices_box)
        self.device_list = QListWidget()
        revoke = QPushButton("撤销所选设备")
        revoke.clicked.connect(self.revoke_device)
        refresh = QPushButton("刷新设备列表")
        refresh.clicked.connect(self.refresh_devices)
        devices_layout.addWidget(self.device_list)
        devices_layout.addWidget(refresh)
        devices_layout.addWidget(revoke)
        layout.addWidget(devices_box, 2)
        return page

    def _settings_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.device_name = QLineEdit()
        self.gateway_port = QSpinBox()
        self.gateway_port.setRange(1024, 65535)
        self.advertise_address = QLineEdit()
        self.advertise_address.setPlaceholderText("留空自动检测，例如 192.168.1.10")
        self.history_dir = QLineEdit()
        choose = QPushButton("选择目录")
        choose.clicked.connect(self.choose_history_dir)
        storage_row = QHBoxLayout()
        storage_row.addWidget(self.history_dir)
        storage_row.addWidget(choose)
        self.close_mode = QComboBox()
        self.close_mode.addItem("最小化到托盘", "tray")
        self.close_mode.addItem("窗口和托盘均隐藏", "hidden")
        shortcut_box = QGroupBox("全局快捷键")
        shortcut_layout = QFormLayout(shortcut_box)
        self.shortcut_edits: dict[str, ShortcutCaptureEdit] = {}
        for action, label in SHORTCUT_ACTIONS:
            editor = ShortcutCaptureEdit()
            editor.recording_started.connect(self._pause_hotkeys_for_recording)
            editor.recording_finished.connect(self._resume_hotkeys_after_recording)
            editor.recording_cancelled.connect(self._shortcut_recording_cancelled)
            editor.candidate_changed.connect(
                lambda sequence, selected_action=action: self._preview_shortcut_candidate(selected_action, sequence)
            )
            self.shortcut_edits[action] = editor
            shortcut_layout.addRow(label, editor)
        shortcut_help = QLabel(
            "点击输入框后按组合键；Backspace/Delete 清空；Esc取消并恢复原值。"
            "冲突项会立即标红。F3 默认用于“提交当前缓冲”；若要分配给其他功能，"
            "请先清空原来的 F3。"
        )
        shortcut_help.setWordWrap(True)
        self.shortcut_status = QLabel("保存后立即生效")
        reset_shortcuts = QPushButton("恢复默认快捷键")
        reset_shortcuts.clicked.connect(self.reset_shortcuts)
        shortcut_layout.addRow(shortcut_help)
        shortcut_layout.addRow(self.shortcut_status)
        shortcut_layout.addRow(reset_shortcuts)
        save = QPushButton("保存全部设置（快捷键立即生效；端口需重启）")
        save.clicked.connect(self.save_settings)
        quit_button = QPushButton("完全退出")
        quit_button.clicked.connect(self.quit_completely)
        form.addRow("电脑名称", self.device_name)
        form.addRow("LAN 端口", self.gateway_port)
        form.addRow("对外配对 IPv4", self.advertise_address)
        form.addRow("历史目录（清空即不保存）", storage_row)
        form.addRow("关闭窗口时", self.close_mode)
        form.addRow(shortcut_box)
        form.addRow(save)
        form.addRow(quit_button)
        return page

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.tray.setToolTip("Screen Assistant")
        menu = QMenu()
        show_action = QAction("显示窗口", self)
        show_action.triggered.connect(self.show_from_instance)
        quit_action = QAction("完全退出", self)
        quit_action.triggered.connect(self.quit_completely)
        menu.addAction(show_action)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_from_instance() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)

    def _load_all_ui(self) -> None:
        self._reload_model_list()
        self._reload_profile_list()
        self.refresh_history()
        self.refresh_devices()
        self.device_name.setText(str(self.config.data.get("device_name") or ""))
        self.gateway_port.setValue(int(self.config.data["lan"].get("port") or 18765))
        self.advertise_address.setText(str(self.config.data["lan"].get("advertise_address") or ""))
        self.history_dir.setText(str(self.config.data["storage"].get("history_dir") or ""))
        index = self.close_mode.findData(self.config.data["ui"].get("close_mode"))
        self.close_mode.setCurrentIndex(max(0, index))
        for action, editor in self.shortcut_edits.items():
            editor.setText(str(self.config.data["shortcuts"].get(action) or ""))
        self._update_buffer_ui()

    def _reload_model_list(self) -> None:
        self.model_list.clear()
        for model in self.config.data["models"]:
            item = QListWidgetItem(model["name"])
            item.setData(Qt.ItemDataRole.UserRole, model["id"])
            self.model_list.addItem(item)
        self.model_list.setCurrentRow(0)
        self._reload_profile_model_combo()

    def _load_model_editor(self, row: int) -> None:
        if row < 0 or row >= len(self.config.data["models"]):
            return
        model = self.config.data["models"][row]
        self.model_name.setText(model["name"])
        self.model_base_url.setText(model["base_url"])
        self.model_api_key.setText(model["api_key"])
        self.model_model.setText(model["model"])
        self.model_timeout.setValue(model["timeout_seconds"])
        self.model_max_tokens.setValue(model["max_tokens"])
        effort_index = self.model_reasoning_effort.findData(model.get("reasoning_effort", ""))
        self.model_reasoning_effort.setCurrentIndex(max(0, effort_index))

    def _model_from_editor(self, original_id: str) -> dict[str, Any]:
        return {
            "id": original_id,
            "name": self.model_name.text().strip() or "模型配置",
            "base_url": normalize_base_url(self.model_base_url.text()),
            "api_key": self.model_api_key.text().strip(),
            "model": self.model_model.text().strip(),
            "timeout_seconds": self.model_timeout.value(),
            "max_tokens": self.model_max_tokens.value(),
            "reasoning_effort": normalize_reasoning_effort(
                self.model_reasoning_effort.currentData()
            ),
        }

    def add_model(self) -> None:
        self.config.data["models"].append({"id": uuid.uuid4().hex, "name": "新模型", "base_url": "", "api_key": "", "model": "", "timeout_seconds": 120, "max_tokens": 2048, "reasoning_effort": ""})
        self.config.save()
        self._reload_model_list()
        self.model_list.setCurrentRow(len(self.config.data["models"]) - 1)

    def delete_model(self) -> None:
        row = self.model_list.currentRow()
        if len(self.config.data["models"]) <= 1 or row < 0:
            self._show_error("至少保留一个模型连接")
            return
        model_id = self.config.data["models"][row]["id"]
        if any(profile.get("model_id") == model_id for profile in self.config.data["profiles"]):
            self._show_error("该模型仍被配置组使用")
            return
        self.config.data["models"].pop(row)
        self.config.save()
        self._reload_model_list()

    def save_model(self) -> None:
        row = self.model_list.currentRow()
        if row < 0:
            return
        original_id = self.config.data["models"][row]["id"]
        candidate = self._model_from_editor(original_id)
        try:
            for profile in self.config.data["profiles"]:
                if profile.get("model_id") == original_id:
                    validate_reasoning_extra_body(candidate, profile)
        except ValueError as exc:
            self._show_error(str(exc))
            return
        self.config.data["models"][row] = candidate
        self.config.save()
        self._reload_model_list()
        self.model_list.setCurrentRow(row)
        self._show_status("模型连接已保存")

    def test_model(self) -> None:
        row = self.model_list.currentRow()
        model = self._model_from_editor(self.config.data["models"][row]["id"])

        def work() -> None:
            try:
                provider = OpenAICompatibleProvider(model)
                try:
                    message = provider.test_connection()
                finally:
                    provider.close()
                self.signals.status.emit(message)
            except Exception as exc:
                self.signals.status.emit(f"连接失败：{exc}")

        threading.Thread(target=work, daemon=True).start()
        self._show_status("正在测试连接...")

    def _reload_profile_model_combo(self) -> None:
        if not hasattr(self, "profile_model"):
            return
        current = self.profile_model.currentData()
        self.profile_model.clear()
        for model in self.config.data["models"]:
            self.profile_model.addItem(model["name"], model["id"])
        index = self.profile_model.findData(current)
        if index >= 0:
            self.profile_model.setCurrentIndex(index)

    def _reload_profile_list(self) -> None:
        self.profile_list.clear()
        active = self.config.data.get("active_profile_id")
        active_row = 0
        for row, profile in enumerate(self.config.data["profiles"]):
            label = f"● {profile['name']}" if profile["id"] == active else profile["name"]
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, profile["id"])
            self.profile_list.addItem(item)
            if profile["id"] == active:
                active_row = row
        self._reload_profile_model_combo()
        self.profile_list.setCurrentRow(active_row)

    def _load_profile_editor(self, row: int) -> None:
        if row < 0 or row >= len(self.config.data["profiles"]):
            return
        profile = self.config.data["profiles"][row]
        self.profile_name.setText(profile["name"])
        index = self.profile_model.findData(profile["model_id"])
        self.profile_model.setCurrentIndex(max(0, index))
        self.profile_system.setPlainText(profile.get("system_prompt", ""))
        self.profile_prompt.setPlainText(profile.get("prompt_template", ""))
        self.profile_extra_enabled.setChecked(bool(profile.get("extra_body_enabled")))
        extra = profile.get("extra_body", {})
        self.profile_extra.setPlainText(extra if isinstance(extra, str) else json.dumps(extra, ensure_ascii=False, indent=2))

    def add_profile(self) -> None:
        self.config.data["profiles"].append({"id": uuid.uuid4().hex, "name": "新配置", "model_id": self.config.data["models"][0]["id"], "system_prompt": "", "prompt_template": "请分析这些截图。", "language": "auto", "extra_body_enabled": False, "extra_body": {}})
        self.config.save()
        self._reload_profile_list()
        self.profile_list.setCurrentRow(len(self.config.data["profiles"]) - 1)

    def delete_profile(self) -> None:
        row = self.profile_list.currentRow()
        if len(self.config.data["profiles"]) <= 1 or row < 0:
            self._show_error("至少保留一个配置组")
            return
        removed = self.config.data["profiles"].pop(row)
        if self.config.data.get("active_profile_id") == removed["id"]:
            self.config.data["active_profile_id"] = self.config.data["profiles"][0]["id"]
        self.config.save()
        self._reload_profile_list()
        self.events.publish("config_changed", active_profile=self._public_active_profile())

    def save_profile(self) -> None:
        row = self.profile_list.currentRow()
        if row < 0:
            return
        raw_extra = self.profile_extra.toPlainText().strip() or "{}"
        try:
            extra = json.loads(raw_extra)
            if not isinstance(extra, dict):
                raise ValueError
        except ValueError:
            self._show_error("extra_body 必须是 JSON 对象")
            return
        profile_id = self.config.data["profiles"][row]["id"]
        self.config.data["profiles"][row] = {
            "id": profile_id, "name": self.profile_name.text().strip() or "配置",
            "model_id": str(self.profile_model.currentData()), "system_prompt": self.profile_system.toPlainText(),
            "prompt_template": self.profile_prompt.toPlainText(), "language": "auto",
            "extra_body_enabled": self.profile_extra_enabled.isChecked(), "extra_body": extra,
        }
        try:
            parse_extra_body(self.config.data["profiles"][row])
            selected_model = next(
                model
                for model in self.config.data["models"]
                if model["id"] == self.config.data["profiles"][row]["model_id"]
            )
            validate_reasoning_extra_body(
                selected_model,
                self.config.data["profiles"][row],
            )
        except ValueError as exc:
            self._show_error(str(exc))
            return
        self.config.save()
        self._reload_profile_list()
        self.profile_list.setCurrentRow(row)
        self.events.publish("config_changed", active_profile=self._public_active_profile())
        self._show_status("配置组已保存")

    def activate_selected_profile(self) -> None:
        row = self.profile_list.currentRow()
        if row < 0:
            return
        self.config.data["active_profile_id"] = self.config.data["profiles"][row]["id"]
        self.config.save()
        self._reload_profile_list()
        self.events.publish("config_changed", active_profile=self._public_active_profile())
        self._show_status("当前配置已切换")

    def _capture_dir(self) -> Path:
        root = Path(tempfile.gettempdir()) / "screen-assistant" / "buffer"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def capture_to_buffer(self, multi: bool = False) -> None:
        if not multi:
            self._delete_buffer_files()
            self.buffer = []
        if len(self.buffer) >= 8:
            raise ValueError("每次任务最多 8 张截图")
        path = capture_fullscreen(self._capture_dir())
        self.buffer.append(path)
        self._update_buffer_ui()

    def start_region_capture(self) -> None:
        if not self.region_capture.start():
            self._show_status("区域截图已经在进行中")
        else:
            self._show_status("请点击两次选择区域，Esc 取消")

    @Slot(object)
    def _region_selected(self, points: object) -> None:
        first, second = points
        bbox = normalize_bbox(first, second)
        if bbox is None:
            self._show_error("区域无效")
            return
        self._delete_buffer_files()
        self.buffer = [capture_region(self._capture_dir(), bbox)]
        self._update_buffer_ui()

    def submit_buffer(self) -> str:
        paths = [path for path in self.buffer if path.exists()]
        profile = dict(self.config.active_profile())
        model = dict(self.config.model_for_profile(profile))
        replacing = self.tasks.busy
        task_id = self.tasks.start(
            profile,
            model,
            paths,
            ephemeral=True,
            replace_running=True,
        )
        self.buffer = []
        self._update_buffer_ui()
        self.busy_label.setText("模型处理中")
        if replacing:
            self._show_status("已废弃上一任务，开始处理新截图")
        return task_id

    def clear_buffer(self) -> None:
        self._delete_buffer_files()
        self.buffer = []
        self._update_buffer_ui()

    def _delete_buffer_files(self) -> None:
        for path in self.buffer:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _update_buffer_ui(self) -> None:
        self.buffer_label.setText(f"截图缓冲：{len(self.buffer)}")
        self.buffer_list.clear()
        for index, path in enumerate(self.buffer, start=1):
            item = QListWidgetItem(f"图 {index}")
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                item.setIcon(QIcon(pixmap))
                item.setToolTip(f"{path.name}\n{pixmap.width()} × {pixmap.height()}")
            self.buffer_list.addItem(item)
        if self.buffer:
            self.buffer_list.setCurrentRow(len(self.buffer) - 1)
        else:
            self._show_buffer_preview(-1)
        self.events.publish("buffer_changed", buffer_count=len(self.buffer))

    @Slot(int)
    def _show_buffer_preview(self, row: int) -> None:
        if row < 0 or row >= len(self.buffer):
            self.buffer_preview.clear()
            self.buffer_preview.setText("截图缓冲为空")
            return
        path = self.buffer[row]
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.buffer_preview.clear()
            self.buffer_preview.setText("无法加载截图预览")
            return
        self.buffer_preview.setPixmap(
            pixmap.scaled(
                QSize(560, 220),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.buffer_preview.setToolTip(f"{path.name}\n{pixmap.width()} × {pixmap.height()}")

    @Slot(object)
    def _render_task(self, task: object) -> None:
        if not isinstance(task, dict):
            return
        self.thinking_view.setMarkdown(str(task.get("thinking_text") or ""))
        result = str(task.get("result_text") or "")
        error = str(task.get("error_message") or "")
        self._latest_result_markdown = result
        self.result_view.setMarkdown(result if result else (f"**任务失败**\n\n{error}" if error else ""))
        self.busy_label.setText("模型处理中" if task.get("status") == "running" else str(task.get("status") or "就绪"))
        if task.get("status") in {"completed", "failed"}:
            self.refresh_history()

    def replay_current_result(self) -> None:
        if self.replay.active:
            self.replay.stop()
            return
        try:
            self.hotkeys.stop()
            self.replay.start(
                self._latest_result_markdown,
                fast_mode=self.replay_fast_mode.isChecked(),
                chars_per_second=self.replay_speed.value(),
                jitter_ratio=self.replay_jitter.value() / 100.0,
            )
            self._show_status("按键回放已启动：切换到目标输入框；Esc或按钮手动关闭")
        except ValueError as exc:
            self._register_hotkeys()
            self._show_error(str(exc))
        except Exception as exc:
            self._register_hotkeys()
            self._show_error(str(exc))

    @Slot(int)
    def _replay_started(self, total: int) -> None:
        self.replay_button.setText("停止代码回放（Esc）")
        self._set_replay_option_controls_enabled(False)
        if self.replay_fast_mode.isChecked():
            self.replay_status.setText(
                f"快速回放进行中：0 / {total}；长按按键约 {self.replay_speed.value()} 字符/秒，Esc停止"
            )
        else:
            self.replay_status.setText(f"按键回放进行中：0 / {total}；每次按键释放输出一个字符，Esc停止")

    @Slot(int, int)
    def _replay_stopped(self, current: int, total: int) -> None:
        self.replay_button.setText("开始按键回放")
        self._set_replay_option_controls_enabled(True)
        self.replay_status.setText(f"按键回放已停止：{current} / {total}")
        self._register_hotkeys()

    @Slot(int)
    def _replay_finished(self, total: int) -> None:
        self.replay_button.setText("关闭代码回放（Esc）")
        self.replay_status.setText(
            f"代码已全部回放：{total} / {total}；键盘保持锁定且不再输出，按 Esc 或按钮关闭"
        )

    @Slot(int, int)
    def _replay_progress(self, current: int, total: int) -> None:
        if self.replay.active:
            if current >= total:
                return
            self.replay_status.setText(f"按键回放进行中：{current} / {total}；Esc停止")

    @Slot(str)
    def _replay_error(self, message: str) -> None:
        self.replay_button.setText("开始按键回放")
        self._set_replay_option_controls_enabled(True)
        self.replay_status.setText(message)
        self._register_hotkeys()
        self._show_error(message)

    def _save_replay_options(self, _value: object = None) -> None:
        self.config.data["replay"] = {
            "fast_mode": self.replay_fast_mode.isChecked(),
            "chars_per_second": self.replay_speed.value(),
            "jitter_percent": self.replay_jitter.value(),
        }
        self.config.save()

    def _set_replay_option_controls_enabled(self, enabled: bool) -> None:
        self.replay_fast_mode.setEnabled(enabled)
        self.replay_speed.setEnabled(enabled)
        self.replay_jitter.setEnabled(enabled)

    def refresh_history(self) -> None:
        if not hasattr(self, "history_list"):
            return
        self.history_list.clear()
        for task in self.tasks.list_tasks():
            item = QListWidgetItem(f"{task.get('created_at', '')}  {task.get('status', '')}  {task.get('profile_name', '')}")
            item.setData(Qt.ItemDataRole.UserRole, task.get("id"))
            self.history_list.addItem(item)

    def _show_history_item(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        task = self.tasks.get_task(str(item.data(Qt.ItemDataRole.UserRole)))
        if task:
            self.history_view.setMarkdown(f"## 思考\n\n{task.get('thinking_text', '')}\n\n## 结果\n\n{task.get('result_text', '')}\n\n{task.get('error_message', '')}")

    def delete_selected_history(self) -> None:
        item = self.history_list.currentItem()
        if item and self.history.delete_task(str(item.data(Qt.ItemDataRole.UserRole))):
            self.refresh_history()

    def clear_history(self) -> None:
        if QMessageBox.question(self, "确认", "确认清空全部本地历史？") == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self.refresh_history()

    def choose_history_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择历史保存目录", self.history_dir.text())
        if selected:
            self.history_dir.setText(selected)

    def save_settings(self) -> None:
        requested = {action: editor.text() for action, editor in self.shortcut_edits.items()}
        shortcuts, errors = validate_shortcuts(requested)
        if errors:
            labels = dict(SHORTCUT_ACTIONS)
            details = "\n".join(f"{labels.get(action, action)}：{message}" for action, message in errors.items())
            self.shortcut_status.setText("快捷键未保存，请修正冲突或格式")
            QMessageBox.warning(self, "快捷键设置无效", details)
            return
        advertise_address = self.advertise_address.text().strip()
        if advertise_address and not is_usable_lan_ipv4(advertise_address):
            QMessageBox.warning(self, "配对地址无效", "对外配对地址必须是电脑当前使用的非回环 IPv4，例如 192.168.1.10。")
            return
        self.config.data["device_name"] = self.device_name.text().strip() or "Screen Assistant"
        self.config.data["lan"]["port"] = self.gateway_port.value()
        self.config.data["lan"]["advertise_address"] = advertise_address
        self.config.data["storage"]["history_dir"] = self.history_dir.text().strip()
        self.config.data["ui"]["close_mode"] = str(self.close_mode.currentData())
        self.config.data["shortcuts"] = shortcuts
        self.config.save()
        self.history.set_directory(self.config.data["storage"]["history_dir"])
        for action, editor in self.shortcut_edits.items():
            editor.setText(shortcuts[action])
        self._register_hotkeys()
        self.shortcut_status.setText("快捷键已保存并生效")
        self._show_status("设置已保存；快捷键已生效，端口和设备名将在重启后生效")

    def reset_shortcuts(self) -> None:
        for action, editor in self.shortcut_edits.items():
            editor.setText(DEFAULT_SHORTCUTS[action])
        self.shortcut_status.setText("已填入默认值，点击“保存全部设置”后生效")

    @Slot()
    def _pause_hotkeys_for_recording(self) -> None:
        if self.replay.active:
            self.replay.stop()
        self.hotkeys.suspend()
        self.hotkeys.stop()
        self.shortcut_status.setText("正在录制快捷键；当前全局快捷键已临时暂停")
        self.shortcut_status.setStyleSheet("color: #1565c0")

    @Slot()
    def _resume_hotkeys_after_recording(self) -> None:
        self._register_hotkeys()
        if "冲突" not in self.shortcut_status.text() and "无效" not in self.shortcut_status.text():
            self.shortcut_status.setText("录制完成；保存后使用新快捷键")
            self.shortcut_status.setStyleSheet("color: #2e7d32")

    @Slot()
    def _shortcut_recording_cancelled(self) -> None:
        self._register_hotkeys()
        self._preview_shortcut_candidate("", "")
        self.shortcut_status.setText("已取消录制，保留原快捷键")
        self.shortcut_status.setStyleSheet("color: #616161")

    def _preview_shortcut_candidate(self, _action: str, _sequence: str) -> None:
        requested = {action: editor.text() for action, editor in self.shortcut_edits.items()}
        _, errors = validate_shortcuts(requested)
        for action, editor in self.shortcut_edits.items():
            editor.set_validation_error(errors.get(action, ""))
        if errors:
            labels = dict(SHORTCUT_ACTIONS)
            affected = "、".join(labels.get(action, action) for action in errors)
            self.shortcut_status.setText(f"快捷键冲突或无效：{affected}")
            self.shortcut_status.setStyleSheet("color: #c62828; font-weight: bold")
        else:
            self.shortcut_status.setText("快捷键可用；点击“保存全部设置”后生效")
            self.shortcut_status.setStyleSheet("color: #2e7d32")

    def _start_gateway(self) -> None:
        if not self.config.data["lan"].get("enabled", True):
            return
        lan = self.config.data["lan"]
        api = GatewayApi(
            self.pairing,
            self.events,
            self.tasks,
            self.history,
            self.bootstrap_payload,
            self.handle_remote_command,
            self.config.public_profiles,
            self.remote_settings_snapshot,
            self.handle_remote_settings,
        )
        self._gateway = GatewayServer(api, str(lan.get("host") or "0.0.0.0"), int(lan.get("port") or 18765))
        self._gateway.start()
        self._refresh_discovery()

    def _refresh_discovery(self) -> None:
        lan = self.config.data["lan"]
        if self._discovery:
            self._discovery.stop()
            self._discovery = None
        try:
            address = local_ipv4(str(lan.get("advertise_address") or ""))
            self._lan_address = address
            self.lan_address_label.setText(f"http://{address}:{lan['port']}")
            self.connection_label.setText(f"LAN: {address}:{lan['port']}")
        except (OSError, ValueError, RuntimeError) as exc:
            self._lan_address = ""
            self.lan_address_label.setText("未检测到局域网 IPv4，请在设置中手动填写")
            self.connection_label.setText("LAN: 未检测到可用配对地址")
            self._show_status(str(exc))
            return
        publisher: DiscoveryPublisher | None = None
        try:
            publisher = DiscoveryPublisher(
                self.config.data["device_name"],
                self.config.data["device_id"],
                int(lan["port"]),
                address=address,
            )
            publisher.start()
            self._discovery = publisher
        except Exception as exc:
            if publisher:
                publisher.stop()
            self._discovery = None
            self._show_status(f"mDNS 发布失败，二维码和手动 IP 仍可使用：{exc}")

    def bootstrap_payload(self) -> dict[str, Any]:
        return {
            "protocol": 1,
            "desktop": {"id": self.config.data["device_id"], "name": self.config.data["device_name"]},
            "active_profile": self._public_active_profile(),
            "profiles": self.config.public_profiles(),
            "buffer_count": len(self.buffer),
            "busy": self.tasks.busy,
            "current_task": self.tasks.snapshot(),
            "tasks": self.tasks.list_tasks(),
        }

    def _public_active_profile(self) -> dict[str, str]:
        profile = self.config.active_profile()
        return {"id": profile["id"], "name": profile["name"]}

    def remote_settings_snapshot(self) -> dict[str, Any]:
        return public_remote_settings(self.config.data)

    def handle_remote_settings(
        self,
        payload: dict[str, Any],
        source_device_id: str,
    ) -> dict[str, Any]:
        normalized = normalize_remote_settings(self.config.data, payload)
        command_id = uuid.uuid4().hex
        self.command_bridge.settings_requested.emit(
            normalized,
            source_device_id,
            command_id,
        )
        return {"command_id": command_id, "status": "accepted"}

    @Slot(object, str, str)
    def _execute_remote_settings(
        self,
        normalized: object,
        source_device_id: str,
        command_id: str,
    ) -> None:
        try:
            if not isinstance(normalized, dict):
                raise ValueError("配置格式无效")
            self.config.data["models"] = normalized["models"]
            self.config.data["profiles"] = normalized["profiles"]
            self.config.data["active_profile_id"] = normalized["active_profile_id"]
            self.config.save()
            self._reload_model_list()
            self._reload_profile_list()
            self.events.publish(
                "settings_changed",
                source_device_id=source_device_id,
                active_profile=self._public_active_profile(),
                profiles=self.config.public_profiles(),
            )
            self.events.publish(
                "command_completed",
                command_id=command_id,
                command="update_settings",
            )
        except Exception as exc:
            self.events.publish(
                "command_failed",
                command_id=command_id,
                command="update_settings",
                message=str(exc),
            )

    def handle_remote_command(
        self,
        command: str,
        profile_id: str | None,
        source_device_id: str,
    ) -> dict[str, Any]:
        if command not in COMMANDS:
            raise ValueError(f"不支持的命令: {command}")
        if command in HEAVY_COMMANDS:
            with self._command_lock:
                if self._heavy_command_pending:
                    raise RuntimeError("busy: 另一个截图命令正在执行")
                self._heavy_command_pending = True
        command_id = uuid.uuid4().hex
        self.command_bridge.requested.emit(
            command,
            profile_id,
            command_id,
            source_device_id,
        )
        return {"command_id": command_id, "status": "accepted"}

    @Slot(str, object, str, str)
    def _execute_remote_command(
        self,
        command: str,
        profile_id: object,
        command_id: str,
        source_device_id: str,
    ) -> None:
        try:
            if command == "capture_fullscreen":
                self.capture_to_buffer(False)
            elif command == "submit_buffer":
                self.submit_buffer()
            elif command == "capture_and_submit":
                self.capture_to_buffer(False)
                self.submit_buffer()
            elif command == "clear_buffer":
                self.clear_buffer()
            elif command == "switch_profile":
                self._switch_profile_by_id(str(profile_id or ""))
            elif command in {
                "scroll_desktop_up",
                "scroll_desktop_down",
                "scroll_apps_up",
                "scroll_apps_down",
            }:
                self.events.publish(
                    "app_scroll",
                    direction="up" if command.endswith("up") else "down",
                    source_device_id=source_device_id,
                )
            self.events.publish("command_completed", command_id=command_id, command=command)
        except Exception as exc:
            self.events.publish("command_failed", command_id=command_id, command=command, message=str(exc))
            self._show_error(str(exc))
        finally:
            if command in HEAVY_COMMANDS:
                with self._command_lock:
                    self._heavy_command_pending = False

    def _switch_profile_by_id(self, profile_id: str) -> None:
        if not any(item["id"] == profile_id for item in self.config.data["profiles"]):
            raise ValueError("配置组不存在")
        self.config.data["active_profile_id"] = profile_id
        self.config.save()
        self._reload_profile_list()
        self.events.publish("config_changed", active_profile=self._public_active_profile())

    def generate_pairing(self) -> None:
        self._refresh_discovery()
        if not self._lan_address:
            QMessageBox.warning(
                self,
                "没有可用的局域网地址",
                "未检测到电脑的局域网 IPv4。请在“设置 → 对外配对 IPv4”填写电脑当前 IP，并保存后重试。",
            )
            return
        code, expiry = self.pairing.issue_code()
        self._pair_code, self._pair_expiry = code, expiry
        self.pair_code_label.setText(code)
        address = f"http://{self._lan_address}:{self.config.data['lan']['port']}"
        payload = json.dumps({"v": 1, "url": address, "desktop_id": self.config.data["device_id"], "code": code}, separators=(",", ":"))
        image = qrcode.make(payload)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue(), "PNG")
        self.qr_label.setPixmap(pixmap.scaled(230, 230, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def refresh_devices(self) -> None:
        self.device_list.clear()
        for device in self.config.data.get("paired_devices", []):
            item = QListWidgetItem(str(device.get("device_name") or device.get("device_id")))
            item.setData(Qt.ItemDataRole.UserRole, device.get("device_id"))
            self.device_list.addItem(item)

    def revoke_device(self) -> None:
        item = self.device_list.currentItem()
        if item and self.pairing.revoke(str(item.data(Qt.ItemDataRole.UserRole))):
            self.refresh_devices()

    def _register_hotkeys(self) -> None:
        self.hotkeys.register(self.config.data.get("shortcuts", {}))

    @Slot(str, str)
    def _hotkey_registration_failed(self, action: str, sequence: str) -> None:
        label = dict(SHORTCUT_ACTIONS).get(action, action)
        self.shortcut_status.setText(f"注册失败：{label}（{sequence or '空'}）")
        self._show_status(f"快捷键注册失败：{label} {sequence}")

    @Slot(str)
    def _hotkey_activated(self, action: str) -> None:
        try:
            if action == "capture_fullscreen": self.capture_to_buffer(False)
            elif action == "capture_multi": self.capture_to_buffer(True)
            elif action == "capture_region": self.start_region_capture()
            elif action == "submit_buffer": self.submit_buffer()
            elif action == "capture_and_submit":
                self.capture_to_buffer(False)
                self.submit_buffer()
            elif action == "clear_buffer": self.clear_buffer()
            elif action == "replay_result": self.replay_current_result()
            elif action == "next_profile":
                profiles = self.config.data["profiles"]
                current = next((i for i, p in enumerate(profiles) if p["id"] == self.config.data["active_profile_id"]), 0)
                self._switch_profile_by_id(profiles[(current + 1) % len(profiles)]["id"])
            elif action in {"scroll_apps_up", "scroll_apps_down"}:
                self._publish_app_control(
                    "app_scroll",
                    direction="up" if action.endswith("up") else "down",
                )
            elif action in {"increase_app_font", "decrease_app_font"}:
                self._publish_app_control(
                    "app_font_scale",
                    delta=0.1 if action == "increase_app_font" else -0.1,
                )
        except Exception as exc:
            self._show_error(str(exc))

    def _publish_app_control(self, event: str, **payload: Any) -> None:
        subscribers = self.events.subscriber_count
        self.events.publish(event, source_device_id="desktop", **payload)
        if subscribers:
            action = "App 翻页" if event == "app_scroll" else "App 字体调整"
            self._show_status(f"{action}已发送到 {subscribers} 个在线 App 连接")
        else:
            self._show_status("没有在线 App 事件连接，控制命令未送达")

    @Slot(str)
    def _show_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)

    @Slot(str)
    def _show_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 10000)

    def _safe_action(self, callback: Any) -> None:
        try:
            callback()
        except Exception as exc:
            self._show_error(str(exc))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._quitting:
            event.accept()
            return
        mode = self.config.data["ui"].get("close_mode", "tray")
        self.hide()
        if mode == "tray":
            self.tray.show()
            self.tray.showMessage("Screen Assistant", "软件继续在局域网中运行", QSystemTrayIcon.MessageIcon.Information, 2500)
        else:
            self.tray.hide()
        event.ignore()

    @Slot()
    def show_from_instance(self) -> None:
        self.tray.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @Slot()
    def quit_completely(self) -> None:
        if self.tasks.busy and QMessageBox.question(self, "任务正在运行", "退出会取消当前模型任务，是否继续？") != QMessageBox.StandardButton.Yes:
            return
        self._quitting = True
        self.replay.stop()
        self.tasks.cancel()
        self.hotkeys.stop()
        self.region_capture.stop()
        self._delete_buffer_files()
        temp_root = Path(tempfile.gettempdir()) / "screen-assistant"
        shutil.rmtree(temp_root, ignore_errors=True)
        if self._discovery:
            self._discovery.stop()
        if self._gateway:
            self._gateway.stop()
        self.tray.hide()
        QApplication.instance().quit()
