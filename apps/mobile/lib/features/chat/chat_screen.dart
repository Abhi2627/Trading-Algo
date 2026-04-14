// features/chat/chat_screen.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api/endpoints.dart';
import '../../core/models/chat.dart';
import '../../shared/theme.dart';
import '../../main.dart' show dioProvider;

class _ChatMsg {
  final String role;
  final String content;
  final String? contextUsed;
  final String? signalId;
  const _ChatMsg({required this.role, required this.content,
      this.contextUsed, this.signalId});
}

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});
  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _controller  = TextEditingController();
  final _scrollCtrl  = ScrollController();
  final List<_ChatMsg> _messages = [];
  bool _typing = false;
  String? _error;

  final _suggestions = {
    'Signals':   ['Why did you buy Reliance?','Explain the TCS signal',
                  'What drove the BTC sell?','Why is confidence low for HDFC?'],
    'Portfolio': ['How is my portfolio doing?','What is my drawdown?',
                  'How much did I make today?','What is my risk mode?'],
    'Education': ['What is RSI?','How does the RL agent work?',
                  'What is the ensemble score?','Explain market regime'],
  };

  @override
  void dispose() {
    _controller.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  Future<void> _send(String text) async {
    if (text.trim().isEmpty || _typing) return;
    _controller.clear();
    setState(() {
      _messages.add(_ChatMsg(role: 'user', content: text.trim()));
      _typing = true;
      _error  = null;
    });
    _scrollToBottom();

    try {
      final dio = await ref.read(dioProvider.future);
      final history = _messages
          .where((m) => m.role != 'user' || _messages.indexOf(m) < _messages.length - 1)
          .map((m) => ChatMessage(role: m.role, content: m.content))
          .toList();
      final resp = await Endpoints(dio).chat(text.trim(), history: history);
      setState(() {
        _messages.add(_ChatMsg(
          role:        'assistant',
          content:     resp.reply,
          contextUsed: resp.contextUsed,
          signalId:    resp.signalId,
        ));
      });
    } catch (_) {
      setState(() => _error = 'Failed to get response. Check your connection.');
    } finally {
      setState(() => _typing = false);
      _scrollToBottom();
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(title: const Text('Ask AlgoTrade')),
      body: Column(
        children: [
          // Suggestion chips
          Container(
            color: AppColors.surface,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: _suggestions.entries.expand((entry) {
                  return entry.value.map((s) => Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ActionChip(
                      label: Text(s),
                      onPressed: () => _send(s),
                      backgroundColor: AppColors.elevated,
                      side: const BorderSide(color: AppColors.borderDef),
                      labelStyle: const TextStyle(
                          color: AppColors.textSecondary, fontSize: 11),
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                    ),
                  ));
                }).toList(),
              ),
            ),
          ),

          // Messages
          Expanded(
            child: _messages.isEmpty
                ? _EmptyChat()
                : ListView.builder(
                    controller: _scrollCtrl,
                    padding: const EdgeInsets.all(16),
                    itemCount: _messages.length + (_typing ? 1 : 0) + (_error != null ? 1 : 0),
                    itemBuilder: (_, i) {
                      if (i == _messages.length && _typing) return _TypingIndicator();
                      if (i == _messages.length && _error != null) return _ErrorBubble(_error!);
                      if (i > _messages.length) return const SizedBox();
                      return _MessageBubble(msg: _messages[i]);
                    },
                  ),
          ),

          // Input
          Container(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
            color: AppColors.surface,
            child: SafeArea(
              top: false,
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _controller,
                      enabled: !_typing,
                      maxLines: null,
                      textInputAction: TextInputAction.send,
                      onSubmitted: _send,
                      decoration: const InputDecoration(
                        hintText: 'Ask about signals, portfolio, trading...',
                      ),
                      style: const TextStyle(
                          color: AppColors.textPrimary, fontSize: 13),
                    ),
                  ),
                  const SizedBox(width: 10),
                  SizedBox(
                    width: 44, height: 44,
                    child: ElevatedButton(
                      onPressed: _typing ? null : () => _send(_controller.text),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.accent,
                        foregroundColor: Colors.white,
                        padding: EdgeInsets.zero,
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(10)),
                      ),
                      child: _typing
                          ? const SizedBox(width: 16, height: 16,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2, color: Colors.white))
                          : const Icon(Icons.send_rounded, size: 18),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  final _ChatMsg msg;
  const _MessageBubble({required this.msg});

  @override
  Widget build(BuildContext context) {
    final isUser = msg.role == 'user';
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        mainAxisAlignment:
            isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (!isUser) ...
            [
              Container(
                width: 28, height: 28,
                decoration: BoxDecoration(
                  color: AppColors.accent.withOpacity(0.2),
                  shape: BoxShape.circle,
                ),
                child: const Icon(Icons.auto_awesome_rounded,
                    size: 14, color: AppColors.accent),
              ),
              const SizedBox(width: 8),
            ],
          Flexible(
            child: Column(
              crossAxisAlignment:
                  isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: isUser ? AppColors.accent : AppColors.surface,
                    borderRadius: BorderRadius.only(
                      topLeft:     const Radius.circular(16),
                      topRight:    const Radius.circular(16),
                      bottomLeft:  Radius.circular(isUser ? 16 : 4),
                      bottomRight: Radius.circular(isUser ? 4 : 16),
                    ),
                    border: isUser ? null
                        : Border.all(color: AppColors.borderDef),
                  ),
                  child: Text(msg.content,
                      style: TextStyle(
                        color: isUser
                            ? Colors.white : AppColors.textSecondary,
                        fontSize: 13, height: 1.4,
                      )),
                ),
                if (!isUser && msg.contextUsed != null) ...
                  [
                    const SizedBox(height: 4),
                    _ContextBadge(msg.contextUsed!),
                  ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ContextBadge extends StatelessWidget {
  final String contextType;
  const _ContextBadge(this.contextType);

  @override
  Widget build(BuildContext context) {
    Color color;
    switch (contextType) {
      case 'signal_explanation': color = AppColors.accent; break;
      case 'portfolio':          color = AppColors.amber;  break;
      default:                   color = AppColors.textMuted;
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Text(
        contextType.replaceAll('_', ' ').toUpperCase(),
        style: TextStyle(color: color, fontSize: 8, fontWeight: FontWeight.w800,
            letterSpacing: 0.5),
      ),
    );
  }
}

class _TypingIndicator extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: AppColors.borderDef),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: List.generate(3, (i) => _Dot(delay: i * 200)),
            ),
          ),
        ],
      ),
    );
  }
}

