import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/user.dart';
import '../services/user_service.dart';

class TeamState {
  final bool isLoading;
  final List<JennyUser> users;
  final String? error;

  const TeamState({this.isLoading = false, this.users = const [], this.error});

  TeamState copyWith({bool? isLoading, List<JennyUser>? users, String? error}) =>
      TeamState(
        isLoading: isLoading ?? this.isLoading,
        users: users ?? this.users,
        error: error,
      );
}

class TeamNotifier extends StateNotifier<TeamState> {
  final UserService _service = UserService();

  TeamNotifier() : super(const TeamState());

  Future<void> loadUsers() async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final users = await _service.listUsers();
      state = state.copyWith(isLoading: false, users: users);
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }
}

final teamProvider = StateNotifierProvider<TeamNotifier, TeamState>((ref) {
  return TeamNotifier();
});
