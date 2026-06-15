class KnowledgeEntry {
  final String id;
  final String businessId;
  final String title;
  final String contentPreview;
  final String source;
  final String category;
  final int chunksCount;
  final String createdAt;

  const KnowledgeEntry({
    required this.id,
    required this.businessId,
    required this.title,
    required this.contentPreview,
    required this.source,
    required this.category,
    required this.chunksCount,
    required this.createdAt,
  });

  factory KnowledgeEntry.fromJson(Map<String, dynamic> json) => KnowledgeEntry(
        id: json['id'] as String,
        businessId: json['business_id'] as String? ?? '',
        title: json['title'] as String? ?? '',
        contentPreview: json['content_preview'] as String? ?? '',
        source: json['source'] as String? ?? '',
        category: json['category'] as String? ?? 'general',
        chunksCount: (json['chunks_count'] as num?)?.toInt() ?? 0,
        createdAt: json['created_at'] as String? ?? '',
      );
}

class KnowledgeStats {
  final String businessId;
  final int totalEntries;
  final int totalChunks;
  final Map<String, int> byCategory;
  final Map<String, int> bySource;

  const KnowledgeStats({
    required this.businessId,
    this.totalEntries = 0,
    this.totalChunks = 0,
    this.byCategory = const {},
    this.bySource = const {},
  });

  factory KnowledgeStats.fromJson(Map<String, dynamic> json) => KnowledgeStats(
        businessId: json['business_id'] as String? ?? '',
        totalEntries: (json['total_entries'] as num?)?.toInt() ?? 0,
        totalChunks: (json['total_chunks'] as num?)?.toInt() ?? 0,
        byCategory: (json['by_category'] as Map<String, dynamic>?)
                ?.map((k, v) => MapEntry(k, (v as num).toInt())) ??
            {},
        bySource: (json['by_source'] as Map<String, dynamic>?)
                ?.map((k, v) => MapEntry(k, (v as num).toInt())) ??
            {},
      );
}
