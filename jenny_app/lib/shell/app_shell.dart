import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/theme/jenny_colors.dart';
import '../core/constants.dart';
import '../providers/ui_state_provider.dart';
import '../providers/auth_provider.dart';
import '../providers/notification_provider.dart';
import '../features/dashboard/dashboard_page.dart';
import '../features/inbox/inbox_page.dart';
import '../features/insights/insights_page.dart';
import '../features/search/search_page.dart';
import '../features/team/team_page.dart';
import '../features/settings/settings_page.dart';
import '../features/knowledge/knowledge_page.dart';
import '../features/automation/automation_page.dart';
import '../features/notifications/notifications_page.dart';

class AppShell extends ConsumerStatefulWidget {
  const AppShell({super.key});

  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  @override
  void initState() {
    super.initState();
    ref.read(notificationProvider.notifier).loadNotifications();
  }

  static final _pages = <Widget>[
    const DashboardPage(),
    const InboxPage(),
    const InsightsPage(),
    const SearchPage(),
    const TeamPage(),
    const KnowledgePage(),
    const AutomationPage(),
    const NotificationsPage(),
    const SettingsPage(),
  ];

  static const _navItems = <_NavItem>[
    _NavItem(Icons.dashboard_rounded, 'Dashboard'),
    _NavItem(Icons.inbox_rounded, 'Inbox'),
    _NavItem(Icons.insights_rounded, 'Insights'),
    _NavItem(Icons.search_rounded, 'Recherche'),
    _NavItem(Icons.people_rounded, 'Équipe'),
    _NavItem(Icons.menu_book_rounded, 'Knowledge'),
    _NavItem(Icons.auto_fix_high_rounded, 'Automation'),
    _NavItem(Icons.notifications_rounded, 'Notifications'),
    _NavItem(Icons.settings_rounded, 'Paramètres'),
  ];

