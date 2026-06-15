import '../core/api/api_client.dart';
import '../models/user.dart';

class UserService {
  final ApiClient _api = ApiClient();

  Future<List<JennyUser>> listUsers() async {
    final response = await _api.get('/users');
    final data = response.data as List<dynamic>;
    return data.map((e) => JennyUser.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<JennyUser> getUser(String userId) async {
    final response = await _api.get('/users/$userId');
    return JennyUser.fromJson(response.data as Map<String, dynamic>);
  }
}
