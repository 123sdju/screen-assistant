import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  ApiException(this.message, {this.statusCode});
  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

bool shouldRetryLanConnection(Object error) {
  return error is! ApiException || error.statusCode != 401;
}

class LanApiClient {
  LanApiClient({required this.baseUrl, this.token, http.Client? client})
    : client = client ?? http.Client();

  final String baseUrl;
  final String? token;
  final http.Client client;
  bool _closed = false;

  Map<String, String> get _headers {
    final headers = <String, String>{'Content-Type': 'application/json'};
    final accessToken = token;
    if (accessToken != null && accessToken.isNotEmpty) {
      headers['Authorization'] = 'Bearer $accessToken';
    }
    return headers;
  }

  Future<Map<String, dynamic>> pair({
    required String code,
    required String deviceId,
    required String deviceName,
  }) {
    return _post('/v1/pair', <String, Object?>{
      'code': code,
      'device_id': deviceId,
      'device_name': deviceName,
    });
  }

  Future<Map<String, dynamic>> bootstrap() => _get('/v1/bootstrap');
  Future<Map<String, dynamic>> task(String id) => _get('/v1/tasks/$id');
  Future<Map<String, dynamic>> settings() => _get('/v1/settings');

  Future<Map<String, dynamic>> updateSettings(Map<String, dynamic> settings) {
    return _put('/v1/settings', <String, Object?>{'settings': settings});
  }

  Future<Map<String, dynamic>> command(String command, {String? profileId}) {
    return _post('/v1/commands', <String, Object?>{
      'command': command,
      'profile_id': ?profileId,
    });
  }

  Future<void> streamEvents(
    void Function(Map<String, dynamic>) onEvent,
    FutureOr<void> Function(Object error) onError,
  ) async {
    if (_closed) return;
    final request = http.Request('GET', Uri.parse('$baseUrl/v1/events'));
    request.headers.addAll(_headers);
    try {
      final response = await client.send(request);
      if (_closed) return;
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final body = await response.stream.bytesToString();
        throw ApiException(
          _errorMessage(response.statusCode, body),
          statusCode: response.statusCode,
        );
      }
      await for (final line
          in response.stream
              .transform(utf8.decoder)
              .transform(const LineSplitter())) {
        if (!line.startsWith('data:')) continue;
        final raw = line.substring(5).trim();
        if (raw.isEmpty) continue;
        final decoded = jsonDecode(raw);
        if (decoded is Map<String, dynamic>) onEvent(decoded);
      }
      if (_closed) return;
      throw ApiException('局域网事件连接已断开');
    } catch (error) {
      if (_closed) return;
      await onError(error);
    }
  }

  Future<Map<String, dynamic>> _get(String path) async {
    try {
      final response = await client
          .get(Uri.parse('$baseUrl$path'), headers: _headers)
          .timeout(const Duration(seconds: 15));
      return _decodeMap(response);
    } on SocketException {
      throw ApiException('无法连接电脑。请确认手机和电脑在同一 Wi-Fi，电脑端正在运行，并允许防火墙访问。');
    } on http.ClientException {
      throw ApiException('无法连接电脑。请确认手机和电脑在同一 Wi-Fi，电脑端正在运行，并允许防火墙访问。');
    } on TimeoutException {
      throw ApiException('连接电脑超时。请检查局域网 IP、Wi-Fi 和 Windows 防火墙。');
    }
  }

  Future<Map<String, dynamic>> _post(
    String path,
    Map<String, Object?> payload,
  ) async {
    try {
      final response = await client
          .post(
            Uri.parse('$baseUrl$path'),
            headers: _headers,
            body: jsonEncode(payload),
          )
          .timeout(const Duration(seconds: 20));
      return _decodeMap(response);
    } on SocketException {
      throw ApiException('无法连接电脑。请确认手机和电脑在同一 Wi-Fi，电脑端正在运行，并允许防火墙访问。');
    } on http.ClientException {
      throw ApiException('无法连接电脑。请确认手机和电脑在同一 Wi-Fi，电脑端正在运行，并允许防火墙访问。');
    } on TimeoutException {
      throw ApiException('连接电脑超时。请检查局域网 IP、Wi-Fi 和 Windows 防火墙。');
    }
  }

  Future<Map<String, dynamic>> _put(
    String path,
    Map<String, Object?> payload,
  ) async {
    try {
      final response = await client
          .put(
            Uri.parse('$baseUrl$path'),
            headers: _headers,
            body: jsonEncode(payload),
          )
          .timeout(const Duration(seconds: 20));
      return _decodeMap(response);
    } on SocketException {
      throw ApiException('无法连接电脑。请确认手机和电脑在同一 Wi-Fi，电脑端正在运行，并允许防火墙访问。');
    } on http.ClientException {
      throw ApiException('无法连接电脑。请确认手机和电脑在同一 Wi-Fi，电脑端正在运行，并允许防火墙访问。');
    } on TimeoutException {
      throw ApiException('连接电脑超时。请检查局域网 IP、Wi-Fi 和 Windows 防火墙。');
    }
  }

  Map<String, dynamic> _decodeMap(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(
        _errorMessage(response.statusCode, response.body),
        statusCode: response.statusCode,
      );
    }
    final value = jsonDecode(utf8.decode(response.bodyBytes));
    if (value is! Map<String, dynamic>) throw ApiException('电脑返回了无效的数据格式');
    return value;
  }

  String _errorMessage(int status, String body) {
    try {
      final value = jsonDecode(body);
      if (value is Map<String, dynamic> && value['detail'] != null) {
        return value['detail'].toString();
      }
    } catch (_) {}
    return 'HTTP $status：$body';
  }

  void close() {
    _closed = true;
    client.close();
  }
}
