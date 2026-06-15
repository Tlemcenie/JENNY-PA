import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/jenny_colors.dart';
import '../../providers/user_provider.dart';
import '../../models/user.dart';
import '../../widgets/shimmer_loading.dart';

class TeamPage extends ConsumerStatefulWidget {
  const TeamPage({super.key});

  @override
  ConsumerState<TeamPage> createState() => _TeamPageState();
}

class _TeamPageState extends ConsumerState<TeamPage> {
  @override
  void initState() {
    super.initState();
    ref.read(teamProvider.notifier).loadUsers();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(teamProvider);

    if (state.isLoading) return const ShimmerList(count: 4);

    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text(
                'Membres de l\'équipe',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
              const Spacer(),
              ElevatedButton.icon(
                onPressed: () {},
                icon: const Icon(Icons.person_add_rounded, size: 18),
                label: const Text('Inviter'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: JennyColors.primary,
                  foregroundColor: Colors.white,
                  elevation: 0,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          Container(
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: JennyColors.divider),
            ),
            child: Column(
              children: [
                _buildTableHeader(),
                ...state.users.asMap().entries.map((entry) {
                  return _buildUserRow(entry.value, entry.key < state.users.length - 1);
                }),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTableHeader() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      decoration: const BoxDecoration(
        color: JennyColors.background,
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
        border: Border(bottom: BorderSide(color: JennyColors.divider)),
      ),
      child: const Row(
        children: [
          Expanded(flex: 3, child: Text('Membre', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: JennyColors.textSecondary))),
          Expanded(flex: 2, child: Text('Email', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: JennyColors.textSecondary))),
          Expanded(child: Text('Rôle', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: JennyColors.textSecondary))),
          Expanded(child: Text('Statut', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: JennyColors.textSecondary))),
          SizedBox(width: 40),
        ],
      ),
    );
  }

  Widget _buildUserRow(JennyUser user, bool showBorder) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      decoration: BoxDecoration(
        border: showBorder ? const Border(bottom: BorderSide(color: JennyColors.divider)) : null,
      ),
      child: Row(
        children: [
          Expanded(
            flex: 3,
            child: Row(
              children: [
                Stack(
                  children: [
                    CircleAvatar(
                      radius: 18,
                      backgroundColor: JennyColors.primaryLight.withValues(alpha: 0.4),
                      child: Text(
                        user.initials,
                        style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: JennyColors.primary),
                      ),
                    ),
                    Positioned(
                      right: 0,
                      bottom: 0,
                      child: Container(
                        width: 10,
                        height: 10,
                        decoration: BoxDecoration(
                          color: user.isOnline ? JennyColors.success : JennyColors.textSecondary,
                          shape: BoxShape.circle,
                          border: Border.all(color: Colors.white, width: 2),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(width: 12),
                Text(user.fullName, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500)),
              ],
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(user.email, style: const TextStyle(fontSize: 13, color: JennyColors.textSecondary)),
          ),
          Expanded(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: _roleColor(user.role).withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                user.role.toUpperCase(),
                style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: _roleColor(user.role)),
                textAlign: TextAlign.center,
              ),
            ),
          ),
          Expanded(
            child: Text(
              user.status,
              style: TextStyle(
                fontSize: 13,
                color: user.isOnline ? JennyColors.success : JennyColors.textSecondary,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
          SizedBox(
            width: 40,
            child: IconButton(
              icon: const Icon(Icons.more_horiz_rounded, size: 20, color: JennyColors.textSecondary),
              onPressed: () {},
            ),
          ),
        ],
      ),
    );
  }

  Color _roleColor(String role) {
    switch (role) {
      case 'admin':
        return const Color(0xFF8B5CF6);
      case 'agent':
        return JennyColors.primary;
      default:
        return JennyColors.structure;
    }
  }
}
