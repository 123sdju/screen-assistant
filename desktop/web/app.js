(() => {
  'use strict';

  const DEFAULT_MAX_TOKENS = 8192;

  const STORAGE = {
    baseUrl: 'screen-assistant.web.base-url',
    token: 'screen-assistant.web.token',
    deviceId: 'screen-assistant.web.device-id',
    deviceName: 'screen-assistant.web.device-name',
    fontScale: 'screen-assistant.web.font-scale',
    compactMode: 'screen-assistant.web.compact-mode',
  };

  const state = {
    baseUrl: '',
    token: '',
    deviceId: '',
    deviceName: 'Screen Assistant Web',
    fontScale: 1,
    compactMode: false,
    wakeLock: null,
    connected: false,
    eventStreamStarted: false,
    eventStreamConnected: false,
    explicitDisconnect: false,
    streamController: null,
    desktop: {},
    profiles: [],
    tasks: [],
    currentTask: null,
    activeProfileId: '',
    activeProfileName: '-',
    bufferCount: 0,
    busy: false,
    page: 'current',
    settings: null,
    settingsLoaded: false,
    settingsDirty: false,
    historyTaskId: '',
  };

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));

  document.addEventListener('DOMContentLoaded', init);

  function init() {
    restoreLocalState();
    bindEvents();
    const qrConnection = applyUrlParameters();
    applyFontScale();
    applyCompactMode();
    void requestScreenWakeLock();
    renderConnectionView();
    if (qrConnection) {
      setConnectionStatus('已读取二维码，正在自动配对...');
      window.setTimeout(() => pairAndConnect(), 0);
    } else if (state.token && state.baseUrl) {
      connectSaved();
    }
  }

  function bindEvents() {
    $('#pair-form').addEventListener('submit', (event) => {
      event.preventDefault();
      pairAndConnect();
    });
    $('#refresh-button').addEventListener('click', () => connectSaved());
    $('#forget-button').addEventListener('click', forgetDesktop);
    $('#history-refresh').addEventListener('click', () => loadBootstrap());
    $('#settings-reload').addEventListener('click', () => loadSettings(true));
    $('#add-model').addEventListener('click', () => openModelEditor());
    $('#add-profile').addEventListener('click', () => openProfileEditor());
    $('#save-settings').addEventListener('click', saveSettings);
    $('#settings-active-profile').addEventListener('change', (event) => {
      if (!state.settings) return;
      state.settings.active_profile_id = event.target.value;
      state.activeProfileId = event.target.value;
      state.settingsDirty = true;
      renderSettings();
    });
    $('#current-profile').addEventListener('change', (event) => {
      sendCommand('switch_profile', event.target.value);
    });
    $('#control-profile').addEventListener('change', (event) => {
      sendCommand('switch_profile', event.target.value);
    });
    $('#font-decrease').addEventListener('click', () => changeFontScale(-0.1));
    $('#font-increase').addEventListener('click', () => changeFontScale(0.1));
    $('#compact-mode-toggle').addEventListener('click', toggleCompactMode);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    document.addEventListener('pointerdown', handleWakeLockInteraction, { passive: true });
    document.addEventListener('keydown', handleWakeLockInteraction);
    window.addEventListener('pagehide', () => { void releaseScreenWakeLock(); });

    document.addEventListener('click', (event) => {
      const target = event.target.closest('button');
      if (!target) return;
      const page = target.dataset.page;
      if (page) {
        showPage(page);
        return;
      }
      const command = target.dataset.command;
      if (command) {
        sendCommand(command);
        return;
      }
      const settingsAction = target.dataset.settingsAction;
      if (settingsAction === 'edit-model') openModelEditor(Number(target.dataset.index));
      if (settingsAction === 'delete-model') deleteModel(Number(target.dataset.index));
      if (settingsAction === 'edit-profile') openProfileEditor(Number(target.dataset.index));
      if (settingsAction === 'delete-profile') deleteProfile(Number(target.dataset.index));
      if (target.dataset.historyId) openHistoryTask(target.dataset.historyId);
    });
  }

  function restoreLocalState() {
    state.baseUrl = localStorage.getItem(STORAGE.baseUrl) || '';
    state.token = localStorage.getItem(STORAGE.token) || '';
    state.deviceId = localStorage.getItem(STORAGE.deviceId) || createDeviceId();
    state.deviceName = localStorage.getItem(STORAGE.deviceName) || state.deviceName;
    state.fontScale = clamp(Number(localStorage.getItem(STORAGE.fontScale) || 1), 0.8, 1.8);
    state.compactMode = localStorage.getItem(STORAGE.compactMode) === 'true';
    localStorage.setItem(STORAGE.deviceId, state.deviceId);
    $('#device-name').value = state.deviceName;
    if (state.baseUrl) $('#base-url').value = state.baseUrl;
  }

  function applyUrlParameters() {
    const params = new URLSearchParams(window.location.search);
    const currentOrigin = window.location.origin;
    const code = String(params.get('code') || '').trim();
    const hasQrConnection = /^\d{6}$/.test(code) && currentOrigin.startsWith('http');
    if (hasQrConnection) {
      // A QR link is authoritative: do not reuse a stale address/token from another desktop.
      state.baseUrl = normalizeBaseUrl(currentOrigin);
      state.token = '';
      localStorage.removeItem(STORAGE.token);
      $('#base-url').value = state.baseUrl;
      $('#pair-code').value = code;
      if (params.get('name')) $('#device-name').value = params.get('name');
      return true;
    }
    if (!state.baseUrl && currentOrigin.startsWith('http')) {
      $('#base-url').value = currentOrigin;
    }
    if (code) $('#pair-code').value = code;
    if (params.get('name')) $('#device-name').value = params.get('name');
    return false;
  }

  function createDeviceId() {
    const random = typeof crypto !== 'undefined' && crypto.randomUUID
      ? crypto.randomUUID().replaceAll('-', '').slice(0, 12)
      : `${Date.now().toString(16)}${Math.floor(Math.random() * 0xffffff).toString(16)}`.slice(0, 12);
    return `web-${random}`;
  }

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, Number.isFinite(value) ? value : minimum));
  }

  function normalizeBaseUrl(value) {
    let raw = String(value || '').trim();
    if (!raw) return '';
    if (!/^https?:\/\//i.test(raw)) raw = `http://${raw}`;
    const url = new URL(raw);
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname) throw new Error('电脑地址必须是 HTTP/HTTPS 地址');
    if (url.pathname === '/web' || url.pathname === '/web/') url.pathname = '';
    url.search = '';
    url.hash = '';
    return url.toString().replace(/\/$/, '');
  }

  function saveConnection() {
    localStorage.setItem(STORAGE.baseUrl, state.baseUrl);
    localStorage.setItem(STORAGE.token, state.token);
    localStorage.setItem(STORAGE.deviceId, state.deviceId);
    localStorage.setItem(STORAGE.deviceName, state.deviceName);
  }

  function renderConnectionView() {
    $('#connect-view').hidden = state.connected;
    $('#app-view').hidden = !state.connected;
    if (!state.connected) {
      $('#pair-form button[type="submit"]').textContent = state.token ? '连接电脑' : '配对并连接';
    }
  }

  function setConnectionStatus(message, error = false) {
    const element = $('#connect-status');
    element.textContent = message;
    element.classList.toggle('error', error);
    $('#connection-summary').textContent = message;
  }

  async function pairAndConnect() {
    try {
      state.baseUrl = normalizeBaseUrl($('#base-url').value);
      const code = $('#pair-code').value.trim();
      state.deviceName = $('#device-name').value.trim() || 'Screen Assistant Web';
      if (!/^\d{6}$/.test(code)) throw new Error('请输入电脑端显示的六位配对码');
      $('#base-url').value = state.baseUrl;
      setConnectionStatus('正在配对...');
      const response = await request('/v1/pair', {
        method: 'POST',
        auth: false,
        body: { code, device_id: state.deviceId, device_name: state.deviceName },
      });
      state.token = String(response.token || '');
      if (!state.token) throw new Error('配对响应缺少 Token');
      saveConnection();
      window.history.replaceState({}, document.title, window.location.pathname);
      await connectSaved();
    } catch (error) {
      setConnectionStatus(`配对失败：${error.message}`, true);
    }
  }

  async function connectSaved() {
    if (!state.baseUrl || !state.token) {
      state.connected = false;
      renderConnectionView();
      return;
    }
    state.explicitDisconnect = false;
    stopEventStream();
    setConnectionStatus('正在连接电脑...');
    try {
      await loadBootstrap();
      state.connected = true;
      renderConnectionView();
      setConnectionStatus('已连接');
      startEventStream();
    } catch (error) {
      state.connected = false;
      if (error.status === 401) {
        state.token = '';
        saveConnection();
        setConnectionStatus('连接凭证已失效，请重新配对', true);
      } else {
        setConnectionStatus(`连接失败：${error.message}`, true);
      }
      renderConnectionView();
    }
  }

  async function loadBootstrap() {
    const data = await request('/v1/bootstrap');
    state.desktop = data.desktop || {};
    state.profiles = Array.isArray(data.profiles) ? data.profiles : [];
    state.tasks = Array.isArray(data.tasks) ? data.tasks : [];
    state.currentTask = data.current_task || null;
    state.activeProfileId = data.active_profile?.id || '';
    state.activeProfileName = data.active_profile?.name || '-';
    state.bufferCount = Number(data.buffer_count || 0);
    state.busy = data.busy === true;
    renderApp();
  }

  function startEventStream() {
    const controller = new AbortController();
    state.streamController = controller;
    state.eventStreamStarted = true;
    state.eventStreamConnected = false;
    runEventStream(controller).catch(() => {});
  }

  async function runEventStream(controller) {
    try {
      const response = await fetch(apiUrl('/v1/events'), {
        headers: authHeaders(),
        signal: controller.signal,
        cache: 'no-store',
      });
      if (!response.ok) throw await responseError(response);
      if (!response.body) throw new Error('浏览器不支持实时事件流');
      state.eventStreamConnected = true;
      renderApp();
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let dataLines = [];
      while (true) {
        const result = await reader.read();
        if (result.done) break;
        buffer += decoder.decode(result.value, { stream: true });
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line === '') {
            dispatchSseData(dataLines.join('\n'));
            dataLines = [];
          } else if (line.startsWith('data:')) {
            dataLines.push(line.slice(5).trim());
          }
        }
      }
      dispatchSseData(dataLines.join('\n'));
      throw new Error('实时事件连接已断开');
    } catch (error) {
      if (controller.signal.aborted || state.explicitDisconnect) return;
      if (error.status === 401) {
        state.token = '';
        saveConnection();
        state.connected = false;
        state.eventStreamConnected = false;
        renderConnectionView();
        setConnectionStatus('连接凭证已失效，请重新配对', true);
        return;
      }
      // Keep the already paired app visible while a mobile WebView retries SSE.
      // A transient stream failure must not look like a full page refresh or undo pairing.
      state.eventStreamConnected = false;
      state.connected = true;
      renderApp();
      window.setTimeout(() => {
        if (!state.explicitDisconnect && state.token) connectSaved();
      }, 3000);
    }
  }

  function dispatchSseData(raw) {
    if (!raw) return;
    try { handleEvent(JSON.parse(raw)); } catch (_) { /* Ignore malformed keep-alive frames. */ }
  }

  function stopEventStream() {
    if (state.streamController) state.streamController.abort();
    state.streamController = null;
    state.eventStreamStarted = false;
    state.eventStreamConnected = false;
  }

  function handleEvent(event) {
    const kind = event.event || '';
    const applyRemoteViewControl = shouldApplyRemoteViewControl(event);
    const reloadSettings = kind === 'settings_changed' && state.page === 'settings' && !state.settingsDirty;
    if (kind === 'connected') state.eventStreamConnected = true;
    if (kind === 'buffer_changed') state.bufferCount = Number(event.buffer_count || 0);
    if (kind === 'config_changed' && event.active_profile) {
      state.activeProfileId = event.active_profile.id || '';
      state.activeProfileName = event.active_profile.name || '-';
    }
    if (kind === 'settings_changed') {
      state.profiles = Array.isArray(event.profiles) ? event.profiles : state.profiles;
      if (event.active_profile) {
        state.activeProfileId = event.active_profile.id || '';
        state.activeProfileName = event.active_profile.name || '-';
      }
      if (!state.settingsDirty) state.settingsLoaded = false;
    }
    if (kind === 'task_snapshot' && event.task) {
      state.currentTask = { ...event.task };
      state.busy = true;
      state.page = 'current';
    }
    if (kind === 'thinking_delta' && matchesCurrentTask(event)) {
      state.currentTask.thinking_text = `${state.currentTask.thinking_text || ''}${event.delta || ''}`;
    }
    if (kind === 'result_delta' && matchesCurrentTask(event)) {
      state.currentTask.result_text = `${state.currentTask.result_text || ''}${event.delta || ''}`;
    }
    if ((kind === 'completed' || kind === 'failed') && event.task && event.task.id === state.currentTask?.id) {
      state.currentTask = { ...event.task };
      state.busy = false;
      state.tasks = [event.task, ...state.tasks.filter((item) => item.id !== event.task.id)];
    }
    if (kind === 'command_failed') showToast(event.message || '电脑执行命令失败', true);
    if (kind === 'app_scroll' && applyRemoteViewControl) {
      const page = $('#page-current');
      page.scrollBy({ top: page.clientHeight * (event.direction === 'up' ? -0.82 : 0.82), behavior: 'smooth' });
    }
    if (kind === 'app_font_scale' && applyRemoteViewControl) {
      const previous = state.fontScale;
      const delta = Number(event.delta || 0);
      if (delta !== 0) changeFontScale(delta);
      if (delta !== 0) {
        const reachedLimit = state.fontScale === previous;
        showToast(
          reachedLimit
            ? `已收到电脑字体调整，当前已到 ${state.fontScale.toFixed(1)}×边界`
            : `已同步电脑字体：${state.fontScale.toFixed(1)}×`,
        );
      }
    }
    renderApp();
    if (reloadSettings) void loadSettings();
  }

  function shouldApplyRemoteViewControl(event) {
    const source = String(event.source_device_id || '');
    return state.page === 'current' && (source === 'desktop' || source !== state.deviceId);
  }

  function matchesCurrentTask(event) {
    return Boolean(state.currentTask && event.task_id && event.task_id === state.currentTask.id);
  }

  async function request(path, options = {}) {
    const response = await fetch(apiUrl(path), {
      method: options.method || 'GET',
      headers: options.auth === false ? jsonHeaders() : authHeaders(),
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: 'no-store',
    });
    if (!response.ok) throw await responseError(response);
    if (response.status === 204) return {};
    return response.json();
  }

  async function responseError(response) {
    let message = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch (_) {}
    const error = new Error(message);
    error.status = response.status;
    return error;
  }

  function apiUrl(path) {
    return `${state.baseUrl}${path}`;
  }

  function jsonHeaders() {
    return { 'Content-Type': 'application/json', Accept: 'application/json' };
  }

  function authHeaders() {
    return { ...jsonHeaders(), Authorization: `Bearer ${state.token}` };
  }

  async function sendCommand(command, profileId = null) {
    if (!state.connected) return;
    try {
      const data = await request('/v1/commands', { method: 'POST', body: { command, profile_id: profileId } });
      showToast(data.status === 'accepted' ? '电脑已接受命令' : '命令已发送');
    } catch (error) {
      showToast(`命令失败：${error.message}`, true);
    }
  }

  async function openHistoryTask(taskId) {
    try {
      const task = await request(`/v1/tasks/${encodeURIComponent(taskId)}`);
      state.currentTask = task;
      state.historyTaskId = taskId;
      showPage('current');
      renderCurrent();
    } catch (error) {
      showToast(`加载历史失败：${error.message}`, true);
    }
  }

  function showPage(page) {
    if (state.compactMode && page !== 'current') return;
    state.page = page;
    $$('.nav-button').forEach((button) => button.classList.toggle('active', button.dataset.page === page));
    $$('[data-page-panel]').forEach((panel) => { panel.hidden = panel.dataset.pagePanel !== page; });
    if (page === 'settings') {
      if (!state.settingsLoaded) loadSettings();
      else renderSettings();
    }
    if (page === 'history') renderHistory();
    renderCurrent();
  }

  function renderApp() {
    renderConnectionView();
    $$('.nav-button').forEach((button) => button.classList.toggle('active', button.dataset.page === state.page));
    $$('[data-page-panel]').forEach((panel) => { panel.hidden = panel.dataset.pagePanel !== state.page; });
    $('#desktop-name').textContent = state.desktop.name || 'Screen Assistant';
    const streamSummary = state.eventStreamStarted && !state.eventStreamConnected
      ? ' · 实时同步重连中...'
      : '';
    $('#connection-summary').textContent = state.connected
      ? `已连接 · ${state.activeProfileName} · 缓冲 ${state.bufferCount} 张${state.busy ? ' · 处理中' : ''}${streamSummary}`
      : '未连接';
    renderProfiles();
    renderCurrent();
    renderHistory();
    if (state.settingsLoaded) renderSettings();
  }

  function renderProfiles() {
    const options = state.profiles.map((profile) => `<option value="${escapeAttribute(profile.id)}">${escapeHtml(profile.name || '配置')}</option>`).join('');
    ['current-profile', 'control-profile', 'settings-active-profile'].forEach((id) => {
      const select = $(`#${id}`);
      if (!select) return;
      const selected = id === 'settings-active-profile' && state.settings
        ? state.settings.active_profile_id
        : state.activeProfileId;
      select.innerHTML = options || '<option value="">暂无配置组</option>';
      if (selected) select.value = selected;
    });
    $('#active-profile-name').textContent = state.activeProfileName;
  }

  function renderCurrent() {
    if (!$('#page-current')) return;
    $('#task-status').textContent = state.busy ? '模型处理中' : (state.currentTask?.status || '就绪');
    $('#buffer-count').textContent = `${state.bufferCount} 张`;
    $('#active-profile-name').textContent = state.activeProfileName;
    const task = state.currentTask;
    const thinking = task?.thinking_text || '';
    const result = task?.result_text || '';
    const error = task?.error_message || '';
    const hasTask = Boolean(task);
    const hasTaskContent = Boolean(thinking || result || error);
    $('#current-empty').hidden = hasTask;
    $('#current-progress').hidden = !hasTask || hasTaskContent;
    $('#thinking-panel').hidden = !thinking;
    $('#result-panel').hidden = !result;
    setMarkdown('#thinking-content', thinking, '模型思考流会显示在这里。');
    setMarkdown('#result-content', result, '模型最终结果会显示在这里。');
    $('#thinking-state').textContent = thinking ? (state.busy ? '实时更新中' : '已完成') : '等待模型输出';
    $('#result-state').textContent = result ? (state.busy ? '实时更新中' : '已完成') : '等待模型输出';
    const errorElement = $('#task-error');
    errorElement.hidden = !error;
    errorElement.textContent = error;
  }

  function setMarkdown(selector, value, emptyMessage) {
    const element = $(selector);
    if (!value) {
      element.classList.add('empty');
      element.textContent = emptyMessage;
      return;
    }
    element.classList.remove('empty');
    element.innerHTML = renderMarkdown(value);
  }

  function renderMarkdown(value) {
    const blocks = [];
    const source = String(value || '').replace(/\r\n?/g, '\n').replace(/```([^\n]*)\n([\s\S]*?)(?:```|$)/g, (_match, language, code) => {
      const index = blocks.push({ language: String(language || '').trim(), code }) - 1;
      return `\u0000${index}\u0000`;
    });
    const lines = escapeHtml(source).split('\n');
    const output = [];
    let listOpen = false;
    const closeList = () => { if (listOpen) { output.push('</ul>'); listOpen = false; } };
    for (const line of lines) {
      const placeholder = line.match(/^\u0000(\d+)\u0000$/);
      if (placeholder) {
        closeList();
        const block = blocks[Number(placeholder[1])];
        const className = block.language ? ` class="language-${escapeAttribute(block.language)}"` : '';
        output.push(`<pre><code${className}>${escapeHtml(block.code)}</code></pre>`);
        continue;
      }
      if (!line.trim()) { closeList(); continue; }
      const heading = line.match(/^(#{1,3})\s+(.+)$/);
      if (heading) { closeList(); output.push(`<h${heading[1].length}>${inlineMarkdown(heading[2])}</h${heading[1].length}>`); continue; }
      const bullet = line.match(/^[-*]\s+(.+)$/);
      if (bullet) { if (!listOpen) { output.push('<ul>'); listOpen = true; } output.push(`<li>${inlineMarkdown(bullet[1])}</li>`); continue; }
      closeList();
      output.push(`<p>${inlineMarkdown(line)}</p>`);
    }
    closeList();
    return output.join('');
  }

  function inlineMarkdown(value) {
    return value
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
  }

  function escapeAttribute(value) {
    return escapeHtml(value).replace(/`/g, '&#96;');
  }

  function renderHistory() {
    const list = $('#history-list');
    if (!list) return;
    if (!state.tasks.length) {
      list.innerHTML = '<div class="empty-list">电脑还没有已保存的文本历史。</div>';
      $('#history-detail').textContent = '选择一条历史任务查看详情。';
      $('#history-detail').classList.add('empty');
      return;
    }
    list.innerHTML = state.tasks.map((task) => `
      <button class="history-item ${task.id === state.historyTaskId ? 'selected' : ''}" type="button" data-history-id="${escapeAttribute(task.id)}">
        <strong>${escapeHtml(task.profile_name || '任务')}</strong>
        <small>${escapeHtml(task.created_at || '')} · ${escapeHtml(task.status || '')}</small>
      </button>`).join('');
  }

  async function loadSettings(force = false) {
    if (state.settingsDirty && !force) {
      showToast('当前配置有未保存修改，请先保存或重新读取', true);
      return;
    }
    state.settingsLoaded = false;
    const status = $('#settings-status');
    status.hidden = false;
    status.textContent = '正在读取电脑配置...';
    try {
      const data = await request('/v1/settings');
      state.settings = {
        models: (data.models || []).map((model) => ({ ...model, api_key_action: 'keep' })),
        profiles: data.profiles || [],
        active_profile_id: data.active_profile_id || '',
      };
      state.settingsLoaded = true;
      state.settingsDirty = false;
      status.hidden = true;
      renderSettings();
    } catch (error) {
      status.hidden = false;
      status.classList.add('error');
      status.textContent = `配置读取失败：${error.message}`;
    }
  }

  function renderSettings() {
    if (!state.settings) return;
    const models = state.settings.models || [];
    const profiles = state.settings.profiles || [];
    $('#model-list').innerHTML = models.length ? models.map((model, index) => `
      <div class="setting-item">
        <div class="setting-item-main"><strong>${escapeHtml(model.name || '模型配置')}</strong><small>${escapeHtml(model.model || '未填写模型')} · Key ${model.api_key_configured ? '已设置' : '未设置'}</small></div>
        <div class="setting-item-actions"><button class="small-button" type="button" data-settings-action="edit-model" data-index="${index}">编辑</button><button class="small-button danger-button" type="button" data-settings-action="delete-model" data-index="${index}">删除</button></div>
      </div>`).join('') : '<div class="empty-list">至少新增一个模型连接。</div>';
    $('#profile-list').innerHTML = profiles.length ? profiles.map((profile, index) => `
      <div class="setting-item">
        <div class="setting-item-main"><strong>${profile.id === state.settings.active_profile_id ? '● ' : ''}${escapeHtml(profile.name || '配置')}</strong><small>${escapeHtml(modelName(profile.model_id))}</small></div>
        <div class="setting-item-actions"><button class="small-button" type="button" data-settings-action="edit-profile" data-index="${index}">编辑</button><button class="small-button danger-button" type="button" data-settings-action="delete-profile" data-index="${index}">删除</button></div>
      </div>`).join('') : '<div class="empty-list">至少新增一个配置组。</div>';
    const active = $('#settings-active-profile');
    active.innerHTML = profiles.map((profile) => `<option value="${escapeAttribute(profile.id)}">${escapeHtml(profile.name || '配置')}</option>`).join('');
    active.value = state.settings.active_profile_id;
    $('#save-settings').disabled = !state.settingsDirty;
  }

  function modelName(modelId) {
    return state.settings.models.find((model) => model.id === modelId)?.name || '未知模型连接';
  }

  function openModelEditor(index = null) {
    const current = index === null ? {
      id: `model-${Date.now()}`,
      name: '新模型', base_url: '', model: '', timeout_seconds: 120, max_tokens: DEFAULT_MAX_TOKENS,
      reasoning_effort: '', api_mode: 'auto', url_mode: 'auto', api_key_configured: false, api_key_action: 'replace',
    } : { ...state.settings.models[index] };
    const dialog = $('#editor-dialog');
    dialog.innerHTML = `
      <form class="editor-form" id="model-editor">
        <h3>${index === null ? '新增模型连接' : '编辑模型连接'}</h3>
        <div class="editor-grid">
          <label><span>名称</span><input name="name" value="${escapeAttribute(current.name)}" required /></label>
          <label><span>模型名</span><input name="model" value="${escapeAttribute(current.model)}" required /></label>
          <label class="full"><span>Base URL</span><input name="base_url" value="${escapeAttribute(current.base_url)}" placeholder="https://api.example.com/v1" required /></label>
          <label class="full"><span>新 API Key</span><input name="api_key" type="password" placeholder="${current.api_key_configured ? '已设置；留空保持原值' : '尚未设置'}" /></label>
          <label class="check-row full"><input name="clear_key" type="checkbox" /> <span>清除电脑中已保存的 API Key</span></label>
          <label><span>URL 模式</span><select name="url_mode">${urlModeOptions(current.url_mode)}</select></label>
          <label><span>接口格式</span><select name="api_mode">${apiModeOptions(current.api_mode)}</select></label>
          <label><span>请求总超时（秒）</span><input name="timeout_seconds" type="number" min="5" max="600" value="${Number(current.timeout_seconds || 120)}" /></label>
          <label><span>Max Output Tokens（含思考）</span><input name="max_tokens" type="number" min="1" max="131072" value="${Number(current.max_tokens || DEFAULT_MAX_TOKENS)}" /></label>
          <label class="full"><span>思考强度</span><select name="reasoning_effort">${reasoningOptions(current.reasoning_effort)}</select></label>
        </div>
        <div class="dialog-actions"><button class="secondary-button" type="button" data-dialog-cancel>取消</button><button class="primary-button" type="submit">确定</button></div>
      </form>`;
    dialog.showModal();
    dialog.querySelector('[data-dialog-cancel]').addEventListener('click', () => dialog.close());
    dialog.querySelector('form').addEventListener('submit', (event) => {
      event.preventDefault();
      const form = new FormData(event.target);
      const key = String(form.get('api_key') || '').trim();
      const clear = form.get('clear_key') === 'on';
      const updated = {
        ...current,
        id: current.id,
        name: String(form.get('name') || '').trim() || '模型配置',
        base_url: String(form.get('base_url') || '').trim(),
        model: String(form.get('model') || '').trim(),
        timeout_seconds: Number(form.get('timeout_seconds') || 120),
        max_tokens: Number(form.get('max_tokens') || DEFAULT_MAX_TOKENS),
        reasoning_effort: String(form.get('reasoning_effort') || ''),
        api_mode: String(form.get('api_mode') || 'auto'),
        url_mode: String(form.get('url_mode') || 'auto'),
        api_key_action: clear ? 'clear' : key ? 'replace' : (current.api_key_configured ? 'keep' : 'replace'),
      };
      if (key) updated.api_key = key;
      if (updated.api_key_action === 'clear') delete updated.api_key;
      if (index === null) state.settings.models.push(updated);
      else state.settings.models[index] = updated;
      state.settingsDirty = true;
      dialog.close();
      renderSettings();
    });
  }

  function openProfileEditor(index = null) {
    if (!state.settings.models.length) { showToast('请先新增模型连接', true); return; }
    const current = index === null ? {
      id: `profile-${Date.now()}`, name: '新配置', model_id: state.settings.models[0].id,
      system_prompt: '', prompt_template: '请分析这些截图。', language: 'auto', extra_body_enabled: false, extra_body: {},
    } : { ...state.settings.profiles[index] };
    const dialog = $('#editor-dialog');
    dialog.innerHTML = `
      <form class="editor-form" id="profile-editor">
        <h3>${index === null ? '新增配置组' : '编辑配置组'}</h3>
        <label><span>名称</span><input name="name" value="${escapeAttribute(current.name)}" required /></label>
        <label><span>模型连接</span><select name="model_id">${state.settings.models.map((model) => `<option value="${escapeAttribute(model.id)}" ${model.id === current.model_id ? 'selected' : ''}>${escapeHtml(model.name || '模型')}</option>`).join('')}</select></label>
        <label><span>System Prompt</span><textarea name="system_prompt">${escapeHtml(current.system_prompt || '')}</textarea></label>
        <label><span>用户提示词</span><textarea name="prompt_template">${escapeHtml(current.prompt_template || '')}</textarea></label>
        <label class="check-row"><input name="extra_body_enabled" type="checkbox" ${current.extra_body_enabled ? 'checked' : ''} /> <span>发送 extra_body</span></label>
        <label><span>extra_body JSON Object</span><textarea name="extra_body">${escapeHtml(JSON.stringify(current.extra_body || {}, null, 2))}</textarea></label>
        <div class="dialog-actions"><button class="secondary-button" type="button" data-dialog-cancel>取消</button><button class="primary-button" type="submit">确定</button></div>
      </form>`;
    dialog.showModal();
    dialog.querySelector('[data-dialog-cancel]').addEventListener('click', () => dialog.close());
    dialog.querySelector('form').addEventListener('submit', (event) => {
      event.preventDefault();
      const form = new FormData(event.target);
      let extra;
      try {
        extra = JSON.parse(String(form.get('extra_body') || '{}'));
        if (!extra || Array.isArray(extra) || typeof extra !== 'object') throw new Error();
      } catch (_) {
        showToast('extra_body 必须是有效的 JSON Object', true);
        return;
      }
      const updated = {
        ...current,
        name: String(form.get('name') || '').trim() || '配置',
        model_id: String(form.get('model_id') || state.settings.models[0].id),
        system_prompt: String(form.get('system_prompt') || ''),
        prompt_template: String(form.get('prompt_template') || ''),
        language: 'auto',
        extra_body_enabled: form.get('extra_body_enabled') === 'on',
        extra_body: extra,
      };
      if (index === null) state.settings.profiles.push(updated);
      else state.settings.profiles[index] = updated;
      if (!state.settings.active_profile_id) state.settings.active_profile_id = updated.id;
      state.settingsDirty = true;
      dialog.close();
      renderSettings();
    });
  }

  function deleteModel(index) {
    if (state.settings.models.length <= 1) { showToast('至少保留一个模型连接', true); return; }
    const id = state.settings.models[index].id;
    if (state.settings.profiles.some((profile) => profile.model_id === id)) { showToast('该模型仍被配置组使用，不能删除', true); return; }
    state.settings.models.splice(index, 1);
    state.settingsDirty = true;
    renderSettings();
  }

  function deleteProfile(index) {
    if (state.settings.profiles.length <= 1) { showToast('至少保留一个配置组', true); return; }
    const removed = state.settings.profiles.splice(index, 1)[0];
    if (state.settings.active_profile_id === removed.id) state.settings.active_profile_id = state.settings.profiles[0].id;
    state.settingsDirty = true;
    renderSettings();
  }

  async function saveSettings() {
    if (!state.settings || !state.settingsDirty) return;
    try {
      await request('/v1/settings', {
        method: 'PUT',
        body: { settings: { models: state.settings.models, profiles: state.settings.profiles, active_profile_id: state.settings.active_profile_id } },
      });
      state.settingsDirty = false;
      state.activeProfileId = state.settings.active_profile_id;
      const active = state.profiles.find((profile) => profile.id === state.activeProfileId);
      if (active) state.activeProfileName = active.name;
      renderSettings();
      renderApp();
      showToast('电脑已接受配置，正在保存并同步');
    } catch (error) {
      showToast(`保存失败：${error.message}`, true);
    }
  }

  function reasoningOptions(selected) {
    return ['', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'].map((value) => `<option value="${value}" ${value === (selected || '') ? 'selected' : ''}>${value || '自动（不发送）'}</option>`).join('');
  }

  function apiModeOptions(selected) {
    return [['auto', '自动'], ['chat_completions', 'Chat Completions'], ['responses', 'Responses']].map(([value, label]) => `<option value="${value}" ${value === (selected || 'auto') ? 'selected' : ''}>${label}</option>`).join('');
  }

  function urlModeOptions(selected) {
    return [['auto', '自动识别'], ['api_root', 'API 根地址'], ['full_endpoint', '完整端点 URL']].map(([value, label]) => `<option value="${value}" ${value === (selected || 'auto') ? 'selected' : ''}>${label}</option>`).join('');
  }

  function changeFontScale(delta, persist = true) {
    state.fontScale = clamp(state.fontScale + delta, 0.8, 1.8);
    if (persist) localStorage.setItem(STORAGE.fontScale, state.fontScale.toFixed(2));
    applyFontScale();
  }

  function applyFontScale() {
    document.documentElement.style.setProperty('--result-scale', state.fontScale.toFixed(2));
    $('#font-scale-label').textContent = `${state.fontScale.toFixed(1)}×`;
  }

  function toggleCompactMode() {
    state.compactMode = !state.compactMode;
    localStorage.setItem(STORAGE.compactMode, String(state.compactMode));
    applyCompactMode();
    if (state.compactMode) showPage('current');
    else renderApp();
  }

  function applyCompactMode() {
    document.body.classList.toggle('compact-mode', state.compactMode);
    const button = $('#compact-mode-toggle');
    if (!button) return;
    button.setAttribute('aria-pressed', String(state.compactMode));
    button.textContent = state.compactMode ? '完整' : '专注';
    button.title = state.compactMode ? '恢复完整页面' : '只显示当前结果和必要状态';
  }

  async function requestScreenWakeLock(notify = false) {
    if (state.wakeLock || document.visibilityState !== 'visible') return Boolean(state.wakeLock);
    if (window.isSecureContext && 'wakeLock' in navigator) {
      try {
        const lock = await navigator.wakeLock.request('screen');
        state.wakeLock = lock;
        lock.addEventListener('release', () => {
          if (state.wakeLock === lock) {
            state.wakeLock = null;
          }
        });
        return true;
      } catch (_) {
        // Fall through to the media fallback; some browsers expose Wake Lock
        // but reject it when the page is not the active tab.
      }
    }
    const fallback = await requestMediaWakeFallback();
    if (!fallback && notify) {
      showToast('当前浏览器不支持网页常亮；请使用 HTTPS/localhost 或兼容媒体保活的浏览器', true);
    }
    return fallback;
  }

  async function requestMediaWakeFallback() {
    if (!window.HTMLCanvasElement || !HTMLCanvasElement.prototype.captureStream || state.wakeLock) {
      return Boolean(state.wakeLock);
    }
    const canvas = document.createElement('canvas');
    canvas.width = 1;
    canvas.height = 1;
    const stream = canvas.captureStream(1);
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.setAttribute('aria-hidden', 'true');
    video.style.cssText = 'position:fixed;width:1px;height:1px;opacity:0;pointer-events:none;';
    video.srcObject = stream;
    document.body.appendChild(video);
    try {
      await video.play();
      state.wakeLock = {
        release: async () => {
          video.pause();
          stream.getTracks().forEach((track) => track.stop());
          video.remove();
        },
      };
      return true;
    } catch (_) {
      stream.getTracks().forEach((track) => track.stop());
      video.remove();
      return false;
    }
  }

  async function releaseScreenWakeLock() {
    const lock = state.wakeLock;
    state.wakeLock = null;
    if (lock) await lock.release().catch(() => {});
  }

  function handleVisibilityChange() {
    if (document.visibilityState === 'visible' && !state.wakeLock) void requestScreenWakeLock();
  }

  function handleWakeLockInteraction() {
    if (document.visibilityState === 'visible' && !state.wakeLock) {
      void requestScreenWakeLock();
    }
  }

  function forgetDesktop() {
    state.explicitDisconnect = true;
    stopEventStream();
    state.connected = false;
    state.token = '';
    state.baseUrl = '';
    localStorage.removeItem(STORAGE.token);
    localStorage.removeItem(STORAGE.baseUrl);
    renderConnectionView();
    $('#base-url').value = window.location.origin.startsWith('http') ? window.location.origin : '';
    $('#pair-code').value = '';
    setConnectionStatus('已移除本机连接');
  }

  function showToast(message, error = false) {
    const toast = document.createElement('div');
    toast.className = `toast${error ? ' error' : ''}`;
    toast.textContent = message;
    $('#toast-region').appendChild(toast);
    window.setTimeout(() => toast.remove(), 4200);
  }
})();
