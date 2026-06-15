import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/jenny_colors.dart';
import '../../providers/auth_provider.dart';
import '../../widgets/animated_gradient_background.dart';
import '../../widgets/glass_container.dart';
import '../../widgets/jenny_button.dart';
import '../../widgets/jenny_text_field.dart';

class SignupPage extends ConsumerStatefulWidget {
  final VoidCallback onSwitchToLogin;
  const SignupPage({super.key, required this.onSwitchToLogin});

  @override
  ConsumerState<SignupPage> createState() => _SignupPageState();
}

class _SignupPageState extends ConsumerState<SignupPage>
    with SingleTickerProviderStateMixin {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _obscure = true;
  late final AnimationController _fadeController;
  late final Animation<double> _fadeAnimation;
  late final Animation<Offset> _slideAnimation;

  @override
  void initState() {
    super.initState();
    _fadeController = AnimationController(
      duration: const Duration(milliseconds: 800),
      vsync: this,
    );
    _fadeAnimation = CurvedAnimation(parent: _fadeController, curve: Curves.easeOutCubic);
    _slideAnimation = Tween<Offset>(
      begin: const Offset(0, 0.1),
      end: Offset.zero,
    ).animate(CurvedAnimation(parent: _fadeController, curve: Curves.easeOutCubic));
    _fadeController.forward();
  }

  @override
  void dispose() {
    _fadeController.dispose();
    _nameController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  void _signup() {
    if (!_formKey.currentState!.validate()) return;
    ref.read(authProvider.notifier).register(
          _nameController.text.trim(),
          _emailController.text.trim(),
          _passwordController.text,
        );
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authProvider);

    ref.listen<AuthState>(authProvider, (prev, next) {
      if (next.status == AuthStatus.error && next.error != null) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(next.error!),
            backgroundColor: JennyColors.error,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          ),
        );
      }
    });

    return Scaffold(
      body: AnimatedGradientBackground(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: FadeTransition(
              opacity: _fadeAnimation,
              child: SlideTransition(
                position: _slideAnimation,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 440),
                  child: GlassContainer(
                    backgroundColor: Colors.white.withValues(alpha: 0.85),
                    borderColor: JennyColors.divider,
                    padding: const EdgeInsets.all(40),
                    child: Form(
                      key: _formKey,
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          _buildLogo(),
                          const SizedBox(height: 8),
                          Text(
                            'Créez votre espace Jenny',
                            style: TextStyle(
                              fontSize: 14,
                              color: JennyColors.textSecondary,
                            ),
                          ),
                          const SizedBox(height: 32),
                          JennyTextField(
                            controller: _nameController,
                            label: 'Nom complet',
                            hintText: 'Jean Dupont',
                            prefixIcon: Icons.person_outline,
                            validator: (v) {
                              if (v == null || v.isEmpty) return 'Nom requis';
                              return null;
                            },
                          ),
                          const SizedBox(height: 16),
                          JennyTextField(
                            controller: _emailController,
                            label: 'Email',
                            hintText: 'vous@exemple.com',
                            prefixIcon: Icons.email_outlined,
                            keyboardType: TextInputType.emailAddress,
                            validator: (v) {
                              if (v == null || v.isEmpty) return 'Email requis';
                              if (!v.contains('@')) return 'Email invalide';
                              return null;
                            },
                          ),
                          const SizedBox(height: 16),
                          JennyTextField(
                            controller: _passwordController,
                            label: 'Mot de passe',
                            hintText: '8+ caractères, majuscule, chiffre, spécial',
                            prefixIcon: Icons.lock_outline,
                            obscureText: _obscure,
                            suffix: IconButton(
                              icon: Icon(
                                _obscure ? Icons.visibility_off_outlined : Icons.visibility_outlined,
                                size: 20,
                                color: JennyColors.textSecondary,
                              ),
                              onPressed: () => setState(() => _obscure = !_obscure),
                            ),
                            validator: (v) {
                              if (v == null || v.length < 8) return 'Min. 8 caractères';
                              return null;
                            },
                          ),
                          const SizedBox(height: 24),
                          JennyButton(
                            label: 'Créer mon compte',
                            onPressed: _signup,
                            isLoading: authState.isLoading,
                          ),
                          const SizedBox(height: 24),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Text(
                                'Déjà un compte ? ',
                                style: TextStyle(
                                  fontSize: 13,
                                  color: JennyColors.textSecondary,
                                ),
                              ),
                              GestureDetector(
                                onTap: widget.onSwitchToLogin,
                                child: const Text(
                                  'Se connecter',
                                  style: TextStyle(
                                    fontSize: 13,
                                    color: JennyColors.primary,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildLogo() {
    return Column(
      children: [
        Container(
          width: 56,
          height: 56,
          decoration: BoxDecoration(
            gradient: JennyColors.primaryGradient,
            borderRadius: BorderRadius.circular(16),
            boxShadow: [
              BoxShadow(
                color: JennyColors.primary.withValues(alpha: 0.3),
                blurRadius: 20,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: const Center(
            child: Text(
              'J',
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.w700,
                color: Colors.white,
              ),
            ),
          ),
        ),
        const SizedBox(height: 16),
        const Text(
          'Jenny',
          style: TextStyle(
            fontSize: 28,
            fontWeight: FontWeight.w700,
            color: JennyColors.textPrimary,
          ),
        ),
      ],
    );
  }
}
