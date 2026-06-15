import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:fl_chart/fl_chart.dart';
import '../../core/theme/jenny_colors.dart';
import '../../providers/insight_provider.dart';
import '../../models/insight.dart';
import '../../widgets/shimmer_loading.dart';

class InsightsPage extends ConsumerStatefulWidget {
  const InsightsPage({super.key});

  @override
  ConsumerState<InsightsPage> createState() => _InsightsPageState();
}

class _InsightsPageState extends ConsumerState<InsightsPage> {
  @override
  void initState() {
    super.initState();
    final state = ref.read(insightProvider);
    if (state.data == null && !state.isLoading) {
      ref.read(insightProvider.notifier).loadInsights();
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(insightProvider);

    if (state.isLoading) return const ShimmerList(count: 3);
    final data = state.data;
    if (data == null) return const Center(child: Text('Aucune donnée'));

    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildSummaryCard(data.summary),
          const SizedBox(height: 24),
          _buildLineChart(data.weeklyTrend),
          const SizedBox(height: 24),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: _buildTopTopicsDetailed(data.topTopics)),
              const SizedBox(width: 20),
              Expanded(child: _buildAiPerformance(data)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSummaryCard(String summary) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        gradient: JennyColors.aiGradient,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFB8DFC9)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.5),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(Icons.insights_rounded, color: Color(0xFF059669), size: 20),
              ),
              const SizedBox(width: 12),
              const Text(
                'Analyse IA',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: Color(0xFF065F46)),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Text(
            summary,
            style: const TextStyle(fontSize: 14, color: Color(0xFF065F46), height: 1.6),
          ),
        ],
      ),
    );
  }

  Widget _buildLineChart(List<WeeklyTrendData> trend) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: JennyColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Tendance des messages', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          const SizedBox(height: 24),
          SizedBox(
            height: 250,
            child: LineChart(
              LineChartData(
                gridData: FlGridData(
                  show: true,
                  drawVerticalLine: false,
                  horizontalInterval: 50,
                  getDrawingHorizontalLine: (value) => FlLine(
                    color: JennyColors.divider,
                    strokeWidth: 1,
                  ),
                ),
                titlesData: FlTitlesData(
                  bottomTitles: AxisTitles(
                    sideTitles: SideTitles(
                      showTitles: true,
                      interval: 1,
                      getTitlesWidget: (value, meta) {
                        final idx = value.toInt();
                        if (idx >= 0 && idx < trend.length) {
                          return Padding(
                            padding: const EdgeInsets.only(top: 8),
                            child: Text(trend[idx].day, style: const TextStyle(fontSize: 11, color: JennyColors.textSecondary)),
                          );
                        }
                        return const SizedBox.shrink();
                      },
                    ),
                  ),
                  leftTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                  topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                  rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                ),
                borderData: FlBorderData(show: false),
                lineBarsData: [
                  LineChartBarData(
                    spots: trend.asMap().entries.map((e) => FlSpot(e.key.toDouble(), e.value.messages.toDouble())).toList(),
                    isCurved: true,
                    color: JennyColors.primary,
                    barWidth: 3,
                    dotData: FlDotData(
                      show: true,
                      getDotPainter: (spot, percent, bar, index) => FlDotCirclePainter(
                        radius: 4,
                        color: Colors.white,
                        strokeWidth: 2,
                        strokeColor: JennyColors.primary,
                      ),
                    ),
                    belowBarData: BarAreaData(
                      show: true,
                      color: JennyColors.primary.withValues(alpha: 0.08),
                    ),
                  ),
                  LineChartBarData(
                    spots: trend.asMap().entries.map((e) => FlSpot(e.key.toDouble(), e.value.resolved.toDouble())).toList(),
                    isCurved: true,
                    color: const Color(0xFF059669),
                    barWidth: 3,
                    dotData: FlDotData(
                      show: true,
                      getDotPainter: (spot, percent, bar, index) => FlDotCirclePainter(
                        radius: 4,
                        color: Colors.white,
                        strokeWidth: 2,
                        strokeColor: const Color(0xFF059669),
                      ),
                    ),
                    belowBarData: BarAreaData(
                      show: true,
                      color: const Color(0xFF059669).withValues(alpha: 0.05),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTopTopicsDetailed(List<TopicData> topics) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: JennyColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Sujets les plus fréquents', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          const SizedBox(height: 16),
          ...topics.map((t) => Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: Row(
                  children: [
                    Expanded(
                      flex: 3,
                      child: Text(t.topic, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500)),
                    ),
                    Expanded(
                      flex: 4,
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(4),
                        child: LinearProgressIndicator(
                          value: t.pct / 100,
                          minHeight: 8,
                          backgroundColor: JennyColors.divider,
                          valueColor: AlwaysStoppedAnimation(JennyColors.primary.withValues(alpha: 0.7)),
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    SizedBox(
                      width: 60,
                      child: Text(
                        '${t.count}',
                        textAlign: TextAlign.right,
                        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: JennyColors.textPrimary),
                      ),
                    ),
                  ],
                ),
              )),
        ],
      ),
    );
  }

  Widget _buildAiPerformance(InsightData data) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: JennyColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Performance IA', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          const SizedBox(height: 20),
          Center(
            child: SizedBox(
              width: 150,
              height: 150,
              child: Stack(
                alignment: Alignment.center,
                children: [
                  SizedBox(
                    width: 150,
                    height: 150,
                    child: CircularProgressIndicator(
                      value: data.kpis.aiHandledPct / 100,
                      strokeWidth: 10,
                      backgroundColor: JennyColors.divider,
                      valueColor: const AlwaysStoppedAnimation(Color(0xFF8B5CF6)),
                      strokeCap: StrokeCap.round,
                    ),
                  ),
                  Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        '${data.kpis.aiHandledPct}%',
                        style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w700, color: JennyColors.textPrimary),
                      ),
                      const Text(
                        'Auto-résolu',
                        style: TextStyle(fontSize: 11, color: JennyColors.textSecondary),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 24),
          ...data.aiActions.map((a) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(a.action, style: const TextStyle(fontSize: 13, color: JennyColors.textPrimary)),
                    Text('${a.count}', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
                  ],
                ),
              )),
        ],
      ),
    );
  }
}
