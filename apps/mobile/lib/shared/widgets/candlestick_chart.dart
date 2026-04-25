// shared/widgets/candlestick_chart.dart
// Custom candlestick chart using Flutter's CustomPainter
// No external charting lib needed — draws directly on canvas
import 'package:flutter/material.dart';
import '../../core/api/endpoints.dart';
import '../../main.dart' show dioProvider;
import 'package:flutter_riverpod/flutter_riverpod.dart';

// Provider for OHLCV data per symbol+days
final ohlcvProvider = FutureProvider.family<List<Map<String, dynamic>>, (String, int)>(
  (ref, args) async {
    final (symbol, days) = args;
    final dio = await ref.watch(dioProvider.future);
    return Endpoints(dio).getOHLCV(symbol, days: days);
  },
);

class CandlestickChart extends ConsumerStatefulWidget {
  final String symbol;
  final double? entryPrice;
  final double? stopLoss;
  final double? takeProfit;

  const CandlestickChart({
    super.key,
    required this.symbol,
    this.entryPrice,
    this.stopLoss,
    this.takeProfit,
  });

  @override
  ConsumerState<CandlestickChart> createState() => _CandlestickChartState();
}

class _CandlestickChartState extends ConsumerState<CandlestickChart> {
  int _days = 90;
  int? _hoverIndex;
  Offset? _hoverOffset;

  static const _periods = [
    ('1M', 30), ('3M', 90), ('6M', 180), ('1Y', 365)
  ];

