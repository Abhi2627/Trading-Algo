// main.dart
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:dio/dio.dart';
import 'core/api/api_client.dart';
import 'features/dashboard/dashboard_screen.dart';
import 'features/signals/signals_screen.dart';
import 'features/portfolio/portfolio_screen.dart';
import 'features/chat/chat_screen.dart';
import 'features/settings/settings_screen.dart';
import 'features/analytics/analytics_screen.dart';
import 'shared/theme.dart';
import 'shared/widgets/splash_screen.dart';
import 'package:flutter_riverpod/legacy.dart';

final dioProvider = FutureProvider<Dio>((ref) => buildDio());
final activeTabProvider = StateProvider<int>((ref) => 0);

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp, DeviceOrientation.portraitDown,
  ]);
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
  ));
  runApp(const ProviderScope(child: AlgoTradeApp()));
}

class AlgoTradeApp extends StatelessWidget {
  const AlgoTradeApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AlgoTrade',
      theme: buildAppTheme(),
      debugShowCheckedModeBanner: false,
      home: SplashScreen(child: const _Shell()),
    );
  }
}

class _Shell extends ConsumerWidget {
  const _Shell();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final idx = ref.watch(activeTabProvider);
    const screens = [
      DashboardScreen(), SignalsScreen(), PortfolioScreen(),
      AnalyticsScreen(), ChatScreen(), SettingsScreen(),
    ];
    return Scaffold(
      body: IndexedStack(index: idx, children: screens),
      bottomNavigationBar: NavigationBar(
        selectedIndex: idx,
        onDestinationSelected: (i) => ref.read(activeTabProvider.notifier).state = i,
        backgroundColor: AppColors.surface,
        indicatorColor: AppColors.accent.withOpacity(0.2),
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        destinations: const [
          NavigationDestination(icon: Icon(Icons.dashboard_outlined),
              selectedIcon: Icon(Icons.dashboard_rounded, color: AppColors.accent),
              label: 'Dashboard'),
          NavigationDestination(icon: Icon(Icons.show_chart_outlined),
              selectedIcon: Icon(Icons.show_chart_rounded, color: AppColors.accent),
              label: 'Signals'),
          NavigationDestination(icon: Icon(Icons.account_balance_wallet_outlined),
              selectedIcon: Icon(Icons.account_balance_wallet_rounded, color: AppColors.accent),
              label: 'Portfolio'),
          NavigationDestination(icon: Icon(Icons.bar_chart_outlined),
              selectedIcon: Icon(Icons.bar_chart_rounded, color: AppColors.accent),
              label: 'Analytics'),
          NavigationDestination(icon: Icon(Icons.auto_awesome_outlined),
              selectedIcon: Icon(Icons.auto_awesome_rounded, color: AppColors.accent),
              label: 'Chat'),
          NavigationDestination(icon: Icon(Icons.settings_outlined),
              selectedIcon: Icon(Icons.settings_rounded, color: AppColors.accent),
              label: 'Settings'),
        ],
      ),
    );
  }
}
