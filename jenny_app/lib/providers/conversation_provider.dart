import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/conversation.dart';
import '../services/conversation_service.dart';

enum LoadStatus { initial, loading, loaded, error }

class ConversationState {
  final LoadStatus status;
  final List<Conversation> conversations;
  final Conversation? selected;
  final String? error;
  final String? filterStatus;
  final String? filterChannel;
  final String searchQuery;

  const ConversationState({
    this.status = LoadStatus.initial,
    this.conversations = const [],
    this.selected,
    this.error,
    this.filterStatus,
    this.filterChannel,
    this.searchQuery = '',
  });

  ConversationState copyWith({
    LoadStatus? status,
    List<Conversation>? conversations,
    Conversation? selected,
    String? error,
    String? filterStatus,
    String? filterChannel,
    String? searchQuery,
  }) =>
      ConversationState(
        status: status ?? this.status,
        conversations: conversations ?? this.conversations,
        selected: selected ?? this.selected,
        error: error,
        filterStatus: filterStatus ?? this.filterStatus,
        filterChannel: filterChannel ?? this.filterChannel,
        searchQuery: searchQuery ?? this.searchQuery,
      );

  int get unreadCount => conversations.where((c) => c.unread).length;

  List<Conversation> get filteredConversations {
    var result = conversations;
    if (searchQuery.isNotEmpty) {
      final q = searchQuery.toLowerCase();
      result = result
          .where((c) =>
              c.customerName.toLowerCase().contains(q) ||
              c.lastMessage.toLowerCase().contains(q))
          .toList();
    }
    return result;
  }
}

class ConversationNotifier extends StateNotifier<ConversationState> {
  final ConversationService _service = ConversationService();

  ConversationNotifier() : super(const ConversationState());

  Future<void> loadConversations() async {
    state = state.copyWith(status: LoadStatus.loading, error: null);
    try {
      final convs = await _service.listConversations(
        status: state.filterStatus,
        channel: state.filterChannel,
      );
      state = state.copyWith(status: LoadStatus.loaded, conversations: convs);
    } catch (e) {
      state = state.copyWith(status: LoadStatus.error, error: e.toString());
    }
  }

  void selectConversation(Conversation conv) {
    state = state.copyWith(selected: conv);
  }

  void setSearch(String query) {
    state = state.copyWith(searchQuery: query);
  }

  void setFilter({String? status, String? channel}) {
    state = state.copyWith(filterStatus: status, filterChannel: channel);
    loadConversations();
  }
}

final conversationProvider =
    StateNotifierProvider<ConversationNotifier, ConversationState>((ref) {
  return ConversationNotifier();
});
