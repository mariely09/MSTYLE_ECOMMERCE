import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';
import 'supabase_client.dart' show supabase, supabaseUrl, supabaseServiceRole, supabaseAdminSelect, supabaseAdminUpsert, supabaseAdminDelete;
import 'product_image_carousel.dart' show kFlaskBaseUrl;

// Shared HTTP client instance
final _http = http.Client();

class BuyerService {
  // ── Cart ──────────────────────────────────────────────────────────────────

  /// Fetch all cart items for the logged-in buyer
  static Future<List<Map<String, dynamic>>> getCartItems(String email) async {
    try {
      final res = await supabase
          .from('cart')
          .select('id, email, product_id, name, price, seller_email, variations, size, quantity, image')
          .eq('email', email)
          .order('id', ascending: false)
          .timeout(const Duration(seconds: 15));
      final items = List<Map<String, dynamic>>.from(res as List);
      debugPrint('getCartItems: found ${items.length} items for $email');

      // For each item, fetch the product's image_colors to find the color-specific image
      for (final item in items) {
        final pid = item['product_id'];
        final selectedColor = (item['variations'] as String? ?? '').trim();
        if (pid != null && selectedColor.isNotEmpty) {
          try {
            final prodRes = await supabase
                .from('products')
                .select('image, image_colors')
                .eq('id', pid)
                .limit(1);
            if ((prodRes as List).isNotEmpty) {
              final prod = prodRes[0];
              final colorImg = parseColorImages(
                prod['image_colors'] as String?,
                prod['image'] as String?,
              )[selectedColor.toLowerCase()];
              if (colorImg != null && colorImg.isNotEmpty) {
                item['image'] = colorImg; // override with color-specific image
              }
            }
          } catch (_) { /* keep original image */ }
        }
      }

      return items;
    } catch (e) {
      debugPrint('getCartItems error: $e');
      // Retry with wildcard select
      try {
        final res2 = await supabase
            .from('cart')
            .select()
            .eq('email', email)
            .order('id', ascending: false);
        final items2 = List<Map<String, dynamic>>.from(res2 as List);
        debugPrint('getCartItems retry: found ${items2.length} items');
        return items2;
      } catch (e2) {
        debugPrint('getCartItems retry error: $e2');
        return [];
      }
    }
  }

  /// Add item to cart — merges with existing same product+color+size, capped at variant stock
  static Future<({bool added, bool stockCapped, String message})> addToCart({
    required String email,
    required int productId,
    required String name,
    required double price,
    required String sellerEmail,
    String? color,
    String? size,
    int quantity = 1,
    String? image,
  }) async {
    // Get variant stock cap
    int? variantStock;
    try {
      final vsRes = await supabase
          .from('variant_inventory')
          .select('stock_quantity')
          .eq('product_id', productId)
          .eq('color', color ?? '')
          .eq('size', size ?? '')
          .maybeSingle();
      if (vsRes != null) {
        variantStock = (vsRes['stock_quantity'] as num?)?.toInt();
      }
    } catch (_) {}

    // Check if same product+color+size already in cart
    final existing = await supabase
        .from('cart')
        .select('id, quantity')
        .eq('email', email)
        .eq('product_id', productId)
        .eq('variations', color ?? '')
        .eq('size', size ?? '')
        .maybeSingle();

    if (existing != null) {
      final existingQty = (existing['quantity'] as num?)?.toInt() ?? 0;
      int newQty = existingQty + quantity;
      // Cap at variant stock
      if (variantStock != null && newQty > variantStock) {
        newQty = variantStock;
      }
      if (newQty <= existingQty) {
        return (added: false, stockCapped: true,
            message: 'Already at maximum stock (${variantStock ?? existingQty} available)');
      }
      await supabase
          .from('cart')
          .update({'quantity': newQty})
          .eq('id', existing['id']);
      return (added: true, stockCapped: newQty == variantStock,
          message: newQty == variantStock ? 'Added (max stock reached)' : 'Quantity updated in cart');
    } else {
      int finalQty = quantity;
      if (variantStock != null && finalQty > variantStock) {
        finalQty = variantStock;
      }
      if (finalQty <= 0) {
        return (added: false, stockCapped: true, message: 'This variant is out of stock');
      }
      await supabase.from('cart').insert({
        'email':        email,
        'product_id':   productId,
        'name':         name,
        'price':        price,
        'seller_email': sellerEmail,
        'variations':   color ?? '',
        'size':         size ?? '',
        'quantity':     finalQty,
        'image':        image ?? '',
      });
      return (added: true, stockCapped: finalQty == variantStock,
          message: 'Added to cart!');
    }
  }

