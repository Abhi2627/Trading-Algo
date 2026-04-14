// features/portfolio/portfolio_screen.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api/endpoints.dart';
import '../../core/models/wallet.dart';
import '../../shared/theme.dart';
import '../../shared/widgets/stat_card.dart';
import '../../shared/widgets/loading_state.dart';
import '../../main.dart' show dioProvider;
import '../dashboard/dashboard_screen.dart' show walletProvider;

final tradeHistoryProvider =
    FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final dio = await ref.watch(dioProvider.future);
  return Endpoints(dio).getTradeHistory();
});

class PortfolioScreen extends ConsumerStatefulWidget {
  const PortfolioScreen({super.key});
  @override
  ConsumerState<PortfolioScreen> createState() => _PortfolioScreenState();
}

class _PortfolioScreenState extends ConsumerState<PortfolioScreen> {
  String? _closingTradeId;

  Future<void> _closeTrade(String tradeId) async {
    setState(() => _closingTradeId = tradeId);
    try {
      final dio = await ref.read(dioProvider.future);
      await Endpoints(dio).closeTrade(tradeId);
      ref.invalidate(walletProvider);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Failed to close trade'),
              backgroundColor: AppColors.red),
        );
      }
    } finally {
      if (mounted) setState(() => _closingTradeId = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final walletAsync = ref.watch(walletProvider);

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(title: const Text('Portfolio')),
      body: walletAsync.when(
        loading: () => const LoadingState(),
        error:   (e, _) => ErrorState(
          message: 'Could not load portfolio.',
          onRetry: () => ref.invalidate(walletProvider),
        ),
        data: (wallet) => RefreshIndicator(
          color: AppColors.accent,
          backgroundColor: AppColors.surface,
          onRefresh: () async => ref.invalidate(walletProvider),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              // Stats
              Row(
                children: [
                  Expanded(child: StatCard(
                    label: 'Total Equity',
                    value: '\u20b9${wallet.totalEquity.toStringAsFixed(0)}',
                    icon: Icons.account_balance_wallet_outlined,
                  )),
                  const SizedBox(width: 10),
                  Expanded(child: StatCard(
                    label: 'Realised P&L',
                    value: '\u20b9${wallet.realisedPnl.toStringAsFixed(0)}',
                    trend: wallet.realisedPnl >= 0 ? 'up' : 'down',
                  )),
                ],
              ),
              const SizedBox(height: 10),
              StatCard(
                label: 'Unrealised P&L',
                value: '\u20b9${wallet.unrealisedPnl.toStringAsFixed(0)}',
                trend: wallet.unrealisedPnl >= 0 ? 'up' : 'down',
                icon: Icons.trending_flat_rounded,
              ),
              const SizedBox(height: 20),

              // Open positions
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text('Open Positions',
                      style: TextStyle(color: AppColors.textPrimary,
                          fontSize: 15, fontWeight: FontWeight.w700)),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: AppColors.elevated,
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(color: AppColors.borderDef),
                    ),
                    child: Text('${wallet.openCount} ACTIVE',
                        style: const TextStyle(
                          color: AppColors.textMuted, fontSize: 9, fontWeight: FontWeight.w800)),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              wallet.openPositions.isEmpty
                  ? const EmptyState(
                      message: 'No open positions.\nGenerate signals and execute trades.',
                      icon: Icons.inbox_outlined)
                  : Column(
                      children: wallet.openPositions
                          .map((p) => _PositionCard(
                                position: p,
                                closing: _closingTradeId == p.tradeId,
                                onClose: () => _closeTrade(p.tradeId),
                              ))
                          .toList(),
                    ),
              const SizedBox(height: 20),

              // Daily budget
              const Text('Daily Risk Budget',
                  style: TextStyle(color: AppColors.textPrimary,
                      fontSize: 15, fontWeight: FontWeight.w700)),
              const SizedBox(height: 10),
              _DailyBudgetCard(wallet: wallet),
              const SizedBox(height: 20),

              // Trade history
              const Text('Trade History',
                  style: TextStyle(color: AppColors.textPrimary,
                      fontSize: 15, fontWeight: FontWeight.w700)),
              const SizedBox(height: 10),
              Consumer(builder: (context, ref, _) {
                final historyAsync = ref.watch(tradeHistoryProvider);
                return historyAsync.when(
                  loading: () => const SizedBox(
                      height: 60, child: LoadingState()),
                  error:   (_, __) => const SizedBox(),
                  data: (trades) => trades.isEmpty
                      ? const EmptyState(
                          message: 'No closed trades yet.',
                          icon: Icons.history_rounded)
                      : Column(
                          children: trades
                              .map((t) => _HistoryTile(trade: t))
                              .toList(),
                        ),
                );
              }),
              const SizedBox(height: 80),
            ],
          ),
        ),
      ),
    );
  }
}

