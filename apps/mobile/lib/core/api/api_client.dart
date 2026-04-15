// core/api/api_client.dart
// Single Dio instance used by all API calls.
// Base URL priority: SharedPreferences (set in Settings) > default LAN IP
// To find your Mac's current IP: ipconfig getifaddr en0
// Set URL directly in the app's Settings screen without rebuilding.
import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';

const String _defaultBaseUrl = 'http://10.27.204.58:8000'; // Mac LAN IP for S23 device
const String _prefKeyApiKey  = 'api_key';
const String _prefKeyBaseUrl = 'base_url';

// Call once at app start and whenever settings change.
Future<Dio> buildDio() async {
  final prefs = await SharedPreferences.getInstance();
  final stored = prefs.getString(_prefKeyApiKey) ?? '';
  final apiKey  = stored.trim().isNotEmpty ? stored.trim() : 'abhay-algotrade-2025';
  final storedUrl = prefs.getString(_prefKeyBaseUrl) ?? '';
  final baseUrl = storedUrl.trim().isNotEmpty ? storedUrl.trim() : _defaultBaseUrl;

  final dio = Dio(
    BaseOptions(
      baseUrl: baseUrl,
      connectTimeout: const Duration(seconds: 30),
      receiveTimeout: const Duration(seconds: 60),
      sendTimeout: const Duration(seconds: 30),
      headers: {
        'X-API-Key':     apiKey,
        'Content-Type':  'application/json',
      },
    ),
  );

  // Log requests in debug mode
  dio.interceptors.add(LogInterceptor(
    requestBody:  false,
    responseBody: false,
    logPrint: (o) => debugPrint(o.toString()),
  ));

  return dio;
}

// Thin wrapper so callers never touch Dio directly
class ApiClient {
  ApiClient(this._dio);
  final Dio _dio;

  Future<T> get<T>(String path, {Map<String, dynamic>? params,
      required T Function(dynamic) fromJson}) async {
    final resp = await _dio.get(path, queryParameters: params);
    return fromJson(resp.data);
  }

  Future<T> post<T>(String path, {dynamic body,
      required T Function(dynamic) fromJson}) async {
    final resp = await _dio.post(path, data: body);
    return fromJson(resp.data);
  }
}

void debugPrint(String msg) {
  // ignore: avoid_print
  print(msg);
}
