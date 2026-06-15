class JennyUser {
  final String id;
  final String fullName;
  final String email;
  final String role;
  final String? avatar;
  final String status;
  final String? createdAt;

  const JennyUser({
    required this.id,
    required this.fullName,
    required this.email,
    required this.role,
    this.avatar,
    this.status = 'offline',
    this.createdAt,
  });

  factory JennyUser.fromJson(Map<String, dynamic> json) => JennyUser(
        id: json['id'] as String,
        fullName: json['full_name'] as String? ?? '',
        email: json['email'] as String? ?? '',
        role: json['role'] as String? ?? 'agent',
        avatar: json['avatar'] as String?,
        status: json['status'] as String? ?? 'offline',
        createdAt: json['created_at'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'full_name': fullName,
        'email': email,
        'role': role,
        'avatar': avatar,
        'status': status,
        'created_at': createdAt,
      };

  String get initials {
    final parts = fullName.trim().split(' ');
    if (parts.length >= 2) return '${parts[0][0]}${parts[1][0]}'.toUpperCase();
    return fullName.isNotEmpty ? fullName[0].toUpperCase() : '?';
  }

  bool get isOnline => status == 'online';
}

class AuthResponse {
  final String accessToken;
  final String tokenType;
  final JennyUser? user;

  const AuthResponse({
    required this.accessToken,
    this.tokenType = 'bearer',
    this.user,
  });

  factory AuthResponse.fromJson(Map<String, dynamic> json) => AuthResponse(
        accessToken: json['access_token'] as String,
        tokenType: json['token_type'] as String? ?? 'bearer',
        user: json['user'] != null
            ? JennyUser.fromJson(json['user'] as Map<String, dynamic>)
            : null,
      );
}