  /// Remove item from cart
  static Future<void> removeFromCart(int cartItemId) async {
    await supabase.from('cart').delete().eq('id', cartItemId);
  }

  /// Update cart item quantity
  static Future<void> updateCartQuantity(int cartItemId, int quantity) async {
    await supabase.from('cart').update({'quantity': quantity}).eq('id', cartItemId);
  }

  /// Update cart item color or size specification
  static Future<void> updateCartSpec(int cartItemId, {String? color, String? size, String? image}) async {
    final update = <String, dynamic>{};
    if (color != null) update['variations'] = color;
    if (size != null) update['size'] = size;
    if (image != null) update['image'] = image;
    if (update.isEmpty) return;
    await supabase.from('cart').update(update).eq('id', cartItemId);
  }

  /// Get distinct colors available for a product (from variant_inventory)
  static Future<List<String>> getProductColors(int productId) async {
    try {
      final res = await supabase
          .from('variant_inventory')
          .select('color, stock_quantity')
          .eq('product_id', productId);
      final rows = List<Map<String, dynamic>>.from(res as List);
      final seen = <String>{};
      final colors = <String>[];
      for (final row in rows) {
        final c = (row['color'] as String? ?? '').trim();
        if (c.isNotEmpty && seen.add(c)) colors.add(c);
      }
      // Fallback: read from products.variations
      if (colors.isEmpty) {
        final prodRes = await supabase
            .from('products')
            .select('variations')
            .eq('id', productId)
            .maybeSingle();
        final raw = prodRes?['variations'] as String? ?? '';
        colors.addAll(raw.split(',').map((e) => e.trim()).where((e) => e.isNotEmpty));
      }
      return colors;
    } catch (_) {
      return [];
    }
  }

  /// Get distinct sizes for a product+color (from variant_inventory)
  static Future<List<String>> getProductSizes(int productId, String color) async {
    try {
      var query = supabase
          .from('variant_inventory')
          .select('size, stock_quantity')
          .eq('product_id', productId);
      if (color.isNotEmpty) query = query.eq('color', color);
      final res = await query;
      final rows = List<Map<String, dynamic>>.from(res as List);
      final seen = <String>{};
      final sizes = <String>[];
      for (final row in rows) {
        final s = (row['size'] as String? ?? '').trim();
        if (s.isNotEmpty && seen.add(s)) sizes.add(s);
      }
      // Fallback: read from products.sizes
      if (sizes.isEmpty) {
        final prodRes = await supabase
            .from('products')
            .select('sizes')
            .eq('id', productId)
            .maybeSingle();
        final raw = prodRes?['sizes'] as String? ?? '';
        sizes.addAll(raw.split(',').map((e) => e.trim()).where((e) => e.isNotEmpty));
      }
      return sizes;
    } catch (_) {
      return [];
    }
  }

  /// Get image_colors map for a product { colorName → imageUrl }
  static Future<Map<String, String>> getProductImageColors(int productId) async {
    try {
      final res = await supabase
          .from('products')
          .select('image, image_colors')
          .eq('id', productId)
          .maybeSingle();
      if (res == null) return {};
      return parseColorImages(res['image_colors'] as String?, res['image'] as String?);
    } catch (_) {
      return {};
    }
  }

