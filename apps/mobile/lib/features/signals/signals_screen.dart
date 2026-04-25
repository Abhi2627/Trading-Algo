// features/signals/signals_screen.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:dio/dio.dart';
import '../../core/api/endpoints.dart';
import '../../core/models/asset.dart';
import '../../core/models/signal.dart';
import '../../shared/theme.dart';
import '../../shared/widgets/signal_badge.dart';
import '../../shared/widgets/loading_state.dart';
import '../../shared/widgets/candlestick_chart.dart';
import '../../main.dart' show dioProvider;

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------

final sectionsProvider = FutureProvider<List<MarketSection>>((ref) async {
  final dio = await ref.watch(dioProvider.future);
  final raw = await Endpoints(dio).getSections();
  return raw.map((e) => MarketSection.fromJson(e as Map<String, dynamic>)).toList();
});

final assetsProvider = FutureProvider<List<Asset>>((ref) async {
  final dio = await ref.watch(dioProvider.future);
  return Endpoints(dio).getAssets();
});

final sectionTopPicksProvider =
    FutureProvider.family<List<Map<String, dynamic>>, String>(
        (ref, sectionId) async {
  final dio = await ref.watch(dioProvider.future);
  // Top picks filtered to section symbols — uses existing top-picks endpoint
  // Section filtering happens client-side since backend top-picks are global
  return Endpoints(dio).getTopPicks(limit: 20);
});

final selectedAssetProvider =
    NotifierProvider<_SelectedAssetNotifier, Asset?>(
        _SelectedAssetNotifier.new);

class _SelectedAssetNotifier extends Notifier<Asset?> {
  @override
  Asset? build() => null;
  void select(Asset? a) => state = a;
}

final latestSignalProvider =
    FutureProvider.family<Signal?, String>((ref, symbol) async {
  final dio = await ref.watch(dioProvider.future);
  try {
    return await Endpoints(dio).getLatestSignal(symbol);
  } catch (_) {
    return null;
  }
});

// ---------------------------------------------------------------------------
// Data model for sections from backend
// ---------------------------------------------------------------------------

class MarketSection {
  final String id;
  final String label;
  final int count;
  final List<String> symbols;
  const MarketSection(
      {required this.id,
      required this.label,
      required this.count,
      required this.symbols});
  factory MarketSection.fromJson(Map<String, dynamic> j) => MarketSection(
        id: j['id'] as String,
        label: j['label'] as String,
        count: j['count'] as int,
        symbols: (j['symbols'] as List).cast<String>(),
      );
}

// ---------------------------------------------------------------------------
// Main screen
// ---------------------------------------------------------------------------

class SignalsScreen extends ConsumerStatefulWidget {
  const SignalsScreen({super.key});
  @override
  ConsumerState<SignalsScreen> createState() => _SignalsScreenState();
}

class _SignalsScreenState extends ConsumerState<SignalsScreen>
    with SingleTickerProviderStateMixin {
  final _searchCtrl = TextEditingController();
  String _search = '';
  bool _generating = false;
  String? _genError;
  bool _genSuccess = false;
  String? _explanation;
  bool _explaining = false;

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _generate(Asset asset) async {
    setState(() {
      _generating = true;
      _genError = null;
      _genSuccess = false;
      _explanation = null;
    });
    try {
      final dio = await ref.read(dioProvider.future);
      await Endpoints(dio).generateSignal(asset.symbol);
      ref.invalidate(latestSignalProvider(asset.symbol));
      ref.invalidate(sectionTopPicksProvider);
      setState(() => _genSuccess = true);
    } on DioException catch (e) {
      setState(() {
        _genError = 'Failed: ${e.response?.data ?? e.message}';
      });
    } catch (e) {
      setState(() => _genError = 'Error: $e');
    } finally {
      setState(() => _generating = false);
    }
  }

  Future<void> _explain(String signalId) async {
    setState(() {
      _explaining = true;
      _explanation = null;
    });
    try {
      final dio = await ref.read(dioProvider.future);
      final r = await Endpoints(dio).explainSignal(signalId);
      setState(() => _explanation = r.explanation);
    } catch (_) {
      setState(() => _explanation = 'Could not fetch explanation.');
    } finally {
      setState(() => _explaining = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final selectedAsset = ref.watch(selectedAssetProvider);

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: Text(selectedAsset != null ? selectedAsset.name : 'Markets'),
        leading: selectedAsset != null
            ? IconButton(
                icon: const Icon(Icons.arrow_back_rounded),
                onPressed: () =>
                    ref.read(selectedAssetProvider.notifier).select(null),
              )
            : null,
      ),
      body: selectedAsset != null
          ? _SignalDetailView(
              asset: selectedAsset,
              generating: _generating,
              genError: _genError,
              genSuccess: _genSuccess,
              explanation: _explanation,
              explaining: _explaining,
              onGenerate: () => _generate(selectedAsset),
              onExplain: (id) => _explain(id),
            )
          : _MarketBrowser(
              search: _search,
              searchCtrl: _searchCtrl,
              onSearchChanged: (v) => setState(() => _search = v),
              onAssetTap: (asset) {
                ref.read(selectedAssetProvider.notifier).select(asset);
                setState(() {
                  _genError = null;
                  _genSuccess = false;
                  _explanation = null;
                });
              },
            ),
    );
  }
}

