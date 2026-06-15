import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:fl_chart/fl_chart.dart';
import '../../core/theme/jenny_colors.dart';
import '../../providers/insight_provider.dart';
import '../../models/insight.dart';
import '../../widgets/kpi_card.dart';
import '../../widgets/shimmer_loading.dart';

class DashboardPage extends ConsumerStatefulWidget {
  const DashboardPage({super.key});

  @override
  ConsumerState<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends ConsumerState<DashboardPage>
    with SingleTickerProviderStateMixin {
  late final AnimationController _animController;

  @override
  void initState() {
    super.initState();
    _animController = AnimationController(
      duration: const Duration(milliseconds: 600),
      vsync: this,
    )..forward();
    ref.read(insightProvider.notifier).loadInsights();
  }

  @override
  void dispose() {
    _animController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(insightProvider);

    if (state.isLoading) {
      return const ShimmerList(count: 4);
    }

    if (state.error != null) {
      return _buildError(state.error!);
    }

    final data = state.data;
    if (data == null) {
      return const Center(child: Text('Aucune donnée'));
    }

    return FadeTransition(
      opacity: CurvedAnimation(parent: _animController, curve: Curves.easeOut),
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildKpis(data.kpis),
            const SizedBox(height: 24),
            _buildAiSummary(data.summary),
            const SizedBox(height: 24),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(flex: 3, child: _buildWeeklyChart(data.weeklyTrend)),
                const SizedBox(width: 20),
                Expanded(flex: 2, child: _buildTopTopics(data.topTopics)),
              ],
            ),
            const SizedBox(height: 24),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: _buildChannelBreakdown(data.channelBreakdown)),
                const SizedBox(width: 20),
                Expanded(child: _buildAiActions(data.aiActions)),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildKpis(KpiData kpis) {
    final items = [
      _KpiItem('Messages totaux', '${kpis.totalMessages}', kpis.messagesChange,
          Icons.message_rounded, JennyColors.primary),
      _KpiItem('Temps de réponse', '${kpis.avgResponseTimeSeconds}s', kpis.responseTimeChange,
          Icons.timer_rounded, JennyColors.structure),
      _KpiItem('Traité par IA', '${kpis.aiHandledPct}%', kpis.aiHandledChange,
          Icons.auto_awesome_rounded, const Color(0xFF8B5CF6)),
      _KpiItem('Satisfaction', '${kpis.csat}/5', (kpis.csatChange * 10).round(),
          Icons.star_rounded, JennyColors.warning),
    ];

    return LayoutBuilder(
      builder: (context, constraints) {
        final crossCount = constraints.maxWidth > 900 ? 4 : 2;
        return GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: crossCount,
            crossAxisSpacing: 16,
            mainAxisSpacing: 16,
            childAspectRatio: 1.6,
          ),
          itemCount: items.length,
          itemBuilder: (context, index) {
            final item = items[index];
            return KpiCard(
              title: item.title,
              value: item.value,
              changePercent: item.change,
              icon: item.icon,
              iconColor: item.color,
              index: index,
            );
          },
        );
      },
    );
  }

  Widget _buildAiSummary(String summary) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: JennyColors.aiGradient,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFB8DFC9)),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.6),
              borderRadius: BorderRadius.circular(10),
            ),
            child: const Icon(Icons.auto_awesome_rounded, color: Color(0xFF059669), size: 22),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Résumé IA de la semaine',
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 14,
                    color: Color(0xFF065F46),
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  summary,
                  style: const TextStyle(fontSize: 13, color: Color(0xFF065F46), height: 1.5),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildWeeklyChart(List<WeeklyTrendData> trend) {
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
          const Text(
            'Activité de la semaine',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w600,
              color: JennyColors.textPrimary,
            ),
          ),
          const SizedBox(height: 24),
          SizedBox(
            height: 220,
            child: BarChart(
              BarChartData(
                alignment: BarChartAlignment.spaceAround,
                maxY: (trend.map((t) => t.messages).reduce((a, b) => a > b ? a : b) * 1.2),
                barTouchData: BarTouchData(
                  touchTooltipData: BarTouchTooltipData(
                    getTooltipItem: (group, groupIndex, rod, rodIndex) {
                      return BarTooltipItem(
                        '${rod.toY.toInt()}',
                        const TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
                      );
                    },
                  ),
                ),
                titlesData: FlTitlesData(
                  show: true,
                  bottomTitles: AxisTitles(
                    sideTitles: SideTitles(
                      showTitles: true,
                      getTitlesWidget: (value, meta) {
                        final idx = value.toInt();
                        if (idx >= 0 && idx < trend.length) {
                          return Padding(
                            padding: const EdgeInsets.only(top: 8),
                            child: Text(
                              trend[idx].day,
                              style: const TextStyle(fontSize: 11, color: JennyColors.textSecondary),
                            ),
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
                gridData: const FlGridData(show: false),
                borderData: FlBorderData(show: false),
                barGroups: trend.asMap().entries.map((entry) {
                  return BarChartGroupData(
                    x: entry.key,
                    barRods: [
                      BarChartRodData(
                        toY: entry.value.messages.toDouble(),
                        color: JennyColors.primary.withValues(alpha: 0.8),
                        width: 16,
                        borderRadius: const BorderRadius.vertical(top: Radius.circular(6)),
                      ),
                      BarChartRodData(
                        toY: entry.value.resolved.toDouble(),
                        color: JennyColors.aiHighlight,
                        width: 16,
                        borderRadius: const BorderRadius.vertical(top: Radius.circular(6)),
                      ),
                    ],
                  );
                }).toList(),
              ),
            ),
          ),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _legendDot(JennyColors.primary.withValues(alpha: 0.8), 'Messages'),
              const SizedBox(width: 20),
              _legendDot(JennyColors.aiHighlight, 'Résolus'),
            ],
          ),
        ],
      ),
    );
  }

  Widget _legendDot(Color color, String label) {
    return Row(
      children: [
        Container(width: 10, height: 10, decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(3))),
        const SizedBox(width: 6),
        Text(label, style: const TextStyle(fontSize: 12, color: JennyColors.textSecondary)),
      ],
    );
  }

  Widget _buildTopTopics(List<TopicData> topics) {
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
          const Text(
            'Top sujets',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: JennyColors.textPrimary),
          ),
          const SizedBox(height: 16),
          ...topics.map((t) => _topicRow(t)),
        ],
      ),
    );
  }

  Widget _topicRow(TopicData topic) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Flexible(
                child: Text(
                  topic.topic,
                  style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: JennyColors.textPrimary),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Text(
                '${topic.pct}%',
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: JennyColors.textSecondary),
              ),
            ],
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: topic.pct / 100,
              minHeight: 6,
              backgroundColor: JennyColors.divider,
              valueColor: AlwaysStoppedAnimation(JennyColors.primary.withValues(alpha: 0.7)),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildChannelBreakdown(List<ChannelData> channels) {
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
          const Text(
            'Répartition par canal',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: JennyColors.textPrimary),
          ),
          const SizedBox(height: 20),
          SizedBox(
            height: 180,
            child: PieChart(
              PieChartData(
                sectionsSpace: 3,
                centerSpaceRadius: 40,
                sections: channels.map((c) {
                  Color color;
                  switch (c.channel) {
                    case 'whatsapp':
                      color = JennyColors.whatsapp;
                    case 'instagram':
                      color = JennyColors.instagram;
                    default:
                      color = JennyColors.email;
                  }
                  return PieChartSectionData(
                    color: color,
                    value: c.pct,
                    title: '${c.pct.round()}%',
                    radius: 32,
                    titleStyle: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Colors.white),
                  );
                }).toList(),
              ),
            ),
          ),
          const SizedBox(height: 16),
          ...channels.map((c) => Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(
                  children: [
                    Container(
                      width: 10,
                      height: 10,
                      decoration: BoxDecoration(
                        color: c.channel == 'whatsapp'
                            ? JennyColors.whatsapp
                            : c.channel == 'instagram'
                                ? JennyColors.instagram
                                : JennyColors.email,
                        borderRadius: BorderRadius.circular(3),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      '${c.channel[0].toUpperCase()}${c.channel.substring(1)}',
                      style: const TextStyle(fontSize: 13, color: JennyColors.textPrimary),
                    ),
                    const Spacer(),
                    Text('${c.count}', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: JennyColors.textSecondary)),
                  ],
                ),
              )),
        ],
      ),
    );
  }

  Widget _buildAiActions(List<AiActionData> actions) {
    final icons = [
      Icons.reply_rounded,
      Icons.edit_note_rounded,
      Icons.escalator_warning_rounded,
      Icons.label_rounded,
    ];
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
          const Text(
            'Actions IA',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: JennyColors.textPrimary),
          ),
          const SizedBox(height: 16),
          ...actions.asMap().entries.map((entry) {
            final a = entry.value;
            return Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: JennyColors.aiHighlight,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Icon(icons[entry.key % icons.length], size: 18, color: const Color(0xFF059669)),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(a.action, style: const TextStyle(fontSize: 13, color: JennyColors.textPrimary)),
                  ),
                  Text(
                    '${a.count}',
                    style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: JennyColors.textPrimary),
                  ),
                ],
              ),
            );
          }),
        ],
      ),
    );
  }

  Widget _buildError(String error) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.error_outline_rounded, size: 48, color: JennyColors.error.withValues(alpha: 0.6)),
          const SizedBox(height: 16),
          const Text('Erreur de chargement', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Text(error, style: const TextStyle(fontSize: 13, color: JennyColors.textSecondary)),
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: () => ref.read(insightProvider.notifier).loadInsights(),
            child: const Text('Réessayer'),
          ),
        ],
      ),
    );
  }
}

class _KpiItem {
  final String title;
  final String value;
  final int change;
  final IconData icon;
  final Color color;
  const _KpiItem(this.title, this.value, this.change, this.icon, this.color);
}
