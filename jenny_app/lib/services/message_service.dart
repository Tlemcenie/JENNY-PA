import '../core/api/api_client.dart';
import '../models/message.dart';

class MessageService {
  final ApiClient _api = ApiClient();

  Future<List<Message>> listMessages(String conversationId) async {
    final response = await _api.get('/conversations/$conversationId/messages');
    final data = response.data as List<dynamic>;
    return data.map((e) => Message.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Message> sendMessage(String conversationId, String text) async {
    final response = await _api.post(
      '/conversations/$conversationId/messages',
      data: {'text': text},
    );
    return Message.fromJson(response.data as Map<String, dynamic>);
  }
}