  @override
  Widget build(BuildContext context) {
    final ohlcvAsync = ref.watch(ohlcvProvider((widget.symbol, _days)));

    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF111118),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withOpacity(0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          _buildHeader(ohlcvAsync),
          // Chart
          ohlcvAsync.when(
            loading: () => const SizedBox(
              height: 220,
              child: Center(
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Color(0xFF7C3AED),
                ),
              ),
            ),
            error: (_, __) => const SizedBox(
              height: 220,
              child: Center(
                child: Text('Chart unavailable',
                    style: TextStyle(color: Colors.white38, fontSize: 12)),
              ),
            ),
            data: (candles) => _buildChart(candles),
          ),
        ],
      ),
    );
  }

  Widget _buildHeader(AsyncValue<List<Map<String, dynamic>>> ohlcvAsync) {
    final candles = ohlcvAsync.value ?? [];
    final latest = candles.isNotEmpty ? candles.last : null;
    final prev   = candles.length >= 2 ? candles[candles.length - 2] : null;
    final change = latest != null && prev != null
        ? (latest['close'] as num).toDouble() - (prev['close'] as num).toDouble()
        : 0.0;
    final changePct = prev != null
        ? change / (prev['close'] as num).toDouble() * 100
        : 0.0;
    final isUp = change >= 0;

    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 12, 12, 8),
      child: Row(
        children: [
          // Price info
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.symbol.split(':').last,
                  style: const TextStyle(
                    color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700),
                ),
                if (latest != null)
                  Row(children: [
                    Text(
                      '\u20b9${(latest['close'] as num).toStringAsFixed(2)}',
                      style: const TextStyle(
                        color: Colors.white, fontSize: 16,
                        fontWeight: FontWeight.w800, fontFamily: 'monospace'),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      '${isUp ? '+' : ''}${change.toStringAsFixed(2)} (${changePct.toStringAsFixed(2)}%)',
                      style: TextStyle(
                        color: isUp ? const Color(0xFF22C55E) : const Color(0xFFEF4444),
                        fontSize: 11, fontWeight: FontWeight.w600),
                    ),
                  ]),
              ],
            ),
          ),
          // Period selector
          Row(
            children: _periods.map((p) {
              final (label, days) = p;
              final selected = _days == days;
              return GestureDetector(
                onTap: () => setState(() {
                  _days = days;
                  _hoverIndex = null;
                }),
                child: Container(
                  margin: const EdgeInsets.only(left: 4),
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: selected
                        ? const Color(0xFF7C3AED)
                        : Colors.transparent,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(label,
                      style: TextStyle(
                        color: selected ? Colors.white : Colors.white38,
                        fontSize: 10, fontWeight: FontWeight.w700)),
                ),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }

  Widget _buildChart(List<Map<String, dynamic>> candles) {
    if (candles.isEmpty) {
      return const SizedBox(
        height: 220,
        child: Center(
          child: Text('No data', style: TextStyle(color: Colors.white38)),
        ),
      );
    }

    return GestureDetector(
      onPanUpdate: (details) {
        final box = context.findRenderObject() as RenderBox?;
        if (box == null) return;
        final local = details.localPosition;
        final chartLeft  = 52.0;
        final chartRight = box.size.width - 8.0;
        final chartW    = chartRight - chartLeft;
        final idx = ((local.dx - chartLeft) / chartW * (candles.length - 1))
            .round()
            .clamp(0, candles.length - 1);
        setState(() {
          _hoverIndex  = idx;
          _hoverOffset = local;
        });
      },
      onPanEnd: (_) => setState(() {
        _hoverIndex  = null;
        _hoverOffset = null;
      }),
      child: Stack(
        children: [
          SizedBox(
            height: 220,
            child: CustomPaint(
              painter: _CandlePainter(
                candles:     candles,
                entryPrice:  widget.entryPrice,
                stopLoss:    widget.stopLoss,
                takeProfit:  widget.takeProfit,
                hoverIndex:  _hoverIndex,
              ),
              size: Size.infinite,
            ),
          ),
          // Tooltip
          if (_hoverIndex != null && _hoverOffset != null)
            _buildTooltip(candles[_hoverIndex!], _hoverOffset!),
        ],
      ),
    );
  }

  Widget _buildTooltip(Map<String, dynamic> candle, Offset offset) {
    final isUp = (candle['close'] as num) >= (candle['open'] as num);
    return Positioned(
      left: (offset.dx + 12).clamp(0, double.infinity),
      top:  (offset.dy - 110).clamp(0, double.infinity),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: const Color(0xF5111118),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFF7C3AED).withOpacity(0.5)),
          boxShadow: [
            BoxShadow(color: Colors.black.withOpacity(0.6), blurRadius: 8)
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(candle['date'] as String,
                style: const TextStyle(
                  color: Colors.white70, fontSize: 10, fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            _row('O', '\u20b9${(candle['open'] as num).toStringAsFixed(2)}',  Colors.white),
            _row('H', '\u20b9${(candle['high'] as num).toStringAsFixed(2)}',  const Color(0xFF22C55E)),
            _row('L', '\u20b9${(candle['low']  as num).toStringAsFixed(2)}',  const Color(0xFFEF4444)),
            _row('C', '\u20b9${(candle['close'] as num).toStringAsFixed(2)}',
                isUp ? const Color(0xFF22C55E) : const Color(0xFFEF4444)),
            _row('V', '${((candle['volume'] as num) / 1e6).toStringAsFixed(2)}M', Colors.white60),
          ],
        ),
      ),
    );
  }

  Widget _row(String label, String value, Color valueColor) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 1),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        SizedBox(
          width: 14,
          child: Text(label,
              style: const TextStyle(color: Colors.white38, fontSize: 10)),
        ),
        const SizedBox(width: 8),
        Text(value,
            style: TextStyle(
              color: valueColor, fontSize: 10,
              fontFamily: 'monospace', fontWeight: FontWeight.w600)),
      ]),
    );
  }
}

class _CandlePainter extends CustomPainter {
  final List<Map<String, dynamic>> candles;
  final double? entryPrice;
  final double? stopLoss;
  final double? takeProfit;
  final int? hoverIndex;

  _CandlePainter({
    required this.candles,
    this.entryPrice,
    this.stopLoss,
    this.takeProfit,
    this.hoverIndex,
  });

