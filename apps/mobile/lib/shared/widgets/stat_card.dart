// shared/widgets/stat_card.dart
import 'package:flutter/material.dart';
import '../theme.dart';

class StatCard extends StatelessWidget {
  final String label;
  final String value;
  final String? subValue;
  final String? trend;   // up | down | null
  final IconData? icon;

  const StatCard({
    super.key,
    required this.label,
    required this.value,
    this.subValue,
    this.trend,
    this.icon,
  });

  @override
  Widget build(BuildContext context) {
    Color trendColor = AppColors.textMuted;
    IconData? trendIcon;
    if (trend == 'up')   { trendColor = AppColors.green; trendIcon = Icons.trending_up_rounded; }
    if (trend == 'down') { trendColor = AppColors.red;   trendIcon = Icons.trending_down_rounded; }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color:        AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border:       Border.all(color: AppColors.borderDef),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(label.toUpperCase(),
                  style: const TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.8,
                  )),
              if (icon != null)
                Icon(icon, color: AppColors.textMuted, size: 16),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: Text(value,
                    style: const TextStyle(
                      color:      AppColors.textPrimary,
                      fontSize:   22,
                      fontWeight: FontWeight.w800,
                    )),
              ),
              if (trendIcon != null)
                Icon(trendIcon, color: trendColor, size: 18),
            ],
          ),
          if (subValue != null) ...
            [
              const SizedBox(height: 4),
              Text(subValue!,
                  style: const TextStyle(
                    color:    AppColors.textSecondary,
                    fontSize: 12,
                  )),
            ],
        ],
      ),
    );
  }
}
