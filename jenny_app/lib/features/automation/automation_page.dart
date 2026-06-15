import 'package:flutter/material.dart';
import '../../core/theme/jenny_colors.dart';

class AutomationPage extends StatelessWidget {
  const AutomationPage({super.key});

  static const _rules = [
    _AutoRule('Auto-réponse Livraison', 'Répondre automatiquement aux questions de suivi de livraison', true, 'delivery_tracking', 620),
    _AutoRule('Gestion des remboursements', 'Initier le processus de remboursement pour les demandes simples', true, 'refund_request', 312),
    _AutoRule('FAQ Automatique', 'Répondre aux questions fréquentes depuis la base de connaissances', true, 'general_inquiry', 245),
    _AutoRule('Escalation VIP', 'Transférer les clients VIP vers un agent humain', false, 'escalation', 89),
    _AutoRule('Coupon automatique', 'Offrir un code promo aux clients insatisfaits', false, 'coupon_issue', 56),
    _AutoRule('Tag automatique', 'Catégoriser automatiquement les messages entrants', true, 'tagging', 1284),
  ];

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text(
                'Règles d\'automatisation',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
              const Spacer(),
              ElevatedButton.icon(
                onPressed: () {},
                icon: const Icon(Icons.add_rounded, size: 18),
                label: const Text('Nouvelle règle'),
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
          ..._rules.map((rule) => _buildRuleCard(rule)),
        ],
      ),
    );
  }

  Widget _buildRuleCard(_AutoRule rule) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: rule.active ? JennyColors.success.withValues(alpha: 0.3) : JennyColors.divider,
        ),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: rule.active
                  ? JennyColors.aiHighlight
                  : JennyColors.divider.withValues(alpha: 0.5),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(
              Icons.auto_fix_high_rounded,
              size: 22,
              color: rule.active ? const Color(0xFF059669) : JennyColors.textSecondary,
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      rule.name,
                      style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: JennyColors.textPrimary),
                    ),
                    const SizedBox(width: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: JennyColors.structure.withValues(alpha: 0.1),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        rule.trigger.replaceAll('_', ' '),
                        style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w600, color: JennyColors.structure),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  rule.description,
                  style: const TextStyle(fontSize: 13, color: JennyColors.textSecondary),
                ),
                const SizedBox(height: 6),
                Text(
                  '${rule.triggered}x déclenchée',
                  style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w500, color: JennyColors.textSecondary),
                ),
              ],
            ),
          ),
          Column(
            children: [
              Switch(
                value: rule.active,
                onChanged: (_) {},
                activeColor: JennyColors.success,
              ),
              IconButton(
                icon: const Icon(Icons.edit_rounded, size: 18, color: JennyColors.textSecondary),
                onPressed: () {},
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _AutoRule {
  final String name;
  final String description;
  final bool active;
  final String trigger;
  final int triggered;
  const _AutoRule(this.name, this.description, this.active, this.trigger, this.triggered);
}
