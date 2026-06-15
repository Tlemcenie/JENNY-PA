class Message {
  final String id;
  final String conversationId;
  final String sender;
  final String text;
  final String createdAt;
  final bool read;

  const Message({
    required this.id,
    required this.conversationId,
    required this.sender,
    required this.text,
    required this.createdAt,
    this.read = false,
  });

  factory Message.fromJson(Map<String, dynamic> json) => Message(
        id: json['id'] as String,
        conversationId: json['conversation_id'] as String? ?? '',
        sender: json['sender'] as String? ?? 'customer',
        text: json['text'] as String? ?? '',
        createdAt: json['created_at'] as String? ?? '',
        read: json['read'] as bool? ?? false,
      );

  bool get isCustomer => sender == 'customer';
  bool get isAgent => sender == 'agent';
}

class AiSuggestion {
  final String suggestedReply;
  final String detectedTopic;
  final String confidence;

  const AiSuggestion({
    required this.suggestedReply,
    required this.detectedTopic,
    required this.confidence,
  });

  factory AiSuggestion.fromJson(Map<String, dynamic> json) => AiSuggestion(
        suggestedReply: json['suggested_reply'] as String? ?? '',
        detectedTopic: json['detected_topic'] as String? ?? '',
        confidence: json['confidence'] as String? ?? '0',
      );

  double get confidenceValue => double.tryParse(confidence) ?? 0;
  int get confidencePercent => (confidenceValue * 100).round();
}