  @override
  void paint(Canvas canvas, Size size) {
    const padTop    = 12.0;
    const padBottom = 28.0;
    const padLeft   = 52.0;
    const padRight  = 8.0;
    final chartW = size.width  - padLeft - padRight;
    final chartH = size.height - padTop  - padBottom;

    // Price range
    final highs = candles.map((c) => (c['high']  as num).toDouble()).toList();
    final lows  = candles.map((c) => (c['low']   as num).toDouble()).toList();
    double maxP = highs.reduce((a, b) => a > b ? a : b);
    double minP = lows .reduce((a, b) => a < b ? a : b);
    final padding = (maxP - minP) * 0.06;
    maxP += padding; minP -= padding;
    final priceRange = maxP - minP;

    double xAt(int i) =>
        padLeft + (i / (candles.length - 1)) * chartW;
    double yAt(double p) =>
        padTop + (1 - (p - minP) / priceRange) * chartH;

    // Grid
    final gridPaint = Paint()
      ..color = Colors.white.withOpacity(0.05)
      ..strokeWidth = 1;
    final labelStyle = TextStyle(
        color: Colors.white.withOpacity(0.35), fontSize: 9);

    for (int g = 0; g <= 4; g++) {
      final y     = padTop + (g / 4) * chartH;
      final price = maxP - (g / 4) * priceRange;
      canvas.drawLine(Offset(padLeft, y), Offset(size.width - padRight, y), gridPaint);
      final tp = TextPainter(
        text: TextSpan(text: '\u20b9${price.toStringAsFixed(0)}', style: labelStyle),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(0, y - 6));
    }

    // Horizontal lines (entry/SL/TP)
    void drawHLine(double price, Color color, String label) {
      if (price < minP || price > maxP) return;
      final y = yAt(price);
      final linePaint = Paint()
        ..color = color.withOpacity(0.7)
        ..strokeWidth = 1
        ..style = PaintingStyle.stroke;
      final path = Path();
      for (double x = padLeft; x < size.width - padRight; x += 8) {
        path.moveTo(x, y);
        path.lineTo(x + 4, y);
      }
      canvas.drawPath(path, linePaint);
      final lp = TextPainter(
        text: TextSpan(
          text: '$label \u20b9${price.toStringAsFixed(0)}',
          style: TextStyle(color: color, fontSize: 8, fontWeight: FontWeight.w700),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      lp.paint(canvas, Offset(padLeft + 4, y - 10));
    }

    if (entryPrice != null) drawHLine(entryPrice!, const Color(0xFF7C3AED), 'Entry');
    if (stopLoss   != null) drawHLine(stopLoss!,   const Color(0xFFEF4444), 'SL');
    if (takeProfit != null) drawHLine(takeProfit!,  const Color(0xFF22C55E), 'TP');

    // Candlesticks
    final candleW = (chartW / candles.length * 0.6).clamp(2.0, 10.0);

    for (int i = 0; i < candles.length; i++) {
      final c      = candles[i];
      final open   = (c['open']  as num).toDouble();
      final close  = (c['close'] as num).toDouble();
      final high   = (c['high']  as num).toDouble();
      final low    = (c['low']   as num).toDouble();
      final isUp   = close >= open;
      final color  = isUp ? const Color(0xFF22C55E) : const Color(0xFFEF4444);
      final x      = xAt(i);

      final paint = Paint()..color = color;

      // Hover highlight
      if (i == hoverIndex) {
        canvas.drawRect(
          Rect.fromLTWH(x - candleW, padTop, candleW * 2, chartH),
          Paint()..color = Colors.white.withOpacity(0.05),
        );
      }

      // Wick
      canvas.drawLine(
        Offset(x, yAt(high)), Offset(x, yAt(low)), paint..strokeWidth = 1);

      // Body
      final top    = yAt(isUp ? close : open);
      final bottom = yAt(isUp ? open  : close);
      final bodyH  = (bottom - top).abs().clamp(1.0, double.infinity);
      canvas.drawRect(
        Rect.fromLTWH(x - candleW / 2, top, candleW, bodyH), paint);
    }

    // X-axis date labels
    final step = (candles.length / 5).ceil();
    for (int i = 0; i < candles.length; i += step) {
      final x    = xAt(i);
      final date = candles[i]['date'] as String;
      final parts = date.split('-');
      final label = '${parts[2]}/${parts[1]}';
      final tp = TextPainter(
        text: TextSpan(text: label, style: labelStyle),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(x - tp.width / 2, size.height - padBottom + 6));
    }
  }

  @override
  bool shouldRepaint(_CandlePainter old) =>
      old.hoverIndex != hoverIndex ||
      old.candles.length != candles.length;
}
