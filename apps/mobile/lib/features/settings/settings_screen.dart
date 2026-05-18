// features/settings/settings_screen.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../shared/theme.dart';
import '../../main.dart' show dioProvider;

final retrainStatusProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  final dio = await ref.watch(dioProvider.future);
  final resp = await dio.get('/wallet/retrain/status');
  return Map<String, dynamic>.from(resp.data as Map);
});

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});
  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  final _keyCtrl = TextEditingController();
  final _urlCtrl = TextEditingController();
  bool _saving = false, _saved = false, _obscure = true, _retraining = false;

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    final p = await SharedPreferences.getInstance();
    _keyCtrl.text = p.getString('api_key')  ?? 'abhay-algotrade-2025';
    _urlCtrl.text = p.getString('base_url') ?? 'http://139.59.23.105:8000';
  }

  Future<void> _save() async {
    setState(() { _saving = true; _saved = false; });
    final p = await SharedPreferences.getInstance();
    await p.setString('api_key',  _keyCtrl.text.trim());
    await p.setString('base_url', _urlCtrl.text.trim());
    ref.invalidate(dioProvider);
    setState(() { _saving = false; _saved = true; });
    Future.delayed(const Duration(seconds: 2), () { if (mounted) setState(() => _saved = false); });
  }

  Future<void> _triggerRetrain() async {
    setState(() => _retraining = true);
    try {
      final dio = await ref.read(dioProvider.future);
      await dio.post('/wallet/retrain');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Retraining queued — takes up to 2 hours'),
          backgroundColor: AppColors.green));
        ref.invalidate(retrainStatusProvider);
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Failed: $e'), backgroundColor: AppColors.red));
    } finally { if (mounted) setState(() => _retraining = false); }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        _Card(title: 'ML Model Retraining', child: _RetrainCard(
          onRetrain: _triggerRetrain, retraining: _retraining)),
        const SizedBox(height: 14),
        _Card(title: 'Strategy Parameters', child: Column(children: [
          _Row('Min confidence', '70%'),
          _Row('ATR SL multiplier', '2.0x  (PSU: 2.5x)'),
          _Row('ATR TP multiplier', '4.0x  (PSU: 5.0x)'),
          _Row('Time exit (flat)', '7 days'),
          _Row('Max portfolio heat', '20%'),
          _Row('Max single position', '30%  (PSU: 15%)'),
          _Row('Max sector', '40%'),
          _Row('Kelly fraction', 'Half-Kelly 50%'),
        ])),
        const SizedBox(height: 14),
        _Card(title: 'Schedule (IST)', child: Column(children: [
          _Row('Morning scan', '8:30 AM Mon–Fri'),
          _Row('Auto-execute', 'After scan'),
          _Row('Real-time monitor', '9:15 AM – 3:30 PM'),
          _Row('Intraday scans', '9:20 AM, 11 AM, 1 PM'),
          _Row('Force-close intraday', '3:15 PM'),
          _Row('Evening report', '3:30 PM'),
          _Row('Weekly report', 'Sun 7:00 PM'),
          _Row('Model retraining', 'Sun 8:00 PM'),
          _Row('Monthly top-up', '1st of month 9 AM'),
        ])),
        const SizedBox(height: 14),
        _Card(title: 'API Configuration', child: Column(children: [
          _Field(label: 'Backend URL', hint: 'http://IP:8000',
              ctrl: _urlCtrl, icon: Icons.link_rounded),
          const SizedBox(height: 10),
          _Field(label: 'API Key', hint: 'your-api-key',
              ctrl: _keyCtrl, icon: Icons.key_rounded, obscure: _obscure,
              suffix: IconButton(
                icon: Icon(_obscure ? Icons.visibility_off_rounded : Icons.visibility_rounded,
                    color: AppColors.textMuted, size: 18),
                onPressed: () => setState(() => _obscure = !_obscure))),
          const SizedBox(height: 14),
          SizedBox(width: double.infinity, height: 44, child: ElevatedButton(
            onPressed: _saving ? null : _save,
            style: ElevatedButton.styleFrom(backgroundColor: AppColors.accent,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
            child: _saving
                ? const SizedBox(width: 18, height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Text('Save Settings', style: TextStyle(fontWeight: FontWeight.w700)))),
          if (_saved) ...[const SizedBox(height: 10), Container(
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
            decoration: BoxDecoration(color: AppColors.green.withOpacity(0.1),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppColors.green.withOpacity(0.3))),
            child: const Row(children: [
              Icon(Icons.check_circle_outline_rounded, color: AppColors.green, size: 14),
              SizedBox(width: 8),
              Text('Saved — reconnecting...', style: TextStyle(color: AppColors.green, fontSize: 11))]))],
        ])),
        const SizedBox(height: 14),
        _Card(title: 'System', child: Column(children: [
          _Row('App', 'AlgoTrade v1.0.0'),
          _Row('Backend', 'FastAPI + PostgreSQL + Redis'),
          _Row('Models', 'PPO RL + Transformer + Groq'),
          _Row('Training', 'Kaggle weekly'),
          _Row('Server', 'DigitalOcean BLR1'),
          _Row('Mode', 'Paper trading only'),
        ])),
        const SizedBox(height: 32),
      ]),
    );
  }
}

