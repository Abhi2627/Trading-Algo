// core/models/chat.dart
class ChatMessage {
  final String role;    // user | assistant
  final String content;

  const ChatMessage({required this.role, required this.content});

  factory ChatMessage.fromJson(Map<String, dynamic> j) =>
      ChatMessage(role: j['role'] as String, content: j['content'] as String);

  Map<String, dynamic> toJson() => {'role': role, 'content': content};
}

class ChatResponse {
  final String reply;
  final String contextUsed;
  final String? signalId;

  const ChatResponse({
    required this.reply,
    required this.contextUsed,
    this.signalId,
  });

  factory ChatResponse.fromJson(Map<String, dynamic> j) => ChatResponse(
    reply:       j['reply']        as String,
    contextUsed: j['context_used'] as String,
    signalId:    j['signal_id']    as String?,
  );
}

class ExplainResponse {
  final String signalId;
  final String symbol;
  final String action;
  final double confidence;
  final String explanation;

  const ExplainResponse({
    required this.signalId,
    required this.symbol,
    required this.action,
    required this.confidence,
    required this.explanation,
  });

  factory ExplainResponse.fromJson(Map<String, dynamic> j) => ExplainResponse(
    signalId:    j['signal_id']  as String,
    symbol:      j['symbol']     as String,
    action:      j['action']     as String,
    confidence:  (j['confidence'] as num).toDouble(),
    explanation: j['explanation'] as String,
  );
}
