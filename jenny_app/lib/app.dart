import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/theme/jenny_theme.dart';
import 'providers/auth_provider.dart';
import 'features/auth/auth_wrapper.dart';
import 'shell/app_shell.dart';

class JennyApp extends ConsumerWidget {
  const JennyApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authProvider);

    return MaterialApp(
      title: 'Jenny AI',
      debugShowCheckedModeBanner: false,
      theme: JennyTheme.light,
      home: AnimatedSwitcher(
        duration: const Duration(milliseconds: 500),
        transitionBuilder: (child, animation) => FadeTransition(
          opacity: animation,
          child: child,
        ),
        child: authState.isAuthenticated
            ? const AppShell(key: ValueKey('shell'))
            : const AuthWrapper(key: ValueKey('auth')),
      ),
    );
  }
}
