// features/analytics/analytics_screen.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../shared/widgets/loading_state.dart';
import '../../main.dart' show dioProvider;
import '../../shared/theme.dart';

class AnalyticsData {
  final int totalTrades, winCount, lossCount;
  final double winRate, avgPnlPct, avgWinPct, avgLossPct, profitFactor, avgDaysHeld;
  final _TradeSummary? bestTrade, worstTrade;
  final Map<String, _BreakdownItem> byExitReason;
  final Map<String, _RegimeItem> byRegime;
  final Map<String, _ConfItem> byConfidence;
  final List<_EquityPoint> equityCurve;

  const AnalyticsData({
    required this.totalTrades, required this.winCount, required this.lossCount,
    required this.winRate, required this.avgPnlPct, required this.avgWinPct,
    required this.avgLossPct, required this.profitFactor, required this.avgDaysHeld,
    this.bestTrade, this.worstTrade,
    required this.byExitReason, required this.byRegime,
    required this.byConfidence, required this.equityCurve,
  });

  factory AnalyticsData.fromJson(Map<String, dynamic> j) => AnalyticsData(
    totalTrades:  j['total_trades']   as int,
    winCount:     j['win_count']      as int,
    lossCount:    j['loss_count']     as int,
    winRate:      (j['win_rate']      as num).toDouble(),
    avgPnlPct:    (j['avg_pnl_pct']   as num).toDouble(),
    avgWinPct:    (j['avg_win_pct']   as num).toDouble(),
    avgLossPct:   (j['avg_loss_pct']  as num).toDouble(),
    profitFactor: (j['profit_factor'] as num).toDouble(),
    avgDaysHeld:  (j['avg_days_held'] as num).toDouble(),
    bestTrade:  j['best_trade']  != null ? _TradeSummary.fromJson(j['best_trade'])  : null,
    worstTrade: j['worst_trade'] != null ? _TradeSummary.fromJson(j['worst_trade']) : null,
    byExitReason: (j['by_exit_reason'] as Map<String, dynamic>).map(
        (k, v) => MapEntry(k, _BreakdownItem.fromJson(v as Map<String, dynamic>))),
    byRegime: (j['by_regime'] as Map<String, dynamic>).map(
        (k, v) => MapEntry(k, _RegimeItem.fromJson(v as Map<String, dynamic>))),
    byConfidence: (j['by_confidence'] as Map<String, dynamic>).map(
        (k, v) => MapEntry(k, _ConfItem.fromJson(v as Map<String, dynamic>))),
    equityCurve: (j['equity_curve'] as List)
        .map((e) => _EquityPoint.fromJson(e as Map<String, dynamic>)).toList(),
  );
}

class _TradeSummary {
  final String symbol; final double pnlPct;
  final String? exitReason; final double? daysHeld;
  _TradeSummary({required this.symbol, required this.pnlPct, this.exitReason, this.daysHeld});
  factory _TradeSummary.fromJson(Map<String, dynamic> j) => _TradeSummary(
    symbol: j['symbol'] as String, pnlPct: (j['pnl_pct'] as num).toDouble(),
    exitReason: j['exit_reason'] as String?,
    daysHeld: j['days_held'] != null ? (j['days_held'] as num).toDouble() : null);
}

class _BreakdownItem {
  final int count, wins; final double winRate, avgPnlPct;
  _BreakdownItem({required this.count, required this.wins, required this.winRate, required this.avgPnlPct});
  factory _BreakdownItem.fromJson(Map<String, dynamic> j) => _BreakdownItem(
    count: j['count'] as int, wins: j['wins'] as int,
    winRate: (j['win_rate'] as num).toDouble(), avgPnlPct: (j['avg_pnl_pct'] as num).toDouble());
}

class _RegimeItem {
  final int count, wins; final double winRate;
  _RegimeItem({required this.count, required this.wins, required this.winRate});
  factory _RegimeItem.fromJson(Map<String, dynamic> j) => _RegimeItem(
    count: j['count'] as int, wins: j['wins'] as int,
    winRate: (j['win_rate'] as num).toDouble());
}

class _ConfItem {
  final int count; final double winRate, avgPnlPct;
  _ConfItem({required this.count, required this.winRate, required this.avgPnlPct});
  factory _ConfItem.fromJson(Map<String, dynamic> j) => _ConfItem(
    count: j['count'] as int, winRate: (j['win_rate'] as num).toDouble(),
    avgPnlPct: (j['avg_pnl_pct'] as num).toDouble());
}

class _EquityPoint {
  final String date; final double cumulativePnl, pnl;
  _EquityPoint({required this.date, required this.cumulativePnl, required this.pnl});
  factory _EquityPoint.fromJson(Map<String, dynamic> j) => _EquityPoint(
    date: j['date'] as String,
    cumulativePnl: (j['cumulative_pnl'] as num).toDouble(),
    pnl: (j['pnl'] as num).toDouble());
}

