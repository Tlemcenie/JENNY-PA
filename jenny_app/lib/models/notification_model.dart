class NotificationItem {
  final String id;
  final String type;
  final String title;
  final String body;
  final bool read;
  final String createdAt;

  const NotificationItem({
    required this.id,
    required this.type,
    required this.title,
    required this.body,
    required this.read,
    required this.createdAt,
  });

  factory NotificationItem.fromJson(Map<String, dynamic> json) => NotificationItem(
        id: json['id'] as String,
        title: json['title'] as String? ?? '',
        type: json['type'] as String? ?? 'system',
        body: json['body'] as String? ?? '',
        read: json['read'] as bool? ?? false,
        createdAt: json['created_at'] as String? ?? '',
      );
}
