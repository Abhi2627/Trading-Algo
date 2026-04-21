// features/dashboard/dashboard_screen.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api/endpoints.dart';
import '../../core/models/wallet.dart';
import '../../shared/theme.dart';
import '../../shared/widgets/stat_card.dart';
import '../../shared/widgets/signal_badge.dart';
import '../../shared/widgets/loading_state.dart';
import '../../main.dart' show dioProvider, activeTabProvider;
import '../signals/signals_screen.dart' show assetsProvider, selectedAssetProvider;

final walletProvider = FutureProvider<WalletSummary>((ref) async {
  final dio = await ref.watch(dioProvider.future);
  return Endpoints(dio).getWalletSummary();
});

final dashboardSignalsProvider = FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final dio = await ref.watch(dioProvider.future);
  return Endpoints(dio).getTopPicks(limit: 5);
});

String _inr(double v) {
  final abs = v.abs();
  if (abs >= 10000000) return '₹${(v / 10000000).toStringAsFixed(1)}Cr';
  if (abs >= 100000)   return '₹${(v / 100000).toStringAsFixed(1)}L';
  return '₹${v.toStringAsFixed(0)}';
}

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final walletAsync  = ref.watch(walletProvider);
    final signalsAsync = ref.watch(dashboardSignalsProvider);

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: const Text('AlgoTrade'),
        actions: [
          walletAsync.when(
            data: (w) => Padding(
              padding: const EdgeInsets.only(right: 16),
              child: Row(children: [
                Container(
                  width: 8, height: 8,
                  decoration: BoxDecoration(
                    color: w.riskMode == 'normal' ? AppColors.green
                         : w.riskMode == 'conservative' ? AppColors.amber
                         : AppColors.red,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 6),
                Text(w.riskMode.toUpperCase(),
                    style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800,
                        color: AppColors.textMuted, letterSpacing: 0.8)),
              ]),
            ),
            loading: () => const SizedBox(),
            error: (_, __) => const SizedBox(),
          ),
        ],
      ),
      body: RefreshIndicator(
        color: AppColors.accent,
        backgroundColor: AppColors.surface,
        onRefresh: () async {
          ref.invalidate(walletProvider);
          ref.invalidate(dashboardSignalsProvider);
        },
        child: walletAsync.when(
          loading: () => const LoadingState(),
          error: (e, _) => ErrorState(
            message: 'Could not load wallet.\nMake sure the backend is running.',
            onRetry: () => ref.invalidate(walletProvider),
          ),
          data: (wallet) => ListView(
            padding: const EdgeInsets.all(16),
            children: [
              GridView.count(
                crossAxisCount: 2, shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                crossAxisSpacing: 10, mainAxisSpacing: 10, childAspectRatio: 1.6,
                children: [
                  StatCard(label: 'Total Equity', value: _inr(wallet.totalEquity),
                      icon: Icons.account_balance_wallet_outlined),
                  StatCard(label: 'Cash Balance', value: _inr(wallet.cashBalance),
                      icon: Icons.payments_outlined),
                  StatCard(label: 'Realised P&L', value: _inr(wallet.realisedPnl),
                      trend: wallet.realisedPnl >= 0 ? 'up' : 'down',
                      icon: Icons.trending_up_rounded),
                  StatCard(label: 'Drawdown',
                      value: '${(wallet.drawdownPct * 100).toStringAsFixed(1)}%',
                      trend: wallet.drawdownPct > 0.05 ? 'down' : 'up',
                      icon: Icons.arrow_downward_rounded),
                ],
              ),
              const SizedBox(height: 20),
              const Text("Today's Top Picks",
                  style: TextStyle(color: AppColors.textPrimary,
                      fontSize: 15, fontWeight: FontWeight.w700)),
              const SizedBox(height: 10),
              signalsAsync.when(
                loading: () => const SizedBox(height: 80, child: LoadingState()),
                error: (_, __) => const SizedBox(),
                data: (picks) => picks.isEmpty
                    ? const EmptyState(
                        message: 'No top picks yet.\nCelery scan runs at 8:30 AM.',
                        icon: Icons.show_chart_rounded)
                    : SizedBox(
                        height: 130,
                        child: ListView.separated(
                          scrollDirection: Axis.horizontal,
                          itemCount: picks.length,
                          separatorBuilder: (_, __) => const SizedBox(width: 10),
                          itemBuilder: (_, i) => _TopPickCard(pick: picks[i]),
                        ),
                      ),
              ),
              const SizedBox(height: 20),
              const Text('Open Positions',
                  style: TextStyle(color: AppColors.textPrimary,
                      fontSize: 15, fontWeight: FontWeight.w700)),
              const SizedBox(height: 10),
              wallet.openPositions.isEmpty
                  ? const EmptyState(message: 'No open positions', icon: Icons.inbox_outlined)
                  : Column(
                      children: wallet.openPositions.map((p) => _PositionTile(position: p)).toList(),
                    ),
              const SizedBox(height: 80),
            ],
          ),
        ),
      ),
    );
  }
}

