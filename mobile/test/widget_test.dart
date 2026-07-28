import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:screen_assistant_mobile/api_client.dart';
import 'package:screen_assistant_mobile/discovery.dart';
import 'package:screen_assistant_mobile/main.dart';
import 'package:screen_assistant_mobile/settings_page.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('shows the LAN pairing screen without a saved desktop', (
    tester,
  ) async {
    FlutterSecureStorage.setMockInitialValues(<String, String>{});
    await tester.pumpWidget(const ScreenAssistantApp());
    await tester.pumpAndSettle();

    expect(find.text('连接局域网电脑'), findsOneWidget);
    expect(find.text('自动发现电脑'), findsOneWidget);
    expect(find.text('扫描电脑二维码'), findsOneWidget);
    expect(find.text('配对并连接'), findsOneWidget);
  });

  test('rejects loopback desktop addresses', () {
    expect(lanAddressProblem('http://127.0.0.1:18765'), isNotNull);
    expect(lanAddressProblem('localhost:18765'), isNotNull);
    expect(lanAddressProblem('http://192.168.1.10:18765'), isNull);
  });

  test('normalizes saved font scale and detects wide layouts', () {
    expect(normalizedFontScale(null), 1.0);
    expect(normalizedFontScale('0.1'), 0.8);
    expect(normalizedFontScale('9'), 1.8);
    expect(useWideLayout(699), isFalse);
    expect(useWideLayout(700), isTrue);
  });

  test('calculates synchronized app page offsets with clamping', () {
    expect(
      nextScrollOffset(
        current: 500,
        viewport: 1000,
        maximum: 2000,
        direction: 'up',
      ),
      0,
    );
    expect(
      nextScrollOffset(
        current: 500,
        viewport: 1000,
        maximum: 2000,
        direction: 'down',
      ),
      1320,
    );
    expect(
      nextScrollOffset(
        current: 1800,
        viewport: 1000,
        maximum: 2000,
        direction: 'down',
      ),
      2000,
    );
  });

  test('applies remote reading controls only on the current result page', () {
    expect(
      shouldApplyRemoteViewControl(
        tabIndex: 0,
        sourceDeviceId: 'desktop',
        localDeviceId: 'app-1',
      ),
      isTrue,
    );
    expect(
      shouldApplyRemoteViewControl(
        tabIndex: 2,
        sourceDeviceId: 'desktop',
        localDeviceId: 'app-1',
      ),
      isFalse,
    );
    expect(
      shouldApplyRemoteViewControl(
        tabIndex: 0,
        sourceDeviceId: 'app-1',
        localDeviceId: 'app-1',
      ),
      isFalse,
    );
  });

  test('remote font changes are incremental and clamped', () {
    expect(nextFontScale(1.0, 0.1), closeTo(1.1, 0.001));
    expect(nextFontScale(1.75, 0.1), 1.8);
    expect(nextFontScale(0.85, -0.1), 0.8);
    expect(resultTextScaler(1.4).scale(10), closeTo(14, 0.01));
  });

  test('ignores streaming events from a superseded task', () {
    final current = <String, dynamic>{'id': 'new-task'};
    expect(
      eventTargetsCurrentTask(<String, dynamic>{
        'task_id': 'new-task',
      }, current),
      isTrue,
    );
    expect(
      eventTargetsCurrentTask(<String, dynamic>{
        'task_id': 'old-task',
      }, current),
      isFalse,
    );
  });

  test('uses a DNS-SD service label within the protocol limit', () {
    expect(DesktopDiscovery.serviceType, '_screenasst._tcp.local');
    expect('screenasst'.codeUnits.length, lessThanOrEqualTo(15));
  });

  testWidgets('restores font scale and exposes the font settings dialog', (
    tester,
  ) async {
    FlutterSecureStorage.setMockInitialValues(<String, String>{
      'font_scale': '1.40',
    });
    await tester.pumpWidget(const ScreenAssistantApp());
    await tester.pumpAndSettle();

    final textContext = tester.element(find.text('连接局域网电脑'));
    expect(MediaQuery.textScalerOf(textContext).scale(10), closeTo(10, 0.01));
    await tester.tap(find.byTooltip('调整字体大小'));
    await tester.pumpAndSettle();
    expect(find.text('App 字体大小'), findsOneWidget);
    expect(find.textContaining('1.40×'), findsOneWidget);
  });

  testWidgets('loads and saves redacted desktop settings', (tester) async {
    String? savedBody;
    final client = MockClient((request) async {
      if (request.method == 'GET') {
        return http.Response(
          jsonEncode({
            'models': [
              {
                'id': 'model-1',
                'name': '模型 A',
                'base_url': 'https://api.example.com/v1',
                'model': 'vision-model',
                'timeout_seconds': 120,
                'max_tokens': 2048,
                'reasoning_effort': 'high',
                'api_key_configured': true,
              },
            ],
            'profiles': [
              {
                'id': 'profile-1',
                'name': '配置 A',
                'model_id': 'model-1',
                'system_prompt': '',
                'prompt_template': '分析截图',
                'language': 'auto',
                'extra_body_enabled': false,
                'extra_body': <String, dynamic>{},
              },
            ],
            'active_profile_id': 'profile-1',
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      savedBody = request.body;
      return http.Response(
        '{"command_id":"settings-1","status":"accepted"}',
        202,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
    });
    final api = LanApiClient(
      baseUrl: 'http://desktop',
      token: 'device-token',
      client: client,
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: SettingsPage(api: api)),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('模型 A'), findsOneWidget);
    expect(find.text('配置 A'), findsOneWidget);
    await tester.tap(find.text('保存到电脑'));
    await tester.pumpAndSettle();
    expect(savedBody, contains('"models"'));
    expect(savedBody, contains('"reasoning_effort":"high"'));
    expect(savedBody, isNot(contains('sk-secret')));
    api.close();
  });
}
