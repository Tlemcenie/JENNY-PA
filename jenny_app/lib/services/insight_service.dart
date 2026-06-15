import '../core/api/api_client.dart';
import '../models/insight.dart';

class InsightService {
  final ApiClient _api = ApiClient();

  Future<InsightData> getInsights() async {
    final response = await _api.get('/insights');
    return InsightData.fromJson(response.data as Map<String, dynamic>);
  }

  Future<KpiData> getKpis() async {
    final response = await _api.get('/insights/kpis');
    return KpiData.fromJson(response.data as Map<String, dynamic>);
  }
}
