import '../core/api/api_client.dart';
import '../models/message.dart';

class AiService {
  final ApiClient _api = ApiClient();

  Future<AiSuggestion> suggest(String text) async {
    final response = await _api.post('/ai/suggest', data: {'text': text});
    return AiSuggestion.fromJson(response.data as Map<String, dynamic>);
  }

  Future<AiSuggestion> suggestForConversation(String conversationId) async {
    final response = await _api.get('/conversations/$conversationId/ai-suggest');
    return AiSuggestion.fromJson(response.data as Map<String, dynamic>);
  }
}
