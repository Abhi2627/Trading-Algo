// shared/widgets/loading_state.dart
import 'package:flutter/material.dart';
import '../theme.dart';

class LoadingState extends StatelessWidget {
  const LoadingState({super.key});

  @override
  Widget build(BuildContext context) => const Center(
    child: CircularProgressIndicator(
      color: AppColors.accent,
      strokeWidth: 2,
    ),
  );
}

class ErrorState extends StatelessWidget {
  final String message;
  final VoidCallback? onRetry;
  const ErrorState({super.key, required this.message, this.onRetry});

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.error_outline_rounded, color: AppColors.red, size: 40),
          const SizedBox(height: 12),
          Text(message,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textSecondary, fontSize: 13)),
          if (onRetry != null) ...
            [
              const SizedBox(height: 16),
              TextButton(
                onPressed: onRetry,
                child: const Text('Retry', style: TextStyle(color: AppColors.accent)),
              ),
            ],
        ],
      ),
    ),
  );
}

class EmptyState extends StatelessWidget {
  final String message;
  final IconData icon;
  const EmptyState({super.key, required this.message, this.icon = Icons.inbox_outlined});

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, color: AppColors.textMuted, size: 40),
        const SizedBox(height: 12),
        Text(message,
            style: const TextStyle(color: AppColors.textMuted, fontSize: 13)),
      ],
    ),
  );
}
