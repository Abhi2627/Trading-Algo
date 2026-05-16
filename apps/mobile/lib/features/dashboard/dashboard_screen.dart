// features/dashboard/dashboard_screen.dart
import 'dart:async';
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

final marketStatusProvider = FutureProvider<Map<String, dynamic>>((ref) async {
  final dio = await ref.watch(dioProvider.future);
  return Endpoints(dio).getMarketStatus();
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

class DashboardScreen extends ConsumerStatefulWidget {
  const DashboardScreen({super.key});

  @override
  ConsumerState<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends ConsumerState<DashboardScreen> {
  Timer? _walletTimer;
  Timer? _signalsTimer;

  @override
  void initState() {
    super.initState();
    // Refresh wallet every 15 seconds
    _walletTimer = Timer.periodic(const Duration(seconds: 15), (_) {
      ref.invalidate(walletProvider);
      ref.invalidate(marketStatusProvider);
    });
    // Refresh signals every 60 seconds
    _signalsTimer = Timer.periodic(const Duration(seconds: 60), (_) {
      ref.invalidate(dashboardSignalsProvider);
    });
  }

  @override
  void dispose() {
    _walletTimer?.cancel();
    _signalsTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
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
          ref.invalidate(marketStatusProvider);
        },
        child: walletAsync.when(
          loading: () => const LoadingState(),
          error: (e, _) => ErrorState(
            message: 'Could not load wallet.\nMake sure the backend is running.',
            onRetry: () {
              ref.invalidate(walletProvider);
              ref.invalidate(dashboardSignalsProvider);
              ref.invalidate(marketStatusProvider);
            },
          ),
          data: (wallet) {
            final marketAsync = ref.watch(marketStatusProvider);
            return ListView(
              padding: const EdgeInsets.all(16),
              children: [
                // Market Status Banner
                marketAsync.maybeWhen(
                  data: (status) {
                    final isOpen = status['is_open'] as bool? ?? true;
                    if (isOpen) return const SizedBox.shrink();
                    return Container(
                      margin: const EdgeInsets.only(bottom: 16),
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                      decoration: BoxDecoration(
                        color: AppColors.amber.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: AppColors.amber.withOpacity(0.4)),
                      ),
                      child: Row(children: [
                        const Icon(Icons.warning_amber_rounded,
                            color: AppColors.amber, size: 16),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Market Closed — ${status['reason'] ?? ''}',
                                style: const TextStyle(
                                  color: AppColors.amber,
                                  fontSize: 12, fontWeight: FontWeight.w700),
                              ),
                              if (status['next_open'] != null)
                                Text(
                                  'Opens: ${status['next_open']}',
                                  style: const TextStyle(
                                    color: AppColors.textMuted, fontSize: 10),
                                ),
                            ],
                          ),
                        ),
                      ]),
                    );
                  },
                  orElse: () => const SizedBox.shrink(),
                ),
              _PortfolioSummaryCard(wallet: wallet),
              const SizedBox(height: 16),
              if (wallet.cashBalance < 2000)
                Container(
                  margin: const EdgeInsets.only(bottom: 16),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: wallet.cashBalance < 500
                        ? AppColors.red.withOpacity(0.1)
                        : AppColors.amber.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: wallet.cashBalance < 500
                          ? AppColors.red.withOpacity(0.4)
                          : AppColors.amber.withOpacity(0.4),
                    ),
                  ),
                  child: Row(children: [
                    Icon(
                      wallet.cashBalance < 500
                          ? Icons.error_outline
                          : Icons.warning_amber_rounded,
                      color: wallet.cashBalance < 500
                          ? AppColors.red
                          : AppColors.amber,
                      size: 16,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        wallet.cashBalance < 500
                            ? 'Trading stopped — add at least \u20b92,000 to resume'
                            : 'Low balance — add \u20b9${(2000 - wallet.cashBalance).toStringAsFixed(0)} to continue trading',
                        style: TextStyle(
                          color: wallet.cashBalance < 500
                              ? AppColors.red
                              : AppColors.amber,
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ]),
                ),
              // Add Funds button
              _AddFundsSection(ref: ref),
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
          );
          },
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

class _AddFundsSection extends StatefulWidget {
  final WidgetRef ref;
  const _AddFundsSection({required this.ref});

  @override
  State<_AddFundsSection> createState() => _AddFundsSectionState();
}

class _AddFundsSectionState extends State<_AddFundsSection> {
  final _controller = TextEditingController();
  bool _loading = false;
  String? _error;
  bool _success = false;

  Future<void> _addFunds(double amount) async {
    if (amount <= 0) {
      setState(() => _error = 'Amount must be greater than 0');
      return;
    }
    setState(() { _loading = true; _error = null; _success = false; });
    try {
      final dio = await widget.ref.read(dioProvider.future);
      await dio.post('/wallet/add-funds', data: {
        'amount': amount,
        'reason': 'manual topup from mobile',
      });
      widget.ref.invalidate(walletProvider);
      setState(() { _success = true; _loading = false; });
      _controller.clear();
      await Future.delayed(const Duration(seconds: 2));
      if (mounted) setState(() => _success = false);
    } catch (e) {
      setState(() { _error = 'Failed to add funds'; _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.accent.withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(children: [
            Icon(Icons.add_circle_outline, color: AppColors.accent, size: 16),
            SizedBox(width: 6),
            Text('Add Paper Money',
                style: TextStyle(color: AppColors.textPrimary,
                    fontSize: 13, fontWeight: FontWeight.w700)),
          ]),
          const SizedBox(height: 10),
          // Quick amount buttons
          Row(children: [500, 1000, 2000].map((amt) =>
            Expanded(
              child: GestureDetector(
                onTap: () => _controller.text = amt.toString(),
                child: Container(
                  margin: const EdgeInsets.only(right: 6),
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  decoration: BoxDecoration(
                    color: AppColors.elevated,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: AppColors.borderDef),
                  ),
                  child: Text('₹$amt',
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                          color: AppColors.textPrimary,
                          fontSize: 11, fontWeight: FontWeight.w700)),
                ),
              ),
            ),
          ).toList()),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(
              child: TextField(
                controller: _controller,
                keyboardType: TextInputType.number,
                style: const TextStyle(color: AppColors.textPrimary, fontSize: 13),
                decoration: InputDecoration(
                  hintText: 'Custom amount',
                  hintStyle: const TextStyle(color: AppColors.textMuted, fontSize: 12),
                  prefixText: '₹ ',
                  prefixStyle: const TextStyle(color: AppColors.textMuted),
                  filled: true,
                  fillColor: AppColors.elevated,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: const BorderSide(color: AppColors.borderDef),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: const BorderSide(color: AppColors.borderDef),
                  ),
                  contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                ),
              ),
            ),
            const SizedBox(width: 8),
            ElevatedButton(
              onPressed: _loading ? null : () {
                final amt = double.tryParse(_controller.text) ?? 0;
                _addFunds(amt);
              },
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.accent,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
              ),
              child: _loading
                  ? const SizedBox(width: 16, height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Text('Add', style: TextStyle(fontWeight: FontWeight.w700)),
            ),
          ]),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(_error!,
                  style: const TextStyle(color: AppColors.red, fontSize: 11)),
            ),
          if (_success)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text('✅ Funds added successfully',
                  style: TextStyle(color: AppColors.green, fontSize: 11)),
            ),
        ],
      ),
    );
  }
}

