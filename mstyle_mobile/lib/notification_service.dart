import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:onesignal_flutter/onesignal_flutter.dart';

class NotificationService {
  static final _plugin = FlutterLocalNotificationsPlugin();
  static bool _initialized = false;

  static const _oneSignalAppId = 'd340ecba-5d1c-4864-a4b9-5895e0cf5a85';

  static Future<void> init() async {
    if (kIsWeb) return; // not supported on web
    if (_initialized) return;
    const android = AndroidInitializationSettings('@mipmap/ic_launcher');
    await _plugin.initialize(
      settings: const InitializationSettings(android: android),
    );
    await _plugin
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.requestNotificationsPermission();
    _initialized = true;
  }

  static Future<void> setupOneSignal() async {
    if (kIsWeb) return; // not supported on web
    await init();

    OneSignal.initialize(_oneSignalAppId);
    await OneSignal.Notifications.requestPermission(true);

    OneSignal.Notifications.addForegroundWillDisplayListener((event) {
      event.preventDefault();
      final notif = event.notification;
      show(
        id: notif.notificationId.hashCode,
        title: notif.title ?? 'MStyle',
        body: notif.body ?? '',
      );
    });
  }

  static Future<String?> getPlayerId() async {
    if (kIsWeb) return null;
    return OneSignal.User.pushSubscription.id;
  }

  static Future<void> show({
    required int id,
    required String title,
    required String body,
  }) async {
    if (kIsWeb) return;
    await init();
    const details = NotificationDetails(
      android: AndroidNotificationDetails(
        'mstyle_buyer',
        'MStyle Buyer',
        channelDescription: 'Order and delivery updates',
        importance: Importance.high,
        priority: Priority.high,
        icon: '@mipmap/ic_launcher',
      ),
    );
    await _plugin.show(
      id: id,
      title: title,
      body: body,
      notificationDetails: details,
    );
  }
}
