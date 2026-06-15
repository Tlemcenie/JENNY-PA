import 'package:flutter/material.dart';

class JennyColors {
  JennyColors._();

  static const Color primary = Color(0xFFFF7F6A);
  static const Color primaryLight = Color(0xFFFCBFB7);
  static const Color structure = Color(0xFF7284A8);
  static const Color background = Color(0xFFFFF9F8);
  static const Color aiHighlight = Color(0xFFE8F3EE);
  static const Color textPrimary = Color(0xFF2A3245);
  static const Color textSecondary = Color(0xFF8E99A4);
  static const Color white = Color(0xFFFFFFFF);
  static const Color surface = Color(0xFFFFF9F8);
  static const Color error = Color(0xFFE74C3C);
  static const Color success = Color(0xFF2ECC71);
  static const Color warning = Color(0xFFF39C12);

  static const Color cardBg = Color(0xFFFFFFFF);
  static const Color divider = Color(0xFFEEF0F4);
  static const Color sidebarBg = Color(0xFF2A3245);
  static const Color sidebarActive = Color(0xFF3D4F6A);
  static const Color glassBg = Color(0x33FFFFFF);
  static const Color glassBorder = Color(0x55FFFFFF);

  static const Color whatsapp = Color(0xFF25D366);
  static const Color instagram = Color(0xFFE4405F);
  static const Color email = Color(0xFF4A90D9);
  static const Color twitter = Color(0xFF1DA1F2);

  static const LinearGradient primaryGradient = LinearGradient(
    colors: [Color(0xFFFF7F6A), Color(0xFFFF9A8B)],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );

  static const LinearGradient backgroundGradient = LinearGradient(
    colors: [Color(0xFFFFF9F8), Color(0xFFFCBFB7), Color(0xFFE8F3EE)],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    stops: [0.0, 0.5, 1.0],
  );

  static const LinearGradient sidebarGradient = LinearGradient(
    colors: [Color(0xFF2A3245), Color(0xFF3D4F6A)],
    begin: Alignment.topCenter,
    end: Alignment.bottomCenter,
  );

  static const LinearGradient aiGradient = LinearGradient(
    colors: [Color(0xFFE8F3EE), Color(0xFFD4EBE0)],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );
}