// ---------------------------------------------------------------------------
// Market browser — sections + search
// ---------------------------------------------------------------------------

class _MarketBrowser extends ConsumerWidget {
  final String search;
  final TextEditingController searchCtrl;
  final ValueChanged<String> onSearchChanged;
  final ValueChanged<Asset> onAssetTap;

  const _MarketBrowser({
    required this.search,
    required this.searchCtrl,
    required this.onSearchChanged,
    required this.onAssetTap,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sectionsAsync = ref.watch(sectionsProvider);
    final assetsAsync = ref.watch(assetsProvider);
    final topPicksAsync = ref.watch(sectionTopPicksProvider('all'));

    return Column(
      children: [
        // Search bar
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
          child: TextField(
            controller: searchCtrl,
            onChanged: onSearchChanged,
            decoration: const InputDecoration(
              hintText: 'Search stocks...',
              prefixIcon:
                  Icon(Icons.search_rounded, color: AppColors.textMuted, size: 20),
            ),
          ),
        ),

        Expanded(
          child: search.isNotEmpty
              // --- Search results ---
              ? assetsAsync.when(
                  loading: () => const LoadingState(),
                  error: (_, __) => const SizedBox(),
                  data: (assets) {
                    final results = assets
                        .where((a) =>
                            a.symbol
                                .toLowerCase()
                                .contains(search.toLowerCase()) ||
                            a.name
                                .toLowerCase()
                                .contains(search.toLowerCase()))
                        .toList();
                    return results.isEmpty
                        ? EmptyState(
                            message: 'No results for "$search"',
                            icon: Icons.search_off_rounded)
                        : ListView.builder(
                            itemCount: results.length,
                            itemBuilder: (_, i) =>
                                _AssetTile(asset: results[i], onTap: onAssetTap),
                          );
                  },
                )
              // --- Sections view ---
              : sectionsAsync.when(
                  loading: () => const LoadingState(),
                  error: (e, _) => ErrorState(
                    message: 'Could not load market sections.',
                    onRetry: () => ref.invalidate(sectionsProvider),
                  ),
                  data: (sections) => ListView(
                    children: [
                      // Top Potentials strip (global, not per-section)
                      topPicksAsync.when(
                        loading: () => const SizedBox(
                            height: 60, child: LoadingState()),
                        error: (_, __) => const SizedBox(),
                        data: (picks) => picks.isEmpty
                            ? const SizedBox()
                            : _TopPotentialsStrip(picks: picks),
                      ),
                      const SizedBox(height: 8),
                      // Section cards
                      ...sections.map((s) => _SectionCard(
                            section: s,
                            allTopPicks: topPicksAsync.value ?? [],
                            onAssetTap: onAssetTap,
                          )),
                      const SizedBox(height: 80),
                    ],
                  ),
                ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Top Potentials horizontal strip
// ---------------------------------------------------------------------------

class _TopPotentialsStrip extends StatelessWidget {
  final List<Map<String, dynamic>> picks;
  const _TopPotentialsStrip({required this.picks});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 12, 16, 8),
          child: Row(
            children: [
              Icon(Icons.bolt_rounded, color: AppColors.amber, size: 14),
              SizedBox(width: 4),
              Text('Top Potentials Today',
                  style: TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 13,
                      fontWeight: FontWeight.w800)),
            ],
          ),
        ),
        SizedBox(
          height: 90,
          child: ListView.builder(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            itemCount: picks.length,
            itemBuilder: (_, i) => _TopPickChip(pick: picks[i]),
          ),
        ),
      ],
    );
  }
}

