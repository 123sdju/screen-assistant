import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:markdown/markdown.dart' as md;

import 'api_client.dart';
import 'discovery.dart';
import 'qr_scanner_page.dart';
import 'settings_page.dart';

void main() => runApp(const ScreenAssistantApp());

String normalizeLanUrl(String value) {
  var clean = value.trim();
  if (!clean.startsWith('http://') && !clean.startsWith('https://')) {
    clean = 'http://$clean';
  }
  return clean.replaceAll(RegExp(r'/+$'), '');
}

String? lanAddressProblem(String value) {
  final uri = Uri.tryParse(normalizeLanUrl(value));
  if (uri == null ||
      !uri.hasAuthority ||
      uri.host.isEmpty ||
      (uri.scheme != 'http' && uri.scheme != 'https')) {
    return '请输入有效的电脑地址，例如 http://192.168.1.10:18765';
  }
  final host = uri.host.toLowerCase();
  if (host == 'localhost' ||
      host == '::1' ||
      host == '0.0.0.0' ||
      host.startsWith('127.')) {
    return '127.0.0.1/localhost 指向手机自身，不能用于连接电脑。请使用电脑的局域网 IP。';
  }
  return null;
}

class WrappingCodeBlockBuilder extends MarkdownElementBuilder {
  @override
  bool isBlockElement() => true;

  @override
  Widget? visitText(md.Text text, TextStyle? preferredStyle) {
    return Container(
      key: const ValueKey<String>('wrapping-code-block'),
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0x0D000000),
        borderRadius: BorderRadius.circular(6),
      ),
      child: SelectionArea(
        child: Text(
          text.text,
          softWrap: true,
          overflow: TextOverflow.visible,
          style: preferredStyle,
        ),
      ),
    );
  }
}

double normalizedFontScale(String? value) {
  final parsed = double.tryParse(value ?? '') ?? 1.0;
  return parsed.clamp(0.8, 1.8).toDouble();
}

bool useWideLayout(double width) => width >= 700;

double nextScrollOffset({
  required double current,
  required double viewport,
  required double maximum,
  required String direction,
}) {
  final delta = viewport * 0.82 * (direction == 'up' ? -1 : 1);
  return (current + delta).clamp(0.0, maximum).toDouble();
}

bool shouldApplyRemoteViewControl({
  required int tabIndex,
  required String sourceDeviceId,
  required String localDeviceId,
}) {
  return tabIndex == 0 && sourceDeviceId != localDeviceId;
}

double nextFontScale(double current, double delta) {
  return (current + delta).clamp(0.8, 1.8).toDouble();
}

bool eventTargetsCurrentTask(
  Map<String, dynamic> event,
  Map<String, dynamic>? currentTask,
) {
  final eventTaskId = event['task_id']?.toString() ?? '';
  final currentTaskId = currentTask?['id']?.toString() ?? '';
  return eventTaskId.isNotEmpty && eventTaskId == currentTaskId;
}

TextScaler resultTextScaler(double scale) =>
    TextScaler.linear(normalizedFontScale(scale.toString()));

class ScreenAssistantApp extends StatefulWidget {
  const ScreenAssistantApp({
    super.key,
    this.storage = const FlutterSecureStorage(),
  });
  final FlutterSecureStorage storage;

  @override
  State<ScreenAssistantApp> createState() => _ScreenAssistantAppState();
}

class _ScreenAssistantAppState extends State<ScreenAssistantApp> {
  double _fontScale = 1.0;

  @override
  void initState() {
    super.initState();
    _restoreFontScale();
  }

  Future<void> _restoreFontScale() async {
    final restored = normalizedFontScale(
      await widget.storage.read(key: 'font_scale'),
    );
    if (mounted) setState(() => _fontScale = restored);
  }

