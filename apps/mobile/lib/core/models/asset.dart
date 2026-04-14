// core/models/asset.dart
class Asset {
  final String symbol;
  final String name;
  final String exchange;
  final String assetType;
  final bool isActive;

  const Asset({
    required this.symbol,
    required this.name,
    required this.exchange,
    required this.assetType,
    required this.isActive,
  });

  factory Asset.fromJson(Map<String, dynamic> j) => Asset(
    symbol:    j['symbol']    as String,
    name:      j['name']      as String,
    exchange:  j['exchange']  as String,
    assetType: j['asset_type'] as String,
    isActive:  j['is_active'] as bool,
  );
}

class AssetPrice {
  final String symbol;
  final String name;
  final double price;
  final String currency;

  const AssetPrice({
    required this.symbol,
    required this.name,
    required this.price,
    required this.currency,
  });

  factory AssetPrice.fromJson(Map<String, dynamic> j) => AssetPrice(
    symbol:   j['symbol']   as String,
    name:     j['name']     as String,
    price:    (j['price'] as num).toDouble(),
    currency: j['currency'] as String,
  );
}
