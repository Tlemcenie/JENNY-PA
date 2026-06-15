import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/notification_model.dart';
import '../services/notification_service.dart';

class NotificationState {
  final bool isLoading;
  final List<NotificationItem> notifications;
  final String? error;

  const NotificationState({
    this.isLoading = false,
    this.notifications = const [],
    this.error,
  });

  NotificationState copyWith({
    bool? isLoading,
    List<NotificationItem>? notifications,
    String? error,
  }) =>
      NotificationState(
        isLoading: isLoading ?? this.isLoading,
        notifications: notifications ?? this.notifications,
        error: error,
      );

  int get unreadCount => notifications.where((n) => !n.read).length;
}

class NotificationNotifier extends StateNotifier<NotificationState> {
  final NotificationService _service = NotificationService();

  NotificationNotifier() : super(const NotificationState());

  Future<void> loadNotifications() async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final items = await _service.listNotifications();
      state = state.copyWith(isLoading: false, notifications: items);
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }
}

final notificationProvider =
    StateNotifierProvider<NotificationNotifier, NotificationState>((ref) {
  return NotificationNotifier();
});
