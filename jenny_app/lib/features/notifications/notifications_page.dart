import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/jenny_colors.dart';
import '../../providers/notification_provider.dart';
import '../../models/notification_model.dart';
import '../../widgets/shimmer_loading.dart';

class NotificationsPage extends ConsumerStatefulWidget {
  const NotificationsPage({super.key});

  @override
  ConsumerState<NotificationsPage> createState() => _NotificationsPageState();
}

class _NotificationsPageState extends ConsumerState<NotificationsPage> {
  @override
  void initState() {
    super.initState();
    final state = ref.read(notificationProvider);
    if (state.notifications.isEmpty && !state.isLoading) {
      ref.read(notificationProvider.notifier).loadNotifications();
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(notificationProvider);

    if (state.isLoading) return const ShimmerList(count: 5);

    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                '${state.unreadCount} non lue(s)',
                style: const TextStyle(fontSize: 14, color: JennyColors.textSecondary),
              ),
              const Spacer(),
              TextButton(
                onPressed: () {},
                child: const Text('Tout marquer comme lu', style: TextStyle(fontSize: 13, color: JennyColors.primary)),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Expanded(
            child: state.notifications.isEmpty
                ? Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.notifications_off_rounded, size: 48, color: JennyColors.textSecondary.withValues(alpha: 0.3)),
                        const SizedBox(height: 12),
                        const Text('Aucune notification', style: TextStyle(color: JennyColors.textSecondary)),
                      ],
                    ),
                  )
                : ListView.builder(
                    itemCount: state.notifications.length,
                    itemBuilder: (context, index) {
                      return _buildNotificationTile(state.notifications[index]);
                    },
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildNotificationTile(NotificationItem notif) {
    final config = _typeConfig(notif.type);
    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: notif.read ? Colors.white : JennyColors.primary.withValues(alpha: 0.03),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: notif.read ? JennyColors.divider : JennyColors.primary.withValues(alpha: 0.2),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: config.color.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(config.icon, size: 20, color: config.color),
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
                        notif.title,
                        style: TextStyle(
                          fontSize: 14,
                          fontWeight: notif.read ? FontWeight.w500 : FontWeight.w600,
                          color: JennyColors.textPrimary,
                        ),
                      ),
                    ),
                    if (!notif.read)
                      Container(
                        width: 8,
                        height: 8,
                        decoration: const BoxDecoration(
                          color: JennyColors.primary,
                          shape: BoxShape.circle,
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  notif.body,
                  style: const TextStyle(fontSize: 13, color: JennyColors.textSecondary, height: 1.4),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  _NotifTypeConfig _typeConfig(String type) {
    switch (type) {
      case 'new_message':
        return _NotifTypeConfig(Icons.message_rounded, JennyColors.primary);
      case 'ai_resolved':
        return _NotifTypeConfig(Icons.auto_awesome_rounded, const Color(0xFF059669));
      case 'assignment':
        return _NotifTypeConfig(Icons.person_add_rounded, JennyColors.structure);
      case 'escalation':
        return _NotifTypeConfig(Icons.warning_amber_rounded, JennyColors.warning);
      default:
        return _NotifTypeConfig(Icons.info_outline_rounded, JennyColors.structure);
    }
  }
}

class _NotifTypeConfig {
  final IconData icon;
  final Color color;
  const _NotifTypeConfig(this.icon, this.color);
}
