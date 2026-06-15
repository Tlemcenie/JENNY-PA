import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/insight.dart';
import '../services/insight_service.dart';

class InsightState {
  final bool isLoading;
  final InsightData? data;
  final String? error;

  const InsightState({this.isLoading = false, this.data, this.error});

  InsightState copyWith({bool? isLoading, InsightData? data, String? error}) =>
      InsightState(
        isLoading: isLoading ?? this.isLoading,
        data: data ?? this.data,
        error: error,
      );
}

class InsightNotifier extends StateNotifier<InsightState> {
  final InsightService _service = InsightService();

  InsightNotifier() : super(const InsightState());

  Future<void> loadInsights() async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final data = await _service.getInsights();
      state = state.copyWith(isLoading: false, data: data);
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }
}

final insightProvider = StateNotifierProvider<InsightNotifier, InsightState>((ref) {
  return InsightNotifier();
});
