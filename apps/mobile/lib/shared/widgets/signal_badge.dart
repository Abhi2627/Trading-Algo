// shared/widgets/signal_badge.dart
import 'package:flutter/material.dart';
import '../theme.dart';

class SignalBadge extends StatelessWidget {
  final String action;
  final double confidence;
  final bool small;

  const SignalBadge({
    super.key,
    required this.action,
    required this.confidence,
    this.small = false,
  });

  @override
  Widget build(BuildContext context) {
    final cfg = _config();
    final pct = '${(confidence * 100).toStringAsFixed(0)}%';
    final fs  = small ? 10.0 : 12.0;
    final px  = small ? 8.0  : 12.0;
    final py  = small ? 3.0  : 6.0;

    return Container(
      padding: EdgeInsets.symmetric(horizontal: px, vertical: py),
      decoration: BoxDecoration(
        color:        cfg.bg.withOpacity(0.15),
        borderRadius: BorderRadius.circular(20),
        border:       Border.all(color: cfg.bg.withOpacity(0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(cfg.icon, color: cfg.bg, size: fs + 2),
          const SizedBox(width: 4),
          Text(
            '${cfg.label} $pct',
            style: TextStyle(
              color:      cfg.bg,
              fontSize:   fs,
              fontWeight: FontWeight.w800,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }

  _BadgeConfig _config() {
    switch (action) {
      case 'buy':  return _BadgeConfig(AppColors.green, Icons.arrow_upward_rounded,  'BUY');
      case 'sell': return _BadgeConfig(AppColors.red,   Icons.arrow_downward_rounded,'SELL');
      default:     return _BadgeConfig(AppColors.amber, Icons.remove_rounded,        'HOLD');
    }
  }
}

class _BadgeConfig {
  final Color  bg;
  final IconData icon;
  final String label;
  const _BadgeConfig(this.bg, this.icon, this.label);
}
