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
import '../../main.dart' show dioProvider;

final assetsProvider = FutureProvider<List<Asset>>((ref) async {
  final dio = await ref.watch(dioProvider.future);
  return Endpoints(dio).getAssets();
});

final selectedAssetProvider = NotifierProvider<_SelectedAssetNotifier, Asset?>(
    _SelectedAssetNotifier.new);

class _SelectedAssetNotifier extends Notifier<Asset?> {
  @override
  Asset? build() => null;
  void select(Asset? a) => state = a;
}

final latestSignalProvider = FutureProvider.family<Signal?, String>((ref, symbol) async {
  final dio = await ref.watch(dioProvider.future);
  try {
    return await Endpoints(dio).getLatestSignal(symbol);
  } catch (_) { return null; }
});

class SignalsScreen extends ConsumerStatefulWidget {
  const SignalsScreen({super.key});
  @override
  ConsumerState<SignalsScreen> createState() => _SignalsScreenState();
}

class _SignalsScreenState extends ConsumerState<SignalsScreen> {
  String _search      = '';
  String _filter      = 'All';
  bool   _generating  = false;
  String? _genError;
  bool   _genSuccess  = false;
  String? _explanation;
  bool   _explaining  = false;

  Future<void> _generate(Asset asset) async {
    setState(() { _generating = true; _genError = null; _genSuccess = false; _explanation = null; });
    try {
      final dio = await ref.read(dioProvider.future);
      await Endpoints(dio).generateSignal(asset.symbol);
      ref.invalidate(latestSignalProvider(asset.symbol));
      setState(() { _genSuccess = true; });
    } on DioException catch (e) {
      setState(() { _genError = 'Failed: ${e.response?.data ?? e.message}'; });
    } catch (e) {
      setState(() { _genError = 'Failed to generate signal: $e'; });
    } finally {
      setState(() { _generating = false; });
    }
  }

  Future<void> _explain(String signalId) async {
    setState(() { _explaining = true; _explanation = null; });
    try {
      final dio = await ref.read(dioProvider.future);
      final r   = await Endpoints(dio).explainSignal(signalId);
      setState(() { _explanation = r.explanation; });
    } catch (_) {
      setState(() { _explanation = 'Could not fetch explanation.'; });
    } finally {
      setState(() { _explaining = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final assetsAsync   = ref.watch(assetsProvider);
    final selectedAsset = ref.watch(selectedAssetProvider);

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(title: const Text('Signals')),
      body: assetsAsync.when(
        loading: () => const LoadingState(),
        error:   (e, _) => ErrorState(
          message: 'Could not load assets.',
          onRetry: () => ref.invalidate(assetsProvider),
        ),
        data: (assets) {
          final filtered = assets.where((a) {
            final matchSearch = a.symbol.toLowerCase().contains(_search.toLowerCase()) ||
                a.name.toLowerCase().contains(_search.toLowerCase());
            final matchFilter = _filter == 'All' ||
                a.assetType.toLowerCase() == _filter.toLowerCase();
            return matchSearch && matchFilter;
          }).toList();

          return selectedAsset == null
              ? _assetList(filtered)
              : _signalDetail(selectedAsset);
        },
      ),
    );
  }

  Widget _assetList(List<Asset> assets) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
          child: TextField(
            onChanged: (v) => setState(() => _search = v),
            decoration: const InputDecoration(
              hintText: 'Search assets...',
              prefixIcon: Icon(Icons.search_rounded, color: AppColors.textMuted, size: 20),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Row(
            children: ['All','Equity','Crypto','Forex'].map((f) =>
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: Text(f),
                  selected: _filter == f,
                  onSelected: (_) => setState(() => _filter = f),
                  selectedColor: AppColors.accent,
                  backgroundColor: AppColors.elevated,
                  labelStyle: TextStyle(
                    color: _filter == f ? Colors.white : AppColors.textSecondary,
                    fontSize: 12, fontWeight: FontWeight.w600,
                  ),
                  side: BorderSide(color: _filter == f ? AppColors.accent : AppColors.borderDef),
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                ),
              )
            ).toList(),
          ),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: ListView.builder(
            itemCount: assets.length,
            itemBuilder: (_, i) {
              final a = assets[i];
              final typeColor = a.assetType == 'equity' ? AppColors.accent
                  : a.assetType == 'crypto' ? AppColors.amber : AppColors.teal;
              return ListTile(
                onTap: () {
                  ref.read(selectedAssetProvider.notifier).select(a);
                  setState(() {
                    _genError = null; _genSuccess = false;
                    _explanation = null;
                  });
                },
                tileColor: AppColors.surface,
                contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                title: Text(a.symbol,
                    style: const TextStyle(
                      color: AppColors.textPrimary,
                      fontWeight: FontWeight.w700, fontSize: 13)),
                subtitle: Text(a.name,
                    style: const TextStyle(color: AppColors.textMuted, fontSize: 11)),
                trailing: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: typeColor.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: typeColor.withOpacity(0.3)),
                  ),
                  child: Text(a.assetType.toUpperCase(),
                      style: TextStyle(color: typeColor, fontSize: 9, fontWeight: FontWeight.w800)),
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  Widget _signalDetail(Asset asset) {
    final signalAsync = ref.watch(latestSignalProvider(asset.symbol));

    return Column(
      children: [
        // Back bar
        Container(
          color: AppColors.surface,
          child: ListTile(
            leading: IconButton(
              icon: const Icon(Icons.arrow_back_rounded, color: AppColors.textPrimary),
              onPressed: () =>
                  ref.read(selectedAssetProvider.notifier).select(null),
            ),
            title: Text(asset.name,
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontWeight: FontWeight.w700, fontSize: 15)),
            subtitle: Text(asset.symbol,
                style: const TextStyle(color: AppColors.textMuted, fontSize: 11)),
            trailing: ElevatedButton.icon(
              onPressed: _generating ? null : () => _generate(asset),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.accent,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
              ),
              icon: _generating
                  ? const SizedBox(width: 14, height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Icon(Icons.auto_graph_rounded, size: 16),
              label: Text(_generating ? 'Generating...' : 'Generate',
                  style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
            ),
          ),
        ),
        if (_genSuccess)
          Container(
            width: double.infinity, color: AppColors.green.withOpacity(0.1),
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
            child: const Text('Signal generated successfully!',
                style: TextStyle(color: AppColors.green, fontSize: 12, fontWeight: FontWeight.w600)),
          ),
        if (_genError != null)
          Container(
            width: double.infinity, color: AppColors.red.withOpacity(0.1),
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
            child: Text(_genError!,
                style: const TextStyle(color: AppColors.red, fontSize: 12)),
          ),
        Expanded(
          child: signalAsync.when(
            loading: () => const LoadingState(),
            error:   (_, __) => EmptyState(
              message: 'No signal for ${asset.symbol} yet.\nTap Generate to create one.',
              icon: Icons.show_chart_rounded,
            ),
            data: (signal) => signal == null
                ? EmptyState(
                    message: 'No signal for ${asset.symbol} yet.\nTap Generate to create one.',
                    icon: Icons.show_chart_rounded,
                  )
                : _SignalDetailBody(
                    signal: signal,
                    explanation: _explanation,
                    explaining: _explaining,
                    onExplain: () => _explain(signal.signalId),
                  ),
          ),
        ),
      ],
    );
  }
}

class _SignalDetailBody extends StatelessWidget {
  final Signal signal;
  final String? explanation;
  final bool explaining;
  final VoidCallback onExplain;
  const _SignalDetailBody({
    required this.signal,
    required this.explanation,
    required this.explaining,
    required this.onExplain,
  });

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // Badge + regime
        Row(
          children: [
            SignalBadge(action: signal.action, confidence: signal.confidence),
            const SizedBox(width: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: AppColors.elevated,
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: AppColors.borderDef),
              ),
              child: Text(signal.marketRegime.toUpperCase(),
                  style: const TextStyle(color: AppColors.accent, fontSize: 10,
                      fontWeight: FontWeight.w800)),
            ),
          ],
        ),
        const SizedBox(height: 16),

        // Model scores
        _SectionTitle('Model Scores'),
        _ScoreBar('RL Score',          signal.rlScore),
        _ScoreBar('Transformer Score', signal.transformerScore),
        _ScoreBar('Sentiment Score',   signal.sentimentScore),
        _ScoreBar('Ensemble Score',    signal.ensembleScore),
        const SizedBox(height: 16),

        // Technical indicators
        _SectionTitle('Technical Indicators'),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          crossAxisSpacing: 8,
          mainAxisSpacing: 8,
          childAspectRatio: 2.4,
          children: [
            _IndicatorTile('RSI 14',     signal.rsi?.toStringAsFixed(1)),
            _IndicatorTile('ADX',        signal.adx?.toStringAsFixed(1)),
            _IndicatorTile('Vol Ratio',  signal.volRatio?.toStringAsFixed(2)),
            _IndicatorTile('ATR %',      signal.atrPct != null
                ? '${(signal.atrPct! * 100).toStringAsFixed(2)}%' : null),
          ],
        ),
        const SizedBox(height: 16),

