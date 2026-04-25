// core/api/endpoints.dart
// All API calls in one place. Each function maps to one backend endpoint.
import 'package:dio/dio.dart';
import '../models/wallet.dart';
import '../models/signal.dart';
import '../models/asset.dart';
import '../models/chat.dart';

class Endpoints {
  Endpoints(this._dio);
  final Dio _dio;

  // ---- Health ----
  Future<bool> healthCheck() async {
    try {
      final resp = await _dio.get('/health');
      return resp.statusCode == 200;
    } catch (_) { return false; }
  }

  // ---- Assets ----
  Future<List<Asset>> getAssets({String? assetType}) async {
    final resp = await _dio.get('/assets/',
        queryParameters: assetType != null ? {'asset_type': assetType} : null);
    final list = resp.data['assets'] as List;
    return list.map((e) => Asset.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<dynamic>> getSections() async {
    final resp = await _dio.get('/assets/sections');
    final list = resp.data['sections'] as List;
    return list;
  }

  Future<AssetPrice> getAssetPrice(String symbol) async {
    final resp = await _dio.get('/assets/${Uri.encodeComponent(symbol)}/price');
    return AssetPrice.fromJson(resp.data as Map<String, dynamic>);
  }

  // ---- Signals ----
  Future<Map<String, dynamic>> generateSignal(String symbol,
      {List<String>? headlines}) async {
    final resp = await _dio.post(
      '/signals/generate/${Uri.encodeComponent(symbol)}',
      data: headlines ?? [],
    );
    return resp.data as Map<String, dynamic>;
  }

  Future<Signal> getLatestSignal(String symbol) async {
    final resp = await _dio.get('/signals/latest/${Uri.encodeComponent(symbol)}');
    return Signal.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<List<Signal>> getSignalHistory(String symbol, {int limit = 20}) async {
    final resp = await _dio.get(
      '/signals/history/${Uri.encodeComponent(symbol)}',
      queryParameters: {'limit': limit},
    );
    final list = resp.data['signals'] as List;
    return list.map((e) => Signal.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<Map<String, dynamic>>> getTopPicks(
      {int limit = 5, double minConfidence = 0.50}) async {
    final resp = await _dio.get('/signals/top-picks',
        queryParameters: {'limit': limit, 'min_confidence': minConfidence});
    final list = resp.data['picks'] as List;
    return list.cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> getMarketStatus() async {
    final resp = await _dio.get('/signals/market-status');
    return resp.data as Map<String, dynamic>;
  }

  Future<List<Map<String, dynamic>>> getOHLCV(String symbol, {int days = 90}) async {
    final resp = await _dio.get(
      '/signals/ohlcv/${Uri.encodeComponent(symbol)}',
      queryParameters: {'days': days},
    );
    final list = resp.data['candles'] as List;
    return list.cast<Map<String, dynamic>>();
  }

  // ---- Wallet ----
  Future<WalletSummary> getWalletSummary() async {
    final resp = await _dio.get('/wallet/summary');
    return WalletSummary.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<Map<String, dynamic>> openTrade(
      String signalId, String assetSymbol, {bool isIntraday = false}) async {
    final resp = await _dio.post('/wallet/trade/open', data: {
      'signal_id':   signalId,
      'asset_symbol': assetSymbol,
      'is_intraday': isIntraday,
    });
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> closeTrade(String tradeId,
      {String reason = 'manual'}) async {
    final resp = await _dio.post('/wallet/trade/close',
        data: {'trade_id': tradeId, 'reason': reason});
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> applyTopup() async {
    final resp = await _dio.post('/wallet/topup');
    return resp.data as Map<String, dynamic>;
  }

  Future<List<Map<String, dynamic>>> getTradeHistory({int limit = 50}) async {
    final resp = await _dio.get('/wallet/history',
        queryParameters: {'limit': limit});
    final list = resp.data['trades'] as List;
    return list.cast<Map<String, dynamic>>();
  }

  // ---- Chat ----
  Future<ChatResponse> chat(String message,
      {List<ChatMessage> history = const []}) async {
    final resp = await _dio.post('/chat/', data: {
      'message': message,
      'conversation_history': history.map((m) => m.toJson()).toList(),
    });
    return ChatResponse.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<ExplainResponse> explainSignal(String signalId) async {
    final resp = await _dio.get('/chat/explain/$signalId');
    return ExplainResponse.fromJson(resp.data as Map<String, dynamic>);
  }
}