class _PositionCard extends StatelessWidget {
  final Position position;
  final bool closing;
  final VoidCallback onClose;
  const _PositionCard({
    required this.position,
    required this.closing,
    required this.onClose,
  });

  @override
  Widget build(BuildContext context) {
    final isProfit = position.unrealisedPnl >= 0;
    final pnlColor = isProfit ? AppColors.green : AppColors.red;

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.borderDef),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(position.symbol,
                          style: const TextStyle(
                            color: AppColors.textPrimary,
                            fontWeight: FontWeight.w700, fontSize: 14)),
                      Text(position.name,
                          style: const TextStyle(
                            color: AppColors.textMuted, fontSize: 11)),
                    ],
                  ),
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      '${isProfit ? '+' : ''}\u20b9${position.unrealisedPnl.toStringAsFixed(0)}',
                      style: TextStyle(color: pnlColor,
                          fontWeight: FontWeight.w800, fontSize: 15),
                    ),
                    Text('${position.pnlPct.toStringAsFixed(2)}%',
                        style: TextStyle(color: pnlColor, fontSize: 11)),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                _InfoChip('QTY', '${position.quantity}'),
                const SizedBox(width: 8),
                _InfoChip('ENTRY', '\u20b9${position.entryPrice.toStringAsFixed(0)}'),
                const SizedBox(width: 8),
                _InfoChip('CMP', '\u20b9${position.currentPrice.toStringAsFixed(0)}'),
                const Spacer(),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: position.tradeType == 'intraday'
                        ? AppColors.amber.withOpacity(0.1)
                        : AppColors.accent.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(position.tradeType.toUpperCase(),
                      style: TextStyle(
                        color: position.tradeType == 'intraday'
                            ? AppColors.amber : AppColors.accent,
                        fontSize: 9, fontWeight: FontWeight.w800,
                      )),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: Text(
                    'SL: \u20b9${position.stopLoss.toStringAsFixed(0)}  |  TP: \u20b9${position.takeProfit.toStringAsFixed(0)}',
                    style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
                  ),
                ),
                SizedBox(
                  height: 30,
                  child: ElevatedButton(
                    onPressed: closing ? null : onClose,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.red.withOpacity(0.15),
                      foregroundColor: AppColors.red,
                      elevation: 0,
                      padding: const EdgeInsets.symmetric(horizontal: 14),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(6),
                          side: BorderSide(color: AppColors.red.withOpacity(0.3))),
                    ),
                    child: closing
                        ? const SizedBox(width: 12, height: 12,
                            child: CircularProgressIndicator(
                                strokeWidth: 2, color: AppColors.red))
                        : const Text('Close',
                            style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

Widget _InfoChip(String label, String value) => Container(
  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
  decoration: BoxDecoration(
    color: AppColors.elevated,
    borderRadius: BorderRadius.circular(6),
    border: Border.all(color: AppColors.borderDef),
  ),
  child: Column(
    children: [
      Text(label, style: const TextStyle(
          color: AppColors.textMuted, fontSize: 8, fontWeight: FontWeight.w800)),
      Text(value, style: const TextStyle(
          color: AppColors.textPrimary, fontSize: 11, fontWeight: FontWeight.w700,
          fontFamily: 'monospace')),
    ],
  ),
);

class _DailyBudgetCard extends StatelessWidget {
  final WalletSummary wallet;
  const _DailyBudgetCard({required this.wallet});

  @override
  Widget build(BuildContext context) {
    final used  = wallet.dailyBudget.lossUsedToday;
    final limit = wallet.dailyBudget.lossLimit;
    final ratio = limit > 0 ? (used / limit).clamp(0.0, 1.0) : 0.0;
    final barColor = ratio > 0.8 ? AppColors.red
        : ratio > 0.5 ? AppColors.amber : AppColors.green;
    final modeColor = wallet.riskMode == 'normal' ? AppColors.green
        : wallet.riskMode == 'conservative' ? AppColors.amber : AppColors.red;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.borderDef),
      ),
      child: Column(
        children: [
          Row(
            children: [
              Expanded(child: _BudgetItem('Profit Target',
                  '\u20b9${wallet.dailyBudget.profitTarget.toStringAsFixed(0)}',
                  AppColors.green)),
              const SizedBox(width: 10),
              Expanded(child: _BudgetItem('Loss Limit',
                  '\u20b9${wallet.dailyBudget.lossLimit.toStringAsFixed(0)}',
                  AppColors.red)),
            ],
          ),
          const SizedBox(height: 14),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text('Loss Used Today',
                  style: TextStyle(color: AppColors.textSecondary, fontSize: 11)),
              Text(
                '\u20b9${used.toStringAsFixed(0)} / \u20b9${limit.toStringAsFixed(0)}',
                style: TextStyle(color: barColor, fontSize: 11, fontWeight: FontWeight.w700),
              ),
            ],
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value:            ratio,
              backgroundColor:  AppColors.elevated,
              valueColor:       AlwaysStoppedAnimation(barColor),
              minHeight:        8,
            ),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Container(
                width: 8, height: 8,
                decoration: BoxDecoration(
                    color: modeColor, shape: BoxShape.circle),
              ),
              const SizedBox(width: 8),
              Text('${wallet.riskMode.toUpperCase()} MODE',
                  style: TextStyle(
                    color: modeColor, fontSize: 11, fontWeight: FontWeight.w800)),
              const Spacer(),
              Text('Monthly topup: \u20b9${wallet.monthlyTopup.toStringAsFixed(0)}',
                  style: const TextStyle(
                    color: AppColors.textMuted, fontSize: 10)),
            ],
          ),
        ],
      ),
    );
  }
}

