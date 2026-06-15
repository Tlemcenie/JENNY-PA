import 'package:flutter/material.dart';
import '../core/theme/jenny_colors.dart';

class KpiCard extends StatefulWidget {
  final String title;
  final String value;
  final String? subtitle;
  final int? changePercent;
  final IconData icon;
  final Color? iconColor;
  final int index;

  const KpiCard({
    super.key,
    required this.title,
    required this.value,
    this.subtitle,
    this.changePercent,
    required this.icon,
    this.iconColor,
    this.index = 0,
  });

  @override
  State<KpiCard> createState() => _KpiCardState();
}

class _KpiCardState extends State<KpiCard> with SingleTickerProviderStateMixin {
  bool _isHovered = false;

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      onEnter: (_) => setState(() => _isHovered = true),
      onExit: (_) => setState(() => _isHovered = false),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeOutCubic,
        transform: Matrix4.identity()..scale(_isHovered ? 1.02 : 1.0),
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: JennyColors.divider),
          boxShadow: [
            BoxShadow(
              color: _isHovered
                  ? JennyColors.primary.withValues(alpha: 0.08)
                  : Colors.black.withValues(alpha: 0.02),
              blurRadius: _isHovered ? 20 : 10,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: (widget.iconColor ?? JennyColors.primary).withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Icon(
                    widget.icon,
                    size: 20,
                    color: widget.iconColor ?? JennyColors.primary,
                  ),
                ),
                const Spacer(),
                if (widget.changePercent != null) _buildChange(),
              ],
            ),
            const SizedBox(height: 16),
            Text(
              widget.value,
              style: const TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.w700,
                color: JennyColors.textPrimary,
                height: 1,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              widget.title,
              style: const TextStyle(
                fontSize: 13,
                color: JennyColors.textSecondary,
                fontWeight: FontWeight.w500,
              ),
            ),
            if (widget.subtitle != null) ...[
              const SizedBox(height: 2),
              Text(
                widget.subtitle!,
                style: TextStyle(
                  fontSize: 11,
                  color: JennyColors.textSecondary.withValues(alpha: 0.7),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildChange() {
    final isPositive = widget.changePercent! >= 0;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: isPositive
            ? JennyColors.success.withValues(alpha: 0.1)
            : JennyColors.error.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            isPositive ? Icons.trending_up_rounded : Icons.trending_down_rounded,
            size: 14,
            color: isPositive ? JennyColors.success : JennyColors.error,
          ),
          const SizedBox(width: 2),
          Text(
            '${isPositive ? '+' : ''}${widget.changePercent}%',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: isPositive ? JennyColors.success : JennyColors.error,
            ),
          ),
        ],
      ),
    );
  }
}
