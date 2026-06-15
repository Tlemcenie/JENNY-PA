import '../core/api/api_client.dart';
import '../models/notification_model.dart';

class NotificationService {
  final ApiClient _api = ApiClient();

  Future<List<NotificationItem>> listNotifications() async {
    final response = await _api.get('/notifications');
    final data = response.data as List<dynamic>;
    return data.map((e) => NotificationItem.fromJson(e as Map<String, dynamic>)).toList();
  }
}
