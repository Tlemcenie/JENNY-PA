import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/jenny_colors.dart';
import '../../providers/conversation_provider.dart';
import '../../widgets/channel_badge.dart';

class SearchPage extends ConsumerStatefulWidget {
  const SearchPage({super.key});

  @override
  ConsumerState<SearchPage> createState() => _SearchPageState();
}

class _SearchPageState extends ConsumerState<SearchPage> {
  final _searchController = TextEditingController();
  bool _hasSearched = false;

  @override
  void initState() {
    super.initState();
    final state = ref.read(conversationProvider);
    if (state.conversations.isEmpty) {
      ref.read(conversationProvider.notifier).loadConversations();
    }
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final convState = ref.watch(conversationProvider);

    final query = _searchController.text.toLowerCase();
    final results = _hasSearched && query.isNotEmpty
        ? convState.conversations.where((c) {
            return c.customerName.toLowerCase().contains(query) ||
                c.lastMessage.toLowerCase().contains(query) ||
                c.customerEmail.toLowerCase().contains(query) ||
                c.tags.any((t) => t.toLowerCase().contains(query));
          }).toList()
        : <dynamic>[];

    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: JennyColors.divider),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Recherche sémantique',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: JennyColors.textPrimary),
                ),
                const SizedBox(height: 4),
                const Text(
                  'Recherchez dans toutes vos conversations, messages et documents',
                  style: TextStyle(fontSize: 13, color: JennyColors.textSecondary),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _searchController,
                  onSubmitted: (_) => setState(() => _hasSearched = true),
                  onChanged: (_) => setState(() => _hasSearched = true),
                  decoration: InputDecoration(
                    hintText: 'Rechercher par nom, message, tag...',
                    prefixIcon: const Icon(Icons.search_rounded, color: JennyColors.textSecondary),
                    suffixIcon: _searchController.text.isNotEmpty
                        ? IconButton(
                            icon: const Icon(Icons.clear_rounded, size: 18),
                            onPressed: () {
                              _searchController.clear();
                              setState(() => _hasSearched = false);
                            },
                          )
                        : null,
                    filled: true,
                    fillColor: JennyColors.background,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide.none,
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: const BorderSide(color: JennyColors.primary, width: 2),
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          if (_hasSearched && query.isNotEmpty) ...[
            Text(
              '${results.length} résultat(s)',
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: JennyColors.textSecondary),
            ),
            const SizedBox(height: 12),
          ],
          Expanded(
            child: !_hasSearched || query.isEmpty
                ? _buildEmptyState()
                : results.isEmpty
                    ? _buildNoResults()
                    : ListView.builder(
                        itemCount: results.length,
                        itemBuilder: (context, index) {
                          final conv = results[index];
                          return _buildResultCard(conv);
                        },
                      ),
          ),
        ],
      ),
    );
  }

  Widget _buildResultCard(dynamic conv) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: JennyColors.divider),
      ),
      child: Row(
        children: [
          CircleAvatar(
            radius: 20,
            backgroundColor: JennyColors.primaryLight.withValues(alpha: 0.4),
            child: Text(conv.initials, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: JennyColors.primary)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(conv.customerName, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                    const SizedBox(width: 8),
                    ChannelBadge(channel: conv.channel, size: 20),
                    const SizedBox(width: 6),
                    StatusBadge(status: conv.status),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  conv.lastMessage,
                  style: const TextStyle(fontSize: 13, color: JennyColors.textSecondary),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.search_rounded, size: 56, color: JennyColors.textSecondary.withValues(alpha: 0.3)),
          const SizedBox(height: 16),
          const Text('Commencez à taper pour rechercher', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w500, color: JennyColors.textSecondary)),
        ],
      ),
    );
  }

  Widget _buildNoResults() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.search_off_rounded, size: 56, color: JennyColors.textSecondary.withValues(alpha: 0.3)),
          const SizedBox(height: 16),
          const Text('Aucun résultat trouvé', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w500, color: JennyColors.textSecondary)),
        ],
      ),
    );
  }
}