  @override
  Widget build(BuildContext context) {
    final uiState = ref.watch(uiStateProvider);
    final notifState = ref.watch(notificationProvider);

    return Scaffold(
      backgroundColor: JennyColors.background,
      body: Row(
        children: [
          _buildSidebar(uiState, notifState.unreadCount),
          Expanded(
            child: Column(
              children: [
                _buildTopbar(uiState),
                Expanded(
                  child: AnimatedSwitcher(
                    duration: UIConstants.animNormal,
                    transitionBuilder: (child, animation) => FadeTransition(
                      opacity: animation,
                      child: SlideTransition(
                        position: Tween<Offset>(
                          begin: const Offset(0.02, 0),
                          end: Offset.zero,
                        ).animate(CurvedAnimation(
                          parent: animation,
                          curve: Curves.easeOutCubic,
                        )),
                        child: child,
                      ),
                    ),
                    child: KeyedSubtree(
                      key: ValueKey(uiState.selectedNavIndex),
                      child: _pages[uiState.selectedNavIndex],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSidebar(UiState uiState, int unreadNotifs) {
    final isExpanded = uiState.sidebarExpanded;
    return MouseRegion(
      onEnter: (_) => ref.read(uiStateProvider.notifier).setSidebarExpanded(true),
      onExit: (_) => ref.read(uiStateProvider.notifier).setSidebarExpanded(false),
      child: AnimatedContainer(
        duration: UIConstants.animNormal,
        curve: Curves.easeOutCubic,
        width: isExpanded ? UIConstants.sidebarExpanded : UIConstants.sidebarCollapsed,
        decoration: const BoxDecoration(
          gradient: JennyColors.sidebarGradient,
        ),
        child: Column(
          children: [
            const SizedBox(height: 20),
            _buildSidebarLogo(isExpanded),
            const SizedBox(height: 24),
            Expanded(
              child: ListView.builder(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                itemCount: _navItems.length,
                itemBuilder: (context, index) {
                  final item = _navItems[index];
                  final isActive = uiState.selectedNavIndex == index;
                  final showBadge = index == 7 && unreadNotifs > 0;
                  return _SidebarItem(
                    icon: item.icon,
                    label: item.label,
                    isActive: isActive,
                    isExpanded: isExpanded,
                    badgeCount: showBadge ? unreadNotifs : null,
                    onTap: () =>
                        ref.read(uiStateProvider.notifier).setNavIndex(index),
                  );
                },
              ),
            ),
            _buildSidebarFooter(isExpanded),
          ],
        ),
      ),
    );
  }

  Widget _buildSidebarLogo(bool isExpanded) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              gradient: JennyColors.primaryGradient,
              borderRadius: BorderRadius.circular(12),
            ),
            child: const Center(
              child: Text(
                'J',
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              ),
            ),
          ),
          if (isExpanded) ...[
            const SizedBox(width: 12),
            const Text(
              'Jenny',
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w700,
                color: Colors.white,
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildSidebarFooter(bool isExpanded) {
    final auth = ref.watch(authProvider);
    return Container(
      padding: const EdgeInsets.all(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => ref.read(authProvider.notifier).logout(),
        child: Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.08),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Row(
            children: [
              CircleAvatar(
                radius: 16,
                backgroundColor: JennyColors.primary.withValues(alpha: 0.3),
                child: Text(
                  auth.user?.initials ?? 'U',
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: Colors.white,
                  ),
                ),
              ),
              if (isExpanded) ...[
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        auth.user?.fullName ?? 'Utilisateur',
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: Colors.white,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                      Text(
                        auth.user?.email ?? '',
                        style: TextStyle(
                          fontSize: 10,
                          color: Colors.white.withValues(alpha: 0.6),
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
                Icon(Icons.logout_rounded, size: 16, color: Colors.white.withValues(alpha: 0.6)),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildTopbar(UiState uiState) {
    return Container(
      height: 64,
      padding: const EdgeInsets.symmetric(horizontal: 24),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.7),
        border: const Border(bottom: BorderSide(color: JennyColors.divider)),
      ),
      child: Row(
        children: [
          Text(
            _navItems[uiState.selectedNavIndex].label,
            style: const TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: JennyColors.textPrimary,
            ),
          ),
          const Spacer(),
          IconButton(
            icon: const Icon(Icons.search_rounded, color: JennyColors.textSecondary),
            onPressed: () => ref.read(uiStateProvider.notifier).setNavIndex(3),
          ),
          const SizedBox(width: 4),
          Stack(
            children: [
              IconButton(
                icon: const Icon(Icons.notifications_outlined, color: JennyColors.textSecondary),
                onPressed: () => ref.read(uiStateProvider.notifier).setNavIndex(7),
              ),
              if (ref.watch(notificationProvider).unreadCount > 0)
                Positioned(
                  right: 8,
                  top: 8,
                  child: Container(
                    width: 8,
                    height: 8,
                    decoration: const BoxDecoration(
                      color: JennyColors.primary,
                      shape: BoxShape.circle,
                    ),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SidebarItem extends StatefulWidget {
  final IconData icon;
  final String label;
  final bool isActive;
  final bool isExpanded;
  final int? badgeCount;
  final VoidCallback onTap;

  const _SidebarItem({
    required this.icon,
    required this.label,
    required this.isActive,
    required this.isExpanded,
    this.badgeCount,
    required this.onTap,
  });

  @override
  State<_SidebarItem> createState() => _SidebarItemState();
}

class _SidebarItemState extends State<_SidebarItem> {
  bool _isHovered = false;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: MouseRegion(
        onEnter: (_) => setState(() => _isHovered = true),
        onExit: (_) => setState(() => _isHovered = false),
        child: GestureDetector(
          onTap: widget.onTap,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            padding: EdgeInsets.symmetric(
              horizontal: widget.isExpanded ? 12 : 0,
              vertical: 10,
            ),
            decoration: BoxDecoration(
              color: widget.isActive
                  ? JennyColors.primary.withValues(alpha: 0.2)
                  : _isHovered
                      ? Colors.white.withValues(alpha: 0.08)
                      : Colors.transparent,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Row(
              mainAxisAlignment:
                  widget.isExpanded ? MainAxisAlignment.start : MainAxisAlignment.center,
              children: [
                Stack(
                  clipBehavior: Clip.none,
                  children: [
                    Icon(
                      widget.icon,
                      size: 22,
                      color: widget.isActive
                          ? JennyColors.primary
                          : Colors.white.withValues(alpha: 0.7),
                    ),
                    if (widget.badgeCount != null)
                      Positioned(
                        right: -6,
                        top: -4,
                        child: Container(
                          padding: const EdgeInsets.all(3),
                          decoration: const BoxDecoration(
                            color: JennyColors.primary,
                            shape: BoxShape.circle,
                          ),
                          child: Text(
                            '${widget.badgeCount}',
                            style: const TextStyle(
                              fontSize: 8,
                              color: Colors.white,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
                if (widget.isExpanded) ...[
                  const SizedBox(width: 12),
                  Text(
                    widget.label,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: widget.isActive ? FontWeight.w600 : FontWeight.w500,
                      color: widget.isActive
                          ? Colors.white
                          : Colors.white.withValues(alpha: 0.7),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _NavItem {
  final IconData icon;
  final String label;
  const _NavItem(this.icon, this.label);
}