class _TopPickChip extends ConsumerWidget {
  final Map<String, dynamic> pick;
  final ValueChanged<Asset>? onAssetTap;
  const _TopPickChip({required this.pick, this.onAssetTap});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final symbol = pick['symbol'] as String;
    final conf = (pick['confidence'] as num).toDouble();
    final regime = pick['market_regime'] as String? ?? '';
    final rsi = pick['rsi'] as num?;

    return GestureDetector(
      onTap: () {
        final assetsData = ref.read(assetsProvider).value ?? [];
        final asset = assetsData.where((a) => a.symbol == symbol).firstOrNull;
        if (asset != null) {
          ref.read(selectedAssetProvider.notifier).select(asset);
        }
      },
      child: Container(
        width: 130,
        margin: const EdgeInsets.only(right: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AppColors.green.withOpacity(0.4), width: 1.5),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(symbol.split(':').last,
                style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontWeight: FontWeight.w800,
                    fontSize: 12)),
            Text(regime.toUpperCase(),
                style: const TextStyle(
                    color: AppColors.accent,
                    fontSize: 8,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 0.5)),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('${conf.toStringAsFixed(0)}%',
                    style: const TextStyle(
                        color: AppColors.green,
                        fontSize: 11,
                        fontWeight: FontWeight.w700)),
                if (rsi != null)
                  Text('RSI ${rsi.toStringAsFixed(0)}',
                      style: const TextStyle(
                          color: AppColors.textMuted, fontSize: 9)),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Section card with top 3 potentials inline
// ---------------------------------------------------------------------------

class _SectionCard extends ConsumerWidget {
  final MarketSection section;
  final List<Map<String, dynamic>> allTopPicks;
  final ValueChanged<Asset> onAssetTap;

  const _SectionCard({
    required this.section,
    required this.allTopPicks,
    required this.onAssetTap,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final assetsAsync = ref.watch(assetsProvider);

    // Filter top picks to those in this section
    final sectionPicks = allTopPicks
        .where((p) => section.symbols.contains(p['symbol'] as String))
        .take(3)
        .toList();

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.borderDef),
      ),
      child: Theme(
        data: Theme.of(context).copyWith(
          dividerColor: Colors.transparent,
        ),
        child: ExpansionTile(
          tilePadding:
              const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
          childrenPadding: EdgeInsets.zero,
          title: Row(
            children: [
              Expanded(
                child: Text(section.label,
                    style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontWeight: FontWeight.w700,
                        fontSize: 13)),
              ),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: AppColors.elevated,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text('${section.count}',
                    style: const TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 10,
                        fontWeight: FontWeight.w700)),
              ),
            ],
          ),
          subtitle: sectionPicks.isNotEmpty
              ? Padding(
                  padding: const EdgeInsets.only(top: 4, bottom: 2),
                  child: Row(
                    children: [
                      const Icon(Icons.bolt_rounded,
                          color: AppColors.amber, size: 10),
                      const SizedBox(width: 3),
                      Text(
                        sectionPicks
                            .map((p) => (p['symbol'] as String).split(':').last)
                            .join(' · '),
                        style: const TextStyle(
                            color: AppColors.amber,
                            fontSize: 10,
                            fontWeight: FontWeight.w600),
                      ),
                    ],
                  ),
                )
              : null,
          children: [
            assetsAsync.when(
              loading: () => const SizedBox(
                  height: 40, child: Center(child: LoadingState())),
              error: (_, __) => const SizedBox(),
              data: (assets) {
                final sectionAssets = assets
                    .where((a) => section.symbols.contains(a.symbol))
                    .toList();
                return Column(
                  children: [
                    const Divider(height: 1, color: AppColors.borderDef),
                    ...sectionAssets.map(
                      (a) => _AssetTile(
                        asset: a,
                        onTap: onAssetTap,
                        highlight: sectionPicks
                            .any((p) => p['symbol'] == a.symbol),
                        pickData: sectionPicks.firstWhere(
                          (p) => p['symbol'] == a.symbol,
                          orElse: () => {},
                        ),
                      ),
                    ),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Asset tile
// ---------------------------------------------------------------------------

class _AssetTile extends StatelessWidget {
  final Asset asset;
  final ValueChanged<Asset> onTap;
  final bool highlight;
  final Map<String, dynamic> pickData;

  const _AssetTile({
    required this.asset,
    required this.onTap,
    this.highlight = false,
    this.pickData = const {},
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () => onTap(asset),
      child: Container(
        padding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        decoration: BoxDecoration(
          color: highlight
              ? AppColors.green.withOpacity(0.04)
              : Colors.transparent,
          border: Border(
              bottom: BorderSide(color: AppColors.borderDef, width: 0.5)),
        ),
        child: Row(
          children: [
            if (highlight)
              const Padding(
                padding: EdgeInsets.only(right: 8),
                child: Icon(Icons.bolt_rounded,
                    color: AppColors.amber, size: 12),
              ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(asset.symbol.split(':').last,
                      style: const TextStyle(
                          color: AppColors.textPrimary,
                          fontWeight: FontWeight.w700,
                          fontSize: 12)),
                  Text(asset.name,
                      style: const TextStyle(
                          color: AppColors.textMuted, fontSize: 10)),
                ],
              ),
            ),
            if (highlight && pickData.isNotEmpty) ...
              [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      '${(pickData['confidence'] as num).toStringAsFixed(0)}%',
                      style: const TextStyle(
                          color: AppColors.green,
                          fontWeight: FontWeight.w800,
                          fontSize: 11),
                    ),
                    Text(
                      (pickData['action'] as String).toUpperCase(),
                      style: const TextStyle(
                          color: AppColors.green,
                          fontSize: 9,
                          fontWeight: FontWeight.w800),
                    ),
                  ],
                ),
                const SizedBox(width: 8),
              ],
            const Icon(Icons.chevron_right_rounded,
                color: AppColors.textMuted, size: 16),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Signal detail view
// ---------------------------------------------------------------------------

class _SignalDetailView extends ConsumerWidget {
  final Asset asset;
  final bool generating;
  final String? genError;
  final bool genSuccess;
  final String? explanation;
  final bool explaining;
  final VoidCallback onGenerate;
  final ValueChanged<String> onExplain;

  const _SignalDetailView({
    required this.asset,
    required this.generating,
    required this.genError,
    required this.genSuccess,
    required this.explanation,
    required this.explaining,
    required this.onGenerate,
    required this.onExplain,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final signalAsync = ref.watch(latestSignalProvider(asset.symbol));

    return Column(
      children: [
        // Generate button bar
        Container(
          color: AppColors.surface,
          padding:
              const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(asset.symbol,
                  style: const TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 11,
                      fontFamily: 'monospace')),
              ElevatedButton.icon(
                onPressed: generating ? null : onGenerate,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.accent,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(
                      horizontal: 14, vertical: 8),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8)),
                ),
                icon: generating
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Icon(Icons.auto_graph_rounded, size: 16),
                label: Text(
                    generating ? 'Generating...' : 'Generate Signal',
                    style: const TextStyle(
                        fontSize: 12, fontWeight: FontWeight.w700)),
              ),
            ],
          ),
        ),
        if (genSuccess)
          Container(
            width: double.infinity,
            color: AppColors.green.withOpacity(0.1),
            padding:
                const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
            child: const Text('Signal generated!',
                style: TextStyle(
                    color: AppColors.green,
                    fontSize: 12,
                    fontWeight: FontWeight.w600)),
          ),
        if (genError != null)
          Container(
            width: double.infinity,
            color: AppColors.red.withOpacity(0.1),
            padding:
                const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
            child: Text(genError!,
                style:
                    const TextStyle(color: AppColors.red, fontSize: 12)),
          ),
        Expanded(
          child: signalAsync.when(
            loading: () => const LoadingState(),
            error: (_, __) => EmptyState(
              message:
                  'No signal yet.\nTap Generate Signal to create one.',
              icon: Icons.show_chart_rounded,
            ),
            data: (signal) => signal == null
                ? EmptyState(
                    message:
                        'No signal yet.\nTap Generate Signal to create one.',
                    icon: Icons.show_chart_rounded,
                  )
                : _SignalDetailBody(
                    signal: signal,
                    symbol: asset.symbol,
                    explanation: explanation,
                    explaining: explaining,
                    onExplain: () => onExplain(signal.signalId),
                  ),
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Signal detail body (reused from before)
// ---------------------------------------------------------------------------

class _SignalDetailBody extends StatelessWidget {
  final Signal signal;
  final String symbol;
  final String? explanation;
  final bool explaining;
  final VoidCallback onExplain;
  const _SignalDetailBody({
    required this.signal,
    required this.symbol,
    required this.explanation,
    required this.explaining,
    required this.onExplain,
  });

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // Candlestick Chart
        CandlestickChart(symbol: symbol),
        const SizedBox(height: 16),
        Row(
          children: [
            SignalBadge(action: signal.action, confidence: signal.confidence),
            const SizedBox(width: 10),
            Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: AppColors.elevated,
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: AppColors.borderDef),
              ),
              child: Text(signal.marketRegime.toUpperCase(),
                  style: const TextStyle(
                      color: AppColors.accent,
                      fontSize: 10,
                      fontWeight: FontWeight.w800)),
            ),
          ],
        ),
        const SizedBox(height: 16),
        _SectionTitle('Model Scores'),
        _ScoreBar('RL Score', signal.rlScore),
        _ScoreBar('Transformer Score', signal.transformerScore),
        _ScoreBar('Sentiment Score', signal.sentimentScore),
        _ScoreBar('Ensemble Score', signal.ensembleScore),
        const SizedBox(height: 16),
        _SectionTitle('Technical Indicators'),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          crossAxisSpacing: 8,
          mainAxisSpacing: 8,
          childAspectRatio: 2.4,
          children: [
            _IndicatorTile('RSI 14', signal.rsi?.toStringAsFixed(1)),
            _IndicatorTile('ADX', signal.adx?.toStringAsFixed(1)),
            _IndicatorTile('Vol Ratio', signal.volRatio?.toStringAsFixed(2)),
            _IndicatorTile(
                'ATR %',
                signal.atrPct != null
                    ? '${(signal.atrPct! * 100).toStringAsFixed(2)}%'
                    : null),
          ],
        ),
        const SizedBox(height: 16),
        OutlinedButton.icon(
          onPressed: explaining ? null : onExplain,
          style: OutlinedButton.styleFrom(
            foregroundColor: AppColors.accent,
            side: const BorderSide(color: AppColors.accent),
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(8)),
          ),
          icon: explaining
              ? const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(
                      strokeWidth: 2, color: AppColors.accent))
              : const Icon(Icons.auto_awesome_rounded, size: 16),
          label:
              Text(explaining ? 'Explaining...' : 'Explain with AI'),
        ),
        if (explanation != null) ...
          [
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: AppColors.elevated,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: AppColors.borderDef),
              ),
              child: Text(explanation!,
                  style: const TextStyle(
                      color: AppColors.textSecondary,
                      fontSize: 13,
                      height: 1.5)),
            ),
          ],
        const SizedBox(height: 80),
      ],
    );
  }
}

