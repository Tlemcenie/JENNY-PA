import '../core/api/api_client.dart';
import '../models/user.dart';

class AuthService {
  final ApiClient _api = ApiClient();

  Future<AuthResponse> register({
    required String fullName,
    required String email,
    required String password,
  }) async {
    final response = await _api.post('/auth/register', data: {
      'full_name': fullName,
      'email': email,
      'password': password,
    });
    final auth = AuthResponse.fromJson(response.data as Map<String, dynamic>);
    _api.setToken(auth.accessToken);
    return auth;
  }

  Future<AuthResponse> login({
    required String email,
    required String password,
  }) async {
    final response = await _api.post('/auth/login', data: {
      'email': email,
      'password': password,
    });
    final auth = AuthResponse.fromJson(response.data as Map<String, dynamic>);
    _api.setToken(auth.accessToken);
    return auth;
  }

  Future<JennyUser> getMe() async {
    final response = await _api.get('/auth/me');
    return JennyUser.fromJson(response.data as Map<String, dynamic>);
  }

  void logout() {
    _api.clearToken();
  }
}