class _RetrainCard extends ConsumerWidget {
  final VoidCallback onRetrain;
  final bool retraining;
  const _RetrainCard({required this.onRetrain, required this.retraining});

  String _fmt(String? iso) {
    if (iso == null) return '—';
    try {
      final dt = DateTime.parse(iso).toLocal();
      const m = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      return '${dt.day} ${m[dt.month-1]} ${dt.year} ${dt.hour.toString().padLeft(2,'0')}:${dt.minute.toString().padLeft(2,'0')}';
    } catch (_) { return iso; }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(retrainStatusProvider);
    return state.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Text('Could not load status', style: const TextStyle(color: AppColors.textMuted, fontSize: 12)),
      data: (data) {
        final r = data['last_retrain'] as Map<String, dynamic>?;
        final success = r?['success'] == true;
        final skipped = r?['skipped'] == true;
        final color = r == null ? AppColors.textMuted : skipped ? AppColors.amber : success ? AppColors.green : AppColors.red;
        final icon  = r == null ? Icons.schedule_rounded : skipped ? Icons.warning_amber_rounded : success ? Icons.check_circle_rounded : Icons.error_outline_rounded;
        final text  = r == null ? 'Never run' : skipped ? 'Skipped — ${(r['reason'] as String? ?? '').replaceAll('_',' ')}' : success ? 'Completed successfully' : 'Failed — ${(r['reason'] as String? ?? '').replaceAll('_',' ')}';

        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: color.withOpacity(0.08),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: color.withOpacity(0.3))),
            child: Row(children: [
              Icon(icon, color: color, size: 18), const SizedBox(width: 10),
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(text, style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 12)),
                if (r?['run_at'] != null) Text('Run: ${_fmt(r?['run_at'] as String?)}',
                    style: const TextStyle(color: AppColors.textMuted, fontSize: 10)),
              ])),
              IconButton(icon: const Icon(Icons.refresh_rounded, color: AppColors.textMuted, size: 16),
                  onPressed: () => ref.invalidate(retrainStatusProvider),
                  padding: EdgeInsets.zero, constraints: const BoxConstraints()),
            ])),
          if (r != null && !skipped) ...[
            const SizedBox(height: 8),
            if (r['samples_used'] != null) _Row('Samples used', '${r['samples_used']} outcomes'),
            if (r['retrained_at'] != null) _Row('Retrained on', r['retrained_at'] as String),
            if (r['files_updated'] != null) _Row('Files updated', (r['files_updated'] as List).join(', ')),
          ],
          const SizedBox(height: 10),
          Container(padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(color: AppColors.elevated, borderRadius: BorderRadius.circular(8)),
            child: const Text('Auto-runs Sunday 8 PM IST. Needs 10+ closed trades.',
                style: TextStyle(color: AppColors.textMuted, fontSize: 10))),
          const SizedBox(height: 10),
          SizedBox(width: double.infinity, child: ElevatedButton.icon(
            onPressed: retraining ? null : onRetrain,
            icon: retraining
                ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.model_training_rounded, size: 16),
            label: Text(retraining ? 'Queuing...' : 'Retrain Now',
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
            style: ElevatedButton.styleFrom(backgroundColor: AppColors.accent,
                foregroundColor: Colors.white, padding: const EdgeInsets.symmetric(vertical: 12),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))))),
        ]);
      },
    );
  }
}

class _Card extends StatelessWidget {
  final String title; final Widget child;
  const _Card({required this.title, required this.child});
  @override Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.borderDef)),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(title.toUpperCase(), style: const TextStyle(
          color: AppColors.textMuted, fontSize: 9, fontWeight: FontWeight.w800, letterSpacing: 1.0)),
      const SizedBox(height: 10), child]));
}

Widget _Row(String l, String v) => Padding(
  padding: const EdgeInsets.only(bottom: 7),
  child: Row(children: [
    Expanded(child: Text(l, style: const TextStyle(color: AppColors.textMuted, fontSize: 11))),
    Text(v, style: const TextStyle(color: AppColors.textSecondary, fontSize: 11, fontWeight: FontWeight.w600))]));

class _Field extends StatelessWidget {
  final String label, hint; final TextEditingController ctrl;
  final IconData icon; final bool obscure; final Widget? suffix;
  const _Field({required this.label, required this.hint, required this.ctrl,
      required this.icon, this.obscure = false, this.suffix});
  @override Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label, style: const TextStyle(color: AppColors.textSecondary,
          fontSize: 11, fontWeight: FontWeight.w600)),
      const SizedBox(height: 6),
      TextField(controller: ctrl, obscureText: obscure,
        style: const TextStyle(color: AppColors.textPrimary, fontSize: 13),
        decoration: InputDecoration(hintText: hint,
          prefixIcon: Icon(icon, color: AppColors.textMuted, size: 18),
          suffixIcon: suffix))]);
}
