import 'package:flutter/material.dart';
import '../../core/theme/jenny_colors.dart';

class KnowledgePage extends StatefulWidget {
  const KnowledgePage({super.key});

  @override
  State<KnowledgePage> createState() => _KnowledgePageState();
}

class _KnowledgePageState extends State<KnowledgePage> {
  final _categories = ['general', 'horaires', 'tarifs', 'faq', 'politique', 'services', 'equipe'];
  String _selectedCategory = 'general';

  final _sampleEntries = [
    _KbEntry('FAQ - Questions fréquentes', 'Réponses aux questions les plus posées par les clients...', 'text', 'faq', 5, '2 jours'),
    _KbEntry('Tarifs 2025', 'Grille tarifaire complète des services...', 'text', 'tarifs', 3, '1 semaine'),
    _KbEntry('Catalogue Produits.pdf', 'Document PDF avec le catalogue complet des produits...', 'pdf', 'services', 12, '2 semaines'),
    _KbEntry('Politique de retour', 'Conditions de retour et remboursement...', 'text', 'politique', 2, '3 jours'),
    _KbEntry('Horaires d\'ouverture', 'Lundi à Vendredi: 9h-18h, Samedi: 10h-14h...', 'text', 'horaires', 1, '1 mois'),
  ];

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text(
                'Base de connaissances',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
              const Spacer(),
              _buildAddButton('Ajouter du texte', Icons.text_fields_rounded),
              const SizedBox(width: 8),
              _buildAddButton('Uploader un PDF', Icons.upload_file_rounded),
            ],
          ),
          const SizedBox(height: 16),
          _buildStats(),
          const SizedBox(height: 20),
          _buildCategoryFilter(),
          const SizedBox(height: 16),
          ..._sampleEntries.where((e) => _selectedCategory == 'general' || e.category == _selectedCategory).map(_buildEntryCard),
        ],
      ),
    );
  }

  Widget _buildAddButton(String label, IconData icon) {
    return ElevatedButton.icon(
      onPressed: () => _showAddDialog(context),
      icon: Icon(icon, size: 18),
      label: Text(label),
      style: ElevatedButton.styleFrom(
        backgroundColor: JennyColors.primary,
        foregroundColor: Colors.white,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      ),
    );
  }

  Widget _buildStats() {
    return Row(
      children: [
        _statCard('Documents', '${_sampleEntries.length}', Icons.description_rounded, JennyColors.primary),
        const SizedBox(width: 12),
        _statCard('Chunks', '${_sampleEntries.fold(0, (sum, e) => sum + e.chunks)}', Icons.data_object_rounded, const Color(0xFF8B5CF6)),
        const SizedBox(width: 12),
        _statCard('Catégories', '${_categories.length}', Icons.category_rounded, const Color(0xFF059669)),
      ],
    );
  }

  Widget _statCard(String label, String value, IconData icon, Color color) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: JennyColors.divider),
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Icon(icon, size: 18, color: color),
            ),
            const SizedBox(width: 12),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(value, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
                Text(label, style: const TextStyle(fontSize: 12, color: JennyColors.textSecondary)),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildCategoryFilter() {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: _categories.map((cat) {
          final isActive = _selectedCategory == cat;
          return Padding(
            padding: const EdgeInsets.only(right: 8),
            child: GestureDetector(
              onTap: () => setState(() => _selectedCategory = cat),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                decoration: BoxDecoration(
                  color: isActive ? JennyColors.primary : Colors.white,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: isActive ? JennyColors.primary : JennyColors.divider),
                ),
                child: Text(
                  cat == 'general' ? 'Tous' : cat[0].toUpperCase() + cat.substring(1),
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w500,
                    color: isActive ? Colors.white : JennyColors.textSecondary,
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildEntryCard(_KbEntry entry) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: JennyColors.divider),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: entry.source == 'pdf'
                  ? JennyColors.error.withValues(alpha: 0.1)
                  : JennyColors.structure.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(
              entry.source == 'pdf' ? Icons.picture_as_pdf_rounded : Icons.article_rounded,
              size: 20,
              color: entry.source == 'pdf' ? JennyColors.error : JennyColors.structure,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(entry.title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                const SizedBox(height: 2),
                Text(entry.preview, style: const TextStyle(fontSize: 12, color: JennyColors.textSecondary), maxLines: 1, overflow: TextOverflow.ellipsis),
                const SizedBox(height: 6),
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: JennyColors.primary.withValues(alpha: 0.08),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(entry.category, style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w600, color: JennyColors.primary)),
                    ),
                    const SizedBox(width: 8),
                    Text('${entry.chunks} chunks', style: const TextStyle(fontSize: 11, color: JennyColors.textSecondary)),
                    const SizedBox(width: 8),
                    Text('il y a ${entry.ago}', style: const TextStyle(fontSize: 11, color: JennyColors.textSecondary)),
                  ],
                ),
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline_rounded, size: 20, color: JennyColors.textSecondary),
            onPressed: () {},
          ),
        ],
      ),
    );
  }

  void _showAddDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Ajouter du contenu'),
        content: SizedBox(
          width: 400,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                decoration: InputDecoration(
                  labelText: 'Titre',
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                maxLines: 5,
                decoration: InputDecoration(
                  labelText: 'Contenu',
                  alignLabelWithHint: true,
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Annuler')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx),
            style: ElevatedButton.styleFrom(backgroundColor: JennyColors.primary, foregroundColor: Colors.white),
            child: const Text('Ajouter'),
          ),
        ],
      ),
    );
  }
}

class _KbEntry {
  final String title;
  final String preview;
  final String source;
  final String category;
  final int chunks;
  final String ago;
  const _KbEntry(this.title, this.preview, this.source, this.category, this.chunks, this.ago);
}
