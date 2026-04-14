// shared/theme.dart
import 'package:flutter/material.dart';

class AppColors {
  static const background   = Color(0xFF0A0A0F);
  static const surface      = Color(0xFF111118);
  static const elevated     = Color(0xFF16161F);
  static const borderDef    = Color(0xFF1E1E2E);
  static const borderSubtle = Color(0xFF2A2A3E);
  static const accent       = Color(0xFF6366F1);
  static const accentHover  = Color(0xFF4F46E5);
  static const textPrimary  = Color(0xFFF1F5F9);
  static const textSecondary= Color(0xFF94A3B8);
  static const textMuted    = Color(0xFF475569);
  static const green        = Color(0xFF22C55E);
  static const red          = Color(0xFFEF4444);
  static const amber        = Color(0xFFF59E0B);
  static const teal         = Color(0xFF14B8A6);
}

ThemeData buildAppTheme() {
  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    scaffoldBackgroundColor: AppColors.background,
    colorScheme: const ColorScheme.dark(
      primary:   AppColors.accent,
      surface:   AppColors.surface,
      onSurface: AppColors.textPrimary,
      error:     AppColors.red,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.surface,
      foregroundColor: AppColors.textPrimary,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        color: AppColors.textPrimary,
        fontSize: 18,
        fontWeight: FontWeight.w700,
      ),
    ),
    cardTheme: CardThemeData(
      color: AppColors.surface,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: AppColors.borderDef),
      ),
    ),
    dividerColor: AppColors.borderDef,
    textTheme: const TextTheme(
      bodyLarge:  TextStyle(color: AppColors.textPrimary,   fontSize: 14),
      bodyMedium: TextStyle(color: AppColors.textSecondary, fontSize: 13),
      bodySmall:  TextStyle(color: AppColors.textMuted,     fontSize: 11),
      titleLarge: TextStyle(color: AppColors.textPrimary,   fontSize: 20, fontWeight: FontWeight.w700),
      titleMedium:TextStyle(color: AppColors.textPrimary,   fontSize: 16, fontWeight: FontWeight.w600),
      labelSmall: TextStyle(color: AppColors.textMuted,     fontSize: 10, letterSpacing: 0.8),
    ),
    bottomNavigationBarTheme: const BottomNavigationBarThemeData(
      backgroundColor:      AppColors.surface,
      selectedItemColor:    AppColors.accent,
      unselectedItemColor:  AppColors.textMuted,
      type: BottomNavigationBarType.fixed,
      elevation: 0,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surface,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.borderDef),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.borderDef),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.accent, width: 1.5),
      ),
      hintStyle: const TextStyle(color: AppColors.textMuted, fontSize: 13),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    ),
  );
}
