import 'dart:io';

import 'package:flutter/services.dart';
import 'package:multicast_dns/multicast_dns.dart';

class DiscoveredDesktop {
  const DiscoveredDesktop({required this.name, required this.url});
  final String name;
  final String url;
}

class DesktopDiscovery {
  static const String serviceType = '_screenasst._tcp.local';
  static const MethodChannel _channel = MethodChannel('screen_assistant/mdns');
  MDnsClient? _client;

  Future<List<DiscoveredDesktop>> scan() async {
    await stop();
    await _channel.invokeMethod<void>('acquire');
    final client = MDnsClient(
      rawDatagramSocketFactory:
          (
            dynamic host,
            int port, {
            bool? reuseAddress,
            bool? reusePort,
            int? ttl,
          }) {
            return RawDatagramSocket.bind(
              host,
              port,
              reuseAddress: true,
              reusePort: false,
              ttl: ttl ?? 1,
            );
          },
    );
    _client = client;
    await client.start();
    final results = <String, DiscoveredDesktop>{};
    await for (final ptr
        in client
            .lookup<PtrResourceRecord>(
              ResourceRecordQuery.serverPointer(serviceType),
            )
            .timeout(
              const Duration(seconds: 4),
              onTimeout: (sink) => sink.close(),
            )) {
      await for (final srv in client.lookup<SrvResourceRecord>(
        ResourceRecordQuery.service(ptr.domainName),
      )) {
        await for (final record in client.lookup<IPAddressResourceRecord>(
          ResourceRecordQuery.addressIPv4(srv.target),
        )) {
          final name = ptr.domainName.split('.$serviceType').first;
          results[ptr.domainName] = DiscoveredDesktop(
            name: name,
            url: 'http://${record.address.address}:${srv.port}',
          );
          break;
        }
      }
    }
    await stop();
    return results.values.toList();
  }

  Future<void> stop() async {
    _client?.stop();
    _client = null;
    try {
      await _channel.invokeMethod<void>('release');
    } on MissingPluginException {
      // Widget tests and non-Android targets do not register this channel.
    }
  }
}