Widget _SectionTitle(String t) => Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Text(t,
          style: const TextStyle(
              color: AppColors.textMuted,
              fontSize: 10,
              fontWeight: FontWeight.w800,
              letterSpacing: 0.8)),
    );

Widget _ScoreBar(String label, double value) {
  final isPos = value >= 0;
  final pct = (value.abs()).clamp(0.0, 1.0);
  return Padding(
    padding: const EdgeInsets.only(bottom: 10),
    child: Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label,
                style: const TextStyle(
                    color: AppColors.textSecondary,
                    fontSize: 11,
                    fontWeight: FontWeight.w600)),
            Text(value.toStringAsFixed(3),
                style: TextStyle(
                    color: isPos ? AppColors.green : AppColors.red,
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    fontFamily: 'monospace')),
          ],
        ),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: pct,
            backgroundColor: AppColors.elevated,
            valueColor:
                AlwaysStoppedAnimation(isPos ? AppColors.green : AppColors.red),
            minHeight: 6,
          ),
        ),
      ],
    ),
  );
}

Widget _IndicatorTile(String label, String? value) {
  return Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
    decoration: BoxDecoration(
      color: AppColors.elevated,
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: AppColors.borderDef),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text(label,
            style: const TextStyle(
                color: AppColors.textMuted,
                fontSize: 9,
                fontWeight: FontWeight.w800)),
        const SizedBox(height: 2),
        Text(value ?? 'N/A',
            style: const TextStyle(
                color: AppColors.amber,
                fontSize: 13,
                fontWeight: FontWeight.w700,
                fontFamily: 'monospace')),
      ],
    ),
  );
}

