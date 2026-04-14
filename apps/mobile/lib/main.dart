// main.dart — app entry point
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
import 'shared/theme.dart';

// Global Dio provider — rebuilt when settings change
final dioProvider = FutureProvider<Dio>((ref) => buildDio());

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor:          Colors.transparent,
    statusBarIconBrightness: Brightness.light,
  ));
  runApp(const ProviderScope(child: AlgoTradeApp()));
}

class AlgoTradeApp extends StatelessWidget {
  const AlgoTradeApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title:                      'AlgoTrade',
      theme:                      buildAppTheme(),
      debugShowCheckedModeBanner: false,
      home:                       const _Shell(),
    );
  }
}

class _Shell extends StatefulWidget {
  const _Shell();
  @override
  State<_Shell> createState() => _ShellState();
}

class _ShellState extends State<_Shell> {
  int _idx = 0;

  final _screens = const [
    DashboardScreen(),
    SignalsScreen(),
    PortfolioScreen(),
    ChatScreen(),
    SettingsScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _idx,
        children: _screens,
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex:         _idx,
        onDestinationSelected: (i) => setState(() => _idx = i),
        backgroundColor:       AppColors.surface,
        indicatorColor:        AppColors.accent.withOpacity(0.2),
        labelBehavior:         NavigationDestinationLabelBehavior.alwaysShow,
        destinations: const [
          NavigationDestination(
            icon:         Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard_rounded, color: AppColors.accent),
            label: 'Dashboard',
          ),
          NavigationDestination(
            icon:         Icon(Icons.show_chart_outlined),
            selectedIcon: Icon(Icons.show_chart_rounded, color: AppColors.accent),
            label: 'Signals',
          ),
          NavigationDestination(
            icon:         Icon(Icons.account_balance_wallet_outlined),
            selectedIcon: Icon(Icons.account_balance_wallet_rounded,
                color: AppColors.accent),
            label: 'Portfolio',
          ),
          NavigationDestination(
            icon:         Icon(Icons.auto_awesome_outlined),
            selectedIcon: Icon(Icons.auto_awesome_rounded, color: AppColors.accent),
            label: 'Chat',
          ),
          NavigationDestination(
            icon:         Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings_rounded, color: AppColors.accent),
            label: 'Settings',
          ),
        ],
      ),
    );
  }
}
