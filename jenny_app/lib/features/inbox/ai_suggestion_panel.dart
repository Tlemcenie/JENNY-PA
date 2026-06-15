import 'package:flutter/material.dart';
import '../../core/theme/jenny_colors.dart';
import '../../models/conversation.dart';
import '../../models/message.dart';
import '../../widgets/shimmer_loading.dart';

class AiSuggestionPanel extends StatelessWidget {
  final Conversation conversation;
  final AiSuggestion? suggestion;
  final bool isLoading;
  final ValueChanged<String> onUseSuggestion;

  const AiSuggestionPanel({
    super.key,
    required this.conversation,
    this.suggestion,
    required this.isLoading,
    required this.onUseSuggestion,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(left: BorderSide(color: JennyColors.divider)),
      ),
      child: Column(
        children: [
          _buildPanelHeader(),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildCustomerInfo(),
                  const SizedBox(height: 20),
                  _buildAiSuggestion(),
                  const SizedBox(height: 20),
                  _buildTags(),
                  const SizedBox(height: 20),
                  _buildAssignment(),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPanelHeader() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: JennyColors.divider)),
      ),
      child: const Row(
        children: [
          Icon(Icons.auto_awesome_rounded, size: 18, color: Color(0xFF8B5CF6)),
          SizedBox(width: 8),
          Text(
            'Assistant IA',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: JennyColors.textPrimary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildCustomerInfo() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: JennyColors.background,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Client',
            style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: JennyColors.textSecondary),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              CircleAvatar(
                radius: 16,
                backgroundColor: JennyColors.primaryLight.withValues(alpha: 0.4),
                child: Text(
                  conversation.initials,
                  style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: JennyColors.primary),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      conversation.customerName,
                      style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: JennyColors.textPrimary),
                    ),
                    Text(
                      conversation.customerEmail,
                      style: const TextStyle(fontSize: 11, color: JennyColors.textSecondary),
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

  Widget _buildAiSuggestion() {
    if (isLoading) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: const [
          ShimmerLoading(height: 16, width: 120),
          SizedBox(height: 12),
          ShimmerLoading(height: 80),
        ],
      );
    }

    if (suggestion == null) {
      return const SizedBox.shrink();
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        gradient: JennyColors.aiGradient,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFB8DFC9)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.auto_fix_high_rounded, size: 16, color: Color(0xFF059669)),
              const SizedBox(width: 6),
              const Text(
                'Réponse suggérée',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: Color(0xFF065F46)),
              ),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.6),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  '${suggestion!.confidencePercent}%',
                  style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w600, color: Color(0xFF059669)),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            suggestion!.suggestedReply,
            style: const TextStyle(fontSize: 13, color: Color(0xFF065F46), height: 1.5),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.6),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  suggestion!.detectedTopic.replaceAll('_', ' '),
                  style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w600, color: Color(0xFF059669)),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: () => onUseSuggestion(suggestion!.suggestedReply),
              icon: const Icon(Icons.send_rounded, size: 16),
              label: const Text('Utiliser cette réponse'),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF059669),
                foregroundColor: Colors.white,
                elevation: 0,
                padding: const EdgeInsets.symmetric(vertical: 10),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                textStyle: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTags() {
    if (conversation.tags.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Tags',
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: JennyColors.textSecondary),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: conversation.tags.map((tag) {
            return Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: JennyColors.primary.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                tag,
                style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: JennyColors.primary,
                ),
              ),
            );
          }).toList(),
        ),
      ],
    );
  }

  Widget _buildAssignment() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Assigné à',
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: JennyColors.textSecondary),
        ),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: JennyColors.background,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Row(
            children: [
              CircleAvatar(
                radius: 14,
                backgroundColor: JennyColors.structure.withValues(alpha: 0.15),
                child: const Icon(Icons.person_rounded, size: 14, color: JennyColors.structure),
              ),
              const SizedBox(width: 8),
              Text(
                conversation.assignedTo ?? 'Non assigné',
                style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w500,
                  color: JennyColors.textPrimary,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