final analyticsProvider = FutureProvider.autoDispose<AnalyticsData>((ref) async {
  final dio = await ref.watch(dioProvider.future);
  final resp = await dio.get('/wallet/analytics');
  return AnalyticsData.fromJson(resp.data as Map<String, dynamic>);
});

class AnalyticsScreen extends ConsumerWidget {
  const AnalyticsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(analyticsProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Signal Analytics'),
        actions: [IconButton(
          icon: const Icon(Icons.refresh_rounded),
          onPressed: () => ref.invalidate(analyticsProvider))],
      ),
      body: state.when(
        loading: () => const LoadingState(),
        error: (e, _) => ErrorState(
          message: 'Failed to load analytics',
          onRetry: () => ref.invalidate(analyticsProvider),
        ),
        data: (d) => d.totalTrades == 0 ? const _EmptyState() : _AnalyticsBody(data: d),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();
  @override
  Widget build(BuildContext context) => Center(child: Padding(
    padding: const EdgeInsets.all(32),
    child: Column(mainAxisSize: MainAxisSize.min, children: [
      Icon(Icons.bar_chart_rounded, size: 64, color: AppColors.textMuted.withOpacity(0.4)),
      const SizedBox(height: 16),
      const Text('No closed trades yet', style: TextStyle(
          color: AppColors.textPrimary, fontWeight: FontWeight.w700, fontSize: 16)),
      const SizedBox(height: 8),
      const Text('Analytics populate after trades close via SL, TP, or time exit.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AppColors.textMuted, fontSize: 13)),
    ]),
  ));
}

class _AnalyticsBody extends StatelessWidget {
  final AnalyticsData data;
  const _AnalyticsBody({required this.data});
  int _max(Iterable<int> vals) => vals.isEmpty ? 1 : vals.reduce((a, b) => a > b ? a : b);

  @override
  Widget build(BuildContext context) {
    final exitMax = _max(data.byExitReason.values.map((v) => v.count));
    final regMax  = _max(data.byRegime.values.map((v) => v.count));
    final confMax = _max(data.byConfidence.values.map((v) => v.count));
    return ListView(padding: const EdgeInsets.all(16), children: [
      const _H('Overview'), const SizedBox(height: 8),
      GridView.count(crossAxisCount: 2, crossAxisSpacing: 10, mainAxisSpacing: 10,
        childAspectRatio: 1.6, shrinkWrap: true, physics: const NeverScrollableScrollPhysics(),
        children: [
          _KpiCard(label: 'Win Rate', value: '${data.winRate.toStringAsFixed(1)}%',
            sub: '${data.winCount}W \u00b7 ${data.lossCount}L',
            color: data.winRate >= 50 ? AppColors.green : AppColors.red),
          _KpiCard(label: 'Profit Factor',
            value: data.profitFactor >= 999 ? '\u221e' : data.profitFactor.toStringAsFixed(2),
            sub: 'wins \u00f7 losses',
            color: data.profitFactor >= 1.5 ? AppColors.green
                : data.profitFactor >= 1 ? AppColors.amber : AppColors.red),
          _KpiCard(label: 'Avg P&L', value: _pct(data.avgPnlPct),
            sub: 'W: ${_pct(data.avgWinPct)}  L: ${_pct(data.avgLossPct)}',
            color: data.avgPnlPct >= 0 ? AppColors.green : AppColors.red),
          _KpiCard(label: 'Avg Hold', value: '${data.avgDaysHeld.toStringAsFixed(1)}d',
            sub: '${data.totalTrades} trades total', color: AppColors.textPrimary),
        ]),
      const SizedBox(height: 20),
      const _H('Equity Curve'), const SizedBox(height: 8),
      _EquityCurveCard(points: data.equityCurve),
      const SizedBox(height: 14),
      _WinRateBar(winRate: data.winRate),
      if (data.bestTrade != null || data.worstTrade != null) ...[
        const SizedBox(height: 20), const _H('Highlights'), const SizedBox(height: 8),
        if (data.bestTrade != null) _TradeHighlight(trade: data.bestTrade!, isBest: true),
        if (data.worstTrade != null) ...[const SizedBox(height: 8),
          _TradeHighlight(trade: data.worstTrade!, isBest: false)],
      ],
      const SizedBox(height: 20), const _H('Exit Reason'), const SizedBox(height: 8),
      ...data.byExitReason.entries.map((e) => _BarRow(
          label: e.key.replaceAll('_', ' '), count: e.value.count,
          maxCount: exitMax, winRate: e.value.winRate, avgPnl: e.value.avgPnlPct)),
      const SizedBox(height: 20), const _H('Market Regime'), const SizedBox(height: 8),
      ...data.byRegime.entries.map((e) => _BarRow(
          label: e.key, count: e.value.count, maxCount: regMax, winRate: e.value.winRate)),
      const SizedBox(height: 20), const _H('Confidence Bucket'), const SizedBox(height: 8),
      ...data.byConfidence.entries.map((e) => _BarRow(
          label: e.key, count: e.value.count, maxCount: confMax,
          winRate: e.value.winRate, avgPnl: e.value.avgPnlPct)),
      const SizedBox(height: 8),
      const Text('Higher confidence \u2192 higher win rate. If not, model needs calibration.',
          style: TextStyle(color: AppColors.textMuted, fontSize: 11)),
      const SizedBox(height: 32),
    ]);
  }
}

String _pct(double v, {int d = 1}) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}%';

class _H extends StatelessWidget {
  final String t; const _H(this.t);
  @override Widget build(BuildContext context) => Text(t, style: const TextStyle(
      color: AppColors.textPrimary, fontWeight: FontWeight.w700, fontSize: 13, letterSpacing: 0.5));
}

class _KpiCard extends StatelessWidget {
  final String label, value; final String? sub; final Color color;
  const _KpiCard({required this.label, required this.value, this.sub, required this.color});
  @override Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.borderDef)),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label, style: const TextStyle(color: AppColors.textMuted, fontSize: 10,
          fontWeight: FontWeight.w700, letterSpacing: 0.8)),
      const SizedBox(height: 4),
      Text(value, style: TextStyle(color: color, fontSize: 22,
          fontWeight: FontWeight.w900, fontFamily: 'monospace')),
      if (sub != null) Text(sub!, maxLines: 1, overflow: TextOverflow.ellipsis,
          style: const TextStyle(color: AppColors.textMuted, fontSize: 10)),
    ]));
}