  /// Fetch buyer's saved address from Supabase users table
  /// Address is stored as separate fields: house_street, barangay, city, province, region, zip_code
  static Future<String> getUserAddress(String email) async {
    try {
      final res = await supabase
          .from('users')
          .select('house_street, barangay, city, province, region, zip_code')
          .eq('email', email)
          .maybeSingle();
      if (res == null) return '';
      final parts = [
        res['house_street'] as String? ?? '',
        res['barangay']     as String? ?? '',
        res['city']         as String? ?? '',
        res['province']     as String? ?? '',
        res['region']       as String? ?? '',
        res['zip_code']     as String? ?? '',
      ].where((p) => p.trim().isNotEmpty).toList();
      return parts.join(', ');
    } catch (_) {
      return '';
    }
  }

  /// Fetch buyer's address as structured fields from Supabase users table
  static Future<Map<String, String>> getUserAddressFields(String email) async {
    try {
      final res = await supabase
          .from('users')
          .select('house_street, barangay, city, province, region, zip_code')
          .eq('email', email)
          .maybeSingle();
      if (res == null) return {};
      return {
        'house_street': res['house_street'] as String? ?? '',
        'barangay':     res['barangay']     as String? ?? '',
        'city':         res['city']         as String? ?? '',
        'province':     res['province']     as String? ?? '',
        'region':       res['region']       as String? ?? '',
        'zip_code':     res['zip_code']     as String? ?? '',
      };
    } catch (_) {
      return {};
    }
  }

  /// Save buyer's address fields to Supabase users table
  static Future<void> updateUserAddress(String email, {
    required String houseStreet,
    required String barangay,
    required String city,
    required String province,
    required String region,
    required String zipCode,
  }) async {
    await supabase.from('users').update({
      'house_street': houseStreet,
      'barangay':     barangay,
      'city':         city,
      'province':     province,
      'region':       region,
      'zip_code':     zipCode,
    }).eq('email', email);
  }

  /// Clear all cart items for buyer
  static Future<void> clearCart(String email) async {
    await supabase.from('cart').delete().eq('email', email);
  }

  // ── Orders ────────────────────────────────────────────────────────────────

  /// Fetch all orders for the logged-in buyer
  static Future<List<Map<String, dynamic>>> getOrders(String email) async {
    final res = await supabase
        .from('orders')
        .select()
        .eq('email', email)
        .order('date', ascending: false);
    return List<Map<String, dynamic>>.from(res as List);
  }

