import 'dart:convert';

import 'package:flutter/material.dart';

import 'api_client.dart';

const reasoningEfforts = <String>[
  '',
  'none',
  'minimal',
  'low',
  'medium',
  'high',
  'xhigh',
  'max',
];

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.api});

  final LanApiClient api;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  bool _loading = true;
  bool _saving = false;
  String _error = '';
  List<Map<String, dynamic>> _models = [];
  List<Map<String, dynamic>> _profiles = [];
  String _activeProfileId = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final data = await widget.api.settings();
      if (!mounted) return;
      setState(() {
        _models = (data['models'] as List<dynamic>? ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(Map<String, dynamic>.from)
            .toList();
        _profiles = (data['profiles'] as List<dynamic>? ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(Map<String, dynamic>.from)
            .toList();
        _activeProfileId = data['active_profile_id']?.toString() ?? '';
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      final conflict = _reasoningConflict();
      if (conflict != null) throw ApiException(conflict);
      await widget.api.updateSettings(<String, dynamic>{
        'models': _models,
        'profiles': _profiles,
        'active_profile_id': _activeProfileId,
      });
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('电脑已接受配置，正在保存并同步到所有 App')));
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('保存失败：$error')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  String? _reasoningConflict() {
    final modelsById = {
      for (final model in _models) model['id']?.toString(): model,
    };
    for (final profile in _profiles) {
      if (profile['extra_body_enabled'] != true) continue;
      final extra = profile['extra_body'];
      if (extra is! Map || !extra.containsKey('reasoning_effort')) continue;
      final model = modelsById[profile['model_id']?.toString()];
      if ((model?['reasoning_effort']?.toString() ?? '').isNotEmpty) {
        return '思考强度与 extra_body 中的 reasoning_effort 重复；'
            '请删除 extra_body 中的该字段，或把模型思考强度设为自动';
      }
    }
    return null;
  }

  Future<void> _editModel([int? index]) async {
    final original = index == null
        ? <String, dynamic>{
            'id': 'model-${DateTime.now().microsecondsSinceEpoch}',
            'name': '新模型',
            'base_url': '',
            'model': '',
            'timeout_seconds': 120,
            'max_tokens': 2048,
            'reasoning_effort': '',
            'api_key_configured': false,
          }
        : Map<String, dynamic>.from(_models[index]);
    final name = TextEditingController(text: original['name']?.toString());
    final baseUrl = TextEditingController(
      text: original['base_url']?.toString(),
    );
    final apiKey = TextEditingController();
    final model = TextEditingController(text: original['model']?.toString());
    final timeout = TextEditingController(
      text: original['timeout_seconds']?.toString() ?? '120',
    );
    final maxTokens = TextEditingController(
      text: original['max_tokens']?.toString() ?? '2048',
    );
    var reasoningEffort = original['reasoning_effort']?.toString() ?? '';
    if (!reasoningEfforts.contains(reasoningEffort)) reasoningEffort = '';
    var clearKey = false;
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: Text(index == null ? '新增模型连接' : '编辑模型连接'),
          content: SizedBox(
            width: 560,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    controller: name,
                    decoration: const InputDecoration(labelText: '名称'),
                  ),
                  TextField(
                    controller: baseUrl,
                    decoration: const InputDecoration(
                      labelText: 'Base URL',
                      hintText: 'https://api.example.com/v1',
                    ),
                  ),
                  TextField(
                    controller: apiKey,
                    obscureText: true,
                    enabled: !clearKey,
                    decoration: InputDecoration(
                      labelText: '新 API Key',
                      hintText: original['api_key_configured'] == true
                          ? '已设置；留空保持原值'
                          : '尚未设置',
                    ),
                  ),
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: clearKey,
                    onChanged: (value) =>
                        setDialogState(() => clearKey = value == true),
                    title: const Text('清除电脑中已保存的 API Key'),
                  ),
                  TextField(
                    controller: model,
                    decoration: const InputDecoration(labelText: '模型名'),
                  ),
                  TextField(
                    controller: timeout,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: '请求总超时（思考 + 输出，秒）',
                    ),
                  ),
                  TextField(
                    controller: maxTokens,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: 'Max Tokens'),
                  ),
                  DropdownButtonFormField<String>(
                    initialValue: reasoningEffort,
                    decoration: const InputDecoration(labelText: '思考强度'),
                    items: reasoningEfforts
                        .map(
                          (effort) => DropdownMenuItem<String>(
                            value: effort,
                            child: Text(effort.isEmpty ? '自动（不发送）' : effort),
                          ),
                        )
                        .toList(),
                    onChanged: (value) =>
                        setDialogState(() => reasoningEffort = value ?? ''),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () {
                final key = apiKey.text.trim();
                Navigator.pop(context, <String, dynamic>{
                  ...original,
                  'name': name.text.trim().isEmpty ? '模型配置' : name.text.trim(),
                  'base_url': baseUrl.text.trim(),
                  'model': model.text.trim(),
                  'timeout_seconds': int.tryParse(timeout.text) ?? 120,
                  'max_tokens': int.tryParse(maxTokens.text) ?? 2048,
                  'reasoning_effort': reasoningEffort,
                  'api_key_action': clearKey
                      ? 'clear'
                      : key.isNotEmpty || index == null
                      ? 'replace'
                      : 'keep',
                  if (key.isNotEmpty) 'api_key': key,
                });
              },
              child: const Text('确定'),
            ),
          ],
        ),
      ),
    );
    for (final controller in [
      name,
      baseUrl,
      apiKey,
      model,
      timeout,
      maxTokens,
    ]) {
      controller.dispose();
    }
    if (result == null || !mounted) return;
    setState(() {
      if (index == null) {
        _models.add(result);
      } else {
        _models[index] = result;
      }
    });
  }

  Future<void> _editProfile([int? index]) async {
    if (_models.isEmpty) return;
    final original = index == null
        ? <String, dynamic>{
            'id': 'profile-${DateTime.now().microsecondsSinceEpoch}',
            'name': '新配置',
            'model_id': _models.first['id'],
            'system_prompt': '',
            'prompt_template': '请分析这些截图。',
            'language': 'auto',
            'extra_body_enabled': false,
            'extra_body': <String, dynamic>{},
          }
        : Map<String, dynamic>.from(_profiles[index]);
    final name = TextEditingController(text: original['name']?.toString());
    final systemPrompt = TextEditingController(
      text: original['system_prompt']?.toString(),
    );
    final promptTemplate = TextEditingController(
      text: original['prompt_template']?.toString(),
    );
    final extraBody = TextEditingController(
      text: const JsonEncoder.withIndent(
        '  ',
      ).convert(original['extra_body'] ?? <String, dynamic>{}),
    );
    var modelId = original['model_id']?.toString() ?? _models.first['id'];
    var extraEnabled = original['extra_body_enabled'] == true;
    String? validationError;
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: Text(index == null ? '新增配置组' : '编辑配置组'),
          content: SizedBox(
            width: 620,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    controller: name,
                    decoration: const InputDecoration(labelText: '名称'),
                  ),
                  DropdownButtonFormField<String>(
                    initialValue: modelId,
                    decoration: const InputDecoration(labelText: '模型连接'),
                    items: _models
                        .map(
                          (item) => DropdownMenuItem<String>(
                            value: item['id']?.toString(),
                            child: Text(item['name']?.toString() ?? '模型'),
                          ),
                        )
                        .toList(),
                    onChanged: (value) {
                      if (value != null) modelId = value;
                    },
                  ),
                  TextField(
                    controller: systemPrompt,
                    minLines: 2,
                    maxLines: 5,
                    decoration: const InputDecoration(
                      labelText: 'System Prompt',
                    ),
                  ),
                  TextField(
                    controller: promptTemplate,
                    minLines: 3,
                    maxLines: 8,
                    decoration: const InputDecoration(labelText: '用户提示词'),
                  ),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    value: extraEnabled,
                    onChanged: (value) =>
                        setDialogState(() => extraEnabled = value),
                    title: const Text('发送 extra_body'),
                  ),
                  TextField(
                    controller: extraBody,
                    enabled: extraEnabled,
                    minLines: 3,
                    maxLines: 8,
                    decoration: InputDecoration(
                      labelText: 'extra_body JSON Object',
                      errorText: validationError,
                    ),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () {
                try {
                  final decoded = jsonDecode(
                    extraBody.text.trim().isEmpty ? '{}' : extraBody.text,
                  );
                  if (decoded is! Map<String, dynamic>) {
                    throw const FormatException();
                  }
                  Navigator.pop(context, <String, dynamic>{
                    ...original,
                    'name': name.text.trim().isEmpty ? '配置' : name.text.trim(),
                    'model_id': modelId,
                    'system_prompt': systemPrompt.text,
                    'prompt_template': promptTemplate.text,
                    'language': 'auto',
                    'extra_body_enabled': extraEnabled,
                    'extra_body': decoded,
                  });
                } catch (_) {
                  setDialogState(() => validationError = '必须是有效的 JSON Object');
                }
              },
              child: const Text('确定'),
            ),
          ],
        ),
      ),
    );
    for (final controller in [name, systemPrompt, promptTemplate, extraBody]) {
      controller.dispose();
    }
    if (result == null || !mounted) return;
    setState(() {
      if (index == null) {
        _profiles.add(result);
        if (_activeProfileId.isEmpty) {
          _activeProfileId = result['id'].toString();
        }
      } else {
        _profiles[index] = result;
      }
    });
  }

  void _deleteModel(int index) {
    if (_models.length <= 1) {
      _message('至少保留一个模型连接');
      return;
    }
    final id = _models[index]['id'];
    if (_profiles.any((profile) => profile['model_id'] == id)) {
      _message('该模型仍被配置组使用，不能删除');
      return;
    }
    setState(() => _models.removeAt(index));
  }

  void _deleteProfile(int index) {
    if (_profiles.length <= 1) {
      _message('至少保留一个配置组');
      return;
    }
    final removed = _profiles.removeAt(index);
    if (_activeProfileId == removed['id']) {
      _activeProfileId = _profiles.first['id'].toString();
    }
    setState(() {});
  }

  void _message(String text) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error.isNotEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('加载配置失败：$_error'),
            const SizedBox(height: 12),
            FilledButton(onPressed: _load, child: const Text('重试')),
          ],
        ),
      );
    }
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                '模型连接',
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            IconButton(
              tooltip: '新增模型连接',
              onPressed: _editModel,
              icon: const Icon(Icons.add),
            ),
          ],
        ),
        ..._models.asMap().entries.map((entry) {
          final model = entry.value;
          return Card(
            child: ListTile(
              leading: const Icon(Icons.hub),
              title: Text(model['name']?.toString() ?? '模型'),
              subtitle: Text(
                '${model['model'] ?? ''}\n${model['base_url'] ?? ''} · Key ${model['api_key_configured'] == true ? '已设置' : '未设置'}',
              ),
              isThreeLine: true,
              onTap: () => _editModel(entry.key),
              trailing: IconButton(
                tooltip: '删除',
                onPressed: () => _deleteModel(entry.key),
                icon: const Icon(Icons.delete_outline),
              ),
            ),
          );
        }),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: Text(
                '任务配置组',
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            IconButton(
              tooltip: '新增配置组',
              onPressed: _editProfile,
              icon: const Icon(Icons.add),
            ),
          ],
        ),
        ..._profiles.asMap().entries.map((entry) {
          final profile = entry.value;
          final model = _models.cast<Map<String, dynamic>?>().firstWhere(
            (item) => item?['id'] == profile['model_id'],
            orElse: () => null,
          );
          return Card(
            child: ListTile(
              leading: Icon(
                profile['id'] == _activeProfileId
                    ? Icons.radio_button_checked
                    : Icons.tune,
              ),
              title: Text(profile['name']?.toString() ?? '配置'),
              subtitle: Text('模型：${model?['name'] ?? '未知'}'),
              onTap: () => _editProfile(entry.key),
              trailing: IconButton(
                tooltip: '删除',
                onPressed: () => _deleteProfile(entry.key),
                icon: const Icon(Icons.delete_outline),
              ),
            ),
          );
        }),
        const SizedBox(height: 18),
        FilledButton.icon(
          onPressed: _saving ? null : _save,
          icon: const Icon(Icons.save),
          label: Padding(
            padding: const EdgeInsets.symmetric(vertical: 14),
            child: Text(_saving ? '保存中...' : '保存到电脑'),
          ),
        ),
        const SizedBox(height: 8),
        const Text('安全说明：电脑不会向 App 返回已有 API Key。Key 输入框留空会保持原值，也可明确替换或清除。'),
      ],
    );
  }
}