class _EquityCurveCard extends StatelessWidget {
  final List<_EquityPoint> points;
  const _EquityCurveCard({required this.points});
  @override Widget build(BuildContext context) {
    if (points.isEmpty) return Container(height: 80, alignment: Alignment.center,
      decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.borderDef)),
      child: const Text('No data yet', style: TextStyle(color: AppColors.textMuted, fontSize: 12)));
    final last = points.last; final isPos = last.cumulativePnl >= 0;
    return Container(padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.borderDef)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text(points.first.date, style: const TextStyle(color: AppColors.textMuted, fontSize: 10)),
          Text('${isPos ? '+' : ''}\u20b9${last.cumulativePnl.toStringAsFixed(2)}',
              style: TextStyle(color: isPos ? AppColors.green : AppColors.red,
                  fontWeight: FontWeight.w900, fontFamily: 'monospace', fontSize: 13)),
          Text(last.date, style: const TextStyle(color: AppColors.textMuted, fontSize: 10)),
        ]),
        const SizedBox(height: 10),
        SizedBox(height: 70, child: CustomPaint(size: const Size(double.infinity, 70),
            painter: _CurvePainter(points: points, positive: isPos))),
      ]));
  }
}

class _CurvePainter extends CustomPainter {
  final List<_EquityPoint> points; final bool positive;
  const _CurvePainter({required this.points, required this.positive});
  @override void paint(Canvas canvas, Size size) {
    if (points.length < 2) return;
    final color = positive ? AppColors.green : AppColors.red;
    final vals = points.map((p) => p.cumulativePnl).toList();
    final minV = vals.reduce((a, b) => a < b ? a : b);
    final maxV = vals.reduce((a, b) => a > b ? a : b);
    final range = (maxV - minV).abs().clamp(0.001, double.infinity);
    double toX(int i) => i / (points.length - 1) * size.width;
    double toY(double v) => size.height - ((v - minV) / range * size.height * 0.85 + size.height * 0.05);
    final path = Path()..moveTo(toX(0), toY(vals[0]));
    for (var i = 1; i < vals.length; i++) path.lineTo(toX(i), toY(vals[i]));
    canvas.drawPath(Path.from(path)..lineTo(toX(points.length-1), size.height)..lineTo(0, size.height)..close(),
      Paint()..shader = LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter,
          colors: [color.withOpacity(0.25), color.withOpacity(0.02)])
          .createShader(Rect.fromLTWH(0, 0, size.width, size.height)));
    canvas.drawPath(path, Paint()..color = color..strokeWidth = 1.5
        ..style = PaintingStyle.stroke..strokeJoin = StrokeJoin.round);
    canvas.drawCircle(Offset(toX(points.length-1), toY(vals.last)), 3, Paint()..color = color);
  }
  @override bool shouldRepaint(_CurvePainter old) => old.points != points;
}

