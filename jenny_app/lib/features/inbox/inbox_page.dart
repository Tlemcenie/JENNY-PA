import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/jenny_colors.dart';
import '../../providers/conversation_provider.dart';
import '../../providers/message_provider.dart';
import '../../widgets/shimmer_loading.dart';
import 'conversation_list.dart';
import 'chat_view.dart';
import 'ai_suggestion_panel.dart';

class InboxPage extends ConsumerStatefulWidget {
  const InboxPage({super.key});

  @override
  ConsumerState<InboxPage> createState() => _InboxPageState();
}

class _InboxPageState extends ConsumerState<InboxPage> {
  @override
  void initState() {
    super.initState();
    ref.read(conversationProvider.notifier).loadConversations();
  }

  @override
  Widget build(BuildContext context) {
    final convState = ref.watch(conversationProvider);
    final msgState = ref.watch(messageProvider);

    return Row(
      children: [
        SizedBox(
          width: 340,
          child: Container(
            decoration: const BoxDecoration(
              color: Colors.white,
              border: Border(right: BorderSide(color: JennyColors.divider)),
            ),
            child: Column(
              children: [
                _buildSearchAndFilters(),
                Expanded(
                  child: convState.status == LoadStatus.loading
                      ? const ShimmerList(count: 6)
                      : ConversationList(
                          conversations: convState.filteredConversations,
                          selectedId: convState.selected?.id,
                          onSelect: (conv) {
                            ref.read(conversationProvider.notifier).selectConversation(conv);
                            ref.read(messageProvider.notifier).loadMessages(conv.id);
                          },
                        ),
                ),
              ],
            ),
          ),
        ),
        Expanded(
          child: convState.selected == null
              ? _buildEmptyState()
              : ChatView(
                  conversation: convState.selected!,
                  messages: msgState.messages,
                  isLoading: msgState.isLoading,
                  isSending: msgState.isSending,
                  onSend: (text) {
                    ref.read(messageProvider.notifier).sendMessage(
                          convState.selected!.id,
                          text,
                        );
                  },
                ),
        ),
        if (convState.selected != null)
          SizedBox(
            width: 300,
            child: AiSuggestionPanel(
              conversation: convState.selected!,
              suggestion: msgState.aiSuggestion,
              isLoading: msgState.isLoadingSuggestion,
              onUseSuggestion: (text) {
                ref.read(messageProvider.notifier).sendMessage(
                      convState.selected!.id,
                      text,
                    );
              },
            ),
          ),
      ],
    );
  }

  Widget _buildSearchAndFilters() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: JennyColors.divider)),
      ),
      child: Column(
        children: [
          TextField(
            onChanged: (v) => ref.read(conversationProvider.notifier).setSearch(v),
            decoration: InputDecoration(
              hintText: 'Rechercher une conversation...',
              hintStyle: const TextStyle(fontSize: 13, color: JennyColors.textSecondary),
              prefixIcon: const Icon(Icons.search_rounded, size: 20, color: JennyColors.textSecondary),
              filled: true,
              fillColor: JennyColors.background,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(10),
                borderSide: BorderSide.none,
              ),
              contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              isDense: true,
            ),
            style: const TextStyle(fontSize: 13),
          ),
          const SizedBox(height: 8),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                _filterChip('Tous', null),
                _filterChip('Ouverts', 'open'),
                _filterChip('Résolus', 'resolved'),
                const SizedBox(width: 8),
                Container(width: 1, height: 20, color: JennyColors.divider),
                const SizedBox(width: 8),
                _channelChip('WhatsApp', 'whatsapp'),
                _channelChip('Instagram', 'instagram'),
                _channelChip('Email', 'email'),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _filterChip(String label, String? status) {
    final current = ref.watch(conversationProvider).filterStatus;
    final isActive = current == status;
    return Padding(
      padding: const EdgeInsets.only(right: 6),
      child: GestureDetector(
        onTap: () => ref.read(conversationProvider.notifier).setFilter(status: status),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(
            color: isActive ? JennyColors.primary : JennyColors.background,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w500,
              color: isActive ? Colors.white : JennyColors.textSecondary,
            ),
          ),
        ),
      ),
    );
  }

  Widget _channelChip(String label, String channel) {
    return Padding(
      padding: const EdgeInsets.only(right: 6),
      child: GestureDetector(
        onTap: () => ref.read(conversationProvider.notifier).setFilter(channel: channel),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: JennyColors.background,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            label,
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w500,
              color: JennyColors.textSecondary,
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: JennyColors.primaryLight.withValues(alpha: 0.2),
              shape: BoxShape.circle,
            ),
            child: Icon(
              Icons.chat_bubble_outline_rounded,
              size: 48,
              color: JennyColors.primary.withValues(alpha: 0.5),
            ),
          ),
          const SizedBox(height: 20),
          const Text(
            'Sélectionnez une conversation',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w600,
              color: JennyColors.textPrimary,
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            'Choisissez une conversation dans la liste\npour commencer à répondre',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 13,
              color: JennyColors.textSecondary,
              height: 1.5,
            ),
          ),
        ],
      ),
    );
  }
}
