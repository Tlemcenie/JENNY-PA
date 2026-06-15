import 'package:flutter/material.dart';
import '../../core/theme/jenny_colors.dart';
import '../../models/conversation.dart';
import '../../widgets/channel_badge.dart';

class ConversationList extends StatelessWidget {
  final List<Conversation> conversations;
  final String? selectedId;
  final ValueChanged<Conversation> onSelect;

  const ConversationList({
    super.key,
    required this.conversations,
    this.selectedId,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    if (conversations.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.inbox_rounded, size: 40, color: JennyColors.textSecondary.withValues(alpha: 0.4)),
            const SizedBox(height: 12),
            const Text(
              'Aucune conversation',
              style: TextStyle(color: JennyColors.textSecondary, fontSize: 14),
            ),
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.symmetric(vertical: 4),
      itemCount: conversations.length,
      itemBuilder: (context, index) {
        final conv = conversations[index];
        return _ConversationTile(
          conversation: conv,
          isSelected: conv.id == selectedId,
          onTap: () => onSelect(conv),
        );
      },
    );
  }
}

class _ConversationTile extends StatefulWidget {
  final Conversation conversation;
  final bool isSelected;
  final VoidCallback onTap;

  const _ConversationTile({
    required this.conversation,
    required this.isSelected,
    required this.onTap,
  });

  @override
  State<_ConversationTile> createState() => _ConversationTileState();
}

class _ConversationTileState extends State<_ConversationTile> {
  bool _isHovered = false;

  @override
  Widget build(BuildContext context) {
    final conv = widget.conversation;
    return MouseRegion(
      onEnter: (_) => setState(() => _isHovered = true),
      onExit: (_) => setState(() => _isHovered = false),
      child: GestureDetector(
        onTap: widget.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: widget.isSelected
                ? JennyColors.primary.withValues(alpha: 0.06)
                : _isHovered
                    ? JennyColors.background
                    : Colors.transparent,
            borderRadius: BorderRadius.circular(12),
            border: widget.isSelected
                ? Border.all(color: JennyColors.primary.withValues(alpha: 0.3))
                : null,
          ),
          child: Row(
            children: [
              Stack(
                children: [
                  CircleAvatar(
                    radius: 20,
                    backgroundColor: JennyColors.primaryLight.withValues(alpha: 0.4),
                    child: Text(
                      conv.initials,
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: JennyColors.primary,
                      ),
                    ),
                  ),
                  if (conv.unread)
                    Positioned(
                      right: 0,
                      top: 0,
                      child: Container(
                        width: 10,
                        height: 10,
                        decoration: BoxDecoration(
                          color: JennyColors.primary,
                          shape: BoxShape.circle,
                          border: Border.all(color: Colors.white, width: 2),
                        ),
                      ),
                    ),
                ],
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            conv.customerName,
                            style: TextStyle(
                              fontSize: 13,
                              fontWeight: conv.unread ? FontWeight.w700 : FontWeight.w500,
                              color: JennyColors.textPrimary,
                            ),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        PriorityDot(priority: conv.priority),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      conv.lastMessage,
                      style: TextStyle(
                        fontSize: 12,
                        color: conv.unread ? JennyColors.textPrimary : JennyColors.textSecondary,
                        fontWeight: conv.unread ? FontWeight.w500 : FontWeight.w400,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        ChannelBadge(channel: conv.channel, size: 18),
                        const SizedBox(width: 6),
                        StatusBadge(status: conv.status),
                        const Spacer(),
                        if (conv.tags.isNotEmpty)
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                            decoration: BoxDecoration(
                              color: JennyColors.structure.withValues(alpha: 0.1),
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: Text(
                              conv.tags.first,
                              style: const TextStyle(
                                fontSize: 9,
                                fontWeight: FontWeight.w600,
                                color: JennyColors.structure,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