  /// Place a new order via Flask API (uses service role to bypass RLS)
  static Future<void> placeOrder({
    required String email,
    required String name,
    required int productId,
    required double totalPrice,
    required int quantity,
    required String address,
    required String sellerEmail,
    required String paymentMethod,
    String? color,
    String? size,
    String? image,
    double shippingFee = 50,
  }) async {
    // Direct Supabase insert is blocked by RLS for the anon key.
    // Route through Flask API which uses the service role key.
    final unitPrice = (totalPrice - shippingFee) / quantity;
    final uri = Uri.parse('$kFlaskBaseUrl/api/mobile/place_order');
    final response = await _http.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'email':          email,
        'payment_method': paymentMethod,
        'address':        address,
        'items': [
          {
            'name':         name,
            'product_id':   productId,
            'price':        unitPrice,
            'quantity':     quantity,
            'color':        color ?? '',
            'size':         size ?? '',
            'image':        image ?? '',
            'seller_email': sellerEmail,
            'shipping_fee': shippingFee,
          }
        ],
      }),
    );
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode != 200 || body['success'] != true) {
      throw Exception(body['error'] ?? 'Failed to place order (${response.statusCode})');
    }
  }

  /// Cancel an order
  static Future<void> cancelOrder(int orderId, String reason) async {
    await supabase.from('orders').update({
      'status':               'Cancelled',
      'cancellation_reason':  reason,
      'cancelled_at':         DateTime.now().toIso8601String(),
    }).eq('id', orderId);
  }

  /// Mark order as received (Delivered → Completed)
  static Future<void> confirmReceipt(int orderId) async {
    await supabase.from('orders').update({
      'status':      'Completed',
      'received_at': DateTime.now().toIso8601String(),
    }).eq('id', orderId);
  }

  // ── Wishlist ──────────────────────────────────────────────────────────────
  // All operations go directly to Supabase using the service-role key.
  // user_id in the wishlist table = MD5 hash of email (stable int32).

  static int? _cachedMysqlUserId;
  static String? _cachedMysqlUserEmail;

  /// Derive a stable int32 user_id from email via Flask (Supabase lookup + MD5 fallback).
  static Future<int?> _getMysqlUserId(String email) async {
    if (_cachedMysqlUserId != null && _cachedMysqlUserEmail == email) {
      return _cachedMysqlUserId;
    }
    // Ask Flask — it queries Supabase users table, falls back to MD5 hash
    try {
      final uri = Uri.parse('$kFlaskBaseUrl/api/mobile/get_mysql_user_id')
          .replace(queryParameters: {'email': email});
      final resp = await http.get(uri).timeout(const Duration(seconds: 8));
      if (resp.statusCode == 200) {
        final json = jsonDecode(resp.body) as Map<String, dynamic>;
        if (json['success'] == true) {
          final id = (json['user_id'] as num?)?.toInt();
          if (id != null) {
            _cachedMysqlUserId = id;
            _cachedMysqlUserEmail = email;
            debugPrint('_getUserId: $email → $id (${json['source']})');
            return id;
          }
        }
      }
    } catch (e) {
      debugPrint('_getUserId Flask error: $e');
    }
    // Dart-side fallback: same MD5 algorithm as Flask
    try {
      final rows = await supabaseAdminSelect(
        table: 'users', select: 'id', filters: {'email': email}, limit: 1,
      );
      if (rows.isNotEmpty) {
        final rawId = rows[0]['id'];
        final intId = rawId is int ? rawId : int.tryParse(rawId?.toString() ?? '');
        if (intId != null) {
          _cachedMysqlUserId = intId;
          _cachedMysqlUserEmail = email;
          return intId;
        }
      }
    } catch (_) {}
    // Pure polynomial hash — same algorithm as Flask _resolve_wishlist_user_id:
    // hash_id = (hash_id * 31 + byte) & 0x7FFFFFFF  (over lowercased UTF-8 bytes)
    int hashId = 0;
    for (final byte in utf8.encode(email.toLowerCase())) {
      hashId = (hashId * 31 + byte) & 0x7FFFFFFF;
    }
    _cachedMysqlUserId = hashId;
    _cachedMysqlUserEmail = email;
    debugPrint('_getUserId: $email → $hashId (polynomial hash)');
    return hashId;
  }

  /// Fetch wishlist items with product + promotion details (pure Supabase)
  static Future<List<Map<String, dynamic>>> getWishlist(String email) async {
    try {
      final userId = await _getMysqlUserId(email);
      if (userId == null) return [];

      final wlRows = await supabaseAdminSelect(
        table: 'wishlist', select: 'id,product_id', filters: {'user_id': '$userId'},
      );
      if (wlRows.isEmpty) return [];

      final productIds = wlRows.map((r) => r['product_id']).toList();

      // Fetch products
      final prodUri = Uri.parse('$supabaseUrl/rest/v1/products').replace(queryParameters: {
        'select': 'id,name,price,image,seller_email,variations,sizes',
        'id': 'in.(${productIds.join(',')})',
      });
      final prodResp = await http.get(prodUri, headers: {
        'apikey': supabaseServiceRole, 'Authorization': 'Bearer $supabaseServiceRole',
      });
      final prodList = prodResp.statusCode == 200
          ? List<Map<String, dynamic>>.from(jsonDecode(prodResp.body) as List)
          : <Map<String, dynamic>>[];
      final prodMap = {for (final p in prodList) p['id'] as int: p};

      // Fetch active promotions
      final today = DateTime.now().toIso8601String().split('T')[0];
      final promoUri = Uri.parse('$supabaseUrl/rest/v1/promotions').replace(queryParameters: {
        'select': 'id,type,discount_value,code,product_scope',
        'is_active': 'eq.true', 'start_date': 'lte.$today', 'end_date': 'gte.$today',
      });
      final promoResp = await http.get(promoUri, headers: {
        'apikey': supabaseServiceRole, 'Authorization': 'Bearer $supabaseServiceRole',
      });
      final promos = promoResp.statusCode == 200
          ? List<Map<String, dynamic>>.from(jsonDecode(promoResp.body) as List)
          : <Map<String, dynamic>>[];

      final promoMap = <int, Map<String, dynamic>>{};
      for (final promo in promos) {
        if ((promo['product_scope'] as String? ?? 'all') == 'all') {
          for (final pid in productIds) {
            final id = pid as int;
            if (!promoMap.containsKey(id)) promoMap[id] = promo;
          }
        }
      }

      final items = <Map<String, dynamic>>[];
      for (final row in wlRows) {
        final pid = row['product_id'] as int;
        final prod = prodMap[pid];
        if (prod == null) continue;
        final basePrice = double.tryParse(prod['price']?.toString() ?? '0') ?? 0;
        final promo = promoMap[pid];
        double? salePrice;
        String promoType = '', promoCode = '';
        double promoDiscount = 0;
        if (promo != null) {
          promoType = promo['type'] as String? ?? '';
          promoDiscount = double.tryParse(promo['discount_value']?.toString() ?? '0') ?? 0;
          promoCode = promo['code'] as String? ?? '';
          if (promoType == 'percentage' && promoDiscount > 0) {
            salePrice = (basePrice * (1 - promoDiscount / 100)).clamp(0.01, double.infinity);
          } else if (promoType == 'fixed' && promoDiscount > 0) {
            salePrice = (basePrice - promoDiscount).clamp(0.01, double.infinity);
          }
        }
        items.add({
          'id': row['id'], 'product_id': pid,
          'products': {
            'id': pid, 'name': prod['name'] ?? '', 'price': basePrice,
            'sale_price': salePrice, 'image': prod['image'] ?? '',
            'seller_email': prod['seller_email'] ?? '',
            'variations': prod['variations'] ?? '', 'sizes': prod['sizes'] ?? '',
            'promotion_type': promoType, 'promotion_discount': promoDiscount,
            'promotion_code': promoCode,
          },
        });
      }
      debugPrint('getWishlist: ${items.length} items for $email');
      return items;
    } catch (e) {
      debugPrint('getWishlist error: $e');
      return [];
    }
  }

  /// Add to wishlist (direct Supabase insert)
  static Future<void> addToWishlist(String email, int productId) async {
    debugPrint('addToWishlist: $email product=$productId');
    final userId = await _getMysqlUserId(email);
    if (userId == null) throw Exception('Could not resolve user ID for $email');

    // Check existing
    final existing = await supabaseAdminSelect(
      table: 'wishlist', select: 'id',
      filters: {'user_id': '$userId', 'product_id': '$productId'},
    );
    if (existing.isNotEmpty) { debugPrint('addToWishlist: already exists'); return; }

    // Insert
    final uri = Uri.parse('$supabaseUrl/rest/v1/wishlist');
    final resp = await http.post(uri,
      headers: {
        'apikey': supabaseServiceRole, 'Authorization': 'Bearer $supabaseServiceRole',
        'Content-Type': 'application/json', 'Prefer': 'return=representation',
      },
      body: jsonEncode({'user_id': userId, 'product_id': productId}),
    );
    debugPrint('addToWishlist: ${resp.statusCode} ${resp.body}');
    if (resp.statusCode != 200 && resp.statusCode != 201 && resp.statusCode != 204) {
      throw Exception('Supabase insert failed (${resp.statusCode}): ${resp.body}');
    }
    debugPrint('addToWishlist: SUCCESS user_id=$userId product_id=$productId');
  }

  /// Remove from wishlist (direct Supabase delete)
  static Future<void> removeFromWishlist(String email, int productId) async {
    debugPrint('removeFromWishlist: $email product=$productId');
    final userId = await _getMysqlUserId(email);
    if (userId == null) throw Exception('Could not resolve user ID for $email');

    final uri = Uri.parse('$supabaseUrl/rest/v1/wishlist').replace(queryParameters: {
      'user_id': 'eq.$userId', 'product_id': 'eq.$productId',
    });
    final resp = await http.delete(uri, headers: {
      'apikey': supabaseServiceRole, 'Authorization': 'Bearer $supabaseServiceRole',
      'Prefer': 'return=minimal',
    });
    debugPrint('removeFromWishlist: ${resp.statusCode}');
    if (resp.statusCode != 200 && resp.statusCode != 204) {
      throw Exception('Supabase delete failed (${resp.statusCode}): ${resp.body}');
    }
  }

  /// Check if product is in wishlist (direct Supabase query)
  static Future<bool> isInWishlist(String email, int productId) async {
    try {
      final userId = await _getMysqlUserId(email);
      if (userId == null) return false;
      final rows = await supabaseAdminSelect(
        table: 'wishlist', select: 'id',
        filters: {'user_id': '$userId', 'product_id': '$productId'},
      );
      return rows.isNotEmpty;
    } catch (e) {
      debugPrint('isInWishlist error: $e');
      return false;
    }
  }



  // ── Notifications ─────────────────────────────────────────────────────────
  /// Fetch buyer notifications
  static Future<List<Map<String, dynamic>>> getNotifications(String email) async {
    final res = await supabase
        .from('buyer_notifications')
        .select()
        .eq('buyer_email', email)
        .order('created_at', ascending: false)
        .limit(50);
    return List<Map<String, dynamic>>.from(res as List);
  }

  /// Count unread notifications
  static Future<int> getUnreadCount(String email) async {
    final res = await supabase
        .from('buyer_notifications')
        .select('id')
        .eq('buyer_email', email)
        .eq('is_read', false);
    return (res as List).length;
  }

  /// Mark notification as read
  static Future<void> markNotificationRead(int notifId) async {
    await supabase
        .from('buyer_notifications')
        .update({'is_read': true})
        .eq('id', notifId);
  }

  /// Mark all notifications as read
  static Future<void> markAllNotificationsRead(String email) async {
    await supabase
        .from('buyer_notifications')
        .update({'is_read': true})
        .eq('buyer_email', email)
        .eq('is_read', false);
  }

  /// Delete a notification
  static Future<void> deleteNotification(int notifId) async {
    await supabase.from('buyer_notifications').delete().eq('id', notifId);
  }

  /// Delete all notifications for buyer
  static Future<void> deleteAllNotifications(String email) async {
    await supabase
        .from('buyer_notifications')
        .delete()
        .eq('buyer_email', email);
  }

  // ── Products ──────────────────────────────────────────────────────────────

  /// Fetch featured/all products
  /// Only returns products that have had stock set (quantity > 0 OR sold > 0).
  /// Excludes flagged products and inactive products.
  static Future<List<Map<String, dynamic>>> getProducts({
    int limit = 20,
    int offset = 0,
    String? category,
    List<String>? categories,
  }) async {
    try {
      var query = supabase
          .from('products')
          .select('id, name, price, image, category, seller_email, quantity, sold, rating, variations, sizes')
          .or('quantity.gt.0,sold.gt.0');

      if (category != null) {
        query = query.eq('category', category);
      } else if (categories != null && categories.isNotEmpty) {
        query = query.inFilter('category', categories);
      }

      final res = await query
          .order('id', ascending: false)
          .range(offset, offset + limit - 1)
          .timeout(const Duration(seconds: 15));

      final list = List<Map<String, dynamic>>.from(res as List);

      // Client-side filter: exclude flagged and inactive products
      return list.where((p) {
        if (p['is_active'] == false) return false;
        final flaggedAt = p['flagged_at'];
        if (flaggedAt != null && flaggedAt.toString().isNotEmpty) return false;
        return true;
      }).toList();
    } catch (e) {
      debugPrint('BuyerService.getProducts error: $e');
      return [];
    }
  }

  /// Get stock for a specific product variant (color+size)
  static Future<int?> getVariantStock(int productId, String color, String size) async {
    try {
      final res = await supabase
          .from('variant_inventory')
          .select('stock_quantity')
          .eq('product_id', productId)
          .eq('color', color)
          .eq('size', size)
          .maybeSingle();
      return (res?['stock_quantity'] as num?)?.toInt();
    } catch (_) {
      return null;
    }
  }

  /// Fetch single product by id
  static Future<Map<String, dynamic>?> getProduct(int productId) async {
    // Fetch product (includes image_colors for color swatch images)
    final productList = await supabase
        .from('products')
        .select('*, image_colors')
        .eq('id', productId)
        .limit(1);

    if (productList == null || (productList as List).isEmpty) return null;
    final productData = Map<String, dynamic>.from(productList[0]);

    // Fetch reviews separately
    try {
      final reviewsRes = await supabase
          .from('reviews')
          .select('rating, review_text, customer_email, created_at')
          .eq('product_id', productId)
          .order('created_at', ascending: false);
      productData['reviews'] = reviewsRes;
    } catch (_) {
      productData['reviews'] = [];
    }

    return productData;
  }

  /// Parse image_colors string into a Map<colorName, imageUrl>
  /// image_colors format: "filename_or_url:ColorName,filename_or_url:ColorName"
  static Map<String, String> parseColorImages(String? imageColors, String? imageString) {
    final result = <String, String>{};
    if (imageColors == null || imageColors.trim().isEmpty) return result;

    // Build a map of filename → full URL from the image column
    final urlMap = <String, String>{};
    if (imageString != null) {
      for (final part in imageString.split(',').map((e) => e.trim()).where((e) => e.isNotEmpty)) {
        final filename = part.split('/').last; // extract filename from URL
        urlMap[filename] = part;
        urlMap[part] = part; // also map full URL to itself
      }
    }

    for (final mapping in imageColors.split(',').map((e) => e.trim()).where((e) => e.isNotEmpty)) {
      final colonIdx = mapping.lastIndexOf(':');
      if (colonIdx <= 0) continue;
      final rawFile = mapping.substring(0, colonIdx).trim();
      final colorName = mapping.substring(colonIdx + 1).trim();
      if (colorName.isEmpty) continue;

      // Resolve to full URL
      String? url = urlMap[rawFile];
      url ??= urlMap[rawFile.split('/').last];
      if (url == null) {
        // Fallback: treat rawFile as a URL or build Flask URL
        url = rawFile.startsWith('http') ? rawFile : '$kFlaskBaseUrl/static/images/uploads/$rawFile';
      }
      result[colorName.toLowerCase()] = url;
    }
    return result;
  }

  // ── Reviews ───────────────────────────────────────────────────────────────

  /// Submit a product review
  static Future<void> submitReview({
    required int orderId,
    required int productId,
    required String customerEmail,
    required String sellerEmail,
    required int rating,
    required String reviewText,
  }) async {
    await supabase.from('reviews').insert({
      'order_id':       orderId,
      'product_id':     productId,
      'customer_email': customerEmail,
      'seller_email':   sellerEmail,
      'rating':         rating,
      'review_text':    reviewText,
    });
  }
}
