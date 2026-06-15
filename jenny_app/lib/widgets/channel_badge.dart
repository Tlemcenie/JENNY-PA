import 'package:flutter/material.dart';
import '../core/theme/jenny_colors.dart';

class ChannelBadge extends StatelessWidget {
  final String channel;
  final double size;

  const ChannelBadge({super.key, required this.channel, this.size = 28});

  @override
  Widget build(BuildContext context) {
    final config = _channelConfig(channel);
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: config.color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Icon(config.icon, size: size * 0.55, color: config.color),
    );
  }

  static _ChannelConfig _channelConfig(String channel) {
    switch (channel.toLowerCase()) {
      case 'whatsapp':
        return _ChannelConfig(JennyColors.whatsapp, Icons.chat_rounded);
      case 'instagram':
        return _ChannelConfig(JennyColors.instagram, Icons.camera_alt_rounded);
      case 'email':
        return _ChannelConfig(JennyColors.email, Icons.email_rounded);
      case 'twitter':
        return _ChannelConfig(JennyColors.twitter, Icons.alternate_email_rounded);
      default:
        return _ChannelConfig(JennyColors.structure, Icons.message_rounded);
    }
  }
}

class _ChannelConfig {
  final Color color;
  final IconData icon;
  const _ChannelConfig(this.color, this.icon);
}

class StatusBadge extends StatelessWidget {
  final String status;

  const StatusBadge({super.key, required this.status});

  @override
  Widget build(BuildContext context) {
    final isOpen = status == 'open';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: isOpen
            ? JennyColors.success.withValues(alpha: 0.12)
            : JennyColors.textSecondary.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        isOpen ? 'Open' : 'Resolved',
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          color: isOpen ? JennyColors.success : JennyColors.textSecondary,
        ),
      ),
    );
  }
}

class PriorityDot extends StatelessWidget {
  final String priority;

  const PriorityDot({super.key, required this.priority});

  @override
  Widget build(BuildContext context) {
    Color color;
    switch (priority.toLowerCase()) {
      case 'high':
        color = JennyColors.error;
      case 'medium':
        color = JennyColors.warning;
      default:
        color = JennyColors.success;
    }
    return Container(
      width: 8,
      height: 8,
      decoration: BoxDecoration(shape: BoxShape.circle, color: color),
    );
  }
}
