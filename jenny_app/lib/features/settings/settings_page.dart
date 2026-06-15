import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/jenny_colors.dart';
import '../../providers/auth_provider.dart';

class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    final user = auth.user;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildSection(
            'Profil',
            Icons.person_outline_rounded,
            [
              _buildProfileCard(user),
            ],
          ),
          const SizedBox(height: 24),
          _buildSection(
            'Intégrations',
            Icons.extension_rounded,
            [
              _buildIntegrationTile('WhatsApp Business', 'Connectez votre numéro WhatsApp', Icons.chat_rounded, JennyColors.whatsapp, true),
              _buildIntegrationTile('Instagram', 'Connectez votre compte Instagram Pro', Icons.camera_alt_rounded, JennyColors.instagram, false),
              _buildIntegrationTile('Email SMTP', 'Configurez votre serveur email', Icons.email_rounded, JennyColors.email, true),
              _buildIntegrationTile('Google Calendar', 'Synchronisez vos rendez-vous', Icons.calendar_month_rounded, const Color(0xFF4285F4), false),
              _buildIntegrationTile('Stripe', 'Activez les paiements en ligne', Icons.payment_rounded, const Color(0xFF635BFF), false),
            ],
          ),
          const SizedBox(height: 24),
          _buildSection(
            'Notifications',
            Icons.notifications_outlined,
            [
              _buildToggleTile('Nouveaux messages', 'Recevoir une notification pour chaque nouveau message', true),
              _buildToggleTile('Résolutions IA', 'Être notifié quand l\'IA résout une conversation', true),
              _buildToggleTile('Escalations', 'Alertes quand un agent humain est nécessaire', true),
              _buildToggleTile('Rapports hebdomadaires', 'Recevoir un résumé par email chaque lundi', false),
            ],
          ),
          const SizedBox(height: 24),
          _buildSection(
            'Danger',
            Icons.warning_amber_rounded,
            [
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: JennyColors.error.withValues(alpha: 0.05),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: JennyColors.error.withValues(alpha: 0.2)),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('Déconnexion', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: JennyColors.error)),
                          const SizedBox(height: 2),
                          Text('Vous serez redirigé vers la page de connexion', style: TextStyle(fontSize: 12, color: JennyColors.error.withValues(alpha: 0.7))),
                        ],
                      ),
                    ),
                    ElevatedButton(
                      onPressed: () => ref.read(authProvider.notifier).logout(),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: JennyColors.error,
                        foregroundColor: Colors.white,
                        elevation: 0,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      ),
                      child: const Text('Se déconnecter'),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSection(String title, IconData icon, List<Widget> children) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: JennyColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 20, color: JennyColors.primary),
              const SizedBox(width: 8),
              Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: JennyColors.textPrimary)),
            ],
          ),
          const SizedBox(height: 16),
          ...children,
        ],
      ),
    );
  }

  Widget _buildProfileCard(dynamic user) {
    return Row(
      children: [
        CircleAvatar(
          radius: 30,
          backgroundColor: JennyColors.primaryLight.withValues(alpha: 0.4),
          child: Text(
            user?.initials ?? 'U',
            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600, color: JennyColors.primary),
          ),
        ),
        const SizedBox(width: 16),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(user?.fullName ?? 'Utilisateur', style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
              const SizedBox(height: 2),
              Text(user?.email ?? '', style: const TextStyle(fontSize: 13, color: JennyColors.textSecondary)),
              const SizedBox(height: 4),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: const Color(0xFF8B5CF6).withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  (user?.role ?? 'user').toString().toUpperCase(),
                  style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: Color(0xFF8B5CF6)),
                ),
              ),
            ],
          ),
        ),
        OutlinedButton(
          onPressed: () {},
          style: OutlinedButton.styleFrom(
            foregroundColor: JennyColors.primary,
            side: const BorderSide(color: JennyColors.divider),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          ),
          child: const Text('Modifier'),
        ),
      ],
    );
  }

  Widget _buildIntegrationTile(String name, String desc, IconData icon, Color color, bool connected) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, size: 20, color: color),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(name, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500)),
                Text(desc, style: const TextStyle(fontSize: 12, color: JennyColors.textSecondary)),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              color: connected ? JennyColors.success.withValues(alpha: 0.1) : JennyColors.divider,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              connected ? 'Connecté' : 'Connecter',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: connected ? JennyColors.success : JennyColors.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildToggleTile(String title, String desc, bool value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500)),
                Text(desc, style: const TextStyle(fontSize: 12, color: JennyColors.textSecondary)),
              ],
            ),
          ),
          Switch(
            value: value,
            onChanged: (_) {},
            activeColor: JennyColors.primary,
          ),
        ],
      ),
    );
  }
}