class _TopPickCard extends ConsumerWidget {
  final Map<String, dynamic> pick;
  const _TopPickCard({required this.pick});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final confidence = (pick['confidence'] as num).toDouble();
    final action     = pick['action'] as String;
    final symbol     = pick['symbol'] as String;
    final regime     = pick['market_regime'] as String? ?? '';
    final rsi        = pick['rsi'] as num?;
    final ticker     = symbol.split(':').last;
    final exchange   = symbol.split(':').first;

    return GestureDetector(
      onTap: () {
        final assets = ref.read(assetsProvider).value ?? [];
        final asset  = assets.where((a) => a.symbol == symbol).firstOrNull;
        if (asset != null) ref.read(selectedAssetProvider.notifier).select(asset);
        ref.read(activeTabProvider.notifier).state = 1;
      },
      child: Container(
        width: 200,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.green.withOpacity(0.4), width: 1.5),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(ticker, overflow: TextOverflow.ellipsis,
                        style: const TextStyle(color: AppColors.textPrimary,
                            fontWeight: FontWeight.w700, fontSize: 13)),
                    Text(exchange, style: const TextStyle(
                        color: AppColors.textMuted, fontSize: 9, fontWeight: FontWeight.w600)),
                  ]),
                ),
                SignalBadge(action: action, confidence: confidence / 100, small: true),
              ],
            ),
            const SizedBox(height: 6),
            Row(children: [
              Text(regime.toUpperCase(),
                  style: const TextStyle(color: AppColors.accent, fontSize: 9,
                      fontWeight: FontWeight.w800, letterSpacing: 0.6)),
              if (rsi != null) ...[
                const SizedBox(width: 8),
                Text('RSI ${rsi.toStringAsFixed(0)}',
                    style: const TextStyle(color: AppColors.textMuted, fontSize: 9)),
              ],
            ]),
            const SizedBox(height: 6),
            ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: LinearProgressIndicator(
                value: confidence / 100,
                backgroundColor: AppColors.elevated,
                valueColor: const AlwaysStoppedAnimation(AppColors.green),
                minHeight: 3,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PositionTile extends StatelessWidget {
  final Position position;
  const _PositionTile({required this.position});

  @override
  Widget build(BuildContext context) {
    final isProfit = position.unrealisedPnl >= 0;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.borderDef),
      ),
      child: Row(children: [
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(position.symbol, style: const TextStyle(
              color: AppColors.textPrimary, fontWeight: FontWeight.w700, fontSize: 13)),
          Text('${position.quantity} shares',
              style: const TextStyle(color: AppColors.textMuted, fontSize: 11)),
        ])),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text('${isProfit ? '+' : ''}${position.unrealisedPnl.toStringAsFixed(0)}',
              style: TextStyle(color: isProfit ? AppColors.green : AppColors.red,
                  fontWeight: FontWeight.w700, fontSize: 13, fontFamily: 'monospace')),
          Text('${position.pnlPct.toStringAsFixed(2)}%',
              style: TextStyle(color: isProfit ? AppColors.green : AppColors.red, fontSize: 10)),
        ]),
      ]),
    );
  }
}
