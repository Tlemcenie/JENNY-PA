class ApiConstants {
  ApiConstants._();

  /// Surcharge au build : `--dart-define=API_BASE_URL=http://127.0.0.1:8000/api/v1/mock`
  /// (émulateur Android : `http://10.0.2.2:8000/api/v1/mock`)
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000/api/v1/mock',
  );

  static const String prodBaseUrl = String.fromEnvironment(
    'API_PROD_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000/api/v1',
  );

  static const Duration timeout = Duration(seconds: 30);
  static const Duration connectTimeout = Duration(seconds: 10);
}

class UIConstants {
  UIConstants._();

  static const double spacing2 = 2;
  static const double spacing4 = 4;
  static const double spacing8 = 8;
  static const double spacing12 = 12;
  static const double spacing16 = 16;
  static const double spacing20 = 20;
  static const double spacing24 = 24;
  static const double spacing32 = 32;
  static const double spacing40 = 40;
  static const double spacing48 = 48;

  static const double radiusSm = 8;
  static const double radiusMd = 12;
  static const double radiusLg = 16;
  static const double radiusXl = 24;
  static const double radiusRound = 999;

  static const double sidebarCollapsed = 72;
  static const double sidebarExpanded = 240;

  static const Duration animFast = Duration(milliseconds: 200);
  static const Duration animNormal = Duration(milliseconds: 350);
  static const Duration animSlow = Duration(milliseconds: 500);
}