class _PositionTile extends StatelessWidget {
  final Position position;
  const _PositionTile({required this.position});

  @override
  Widget build(BuildContext context) {
    final isProfit  = position.unrealisedPnl >= 0;
    final color     = isProfit ? AppColors.green : AppColors.red;
    final invested  = position.entryPrice * position.quantity;
    final current   = position.currentPrice * position.quantity;
    final ticker    = position.symbol.contains(':') ? position.symbol.split(':').last : position.symbol;

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        // Top row: symbol + P&L
        Row(children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(ticker, style: const TextStyle(
                color: AppColors.textPrimary, fontWeight: FontWeight.w700, fontSize: 14)),
            Text('${position.quantity} shares · ${position.tradeType}',
                style: const TextStyle(color: AppColors.textMuted, fontSize: 11)),
          ])),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text('${isProfit ? '+' : ''}₹${position.unrealisedPnl.toStringAsFixed(2)}',
                style: TextStyle(color: color, fontWeight: FontWeight.w900,
                    fontSize: 15, fontFamily: 'monospace')),
            Text('${isProfit ? '+' : ''}${position.pnlPct.toStringAsFixed(2)}%',
                style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700)),
          ]),
        ]),
        const SizedBox(height: 8),
        // Bottom row: invested → current value
        Row(children: [
          Text('Invested ', style: const TextStyle(color: AppColors.textMuted, fontSize: 10)),
          Text(_inr(invested), style: const TextStyle(
              color: AppColors.textSecondary, fontSize: 11, fontFamily: 'monospace')),
          const SizedBox(width: 6),
          const Icon(Icons.arrow_forward_rounded, size: 10, color: AppColors.textMuted),
          const SizedBox(width: 6),
          Text('Current ', style: const TextStyle(color: AppColors.textMuted, fontSize: 10)),
          Text(_inr(current), style: const TextStyle(
              color: AppColors.textPrimary, fontSize: 11,
              fontFamily: 'monospace', fontWeight: FontWeight.w700)),
          const Spacer(),
          Text('SL ₹${position.stopLoss.toStringAsFixed(0)}',
              style: const TextStyle(color: AppColors.textMuted, fontSize: 9)),
          const SizedBox(width: 8),
          Text('TP ₹${position.takeProfit.toStringAsFixed(0)}',
              style: const TextStyle(color: AppColors.textMuted, fontSize: 9)),
        ]),
      ]),
    );
  }
}