class _WinRateBar extends StatelessWidget {
  final double winRate; const _WinRateBar({required this.winRate});
  @override Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.borderDef)),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        const Text('Win Rate vs Target', style: TextStyle(
            color: AppColors.textPrimary, fontWeight: FontWeight.w700, fontSize: 13)),
        Text(winRate >= 55 ? '\u2705 On track' : '\u26a0 Below threshold',
            style: TextStyle(color: winRate >= 55 ? AppColors.green : AppColors.amber,
                fontSize: 11, fontWeight: FontWeight.w600)),
      ]),
      const SizedBox(height: 10),
      ClipRRect(borderRadius: BorderRadius.circular(4),
        child: LinearProgressIndicator(value: (winRate / 100).clamp(0.0, 1.0), minHeight: 8,
            backgroundColor: AppColors.elevated,
            valueColor: AlwaysStoppedAnimation(winRate >= 55 ? AppColors.green : AppColors.amber))),
      const SizedBox(height: 6),
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text('${winRate.toStringAsFixed(1)}% current',
            style: const TextStyle(color: AppColors.textMuted, fontSize: 10)),
        const Text('55% target (Zerodha live)',
            style: TextStyle(color: AppColors.textMuted, fontSize: 10)),
      ]),
    ]));
}

class _TradeHighlight extends StatelessWidget {
  final _TradeSummary trade; final bool isBest;
  const _TradeHighlight({required this.trade, required this.isBest});
  @override Widget build(BuildContext context) {
    final color = isBest ? AppColors.green : AppColors.red;
    final ticker = trade.symbol.contains(':') ? trade.symbol.split(':').last : trade.symbol;
    return Container(padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: color.withOpacity(0.06),
          borderRadius: BorderRadius.circular(12), border: Border.all(color: color.withOpacity(0.25))),
      child: Row(children: [
        Container(width: 36, height: 36,
          decoration: BoxDecoration(color: color.withOpacity(0.15), borderRadius: BorderRadius.circular(8)),
          child: Icon(isBest ? Icons.emoji_events_rounded : Icons.trending_down_rounded, color: color, size: 18)),
        const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(isBest ? 'BEST TRADE' : 'WORST TRADE',
              style: TextStyle(color: color, fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.8)),
          Text(ticker, style: const TextStyle(color: AppColors.textPrimary, fontWeight: FontWeight.w700, fontSize: 14)),
          Text([
            if (trade.exitReason != null) trade.exitReason!.replaceAll('_', ' '),
            if (trade.daysHeld != null) '${trade.daysHeld!.toStringAsFixed(1)}d held',
          ].join(' \u00b7 '), style: const TextStyle(color: AppColors.textMuted, fontSize: 11)),
        ])),
        Text(_pct(trade.pnlPct), style: TextStyle(color: color,
            fontWeight: FontWeight.w900, fontSize: 16, fontFamily: 'monospace')),
      ]));
  }
}

class _BarRow extends StatelessWidget {
  final String label; final int count, maxCount; final double winRate; final double? avgPnl;
  const _BarRow({required this.label, required this.count, required this.maxCount,
      required this.winRate, this.avgPnl});
  @override Widget build(BuildContext context) {
    final frac = maxCount > 0 ? count / maxCount : 0.0;
    final isPos = (avgPnl ?? 0) >= 0;
    return Padding(padding: const EdgeInsets.only(bottom: 8),
      child: Row(children: [
        SizedBox(width: 90, child: Text(label.length > 12 ? '${label.substring(0, 11)}\u2026' : label,
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 10, fontFamily: 'monospace'),
            textAlign: TextAlign.right)),
        const SizedBox(width: 8),
        Expanded(child: ClipRRect(borderRadius: BorderRadius.circular(3),
          child: LinearProgressIndicator(value: frac.clamp(0.04, 1.0), minHeight: 6,
              backgroundColor: AppColors.elevated,
              valueColor: AlwaysStoppedAnimation(isPos ? AppColors.green : AppColors.red)))),
        const SizedBox(width: 6),
        SizedBox(width: 24, child: Text('$count', textAlign: TextAlign.right,
            style: const TextStyle(color: AppColors.textMuted, fontSize: 10, fontFamily: 'monospace'))),
        SizedBox(width: 36, child: Text('${winRate.toStringAsFixed(0)}%', textAlign: TextAlign.right,
            style: TextStyle(color: winRate >= 50 ? AppColors.green : AppColors.red,
                fontSize: 10, fontWeight: FontWeight.w700, fontFamily: 'monospace'))),
        if (avgPnl != null)
          SizedBox(width: 44, child: Text(_pct(avgPnl!), textAlign: TextAlign.right,
              style: TextStyle(color: isPos ? AppColors.green : AppColors.red,
                  fontSize: 10, fontFamily: 'monospace'))),
      ]));
  }
}