        // Explain button
        OutlinedButton.icon(
          onPressed: explaining ? null : onExplain,
          style: OutlinedButton.styleFrom(
            foregroundColor: AppColors.accent,
            side: const BorderSide(color: AppColors.accent),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          ),
          icon: explaining
              ? const SizedBox(width: 14, height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.accent))
              : const Icon(Icons.auto_awesome_rounded, size: 16),
          label: Text(explaining ? 'Explaining...' : 'Explain with AI'),
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
                    color: AppColors.textSecondary, fontSize: 13, height: 1.5)),
            ),
          ],
        const SizedBox(height: 80),
      ],
    );
  }
}

Widget _SectionTitle(String t) => Padding(
  padding: const EdgeInsets.only(bottom: 10),
  child: Text(t, style: const TextStyle(
      color: AppColors.textMuted, fontSize: 10,
      fontWeight: FontWeight.w800, letterSpacing: 0.8)),
);

Widget _ScoreBar(String label, double value) {
  final isPos = value >= 0;
  final pct   = (value.abs()).clamp(0.0, 1.0);
  return Padding(
    padding: const EdgeInsets.only(bottom: 10),
    child: Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: const TextStyle(
                color: AppColors.textSecondary, fontSize: 11, fontWeight: FontWeight.w600)),
            Text(value.toStringAsFixed(3),
                style: TextStyle(
                  color: isPos ? AppColors.green : AppColors.red,
                  fontSize: 11, fontWeight: FontWeight.w700, fontFamily: 'monospace',
                )),
          ],
        ),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value:           pct,
            backgroundColor: AppColors.elevated,
            valueColor:      AlwaysStoppedAnimation(isPos ? AppColors.green : AppColors.red),
            minHeight:       6,
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
        Text(label, style: const TextStyle(
            color: AppColors.textMuted, fontSize: 9, fontWeight: FontWeight.w800)),
        const SizedBox(height: 2),
        Text(value ?? 'N/A',
            style: const TextStyle(
              color: AppColors.amber, fontSize: 13,
              fontWeight: FontWeight.w700, fontFamily: 'monospace',
            )),
      ],
    ),
  );
}