  Future<void> _setFontScale(double value) async {
    final normalized = normalizedFontScale(value.toString());
    setState(() => _fontScale = normalized);
    await widget.storage.write(
      key: 'font_scale',
      value: normalized.toStringAsFixed(2),
    );
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Screen Assistant',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff3157d5)),
        useMaterial3: true,
      ),
      home: AppShell(
        storage: widget.storage,
        fontScale: _fontScale,
        onFontScaleChanged: _setFontScale,
      ),
    );
  }
}

class AppShell extends StatefulWidget {
  const AppShell({
    super.key,
    required this.storage,
    required this.fontScale,
    required this.onFontScaleChanged,
  });
  final FlutterSecureStorage storage;
  final double fontScale;
  final ValueChanged<double> onFontScaleChanged;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> with WidgetsBindingObserver {
  final _urlController = TextEditingController(
    text: 'http://192.168.1.2:18765',
  );
  final _codeController = TextEditingController();
  final _nameController = TextEditingController(text: 'Screen Assistant App');
  final _discovery = DesktopDiscovery();
  List<DiscoveredDesktop> _discovered = const [];
  bool _discovering = false;
  bool _loading = true;
  bool _pairing = false;
  bool _connected = false;
  String _status = '等待连接';
  String _deviceId = '';
  String _token = '';
  String _baseUrl = '';
  LanApiClient? _api;
  int _streamGeneration = 0;
  Timer? _reconnectTimer;
  Map<String, dynamic> _desktop = const {};
  List<Map<String, dynamic>> _profiles = const [];
  List<Map<String, dynamic>> _tasks = const [];
  Map<String, dynamic>? _currentTask;
  String _activeProfileId = '';
  String _activeProfileName = '-';
  int _bufferCount = 0;
  bool _busy = false;
  int _tabIndex = 0;
  int _settingsRevision = 0;
  late double _fontScaleValue;
  final _currentPageController = ScrollController();

  @override
  void initState() {
    super.initState();
    _fontScaleValue = widget.fontScale;
    WidgetsBinding.instance.addObserver(this);
    _restore();
  }

  @override
  void didUpdateWidget(covariant AppShell oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.fontScale != widget.fontScale) {
      _fontScaleValue = widget.fontScale;
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _reconnectTimer?.cancel();
    _api?.close();
    _discovery.stop();
    _urlController.dispose();
    _codeController.dispose();
    _nameController.dispose();
    _currentPageController.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && _token.isNotEmpty) {
      _connectSaved();
    }
  }

  Future<void> _restore() async {
    var deviceId = await widget.storage.read(key: 'device_id');
    if (deviceId == null || deviceId.isEmpty) {
      final random = Random.secure();
      deviceId =
          'app-${DateTime.now().millisecondsSinceEpoch.toRadixString(16)}-${random.nextInt(1 << 24).toRadixString(16)}';
      await widget.storage.write(key: 'device_id', value: deviceId);
    }
    _deviceId = deviceId;
    _baseUrl = await widget.storage.read(key: 'base_url') ?? '';
    _token = await widget.storage.read(key: 'token') ?? '';
    if (_baseUrl.isNotEmpty) _urlController.text = _baseUrl;
    if (_baseUrl.isNotEmpty && _token.isNotEmpty) {
      await _connectSaved();
    } else if (mounted) {
      setState(() => _loading = false);
    }
  }

  Future<void> _discover() async {
    setState(() {
      _discovering = true;
      _status = '正在搜索局域网电脑...';
    });
    try {
      final found = await _discovery.scan();
      if (!mounted) return;
      setState(() {
        _discovered = found;
        _status = found.isEmpty
            ? '未自动发现电脑，可扫码或手动输入 IP'
            : '发现 ${found.length} 台电脑';
      });
    } catch (error) {
      if (mounted) setState(() => _status = '自动发现失败：$error');
    } finally {
      if (mounted) setState(() => _discovering = false);
    }
  }

