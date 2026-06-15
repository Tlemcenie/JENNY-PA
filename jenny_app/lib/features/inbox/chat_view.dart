import 'package:flutter/material.dart';
import '../../core/theme/jenny_colors.dart';
import '../../models/conversation.dart';
import '../../models/message.dart';
import '../../widgets/channel_badge.dart';
import '../../widgets/shimmer_loading.dart';

class ChatView extends StatefulWidget {
  final Conversation conversation;
  final List<Message> messages;
  final bool isLoading;
  final bool isSending;
  final ValueChanged<String> onSend;

  const ChatView({
    super.key,
    required this.conversation,
    required this.messages,
    required this.isLoading,
    required this.isSending,
    required this.onSend,
  });

  @override
  State<ChatView> createState() => _ChatViewState();
}

class _ChatViewState extends State<ChatView> {
  final _controller = TextEditingController();
  final _scrollController = ScrollController();

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(ChatView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.messages.length > oldWidget.messages.length) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToBottom());
    }
  }

  void _scrollToBottom() {
    if (_scrollController.hasClients) {
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOutCubic,
      );
    }
  }

  void _handleSend() {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    widget.onSend(text);
    _controller.clear();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: JennyColors.background,
        border: Border(right: BorderSide(color: JennyColors.divider)),
      ),
      child: Column(
        children: [
          _buildHeader(),
          Expanded(
            child: widget.isLoading
                ? const ShimmerList(count: 4)
                : _buildMessageList(),
          ),
          _buildInput(),
        ],
      ),
    );
  }

  Widget _buildHeader() {
    final conv = widget.conversation;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(bottom: BorderSide(color: JennyColors.divider)),
      ),
      child: Row(
        children: [
          CircleAvatar(
            radius: 18,
            backgroundColor: JennyColors.primaryLight.withValues(alpha: 0.4),
            child: Text(
              conv.initials,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: JennyColors.primary,
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  conv.customerName,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: JennyColors.textPrimary,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  conv.customerEmail,
                  style: const TextStyle(fontSize: 11, color: JennyColors.textSecondary),
                ),
              ],
            ),
          ),
          ChannelBadge(channel: conv.channel),
          const SizedBox(width: 8),
          StatusBadge(status: conv.status),
        ],
      ),
    );
  }

  Widget _buildMessageList() {
    return ListView.builder(
      controller: _scrollController,
      padding: const EdgeInsets.all(20),
      itemCount: widget.messages.length,
      itemBuilder: (context, index) {
        final msg = widget.messages[index];
        final isCustomer = msg.isCustomer;
        return Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Row(
            mainAxisAlignment: isCustomer ? MainAxisAlignment.start : MainAxisAlignment.end,
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              if (isCustomer) ...[
                CircleAvatar(
                  radius: 14,
                  backgroundColor: JennyColors.structure.withValues(alpha: 0.15),
                  child: const Icon(Icons.person_rounded, size: 14, color: JennyColors.structure),
                ),
                const SizedBox(width: 8),
              ],
              Flexible(
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 300),
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                  decoration: BoxDecoration(
                    color: isCustomer ? Colors.white : JennyColors.primary,
                    borderRadius: BorderRadius.only(
                      topLeft: const Radius.circular(16),
                      topRight: const Radius.circular(16),
                      bottomLeft: isCustomer ? const Radius.circular(4) : const Radius.circular(16),
                      bottomRight: isCustomer ? const Radius.circular(16) : const Radius.circular(4),
                    ),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withValues(alpha: 0.04),
                        blurRadius: 8,
                        offset: const Offset(0, 2),
                      ),
                    ],
                  ),
                  child: Text(
                    msg.text,
                    style: TextStyle(
                      fontSize: 13,
                      color: isCustomer ? JennyColors.textPrimary : Colors.white,
                      height: 1.5,
                    ),
                  ),
                ),
              ),
              if (!isCustomer) ...[
                const SizedBox(width: 8),
                CircleAvatar(
                  radius: 14,
                  backgroundColor: JennyColors.primary.withValues(alpha: 0.15),
                  child: const Text('J', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: JennyColors.primary)),
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _buildInput() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        border: const Border(top: BorderSide(color: JennyColors.divider)),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.03),
            blurRadius: 10,
            offset: const Offset(0, -2),
          ),
        ],
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _controller,
              onSubmitted: (_) => _handleSend(),
              decoration: InputDecoration(
                hintText: 'Écrire un message...',
                hintStyle: const TextStyle(fontSize: 13, color: JennyColors.textSecondary),
                filled: true,
                fillColor: JennyColors.background,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide.none,
                ),
                contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              ),
              style: const TextStyle(fontSize: 13),
            ),
          ),
          const SizedBox(width: 10),
          GestureDetector(
            onTap: widget.isSending ? null : _handleSend,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                gradient: JennyColors.primaryGradient,
                borderRadius: BorderRadius.circular(12),
                boxShadow: [
                  BoxShadow(
                    color: JennyColors.primary.withValues(alpha: 0.3),
                    blurRadius: 8,
                    offset: const Offset(0, 2),
                  ),
                ],
              ),
              child: widget.isSending
                  ? const Center(
                      child: SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          valueColor: AlwaysStoppedAnimation(Colors.white),
                        ),
                      ),
                    )
                  : const Icon(Icons.send_rounded, color: Colors.white, size: 20),
            ),
          ),
        ],
      ),
    );
  }
}