Widget _BudgetItem(String label, String value, Color color) => Column(
  crossAxisAlignment: CrossAxisAlignment.start,
  children: [
    Text(label, style: const TextStyle(
        color: AppColors.textMuted, fontSize: 10, fontWeight: FontWeight.w700)),
    const SizedBox(height: 2),
    Text(value, style: TextStyle(
        color: color, fontSize: 16, fontWeight: FontWeight.w800)),
  ],
);

class _HistoryTile extends StatelessWidget {
  final Map<String, dynamic> trade;
  const _HistoryTile({required this.trade});

  @override
  Widget build(BuildContext context) {
    final pnl     = (trade['realized_pnl'] as num).toDouble();
    final pnlPct  = (trade['pnl_pct']      as num).toDouble();
    final isProfit = pnl >= 0;
    final color   = isProfit ? AppColors.green : AppColors.red;
    final exitTime = trade['exit_time'] as String?;
    final dateStr  = exitTime != null
        ? DateTime.parse(exitTime).toLocal().toString().substring(0, 16)
        : 'N/A';

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.borderDef),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(trade['symbol'] as String,
                    style: const TextStyle(
                      color: AppColors.textPrimary,
                      fontWeight: FontWeight.w700, fontSize: 13)),
                Text('${trade['quantity']} shares  ·  $dateStr',
                    style: const TextStyle(
                      color: AppColors.textMuted, fontSize: 10)),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text('${isProfit ? '+' : ''}₹${pnl.toStringAsFixed(0)}',
                  style: TextStyle(
                    color: color, fontWeight: FontWeight.w700, fontSize: 13)),
              Text('${pnlPct.toStringAsFixed(2)}%',
                  style: TextStyle(color: color, fontSize: 10)),
            ],
          ),
        ],
      ),
    );
  }
}