class _PortfolioSummaryCard extends StatelessWidget {
  final WalletSummary wallet;
  const _PortfolioSummaryCard({required this.wallet});

  @override
  Widget build(BuildContext context) {
    final totalPnl  = wallet.unrealisedPnl + wallet.realisedPnl;
    final invested  = wallet.investedBalance;
    final current   = invested + wallet.unrealisedPnl;
    final totalPct  = invested > 0 ? (totalPnl / invested) * 100 : 0.0;
    final isUp      = totalPnl >= 0;
    final pnlColor  = isUp ? AppColors.green : AppColors.red;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.borderDef),
      ),
      child: Column(children: [
        // Invested → Current
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('INVESTED', style: TextStyle(color: AppColors.textMuted,
                fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.8)),
            const SizedBox(height: 2),
            Text(_inr(invested), style: const TextStyle(color: AppColors.textPrimary,
                fontSize: 22, fontWeight: FontWeight.w900, fontFamily: 'monospace')),
          ]),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            const Text('CURRENT VALUE', style: TextStyle(color: AppColors.textMuted,
                fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.8)),
            const SizedBox(height: 2),
            Text(_inr(current), style: const TextStyle(color: AppColors.textPrimary,
                fontSize: 22, fontWeight: FontWeight.w900, fontFamily: 'monospace')),
          ]),
        ]),
        const SizedBox(height: 12),
        // P&L hero
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            color: pnlColor.withOpacity(0.08),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: pnlColor.withOpacity(0.25)),
          ),
          child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            Row(children: [
              Container(width: 32, height: 32,
                decoration: BoxDecoration(
                    color: pnlColor.withOpacity(0.15), shape: BoxShape.circle),
                child: Icon(isUp ? Icons.trending_up_rounded : Icons.trending_down_rounded,
                    color: pnlColor, size: 16)),
              const SizedBox(width: 10),
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('TOTAL P&L', style: TextStyle(color: AppColors.textMuted,
                    fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.8)),
                Text('${isUp ? '+' : ''}₹${totalPnl.abs().toStringAsFixed(2)}',
                    style: TextStyle(color: pnlColor, fontSize: 18,
                        fontWeight: FontWeight.w900, fontFamily: 'monospace')),
              ]),
            ]),
            Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text('${isUp ? '+' : ''}${totalPct.toStringAsFixed(2)}%',
                  style: TextStyle(color: pnlColor, fontSize: 22,
                      fontWeight: FontWeight.w900, fontFamily: 'monospace')),
              const Text('overall return', style: TextStyle(
                  color: AppColors.textMuted, fontSize: 9)),
            ]),
          ]),
        ),
        const SizedBox(height: 12),
        // Pills row
        Row(children: [
          _Pill(label: 'Unrealised', value: wallet.unrealisedPnl, signed: true),
          const SizedBox(width: 8),
          _Pill(label: 'Realised', value: wallet.realisedPnl, signed: true),
          const SizedBox(width: 8),
          _Pill(label: 'Cash', value: wallet.cashBalance, signed: false, neutral: true),
        ]),
        const SizedBox(height: 12),
        // Risk mode + equity footer
        Divider(color: AppColors.borderDef, height: 1),
        const SizedBox(height: 10),
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Row(children: [
            Container(width: 7, height: 7,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: wallet.riskMode == 'normal' ? AppColors.green
                    : wallet.riskMode == 'conservative' ? AppColors.amber : AppColors.red,
              )),
            const SizedBox(width: 6),
            Text(wallet.riskMode.toUpperCase(),
                style: TextStyle(
                  color: wallet.riskMode == 'normal' ? AppColors.green
                      : wallet.riskMode == 'conservative' ? AppColors.amber : AppColors.red,
                  fontSize: 10, fontWeight: FontWeight.w800, letterSpacing: 0.8)),
          ]),
          Text('Equity ${_inr(wallet.totalEquity)} · Peak ${_inr(wallet.peakEquity)}',
              style: const TextStyle(color: AppColors.textMuted, fontSize: 10)),
        ]),
      ]),
    );
  }
}

class _Pill extends StatelessWidget {
  final String label;
  final double value;
  final bool signed;
  final bool neutral;
  const _Pill({required this.label, required this.value,
      required this.signed, this.neutral = false});

  @override
  Widget build(BuildContext context) {
    final isUp  = value >= 0;
    final color = neutral ? AppColors.accent
        : isUp ? AppColors.green : AppColors.red;
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 8),
        decoration: BoxDecoration(
          color: AppColors.elevated,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(children: [
          Text(label, style: const TextStyle(color: AppColors.textMuted,
              fontSize: 9, fontWeight: FontWeight.w700, letterSpacing: 0.6)),
          const SizedBox(height: 3),
          Text('${signed && isUp ? '+' : ''}${_inr(value)}',
              style: TextStyle(color: color, fontSize: 12,
                  fontWeight: FontWeight.w800, fontFamily: 'monospace')),
        ]),
      ),
    );
  }
}