  Future<void> _scanQr() async {
    final raw = await Navigator.of(
      context,
    ).push<String>(MaterialPageRoute(builder: (_) => const QrScannerPage()));
    if (raw == null) return;
    try {
      final payload = jsonDecode(raw);
      if (payload is! Map<String, dynamic> ||
          payload['url'] == null ||
          payload['code'] == null) {
        throw const FormatException();
      }
      final problem = lanAddressProblem(payload['url'].toString());
      if (problem != null) {
        _showMessage('电脑二维码中的地址无效：$problem\n请升级电脑端并重新生成二维码。');
        return;
      }
      setState(() {
        _urlController.text = payload['url'].toString();
        _codeController.text = payload['code'].toString();
        _status = '已读取二维码，请点击配对';
      });
    } catch (_) {
      _showMessage('二维码不是 Screen Assistant 配对码');
    }
  }

  Future<void> _pair() async {
    final problem = lanAddressProblem(_urlController.text);
    if (problem != null) {
      setState(() => _status = problem);
      _showMessage(problem);
      return;
    }
    final url = normalizeLanUrl(_urlController.text);
    final code = _codeController.text.trim();
    if (code.length != 6) {
      _showMessage('请输入电脑端显示的六位配对码');
      return;
    }
    setState(() {
      _pairing = true;
      _status = '正在配对...';
    });
    final api = LanApiClient(baseUrl: url);
    try {
      final response = await api.pair(
        code: code,
        deviceId: _deviceId,
        deviceName: _nameController.text.trim(),
      );
      final token = response['token']?.toString() ?? '';
      if (token.isEmpty) throw ApiException('配对响应缺少 Token');
      await widget.storage.write(key: 'base_url', value: url);
      await widget.storage.write(key: 'token', value: token);
      _baseUrl = url;
      _token = token;
      await _connectSaved();
    } catch (error) {
      if (mounted) setState(() => _status = '配对失败：$error');
    } finally {
      api.close();
      if (mounted) setState(() => _pairing = false);
    }
  }

  Future<void> _connectSaved() async {
    _reconnectTimer?.cancel();
    _streamGeneration++;
    _api?.close();
    final generation = _streamGeneration;
    final api = LanApiClient(baseUrl: _baseUrl, token: _token);
    _api = api;
    if (mounted) {
      setState(() {
        _loading = true;
        _status = '正在连接电脑...';
      });
    }
    try {
      final data = await api.bootstrap();
      if (!mounted || generation != _streamGeneration) return;
      _applyBootstrap(data);
      setState(() {
        _connected = true;
        _loading = false;
        _status = '已连接';
      });
      unawaited(
        api.streamEvents(
          (event) {
            if (mounted && generation == _streamGeneration) _handleEvent(event);
          },
          (error) {
            if (!mounted || generation != _streamGeneration) return;
            setState(() {
              _connected = false;
              _status = '连接断开，正在重连...';
            });
            _reconnectTimer?.cancel();
            _reconnectTimer = Timer(const Duration(seconds: 3), _connectSaved);
          },
        ),
      );
    } catch (error) {
      if (!mounted || generation != _streamGeneration) return;
      setState(() {
        _connected = false;
        _loading = false;
        _status = '连接失败：$error';
      });
      if (error is ApiException && error.statusCode == 401) return;
      _reconnectTimer = Timer(const Duration(seconds: 3), _connectSaved);
    }
  }

