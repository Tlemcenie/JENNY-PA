import 'package:flutter/material.dart';
import '../core/theme/jenny_colors.dart';

class JennyTextField extends StatefulWidget {
  final TextEditingController? controller;
  final String? hintText;
  final String? label;
  final IconData? prefixIcon;
  final Widget? suffix;
  final bool obscureText;
  final TextInputType? keyboardType;
  final String? Function(String?)? validator;
  final ValueChanged<String>? onChanged;
  final VoidCallback? onTap;
  final bool readOnly;
  final int maxLines;
  final FocusNode? focusNode;

  const JennyTextField({
    super.key,
    this.controller,
    this.hintText,
    this.label,
    this.prefixIcon,
    this.suffix,
    this.obscureText = false,
    this.keyboardType,
    this.validator,
    this.onChanged,
    this.onTap,
    this.readOnly = false,
    this.maxLines = 1,
    this.focusNode,
  });

  @override
  State<JennyTextField> createState() => _JennyTextFieldState();
}

class _JennyTextFieldState extends State<JennyTextField> {
  bool _isFocused = false;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        if (widget.label != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(
              widget.label!,
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: JennyColors.textPrimary,
              ),
            ),
          ),
        AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            boxShadow: _isFocused
                ? [
                    BoxShadow(
                      color: JennyColors.primary.withValues(alpha: 0.15),
                      blurRadius: 12,
                      offset: const Offset(0, 4),
                    ),
                  ]
                : [],
          ),
          child: Focus(
            onFocusChange: (focused) => setState(() => _isFocused = focused),
            child: TextFormField(
              controller: widget.controller,
              obscureText: widget.obscureText,
              keyboardType: widget.keyboardType,
              validator: widget.validator,
              onChanged: widget.onChanged,
              onTap: widget.onTap,
              readOnly: widget.readOnly,
              maxLines: widget.maxLines,
              focusNode: widget.focusNode,
              style: const TextStyle(fontSize: 14, color: JennyColors.textPrimary),
              decoration: InputDecoration(
                hintText: widget.hintText,
                prefixIcon: widget.prefixIcon != null
                    ? Icon(widget.prefixIcon, size: 20, color: JennyColors.textSecondary)
                    : null,
                suffixIcon: widget.suffix,
                filled: true,
                fillColor: Colors.white,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: JennyColors.divider),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: JennyColors.divider),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: JennyColors.primary, width: 2),
                ),
                errorBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: JennyColors.error),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
