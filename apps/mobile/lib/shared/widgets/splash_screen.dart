import 'package:flutter/material.dart';
import 'dart:async';
import '../theme.dart';

class SplashScreen extends StatefulWidget {
  final Widget child;
  const SplashScreen({super.key, required this.child});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen>
    with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;
  late Animation<double> _fade;
  late Animation<double> _scale;
  bool _done = false;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(vsync: this, duration: const Duration(milliseconds: 800));
    _fade  = Tween<double>(begin: 0, end: 1).animate(
        CurvedAnimation(parent: _ctrl, curve: Curves.easeOut));
    _scale = Tween<double>(begin: 0.85, end: 1).animate(
        CurvedAnimation(parent: _ctrl, curve: Curves.easeOutBack));
    _ctrl.forward();

    Timer(const Duration(milliseconds: 2200), () {
      if (mounted) setState(() => _done = true);
    });
  }

  @override
  void dispose() { _ctrl.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    if (_done) return widget.child;
    return Scaffold(
      backgroundColor: const Color(0xFF0A0A0F),
      body: Center(
        child: FadeTransition(
          opacity: _fade,
          child: ScaleTransition(
            scale: _scale,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                // Hexagon logo mark
                SizedBox(
                  width: 120, height: 120,
                  child: CustomPaint(painter: _HexLogoPainter()),
                ),
                const SizedBox(height: 28),
                const Text('AlgoTrade',
                    style: TextStyle(
                      color: Color(0xFFF8FAFC),
                      fontSize: 34,
                      fontWeight: FontWeight.w700,
                      letterSpacing: -0.5,
                    )),
                const SizedBox(height: 8),
                const Text('PAPER TRADING',
                    style: TextStyle(
                      color: Color(0xFF64748B),
                      fontSize: 11,
                      fontWeight: FontWeight.w500,
                      letterSpacing: 5,
                    )),
                const SizedBox(height: 4),
                Container(width: 60, height: 2,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(1),
                      gradient: const LinearGradient(colors: [
                        Color(0xFF7C3AED), Color(0xFF22C55E)]),
                    )),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _HexLogoPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final cy = size.height / 2;
    final r = size.width * 0.45;

    // Hex path
    final hex = Path();
    for (int i = 0; i < 6; i++) {
      final angle = (i * 60 - 90) * 3.14159 / 180;
      final x = cx + r * cos(angle);
      final y = cy + r * sin(angle);
      i == 0 ? hex.moveTo(x, y) : hex.lineTo(x, y);
    }
    hex.close();

    // Fill hex
    canvas.drawPath(hex, Paint()..color = const Color(0xFF1E1B2E));

    // Hex border
    canvas.drawPath(hex, Paint()
      ..color = const Color(0xFF7C3AED)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5);

    // Candlesticks (simplified)
    final bars = [
      (cx - 22, cy + 10, 20.0, const Color(0xFFEF4444)),
      (cx - 10, cy, 28.0,     const Color(0xFF22C55E)),
      (cx + 2,  cy - 8, 32.0, const Color(0xFF22C55E)),
      (cx + 14, cy + 4, 22.0, const Color(0xFFF59E0B)),
    ];

    for (final bar in bars) {
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(bar.$1 - 3, bar.$2 - bar.$3 / 2, 7, bar.$3),
          const Radius.circular(1)),
        Paint()..color = bar.$4);
    }

    // Trend line
    final trendPath = Path()
      ..moveTo(cx - 22, cy + 10)
      ..lineTo(cx - 10, cy - 2)
      ..lineTo(cx + 2, cy - 12)
      ..lineTo(cx + 14, cy - 4);

    canvas.drawPath(trendPath, Paint()
      ..color = const Color(0xFF7C3AED)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round);
  }

  double cos(double a) => (a == 0) ? 1 : _cos(a);
  double sin(double a) => _sin(a);

  double _cos(double x) {
    double result = 1, term = 1;
    for (int i = 1; i <= 10; i++) {
      term *= -x * x / (2 * i * (2 * i - 1));
      result += term;
    }
    return result;
  }

  double _sin(double x) {
    double result = x, term = x;
    for (int i = 1; i <= 10; i++) {
      term *= -x * x / ((2 * i + 1) * (2 * i));
      result += term;
    }
    return result;
  }

  @override
  bool shouldRepaint(_) => false;
}