  void _applyBootstrap(Map<String, dynamic> data) {
    final profiles = (data['profiles'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .toList();
    final tasks = (data['tasks'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .toList();
    final active = data['active_profile'];
    setState(() {
      _desktop = data['desktop'] is Map<String, dynamic>
          ? data['desktop'] as Map<String, dynamic>
          : const {};
      _profiles = profiles;
      _tasks = tasks;
      _currentTask = data['current_task'] is Map<String, dynamic>
          ? Map<String, dynamic>.from(data['current_task'] as Map)
          : null;
      _activeProfileId = active is Map ? active['id']?.toString() ?? '' : '';
      _activeProfileName = active is Map
          ? active['name']?.toString() ?? '-'
          : '-';
      _bufferCount = (data['buffer_count'] as num?)?.toInt() ?? 0;
      _busy = data['busy'] == true;
    });
  }

  void _handleEvent(Map<String, dynamic> event) {
    final kind = event['event']?.toString() ?? '';
    final scrollDirection = kind == 'app_scroll'
        ? event['direction']?.toString()
        : null;
    final fontDelta = kind == 'app_font_scale'
        ? (event['delta'] as num?)?.toDouble()
        : null;
    final shouldApplyViewControl = shouldApplyRemoteViewControl(
      tabIndex: _tabIndex,
      sourceDeviceId: event['source_device_id']?.toString() ?? '',
      localDeviceId: _deviceId,
    );
    setState(() {
      if (kind == 'buffer_changed') {
        _bufferCount = (event['buffer_count'] as num?)?.toInt() ?? 0;
      }
      if (kind == 'config_changed' && event['active_profile'] is Map) {
        final active = event['active_profile'] as Map;
        _activeProfileId = active['id']?.toString() ?? '';
        _activeProfileName = active['name']?.toString() ?? '-';
      }
      if (kind == 'settings_changed') {
        _settingsRevision++;
        if (event['profiles'] is List) {
          _profiles = (event['profiles'] as List)
              .whereType<Map<String, dynamic>>()
              .map(Map<String, dynamic>.from)
              .toList();
        }
        if (event['active_profile'] is Map) {
          final active = event['active_profile'] as Map;
          _activeProfileId = active['id']?.toString() ?? '';
          _activeProfileName = active['name']?.toString() ?? '-';
        }
      }
      if (kind == 'task_snapshot' && event['task'] is Map) {
        _currentTask = Map<String, dynamic>.from(event['task'] as Map);
        _busy = true;
        _tabIndex = 0;
      }
      if (kind == 'thinking_delta' &&
          eventTargetsCurrentTask(event, _currentTask)) {
        _currentTask ??= <String, dynamic>{};
        _currentTask!['thinking_text'] =
            '${_currentTask!['thinking_text'] ?? ''}${event['delta'] ?? ''}';
      }
      if (kind == 'result_delta' &&
          eventTargetsCurrentTask(event, _currentTask)) {
        _currentTask ??= <String, dynamic>{};
        _currentTask!['result_text'] =
            '${_currentTask!['result_text'] ?? ''}${event['delta'] ?? ''}';
      }
      if ((kind == 'completed' || kind == 'failed') &&
          event['task'] is Map &&
          (event['task'] as Map)['id']?.toString() ==
              _currentTask?['id']?.toString()) {
        _currentTask = Map<String, dynamic>.from(event['task'] as Map);
        _busy = false;
        final id = _currentTask!['id'];
        _tasks.removeWhere((item) => item['id'] == id);
        _tasks.insert(0, Map<String, dynamic>.from(_currentTask!));
      }
      if (shouldApplyViewControl &&
          (kind == 'app_scroll' || kind == 'app_font_scale')) {
        _status = kind == 'app_scroll' ? '已连接 · 已收到电脑翻页' : '已连接 · 已收到电脑字体调整';
      }
    });
    if (shouldApplyViewControl &&
        (scrollDirection == 'up' || scrollDirection == 'down')) {
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => _applyRemoteAppScroll(scrollDirection!),
      );
    }
    if (shouldApplyViewControl && fontDelta != null && fontDelta != 0) {
      _applyRemoteFontScale(fontDelta);
    }
    if (kind == 'command_failed') {
      _showMessage(event['message']?.toString() ?? '电脑执行命令失败');
    }
  }

  void _applyRemoteFontScale(double delta) {
    _fontScaleValue = nextFontScale(_fontScaleValue, delta);
    widget.onFontScaleChanged(_fontScaleValue);
  }

  void _applyRemoteAppScroll(String direction) {
    final controller = _currentPageController;
    if (!controller.hasClients) return;
    final position = controller.position;
    final target = nextScrollOffset(
      current: position.pixels,
      viewport: position.viewportDimension,
      maximum: position.maxScrollExtent,
      direction: direction,
    );
    controller.animateTo(
      target,
      duration: const Duration(milliseconds: 280),
      curve: Curves.easeOutCubic,
    );
  }

  Future<void> _sendCommand(String command, {String? profileId}) async {
    try {
      await _api!.command(command, profileId: profileId);
      _showMessage('电脑已接受命令');
    } catch (error) {
      _showMessage('命令失败：$error');
    }
  }

  Future<void> _openHistoryTask(Map<String, dynamic> summary) async {
    try {
      final task = await _api!.task(summary['id'].toString());
      setState(() {
        _currentTask = task;
        _tabIndex = 0;
      });
    } catch (error) {
      _showMessage('加载历史失败：$error');
    }
  }

  Future<void> _forgetDesktop() async {
    _streamGeneration++;
    _reconnectTimer?.cancel();
    _api?.close();
    await widget.storage.delete(key: 'base_url');
    await widget.storage.delete(key: 'token');
    if (!mounted) return;
    setState(() {
      _connected = false;
      _loading = false;
      _token = '';
      _baseUrl = '';
      _status = '已移除本机连接';
    });
  }

  void _showMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _showFontSettings() async {
    var selected = widget.fontScale;
    await showDialog<void>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('App 字体大小'),
          content: SizedBox(
            width: 420,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  '预览文字  ${selected.toStringAsFixed(2)}×',
                  textScaler: resultTextScaler(selected),
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                Slider(
                  value: selected,
                  min: 0.8,
                  max: 1.8,
                  divisions: 10,
                  label: '${selected.toStringAsFixed(1)}×',
                  onChanged: (value) {
                    setDialogState(() => selected = value);
                    widget.onFontScaleChanged(value);
                  },
                ),
                const Text('会同时调整连接页、遥控按钮、历史和 Markdown 结果字体'),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () {
                setDialogState(() => selected = 1.0);
                widget.onFontScaleChanged(1.0);
              },
              child: const Text('恢复默认'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('完成'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _fontAction() => IconButton(
    tooltip: '调整字体大小',
    onPressed: _showFontSettings,
    icon: const Icon(Icons.format_size),
  );

  @override
  Widget build(BuildContext context) {
    if (_loading && !_connected) {
      return Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const CircularProgressIndicator(),
              const SizedBox(height: 16),
              Text(_status),
            ],
          ),
        ),
      );
    }
    return _connected ? _home() : _connectionPage();
  }

  Widget _connectionPage() {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Screen Assistant'),
        actions: [_fontAction()],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text('连接局域网电脑', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 8),
          Text(_status),
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed: _discovering ? null : _discover,
            icon: const Icon(Icons.radar),
            label: Text(_discovering ? '正在发现...' : '自动发现电脑'),
          ),
          if (_discovered.isNotEmpty) ...[
            const SizedBox(height: 8),
            ..._discovered.map(
              (desktop) => Card(
                child: ListTile(
                  title: Text(desktop.name),
                  subtitle: Text(desktop.url),
                  onTap: () =>
                      setState(() => _urlController.text = desktop.url),
                ),
              ),
            ),
          ],
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: _scanQr,
            icon: const Icon(Icons.qr_code_scanner),
            label: const Text('扫描电脑二维码'),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _urlController,
            decoration: const InputDecoration(
              labelText: '电脑地址',
              hintText: 'http://192.168.1.10:18765',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _codeController,
            keyboardType: TextInputType.number,
            maxLength: 6,
            decoration: const InputDecoration(
              labelText: '六位配对码',
              border: OutlineInputBorder(),
            ),
          ),
          TextField(
            controller: _nameController,
            decoration: const InputDecoration(
              labelText: '本机名称',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _pairing ? null : _pair,
            child: Text(_pairing ? '配对中...' : '配对并连接'),
          ),
        ],
      ),
    );
  }

