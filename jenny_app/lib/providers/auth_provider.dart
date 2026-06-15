import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/user.dart';
import '../services/auth_service.dart';

enum AuthStatus { initial, loading, authenticated, unauthenticated, error }

class AuthState {
  final AuthStatus status;
  final JennyUser? user;
  final String? token;
  final String? error;

  const AuthState({
    this.status = AuthStatus.initial,
    this.user,
    this.token,
    this.error,
  });

  AuthState copyWith({
    AuthStatus? status,
    JennyUser? user,
    String? token,
    String? error,
  }) =>
      AuthState(
        status: status ?? this.status,
        user: user ?? this.user,
        token: token ?? this.token,
        error: error,
      );

  bool get isAuthenticated => status == AuthStatus.authenticated;
  bool get isLoading => status == AuthStatus.loading;
}

class AuthNotifier extends StateNotifier<AuthState> {
  final AuthService _authService = AuthService();

  AuthNotifier() : super(const AuthState());

  Future<void> login(String email, String password) async {
    state = state.copyWith(status: AuthStatus.loading, error: null);
    try {
      final auth = await _authService.login(email: email, password: password);
      final user = auth.user ?? await _authService.getMe();
      state = state.copyWith(
        status: AuthStatus.authenticated,
        user: user,
        token: auth.accessToken,
      );
    } catch (e) {
      state = state.copyWith(
        status: AuthStatus.error,
        error: _parseError(e),
      );
    }
  }

  Future<void> register(String fullName, String email, String password) async {
    state = state.copyWith(status: AuthStatus.loading, error: null);
    try {
      final auth = await _authService.register(
        fullName: fullName,
        email: email,
        password: password,
      );
      final user = auth.user ?? await _authService.getMe();
      state = state.copyWith(
        status: AuthStatus.authenticated,
        user: user,
        token: auth.accessToken,
      );
    } catch (e) {
      state = state.copyWith(
        status: AuthStatus.error,
        error: _parseError(e),
      );
    }
  }

  void logout() {
    _authService.logout();
    state = const AuthState(status: AuthStatus.unauthenticated);
  }

  String _parseError(dynamic e) {
    if (e is DioException) {
      if (e.type == DioExceptionType.connectionError ||
          e.type == DioExceptionType.connectionTimeout) {
        return 'Impossible de joindre l’API. Lancez le backend (ex. port 8000) ou définissez '
            'API_BASE_URL avec --dart-define.';
      }
      final code = e.response?.statusCode;
      if (code == 409) return 'Un compte existe déjà avec cet email';
      if (code == 401) return 'Email ou mot de passe incorrect';
      if (code == 422) {
        final detail = e.response?.data;
        if (detail is String && detail.isNotEmpty) return detail;
        return 'Vérifiez les informations saisies';
      }
    }
    if (e.toString().contains('409')) return 'Un compte existe déjà avec cet email';
    if (e.toString().contains('401')) return 'Email ou mot de passe incorrect';
    if (e.toString().contains('422')) return 'Vérifiez les informations saisies';
    return 'Erreur de connexion. Vérifiez votre réseau.';
  }
}

final authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  return AuthNotifier();
});
