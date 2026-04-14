// core/models/wallet.dart
class Position {
  final String tradeId;
  final String symbol;
  final String name;
  final int quantity;
  final double entryPrice;
  final double currentPrice;
  final double unrealisedPnl;
  final double pnlPct;
  final double stopLoss;
  final double takeProfit;
  final String tradeType;
  final String entryTime;

  const Position({
    required this.tradeId,
    required this.symbol,
    required this.name,
    required this.quantity,
    required this.entryPrice,
    required this.currentPrice,
    required this.unrealisedPnl,
    required this.pnlPct,
    required this.stopLoss,
    required this.takeProfit,
    required this.tradeType,
    required this.entryTime,
  });

  factory Position.fromJson(Map<String, dynamic> j) => Position(
    tradeId:      j['trade_id']       as String,
    symbol:       j['symbol']         as String,
    name:         j['name']           as String,
    quantity:     j['quantity']       as int,
    entryPrice:   (j['entry_price']   as num).toDouble(),
    currentPrice: (j['current_price'] as num).toDouble(),
    unrealisedPnl:(j['unrealised_pnl'] as num).toDouble(),
    pnlPct:       (j['pnl_pct']       as num).toDouble(),
    stopLoss:     (j['stop_loss']     as num).toDouble(),
    takeProfit:   (j['take_profit']   as num).toDouble(),
    tradeType:    j['trade_type']     as String,
    entryTime:    j['entry_time']     as String,
  );
}

class DailyBudget {
  final double profitTarget;
  final double lossLimit;
  final double lossUsedToday;
  final double remainingLossBudget;

  const DailyBudget({
    required this.profitTarget,
    required this.lossLimit,
    required this.lossUsedToday,
    required this.remainingLossBudget,
  });

  factory DailyBudget.fromJson(Map<String, dynamic> j) => DailyBudget(
    profitTarget:        (j['profit_target']         as num).toDouble(),
    lossLimit:           (j['loss_limit']            as num).toDouble(),
    lossUsedToday:       (j['loss_used_today']       as num).toDouble(),
    remainingLossBudget: (j['remaining_loss_budget'] as num).toDouble(),
  );
}

class WalletSummary {
  final double cashBalance;
  final double investedBalance;
  final double unrealisedPnl;
  final double realisedPnl;
  final double totalEquity;
  final double peakEquity;
  final double drawdownPct;
  final String riskMode;      // normal | conservative | halted
  final double monthlyTopup;
  final double intradayAllocation;
  final double positionalAllocation;
  final DailyBudget dailyBudget;
  final List<Position> openPositions;
  final int openCount;

  const WalletSummary({
    required this.cashBalance,
    required this.investedBalance,
    required this.unrealisedPnl,
    required this.realisedPnl,
    required this.totalEquity,
    required this.peakEquity,
    required this.drawdownPct,
    required this.riskMode,
    required this.monthlyTopup,
    required this.intradayAllocation,
    required this.positionalAllocation,
    required this.dailyBudget,
    required this.openPositions,
    required this.openCount,
  });

  factory WalletSummary.fromJson(Map<String, dynamic> j) => WalletSummary(
    cashBalance:          (j['cash_balance']          as num).toDouble(),
    investedBalance:      (j['invested_balance']      as num).toDouble(),
    unrealisedPnl:        (j['unrealised_pnl']        as num).toDouble(),
    realisedPnl:          (j['realised_pnl']          as num).toDouble(),
    totalEquity:          (j['total_equity']          as num).toDouble(),
    peakEquity:           (j['peak_equity']           as num).toDouble(),
    drawdownPct:          (j['drawdown_pct']          as num).toDouble(),
    riskMode:             j['risk_mode']              as String,
    monthlyTopup:         (j['monthly_topup']         as num).toDouble(),
    intradayAllocation:   (j['intraday_allocation']   as num).toDouble(),
    positionalAllocation: (j['positional_allocation'] as num).toDouble(),
    dailyBudget:    DailyBudget.fromJson(j['daily_budget'] as Map<String, dynamic>),
    openPositions:  (j['open_positions'] as List)
        .map((e) => Position.fromJson(e as Map<String, dynamic>)).toList(),
    openCount:      j['open_count'] as int,
  );
}
