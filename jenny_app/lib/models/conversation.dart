class Conversation {
  final String id;
  final String customerName;
  final String customerEmail;
  final String channel;
  final String status;
  final bool unread;
  final String priority;
  final List<String> tags;
  final String lastMessage;
  final String lastMessageAt;
  final String createdAt;
  final String? assignedTo;

  const Conversation({
    required this.id,
    required this.customerName,
    required this.customerEmail,
    required this.channel,
    required this.status,
    required this.unread,
    required this.priority,
    required this.tags,
    required this.lastMessage,
    required this.lastMessageAt,
    required this.createdAt,
    this.assignedTo,
  });

  factory Conversation.fromJson(Map<String, dynamic> json) => Conversation(
        id: json['id'] as String,
        customerName: json['customer_name'] as String? ?? '',
        customerEmail: json['customer_email'] as String? ?? '',
        channel: json['channel'] as String? ?? 'email',
        status: json['status'] as String? ?? 'open',
        unread: json['unread'] as bool? ?? false,
        priority: json['priority'] as String? ?? 'low',
        tags: (json['tags'] as List<dynamic>?)?.cast<String>() ?? [],
        lastMessage: json['last_message'] as String? ?? '',
        lastMessageAt: json['last_message_at'] as String? ?? '',
        createdAt: json['created_at'] as String? ?? '',
        assignedTo: json['assigned_to'] as String?,
      );

  String get initials {
    final parts = customerName.trim().split(' ');
    if (parts.length >= 2) return '${parts[0][0]}${parts[1][0]}'.toUpperCase();
    return customerName.isNotEmpty ? customerName[0].toUpperCase() : '?';
  }

  bool get isOpen => status == 'open';
  bool get isHighPriority => priority == 'high';
}
