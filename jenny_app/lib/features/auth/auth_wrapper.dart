import 'package:flutter/material.dart';
import 'login_page.dart';
import 'signup_page.dart';

class AuthWrapper extends StatefulWidget {
  const AuthWrapper({super.key});

  @override
  State<AuthWrapper> createState() => _AuthWrapperState();
}

class _AuthWrapperState extends State<AuthWrapper> {
  bool _showLogin = true;

  void _switchToSignup() => setState(() => _showLogin = false);
  void _switchToLogin() => setState(() => _showLogin = true);

  @override
  Widget build(BuildContext context) {
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 500),
      transitionBuilder: (child, animation) {
        return FadeTransition(
          opacity: animation,
          child: SlideTransition(
            position: Tween<Offset>(
              begin: const Offset(0.05, 0),
              end: Offset.zero,
            ).animate(CurvedAnimation(parent: animation, curve: Curves.easeOutCubic)),
            child: child,
          ),
        );
      },
      child: _showLogin
          ? LoginPage(key: const ValueKey('login'), onSwitchToSignup: _switchToSignup)
          : SignupPage(key: const ValueKey('signup'), onSwitchToLogin: _switchToLogin),
    );
  }
}
