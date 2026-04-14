// core/models/signal.dart
class Signal {
  final String signalId;
  final String action;       // buy | sell | hold
  final double confidence;
  final double ensembleScore;
  final double rlScore;
  final double transformerScore;
  final double sentimentScore;
  final String marketRegime;
  final Map<String, dynamic> technicalIndicators;
  final bool isIntraday;
  final String createdAt;
  // Injected client-side
  String? symbol;

  Signal({
    required this.signalId,
    required this.action,
    required this.confidence,
    required this.ensembleScore,
    required this.rlScore,
    required this.transformerScore,
    required this.sentimentScore,
    required this.marketRegime,
    required this.technicalIndicators,
    required this.isIntraday,
    required this.createdAt,
    this.symbol,
  });

  factory Signal.fromJson(Map<String, dynamic> j) => Signal(
    signalId:          j['signal_id']         as String,
    action:            j['action']             as String,
    confidence:        (j['confidence'] as num).toDouble(),
    ensembleScore:     (j['ensemble_score'] as num).toDouble(),
    rlScore:           (j['rl_score'] as num).toDouble(),
    transformerScore:  (j['transformer_score'] as num).toDouble(),
    sentimentScore:    (j['sentiment_score'] as num).toDouble(),
    marketRegime:      j['market_regime']      as String,
    technicalIndicators: (j['technical_indicators'] as Map<String, dynamic>? ?? {}),
    isIntraday:        j['is_intraday']        as bool,
    createdAt:         j['created_at']         as String,
  );

  double? get rsi    => _toDouble(technicalIndicators['rsi_14']);
  double? get adx    => _toDouble(technicalIndicators['adx']);
  double? get volRatio => _toDouble(technicalIndicators['volume_ratio']);
  double? get atrPct => _toDouble(technicalIndicators['atr_pct']);

  double? _toDouble(dynamic v) {
    if (v == null) return null;
    return (v as num).toDouble();
  }
}
