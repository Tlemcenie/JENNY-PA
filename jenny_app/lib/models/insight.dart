class InsightData {
  final String summary;
  final KpiData kpis;
  final List<TopicData> topTopics;
  final List<ChannelData> channelBreakdown;
  final List<WeeklyTrendData> weeklyTrend;
  final List<AiActionData> aiActions;

  const InsightData({
    required this.summary,
    required this.kpis,
    required this.topTopics,
    required this.channelBreakdown,
    required this.weeklyTrend,
    required this.aiActions,
  });

  factory InsightData.fromJson(Map<String, dynamic> json) => InsightData(
        summary: json['summary'] as String? ?? '',
        kpis: KpiData.fromJson(json['kpis'] as Map<String, dynamic>? ?? {}),
        topTopics: (json['top_topics'] as List<dynamic>?)
                ?.map((e) => TopicData.fromJson(e as Map<String, dynamic>))
                .toList() ??
            [],
        channelBreakdown: (json['channel_breakdown'] as List<dynamic>?)
                ?.map((e) => ChannelData.fromJson(e as Map<String, dynamic>))
                .toList() ??
            [],
        weeklyTrend: (json['weekly_trend'] as List<dynamic>?)
                ?.map((e) => WeeklyTrendData.fromJson(e as Map<String, dynamic>))
                .toList() ??
            [],
        aiActions: (json['ai_actions'] as List<dynamic>?)
                ?.map((e) => AiActionData.fromJson(e as Map<String, dynamic>))
                .toList() ??
            [],
      );
}

class KpiData {
  final int totalMessages;
  final int messagesChange;
  final int avgResponseTimeSeconds;
  final int responseTimeChange;
  final double aiHandledPct;
  final int aiHandledChange;
  final double csat;
  final double csatChange;
  final int activeConversations;
  final int resolvedToday;

  const KpiData({
    this.totalMessages = 0,
    this.messagesChange = 0,
    this.avgResponseTimeSeconds = 0,
    this.responseTimeChange = 0,
    this.aiHandledPct = 0,
    this.aiHandledChange = 0,
    this.csat = 0,
    this.csatChange = 0,
    this.activeConversations = 0,
    this.resolvedToday = 0,
  });

  factory KpiData.fromJson(Map<String, dynamic> json) => KpiData(
        totalMessages: (json['total_messages'] as num?)?.toInt() ?? 0,
        messagesChange: (json['messages_change'] as num?)?.toInt() ?? 0,
        avgResponseTimeSeconds: (json['avg_response_time_seconds'] as num?)?.toInt() ?? 0,
        responseTimeChange: (json['response_time_change'] as num?)?.toInt() ?? 0,
        aiHandledPct: (json['ai_handled_pct'] as num?)?.toDouble() ?? 0,
        aiHandledChange: (json['ai_handled_change'] as num?)?.toInt() ?? 0,
        csat: (json['csat'] as num?)?.toDouble() ?? 0,
        csatChange: (json['csat_change'] as num?)?.toDouble() ?? 0,
        activeConversations: (json['active_conversations'] as num?)?.toInt() ?? 0,
        resolvedToday: (json['resolved_today'] as num?)?.toInt() ?? 0,
      );
}

class TopicData {
  final String topic;
  final int count;
  final double pct;

  const TopicData({required this.topic, required this.count, required this.pct});

  factory TopicData.fromJson(Map<String, dynamic> json) => TopicData(
        topic: json['topic'] as String? ?? '',
        count: (json['count'] as num?)?.toInt() ?? 0,
        pct: (json['pct'] as num?)?.toDouble() ?? 0,
      );
}

class ChannelData {
  final String channel;
  final int count;
  final double pct;

  const ChannelData({required this.channel, required this.count, required this.pct});

  factory ChannelData.fromJson(Map<String, dynamic> json) => ChannelData(
        channel: json['channel'] as String? ?? '',
        count: (json['count'] as num?)?.toInt() ?? 0,
        pct: (json['pct'] as num?)?.toDouble() ?? 0,
      );
}

class WeeklyTrendData {
  final String day;
  final int messages;
  final int resolved;

  const WeeklyTrendData({required this.day, required this.messages, required this.resolved});

  factory WeeklyTrendData.fromJson(Map<String, dynamic> json) => WeeklyTrendData(
        day: json['day'] as String? ?? '',
        messages: (json['messages'] as num?)?.toInt() ?? 0,
        resolved: (json['resolved'] as num?)?.toInt() ?? 0,
      );
}

class AiActionData {
  final String action;
  final int count;

  const AiActionData({required this.action, required this.count});

  factory AiActionData.fromJson(Map<String, dynamic> json) => AiActionData(
        action: json['action'] as String? ?? '',
        count: (json['count'] as num?)?.toInt() ?? 0,
      );
}