  Widget _home() {
    final pages = <Widget>[
      _currentPage(),
      _controlPage(),
      _historyPage(),
      SettingsPage(key: ValueKey(_settingsRevision), api: _api!),
    ];
    final wide = useWideLayout(MediaQuery.sizeOf(context).width);
    final pageBody = Column(
      children: [
        Material(
          color: _connected
              ? Colors.green.withValues(alpha: .12)
              : Colors.orange.withValues(alpha: .12),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                Icon(_connected ? Icons.lan : Icons.lan_outlined, size: 18),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '$_status · $_activeProfileName · 缓冲 $_bufferCount 张${_busy ? ' · 处理中' : ''}',
                  ),
                ),
              ],
            ),
          ),
        ),
        Expanded(
          child: IndexedStack(index: _tabIndex, children: pages),
        ),
      ],
    );
    return Scaffold(
      appBar: AppBar(
        title: Text(_desktop['name']?.toString() ?? 'Screen Assistant'),
        actions: [
          _fontAction(),
          IconButton(onPressed: _connectSaved, icon: const Icon(Icons.refresh)),
          PopupMenuButton<String>(
            onSelected: (value) {
              if (value == 'forget') _forgetDesktop();
            },
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'forget', child: Text('移除此电脑')),
            ],
          ),
        ],
      ),
      body: wide
          ? Row(
              children: [
                NavigationRail(
                  selectedIndex: _tabIndex,
                  onDestinationSelected: (index) =>
                      setState(() => _tabIndex = index),
                  labelType: NavigationRailLabelType.all,
                  destinations: const [
                    NavigationRailDestination(
                      icon: Icon(Icons.auto_awesome),
                      label: Text('当前结果'),
                    ),
                    NavigationRailDestination(
                      icon: Icon(Icons.gamepad),
                      label: Text('遥控'),
                    ),
                    NavigationRailDestination(
                      icon: Icon(Icons.history),
                      label: Text('历史'),
                    ),
                    NavigationRailDestination(
                      icon: Icon(Icons.settings),
                      label: Text('配置'),
                    ),
                  ],
                ),
                const VerticalDivider(width: 1),
                Expanded(child: pageBody),
              ],
            )
          : pageBody,
      bottomNavigationBar: wide
          ? null
          : NavigationBar(
              selectedIndex: _tabIndex,
              onDestinationSelected: (index) =>
                  setState(() => _tabIndex = index),
              destinations: const [
                NavigationDestination(
                  icon: Icon(Icons.auto_awesome),
                  label: '当前结果',
                ),
                NavigationDestination(icon: Icon(Icons.gamepad), label: '遥控'),
                NavigationDestination(icon: Icon(Icons.history), label: '历史'),
                NavigationDestination(icon: Icon(Icons.settings), label: '配置'),
              ],
            ),
    );
  }

  Widget _currentPage() {
    final thinking = _currentTask?['thinking_text']?.toString() ?? '';
    final result = _currentTask?['result_text']?.toString() ?? '';
    final error = _currentTask?['error_message']?.toString() ?? '';
    final content = <Widget>[
      if (_currentTask == null)
        const Padding(
          padding: EdgeInsets.only(top: 80),
          child: Center(child: Text('电脑还没有创建任务')),
        ),
      if (thinking.isNotEmpty) _markdownCard('思考', thinking),
      if (result.isNotEmpty) _markdownCard('结果', result),
      if (error.isNotEmpty)
        Card(
          color: Theme.of(context).colorScheme.errorContainer,
          child: Padding(padding: const EdgeInsets.all(16), child: Text(error)),
        ),
      if (_currentTask != null &&
          thinking.isEmpty &&
          result.isEmpty &&
          error.isEmpty)
        const Center(
          child: Padding(
            padding: EdgeInsets.all(40),
            child: CircularProgressIndicator(),
          ),
        ),
    ];
    return ListView(
      controller: _currentPageController,
      padding: EdgeInsets.all(
        MediaQuery.orientationOf(context) == Orientation.landscape ? 8 : 12,
      ),
      children: content,
    );
  }

  Widget _markdownCard(String title, String value) {
    final media = MediaQuery.of(context);
    return MediaQuery(
      data: media.copyWith(textScaler: resultTextScaler(widget.fontScale)),
      child: Card(
        margin: const EdgeInsets.only(bottom: 8),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: Theme.of(context).textTheme.titleMedium),
              const Divider(),
              SizedBox(
                width: double.infinity,
                child: MarkdownBody(
                  data: value,
                  selectable: true,
                  builders: <String, MarkdownElementBuilder>{
                    'pre': WrappingCodeBlockBuilder(),
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _controlPage() {
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 1050
            ? 3
            : constraints.maxWidth >= 700
            ? 2
            : 1;
        final buttonWidth =
            (constraints.maxWidth - 32 - (columns - 1) * 12) / columns;
        final buttons = <Widget>[
          _commandButton(
            Icons.screenshot_monitor,
            '整屏截图',
            'capture_fullscreen',
          ),
          _commandButton(Icons.upload, '提交当前缓冲', 'submit_buffer'),
          _commandButton(Icons.bolt, '截图并立即提交', 'capture_and_submit'),
          _commandButton(Icons.delete_sweep, '清空截图缓冲', 'clear_buffer'),
          _commandButton(
            Icons.keyboard_arrow_up,
            '所有 App 上翻页',
            'scroll_apps_up',
          ),
          _commandButton(
            Icons.keyboard_arrow_down,
            '所有 App 下翻页',
            'scroll_apps_down',
          ),
        ];
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            DropdownButtonFormField<String>(
              key: ValueKey(_activeProfileId),
              initialValue: _profiles.any((p) => p['id'] == _activeProfileId)
                  ? _activeProfileId
                  : null,
              decoration: const InputDecoration(
                labelText: '当前配置组',
                border: OutlineInputBorder(),
              ),
              items: _profiles
                  .map(
                    (profile) => DropdownMenuItem(
                      value: profile['id'].toString(),
                      child: Text(profile['name'].toString()),
                    ),
                  )
                  .toList(),
              onChanged: (value) {
                if (value != null) {
                  _sendCommand('switch_profile', profileId: value);
                }
              },
            ),
            const SizedBox(height: 20),
            Wrap(
              spacing: 12,
              runSpacing: 2,
              children: buttons
                  .map((button) => SizedBox(width: buttonWidth, child: button))
                  .toList(),
            ),
            const SizedBox(height: 8),
            Text(
              '翻页命令经电脑广播；只有当前停留在结果页的 Screen Assistant App 会同步滚动。',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        );
      },
    );
  }

  Widget _commandButton(IconData icon, String label, String command) => Padding(
    padding: const EdgeInsets.only(bottom: 10),
    child: FilledButton.tonalIcon(
      onPressed: () => _sendCommand(command),
      icon: Icon(icon),
      label: Padding(
        padding: const EdgeInsets.symmetric(vertical: 14),
        child: Text(label),
      ),
    ),
  );

  Widget _historyPage() {
    if (_tasks.isEmpty) return const Center(child: Text('本地电脑没有已保存的文本历史'));
    return RefreshIndicator(
      onRefresh: _connectSaved,
      child: ListView.builder(
        padding: const EdgeInsets.all(12),
        itemCount: _tasks.length,
        itemBuilder: (context, index) {
          final task = _tasks[index];
          return Card(
            child: ListTile(
              leading: Icon(
                task['status'] == 'completed'
                    ? Icons.check_circle
                    : task['status'] == 'failed'
                    ? Icons.error
                    : Icons.hourglass_top,
              ),
              title: Text(task['profile_name']?.toString() ?? '任务'),
              subtitle: Text(task['created_at']?.toString() ?? ''),
              onTap: () => _openHistoryTask(task),
            ),
          );
        },
      ),
    );
  }
}