class _Dot extends StatefulWidget {
  final int delay;
  const _Dot({required this.delay});
  @override
  State<_Dot> createState() => _DotState();
}

class _DotState extends State<_Dot> with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;
  late final Animation<double>   _anim;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(vsync: this,
        duration: const Duration(milliseconds: 600))
      ..repeat(reverse: true);
    _anim = Tween(begin: 0.3, end: 1.0).animate(
        CurvedAnimation(parent: _ctrl, curve: Curves.easeInOut));
    Future.delayed(Duration(milliseconds: widget.delay), () {
      if (mounted) _ctrl.forward();
    });
  }

  @override
  void dispose() { _ctrl.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: _anim,
    builder: (_, __) => Padding(
      padding: const EdgeInsets.symmetric(horizontal: 2),
      child: Opacity(
        opacity: _anim.value,
        child: Container(
          width: 6, height: 6,
          decoration: const BoxDecoration(
            color: AppColors.textMuted, shape: BoxShape.circle),
        ),
      ),
    ),
  );
}

class _ErrorBubble extends StatelessWidget {
  final String msg;
  const _ErrorBubble(this.msg);
  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 8),
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
    decoration: BoxDecoration(
      color: AppColors.red.withOpacity(0.1),
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: AppColors.red.withOpacity(0.3)),
    ),
    child: Text(msg,
        style: const TextStyle(color: AppColors.red, fontSize: 12)),
  );
}

class _EmptyChat extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            color: AppColors.accent.withOpacity(0.1),
            shape: BoxShape.circle,
          ),
          child: const Icon(Icons.auto_awesome_rounded,
              size: 36, color: AppColors.accent),
        ),
        const SizedBox(height: 16),
        const Text('Ask me anything',
            style: TextStyle(color: AppColors.textPrimary,
                fontSize: 16, fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        const Padding(
          padding: EdgeInsets.symmetric(horizontal: 48),
          child: Text(
            'Ask about signals, portfolio performance, or how the AI makes decisions.',
            textAlign: TextAlign.center,
            style: TextStyle(color: AppColors.textMuted, fontSize: 12, height: 1.5),
          ),
        ),
      ],
    ),
  );
}
