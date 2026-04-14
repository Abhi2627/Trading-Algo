// features/settings/settings_screen.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../shared/theme.dart';
import '../../main.dart' show dioProvider;

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});
  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  final _keyCtrl  = TextEditingController();
  final _urlCtrl  = TextEditingController();
  bool  _saving   = false;
  bool  _saved    = false;
  bool  _obscure  = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    _keyCtrl.text = prefs.getString('api_key')  ?? 'abhay-algotrade-2025';
    _urlCtrl.text = prefs.getString('base_url') ?? 'http://10.0.2.2:8000';
  }

  Future<void> _save() async {
    setState(() { _saving = true; _saved = false; });
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('api_key',  _keyCtrl.text.trim());
    await prefs.setString('base_url', _urlCtrl.text.trim());
    // Rebuild Dio with new settings
    ref.invalidate(dioProvider);
    setState(() { _saving = false; _saved = true; });
    Future.delayed(const Duration(seconds: 2),
        () { if (mounted) setState(() => _saved = false); });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const _SectionHeader('API Configuration'),
          const SizedBox(height: 10),
          _Field(
            label: 'Backend URL',
            hint:  'http://10.0.2.2:8000',
            ctrl:  _urlCtrl,
            icon:  Icons.link_rounded,
          ),
          const SizedBox(height: 10),
          _Field(
            label:   'API Key',
            hint:    'abhay-algotrade-2025',
            ctrl:    _keyCtrl,
            icon:    Icons.key_rounded,
            obscure: _obscure,
            suffix:  IconButton(
              icon: Icon(_obscure
                  ? Icons.visibility_off_rounded
                  : Icons.visibility_rounded,
                  color: AppColors.textMuted, size: 18),
              onPressed: () => setState(() => _obscure = !_obscure),
            ),
          ),
          const SizedBox(height: 20),
          SizedBox(
            height: 48,
            child: ElevatedButton(
              onPressed: _saving ? null : _save,
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.accent,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10)),
              ),
              child: _saving
                  ? const SizedBox(width: 18, height: 18,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white))
                  : const Text('Save Settings',
                      style: TextStyle(fontWeight: FontWeight.w700)),
            ),
          ),
          if (_saved) ...
            [
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 14),
                decoration: BoxDecoration(
                  color: AppColors.green.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: AppColors.green.withOpacity(0.3)),
                ),
                child: const Row(
                  children: [
                    Icon(Icons.check_circle_outline_rounded,
                        color: AppColors.green, size: 16),
                    SizedBox(width: 8),
                    Text('Settings saved. Reconnecting...',
                        style: TextStyle(color: AppColors.green, fontSize: 12)),
                  ],
                ),
              ),
            ],
          const SizedBox(height: 30),
          const _SectionHeader('About'),
          const SizedBox(height: 10),
          _InfoTile('App', 'AlgoTrade Mobile v1.0.0'),
          _InfoTile('Backend', 'FastAPI + PostgreSQL + Redis'),
          _InfoTile('Models', 'PPO RL + Transformer + NLP Sentiment'),
          _InfoTile('Note',
              'Paper trading only — no real money involved'),
        ],
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;
  const _SectionHeader(this.title);
  @override
  Widget build(BuildContext context) => Text(
    title.toUpperCase(),
    style: const TextStyle(
      color: AppColors.textMuted, fontSize: 10,
      fontWeight: FontWeight.w800, letterSpacing: 0.8,
    ),
  );
}

class _Field extends StatelessWidget {
  final String label;
  final String hint;
  final TextEditingController ctrl;
  final IconData icon;
  final bool obscure;
  final Widget? suffix;
  const _Field({
    required this.label, required this.hint,
    required this.ctrl,  required this.icon,
    this.obscure = false, this.suffix,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(
            color: AppColors.textSecondary, fontSize: 12,
            fontWeight: FontWeight.w600)),
        const SizedBox(height: 6),
        TextField(
          controller:     ctrl,
          obscureText:    obscure,
          style: const TextStyle(color: AppColors.textPrimary, fontSize: 13),
          decoration: InputDecoration(
            hintText:    hint,
            prefixIcon:  Icon(icon, color: AppColors.textMuted, size: 18),
            suffixIcon:  suffix,
          ),
        ),
      ],
    );
  }
}

Widget _InfoTile(String label, String value) => Padding(
  padding: const EdgeInsets.only(bottom: 8),
  child: Container(
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
    decoration: BoxDecoration(
      color: AppColors.surface,
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: AppColors.borderDef),
    ),
    child: Row(
      children: [
        Text(label, style: const TextStyle(
            color: AppColors.textMuted, fontSize: 11,
            fontWeight: FontWeight.w700)),
        const Spacer(),
        Text(value, style: const TextStyle(
            color: AppColors.textSecondary, fontSize: 11)),
      ],
    ),
  ),
);
