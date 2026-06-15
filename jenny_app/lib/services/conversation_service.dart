import '../core/api/api_client.dart';
import '../models/conversation.dart';

class ConversationService {
  final ApiClient _api = ApiClient();

  Future<List<Conversation>> listConversations({
    String? status,
    String? channel,
    String? query,
  }) async {
    final params = <String, dynamic>{};
    if (status != null) params['status'] = status;
    if (channel != null) params['channel'] = channel;
    if (query != null && query.isNotEmpty) params['q'] = query;

    final response = await _api.get('/conversations', queryParameters: params);
    final data = response.data as List<dynamic>;
    return data.map((e) => Conversation.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Conversation> getConversation(String id) async {
    final response = await _api.get('/conversations/$id');
    return Conversation.fromJson(response.data as Map<String, dynamic>);
  }
}
