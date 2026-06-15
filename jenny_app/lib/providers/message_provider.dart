import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/message.dart';
import '../services/message_service.dart';
import '../services/ai_service.dart';

class MessageState {
  final bool isLoading;
  final List<Message> messages;
  final AiSuggestion? aiSuggestion;
  final bool isSending;
  final bool isLoadingSuggestion;
  final String? error;

  const MessageState({
    this.isLoading = false,
    this.messages = const [],
    this.aiSuggestion,
    this.isSending = false,
    this.isLoadingSuggestion = false,
    this.error,
  });

  MessageState copyWith({
    bool? isLoading,
    List<Message>? messages,
    AiSuggestion? aiSuggestion,
    bool? isSending,
    bool? isLoadingSuggestion,
    String? error,
  }) =>
      MessageState(
        isLoading: isLoading ?? this.isLoading,
        messages: messages ?? this.messages,
        aiSuggestion: aiSuggestion ?? this.aiSuggestion,
        isSending: isSending ?? this.isSending,
        isLoadingSuggestion: isLoadingSuggestion ?? this.isLoadingSuggestion,
        error: error,
      );
}

class MessageNotifier extends StateNotifier<MessageState> {
  final MessageService _messageService = MessageService();
  final AiService _aiService = AiService();

  MessageNotifier() : super(const MessageState());

  Future<void> loadMessages(String conversationId) async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final messages = await _messageService.listMessages(conversationId);
      state = state.copyWith(isLoading: false, messages: messages);
      loadAiSuggestion(conversationId);
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  Future<void> sendMessage(String conversationId, String text) async {
    state = state.copyWith(isSending: true, error: null);
    try {
      final msg = await _messageService.sendMessage(conversationId, text);
      state = state.copyWith(
        isSending: false,
        messages: [...state.messages, msg],
      );
    } catch (e) {
      state = state.copyWith(isSending: false, error: e.toString());
    }
  }

  Future<void> loadAiSuggestion(String conversationId) async {
    state = state.copyWith(isLoadingSuggestion: true);
    try {
      final suggestion = await _aiService.suggestForConversation(conversationId);
      state = state.copyWith(isLoadingSuggestion: false, aiSuggestion: suggestion);
    } catch (_) {
      state = state.copyWith(isLoadingSuggestion: false);
    }
  }

  void clearMessages() {
    state = const MessageState();
  }
}

final messageProvider = StateNotifierProvider<MessageNotifier, MessageState>((ref) {
  return MessageNotifier();
});
