import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';
import 'buyer_cart.dart';
import 'buyer_wishlist.dart';
import 'buyer_checkout.dart';
import 'buyer_view_shop.dart';
import 'buyer_service.dart';
import 'product_image_carousel.dart';
import 'supabase_client.dart' show supabase, supabaseAdminSelect;

const Color _primary   = Color(0xFF1a1a1a);
const Color _accent    = Color(0xFF2c3e50);
const Color _gold      = Color(0xFFd4af37);
const Color _goldLight = Color(0xFFF4D03F);
const Color _textLight = Color(0xFF6c757d);
const Color _bg        = Color(0xFFF8F9FA);
const Color _border    = Color(0xFFE9ECEF);

const _premiumGrad = LinearGradient(
  begin: Alignment.topLeft, end: Alignment.bottomRight,
  colors: [_primary, _accent],
);
const _goldGrad = LinearGradient(
  begin: Alignment.topLeft, end: Alignment.bottomRight,
  colors: [_gold, _goldLight],
);

// ─── Product model ────────────────────────────────────────────────────────────
class ProductDetail {
  final String id;
  final String name;
  final String description;
  final double price;
  final double? salePrice;
  final double? discountPercent;
  final List<String> colors;
  final List<String> sizes;
  final double rating;
  final int reviewCount;
  final int quantity;
  final String sellerEmail;
  final String sellerName;       // business_name or full name
  final String? sellerPicture;   // profile_picture filename/url
  final List<ReviewItem> reviews;

  const ProductDetail({
    required this.id,
    required this.name,
    required this.description,
    required this.price,
    this.salePrice,
    this.discountPercent,
    required this.colors,
    required this.sizes,
    required this.rating,
    required this.reviewCount,
    required this.quantity,
    required this.sellerEmail,
    required this.sellerName,
    this.sellerPicture,
    required this.reviews,
  });
}

class ReviewItem {
  final String reviewer;
  final double rating;
  final String text;
  final String date;
  final String? sellerResponse;

  const ReviewItem({
    required this.reviewer,
    required this.rating,
    required this.text,
    required this.date,
    this.sellerResponse,
  });
}

class BuyerViewProductPage extends StatefulWidget {
  final String userEmail;
  final ProductDetail? product;
  final int? productId;

  const BuyerViewProductPage({
    super.key,
    required this.userEmail,
    this.product,
    this.productId,
  }) : assert(product != null || productId != null, 'Provide product or productId');

  @override
  State<BuyerViewProductPage> createState() => _BuyerViewProductPageState();
}

class _BuyerViewProductPageState extends State<BuyerViewProductPage> {
  String? _selectedColor;
  String? _selectedSize;
  int _quantity = 1;
  int _imageIndex = 0;
  bool _inWishlist = false;
  bool _loadingWishlist = false;

  ProductDetail? _product;
  String? _rawImage;
  Map<String, String> _colorImages = {};
  Map<String, int> _variantStock = {}; // "color|size" → stock_quantity
  bool _loading = true;
  String? _error;

  // Stock for the currently selected color+size
  int get _selectedVariantStock {
    if (_selectedColor == null || _selectedSize == null) return p?.quantity ?? 0;
    final key = '${_selectedColor!.toLowerCase()}|${_selectedSize!.toLowerCase()}';
    return _variantStock[key] ?? 0;
  }

  late final TextEditingController _qtyCtrl;

  @override
  void initState() {
    super.initState();
    _qtyCtrl = TextEditingController(text: '1');
    if (widget.product != null) {
      _product = widget.product;
      _rawImage = null; // ProductDetail passed directly has no raw image string
      _loading = false;
      _checkWishlist();
    } else {
      _loadProduct();
    }
  }

  Future<void> _loadProduct() async {
    try {
      final data = await BuyerService.getProduct(widget.productId!);
      if (data == null) {
        setState(() { _loading = false; _error = 'Product not found'; });
        return;
      }

      final reviews = (data['reviews'] as List? ?? []).map((r) => ReviewItem(
        reviewer: r['customer_email'] ?? 'Anonymous',
        rating: (r['rating'] as num?)?.toDouble() ?? 5.0,
        text: r['review_text'] ?? '',
        date: r['created_at'] != null
            ? DateTime.parse(r['created_at']).toLocal().toString().split(' ')[0]
            : '',
      )).toList();

      // Average rating from actual reviews if available, else use stored rating
      final avgRating = reviews.isNotEmpty
          ? reviews.map((r) => r.rating).reduce((a, b) => a + b) / reviews.length
          : (data['rating'] as num?)?.toDouble() ?? 0.0;

      final colors = (data['variations'] as String? ?? '')
          .split(',').map((e) => e.trim()).where((e) => e.isNotEmpty).toList();
      final sizes = (data['sizes'] as String? ?? '')
          .split(',').map((e) => e.trim()).where((e) => e.isNotEmpty).toList();

      // Total available stock + per-variant stock map
      int totalStock = (data['quantity'] as num?)?.toInt() ?? 0;
      final variantStockMap = <String, int>{};
      try {
        final variants = await supabase
            .from('variant_inventory')
            .select('color, size, stock_quantity')
            .eq('product_id', data['id']);
        if ((variants as List).isNotEmpty) {
          totalStock = variants.fold(0, (sum, v) => sum + ((v['stock_quantity'] as num?)?.toInt() ?? 0));
          for (final v in variants) {
            final c = (v['color'] as String? ?? '').toLowerCase();
            final s = (v['size'] as String? ?? '').toLowerCase();
            variantStockMap['$c|$s'] = (v['stock_quantity'] as num?)?.toInt() ?? 0;
          }
        }
      } catch (_) { /* fall back to product.quantity */ }

      // Fetch seller info via admin REST call (bypasses RLS)
      final sellerEmail = (data['seller_email'] as String? ?? '').trim();
      String sellerDisplayName = sellerEmail;
      String? sellerPicture;
      if (sellerEmail.isNotEmpty) {
        try {
          final rows = await supabaseAdminSelect(
            table: 'users',
            select: 'business_name,first_name,last_name',
            filters: {'email': sellerEmail},
            limit: 1,
          );
          debugPrint('seller rows for $sellerEmail: ${rows.length}');
          if (rows.isNotEmpty) {
            final u = rows[0];
            final biz   = (u['business_name'] as String? ?? '').trim();
            final first = (u['first_name']    as String? ?? '').trim();
            final last  = (u['last_name']     as String? ?? '').trim();
            sellerDisplayName = biz.isNotEmpty
                ? biz
                : '$first $last'.trim().isNotEmpty
                    ? '$first $last'.trim()
                    : sellerEmail;
            debugPrint('seller display name: $sellerDisplayName');
            sellerPicture = null;
          }
        } catch (e) {
          debugPrint('seller info error: $e');
        }
      }

      setState(() {
        _product = ProductDetail(
          id: '${data['id']}',
          name: data['name'] ?? '',
          description: data['description'] ?? '',
          price: (data['price'] as num?)?.toDouble() ?? 0,
          colors: colors,
          sizes: sizes,
          rating: double.parse(avgRating.toStringAsFixed(1)),
          reviewCount: reviews.length,
          quantity: totalStock,
          sellerEmail: sellerEmail,
          sellerName: sellerDisplayName,
          sellerPicture: sellerPicture,
          reviews: reviews,
        );
        _rawImage = data['image'] as String?;
        _colorImages = BuyerService.parseColorImages(
          data['image_colors'] as String?,
          data['image'] as String?,
        );
        _variantStock = variantStockMap;
        _loading = false;
      });
      _checkWishlist();
    } catch (e) {
      setState(() { _loading = false; _error = e.toString(); });
    }
  }

  Future<void> _checkWishlist() async {
    if (_product == null || widget.userEmail.isEmpty) return;
    try {
      final inWl = await BuyerService.isInWishlist(widget.userEmail, int.tryParse(_product!.id) ?? 0);
      if (mounted) setState(() => _inWishlist = inWl);
    } catch (_) {}
  }

  Future<void> _toggleWishlist() async {
    if (_product == null || widget.userEmail.isEmpty) return;
    setState(() => _loadingWishlist = true);
    try {
      final pid = int.tryParse(_product!.id) ?? 0;
      if (_inWishlist) {
        await BuyerService.removeFromWishlist(widget.userEmail, pid);
        if (mounted) setState(() => _inWishlist = false);
      } else {
        await BuyerService.addToWishlist(widget.userEmail, pid);
        if (mounted) setState(() => _inWishlist = true);
      }
    } catch (e) {
      debugPrint('toggleWishlist error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Wishlist error: $e'),
          backgroundColor: Colors.red.shade700,
          behavior: SnackBarBehavior.floating,
          duration: const Duration(seconds: 5),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        ));
      }
      // Re-verify actual state from server on error
      await _checkWishlist();
    } finally {
      if (mounted) setState(() => _loadingWishlist = false);
    }
  }

  ProductDetail? get p => _product;
  bool get _inStock {
    if (p == null) return false;
    if (_selectedColor != null && _selectedSize != null) return _selectedVariantStock > 0;
    return p!.quantity > 0;
  }

  /// Update quantity state + sync the text controller
  void _setQuantity(int qty) {
    final max = _maxQty;
    final clamped = qty.clamp(1, max > 0 ? max : 9999);
    setState(() => _quantity = clamped);
    if (_qtyCtrl.text != '$clamped') {
      _qtyCtrl.text = '$clamped';
      _qtyCtrl.selection = TextSelection.collapsed(offset: _qtyCtrl.text.length);
    }
  }

  int get _maxQty => _selectedVariantStock > 0
      ? _selectedVariantStock
      : (p?.quantity ?? 0);

  @override
  void dispose() {
    _qtyCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return Scaffold(
        backgroundColor: _bg,
        appBar: AppBar(
          backgroundColor: _primary,
          leading: IconButton(
            icon: const Icon(Icons.arrow_back, color: Colors.white),
            onPressed: () => Navigator.pop(context),
          ),
          title: const Text('Loading...', style: TextStyle(color: Colors.white)),
        ),
        body: const Center(child: CircularProgressIndicator(color: _gold)),
      );
    }
    if (_error != null || p == null) {
      return Scaffold(
        backgroundColor: _bg,
        appBar: AppBar(
          backgroundColor: _primary,
          leading: IconButton(
            icon: const Icon(Icons.arrow_back, color: Colors.white),
            onPressed: () => Navigator.pop(context),
          ),
          title: const Text('Error', style: TextStyle(color: Colors.white)),
        ),
        body: Center(child: Text(_error ?? 'Product not found',
          style: const TextStyle(color: _textLight))),
      );
    }
    return Scaffold(
      backgroundColor: _bg,
      body: CustomScrollView(
        slivers: [
          _appBar(),
          SliverToBoxAdapter(child: _imageSection()),
          SliverToBoxAdapter(child: _infoSection()),
          SliverToBoxAdapter(child: _colorSection()),
          SliverToBoxAdapter(child: _sizeSection()),
          SliverToBoxAdapter(child: _quantitySection()),
          SliverToBoxAdapter(child: _sellerSection()),
          SliverToBoxAdapter(child: _reviewsSection()),
          const SliverToBoxAdapter(child: SizedBox(height: 100)),
        ],
      ),
      bottomNavigationBar: _bottomActions(),
    );
  }

  // ─── App Bar ──────────────────────────────────────────────────────────────
  SliverAppBar _appBar() => SliverAppBar(
    pinned: true,
    backgroundColor: _primary,
    elevation: 6,
    leading: IconButton(
      icon: const Icon(Icons.arrow_back, color: Colors.white),
      onPressed: () => Navigator.pop(context),
    ),
    title: ShaderMask(
      shaderCallback: (b) => _goldGrad.createShader(b),
      child: Text(p!.name,
        style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800),
        maxLines: 1, overflow: TextOverflow.ellipsis),
    ),
    actions: [
      _loadingWishlist
          ? const Padding(
              padding: EdgeInsets.all(12),
              child: SizedBox(width: 20, height: 20,
                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)))
          : IconButton(
              icon: AnimatedSwitcher(
                duration: const Duration(milliseconds: 250),
                transitionBuilder: (child, anim) => ScaleTransition(scale: anim, child: child),
                child: Icon(
                  _inWishlist ? Icons.favorite : Icons.favorite_border,
                  key: ValueKey(_inWishlist),
                  color: _inWishlist ? Colors.red.shade400 : Colors.white,
                  size: 24,
                ),
              ),
              onPressed: () async {
                if (widget.userEmail.isEmpty) {
                  _snack('Please log in to add to wishlist');
                  return;
                }
                final wasInWishlist = _inWishlist;
                await _toggleWishlist();
                if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                  content: Text(wasInWishlist ? 'Removed from wishlist' : 'Added to wishlist'),
                  backgroundColor: wasInWishlist ? Colors.red.shade600 : _primary,
                  behavior: SnackBarBehavior.floating,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ));
              },
            ),
    ],
  );

  // ─── Image Section ────────────────────────────────────────────────────────
  Widget _imageSection() => Stack(children: [
    ProductImageCarousel(
      imageString: _rawImage,
      height: 320,
      borderRadius: 0,
      placeholder: Icons.checkroom_outlined,
      initialPage: _imageIndex,
    ),
    // Out of stock overlay
    if (!_inStock)
      Positioned.fill(child: Container(
        color: Colors.black.withOpacity(0.5),
        child: const Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.cancel_outlined, color: Colors.white70, size: 48),
          SizedBox(height: 8),
          Text('OUT OF STOCK', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800,
            fontSize: 18, letterSpacing: 2)),
        ])),
      )),
    // Promo badge
    if (p!.salePrice != null)
      Positioned(top: 12, right: 12,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(gradient: _goldGrad, borderRadius: BorderRadius.circular(14),
            boxShadow: [BoxShadow(color: _gold.withOpacity(0.4), blurRadius: 8)]),
          child: Text('-${p!.discountPercent?.round()}%',
            style: const TextStyle(color: _primary, fontWeight: FontWeight.w800, fontSize: 12)),
        ),
      ),
  ]);

  // ─── Info Section ─────────────────────────────────────────────────────────
  Widget _infoSection() => Container(
    color: Colors.white,
    padding: const EdgeInsets.fromLTRB(16, 18, 16, 16),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(p!.name, style: const TextStyle(color: _accent, fontSize: 20, fontWeight: FontWeight.w800, letterSpacing: -0.5)),
      const SizedBox(height: 8),
      // Price
      if (p!.salePrice != null) ...[
        Row(children: [
          ShaderMask(
            shaderCallback: (b) => _goldGrad.createShader(b),
            child: Text('₱${p!.salePrice!.toStringAsFixed(2)}',
              style: const TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.w900)),
          ),
          const SizedBox(width: 10),
          Text('₱${p!.price.toStringAsFixed(2)}',
            style: TextStyle(color: _textLight.withOpacity(0.7), fontSize: 15,
              decoration: TextDecoration.lineThrough)),
          const SizedBox(width: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(color: _gold.withOpacity(0.12), borderRadius: BorderRadius.circular(8),
              border: Border.all(color: _gold.withOpacity(0.3))),
            child: Text('Save ₱${(p!.price - p!.salePrice!).toStringAsFixed(2)}',
              style: const TextStyle(color: _gold, fontSize: 11, fontWeight: FontWeight.w700)),
          ),
        ]),
      ] else
        ShaderMask(
          shaderCallback: (b) => _goldGrad.createShader(b),
          child: Text('₱${p!.price.toStringAsFixed(2)}',
            style: const TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.w900)),
        ),
      const SizedBox(height: 10),
      // Rating
      Row(children: [
        ...List.generate(5, (i) => Icon(
          i < p!.rating.floor() ? Icons.star
            : (i < p!.rating ? Icons.star_half : Icons.star_border),
          color: _gold, size: 16)),
        const SizedBox(width: 6),
        Text('${p!.rating.toStringAsFixed(1)} (${p!.reviewCount} reviews)',
          style: const TextStyle(color: _textLight, fontSize: 12)),
      ]),
      const SizedBox(height: 12),
      // Description
      Text(p!.description, style: const TextStyle(color: _textLight, fontSize: 13, height: 1.6)),
    ]),
  );

  // ─── Color Section ────────────────────────────────────────────────────────
  Widget _colorSection() => _card(
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        const Text('Color: ', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 14)),
        if (_selectedColor != null)
          Text(_selectedColor!, style: const TextStyle(color: _gold, fontWeight: FontWeight.w700, fontSize: 14))
        else
          const Text('None selected', style: TextStyle(color: _textLight, fontSize: 13)),
      ]),
      const SizedBox(height: 12),
      Wrap(spacing: 10, runSpacing: 10,
        children: p!.colors.map((color) {
          final selected = _selectedColor == color;
          final imageUrl = _colorImages[color.toLowerCase()];
          return GestureDetector(
            onTap: () {
              setState(() { _selectedColor = color; _selectedSize = null; });
              _qtyCtrl.text = '1';
              _quantity = 1;
              // Jump carousel to this color's image
              if (imageUrl != null && _rawImage != null) {
                final urls = _rawImage!.split(',').map((e) => e.trim()).toList();
                final idx = urls.indexWhere((u) => u == imageUrl || u.endsWith(imageUrl.split('/').last));
                if (idx >= 0) setState(() => _imageIndex = idx);
              }
            },
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              width: 64, height: 64,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: selected ? _gold : _border,
                  width: selected ? 2.5 : 1.5,
                ),
                boxShadow: selected ? [BoxShadow(color: _gold.withOpacity(0.35), blurRadius: 8)] : [],
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(10),
                child: imageUrl != null
                    ? Stack(children: [
                        Image.network(
                          imageUrl,
                          width: 64, height: 64,
                          fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) => _colorFallback(color, selected),
                        ),
                        // Color name label at bottom
                        Positioned(
                          bottom: 0, left: 0, right: 0,
                          child: Container(
                            padding: const EdgeInsets.symmetric(vertical: 3),
                            color: Colors.black.withOpacity(0.45),
                            child: Text(color,
                              style: const TextStyle(color: Colors.white, fontSize: 8, fontWeight: FontWeight.w700),
                              textAlign: TextAlign.center, maxLines: 1, overflow: TextOverflow.ellipsis),
                          ),
                        ),
                        if (selected)
                          Positioned(top: 4, right: 4,
                            child: Container(
                              width: 16, height: 16,
                              decoration: const BoxDecoration(color: _gold, shape: BoxShape.circle),
                              child: const Icon(Icons.check, color: _primary, size: 10),
                            ),
                          ),
                      ])
                    : _colorFallback(color, selected),
              ),
            ),
          );
        }).toList(),
      ),
    ]),
  );

  Widget _colorFallback(String color, bool selected) => Container(
    width: 64, height: 64,
    decoration: BoxDecoration(
      gradient: selected ? _goldGrad : null,
      color: selected ? null : _bg,
      borderRadius: BorderRadius.circular(10),
    ),
    child: Center(child: Text(color,
      style: TextStyle(color: selected ? _primary : _accent,
        fontSize: 9, fontWeight: FontWeight.w700),
      textAlign: TextAlign.center, maxLines: 2, overflow: TextOverflow.ellipsis)),
  );

  // ─── Size Section ─────────────────────────────────────────────────────────
  Widget _sizeSection() => _card(
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        const Text('Size: ', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 14)),
        if (_selectedSize != null)
          Text(_selectedSize!, style: const TextStyle(color: _gold, fontWeight: FontWeight.w700, fontSize: 14))
        else
          const Text('None selected', style: TextStyle(color: _textLight, fontSize: 13)),
      ]),
      const SizedBox(height: 12),
      p!.sizes.isEmpty
        ? const Text('No sizes available', style: TextStyle(color: _textLight, fontSize: 13))
        : Wrap(spacing: 10, runSpacing: 10,
            children: p!.sizes.map((size) {
              final selected = _selectedSize == size;
              final variantKey = _selectedColor != null
                  ? '${_selectedColor!.toLowerCase()}|${size.toLowerCase()}'
                  : null;
              final variantQty = variantKey != null ? (_variantStock[variantKey] ?? 0) : -1;
              final isOutOfStock = variantKey != null && variantQty <= 0;
              return GestureDetector(
                onTap: isOutOfStock ? null : () {
                  setState(() { _selectedSize = size; _quantity = 1; });
                  _qtyCtrl.text = '1';
                },
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                  decoration: BoxDecoration(
                    gradient: selected ? _goldGrad : null,
                    color: selected ? null : (isOutOfStock ? const Color(0xFFF5F5F5) : _bg),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: selected ? _gold : (isOutOfStock ? const Color(0xFFE0E0E0) : _border),
                      width: selected ? 2 : 1.5,
                    ),
                    boxShadow: selected ? [BoxShadow(color: _gold.withOpacity(0.3), blurRadius: 8)] : [],
                  ),
                  child: Stack(clipBehavior: Clip.none, children: [
                    Text(size, style: TextStyle(
                      color: selected ? _primary : (isOutOfStock ? const Color(0xFFBDBDBD) : _accent),
                      fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
                      fontSize: 13,
                      decoration: isOutOfStock ? TextDecoration.lineThrough : null,
                    )),
                    if (isOutOfStock)
                      Positioned(
                        top: -4, right: -4,
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 3, vertical: 1),
                          decoration: BoxDecoration(
                            color: Colors.red.shade400,
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: const Text('×', style: TextStyle(color: Colors.white, fontSize: 8, fontWeight: FontWeight.w900)),
                        ),
                      ),
                  ]),
                ),
              );
            }).toList(),
          ),
    ]),
  );

  // ─── Quantity Section ─────────────────────────────────────────────────────
  Widget _quantitySection() {
    final max = _maxQty;
    final hasVariant = _selectedColor != null && _selectedSize != null;
    final atMax = max > 0 && _quantity >= max;
    final atMin = _quantity <= 1;

    // Stock label
    String stockLabel;
    Color stockColor;
    IconData stockIcon;
    if (!hasVariant) {
      stockLabel = 'Select color & size to see stock';
      stockColor = _textLight;
      stockIcon = Icons.info_outline;
    } else if (max <= 0) {
      stockLabel = 'Out of stock for this variant';
      stockColor = Colors.red;
      stockIcon = Icons.cancel_outlined;
    } else {
      stockLabel = '$max in stock';
      stockColor = max <= 3 ? Colors.orange.shade700 : Colors.green.shade600;
      stockIcon = Icons.inventory_2_outlined;
    }

    return _card(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Text('Quantity:', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 14)),
          const Spacer(),

          // ── Minus ──────────────────────────────────────────────────────
          _qtyBtn(
            icon: Icons.remove,
            enabled: !atMin,
            onTap: () => _setQuantity(_quantity - 1),
          ),

          // ── Typeable field ─────────────────────────────────────────────
          SizedBox(
            width: 60,
            child: TextField(
              controller: _qtyCtrl,
              keyboardType: TextInputType.number,
              textAlign: TextAlign.center,
              enabled: max > 0,
              style: TextStyle(
                color: max > 0 ? _accent : _textLight,
                fontWeight: FontWeight.w800,
                fontSize: 16,
              ),
              decoration: InputDecoration(
                contentPadding: const EdgeInsets.symmetric(vertical: 10),
                isDense: true,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: BorderSide(color: _border),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: BorderSide(color: atMax ? _gold.withOpacity(0.6) : _border),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: const BorderSide(color: _gold, width: 2),
                ),
                disabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: BorderSide(color: _border.withOpacity(0.5)),
                ),
                filled: true,
                fillColor: max > 0 ? Colors.white : const Color(0xFFF5F5F5),
              ),
              onChanged: (val) {
                final parsed = int.tryParse(val);
                if (parsed == null) return;
                final clamped = parsed.clamp(1, max > 0 ? max : 9999);
                if (clamped != _quantity) {
                  setState(() => _quantity = clamped);
                  if (clamped != parsed) {
                    // Correct the field if out of range
                    _qtyCtrl.text = '$clamped';
                    _qtyCtrl.selection = TextSelection.collapsed(offset: _qtyCtrl.text.length);
                  }
                }
              },
              onSubmitted: (val) {
                final parsed = int.tryParse(val) ?? 1;
                _setQuantity(parsed.clamp(1, max > 0 ? max : 9999));
              },
            ),
          ),

          // ── Plus ───────────────────────────────────────────────────────
          _qtyBtn(
            icon: Icons.add,
            enabled: max > 0 && !atMax,
            onTap: () => _setQuantity(_quantity + 1),
          ),
        ]),

        const SizedBox(height: 10),

        // ── Stock label ────────────────────────────────────────────────
        Row(children: [
          Icon(stockIcon, size: 13, color: stockColor),
          const SizedBox(width: 5),
          Text(stockLabel, style: TextStyle(fontSize: 11, color: stockColor, fontWeight: FontWeight.w600)),
          if (hasVariant && max > 0 && atMax) ...[
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
              decoration: BoxDecoration(
                color: _gold.withOpacity(0.12),
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: _gold.withOpacity(0.4)),
              ),
              child: const Text('Max reached', style: TextStyle(color: _gold, fontSize: 10, fontWeight: FontWeight.w700)),
            ),
          ],
        ]),
      ]),
    );
  }

  Widget _qtyBtn({required IconData icon, required bool enabled, required VoidCallback onTap}) {
    return GestureDetector(
      onTap: enabled ? onTap : null,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        width: 36, height: 36,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: enabled ? _border : _border.withOpacity(0.4)),
          color: enabled ? Colors.white : const Color(0xFFF5F5F5),
          boxShadow: enabled
              ? [BoxShadow(color: Colors.black.withOpacity(0.06), blurRadius: 4, offset: const Offset(0, 2))]
              : [],
        ),
        child: Icon(icon, size: 18, color: enabled ? _accent : _textLight.withOpacity(0.4)),
      ),
    );
  }

  // ─── Seller Section ───────────────────────────────────────────────────────
  Widget _sellerSection() => _card(
    child: Row(children: [
      // Avatar: profile picture or initial fallback
      Container(
        width: 44, height: 44,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: p!.sellerPicture == null ? _goldGrad : null,
          boxShadow: [BoxShadow(color: _gold.withOpacity(0.3), blurRadius: 8)],
        ),
        clipBehavior: Clip.antiAlias,
        child: p!.sellerPicture != null && p!.sellerPicture!.isNotEmpty
            ? Image.network(
                _resolveSellerPicture(p!.sellerPicture!),
                fit: BoxFit.cover,
                errorBuilder: (_, __, ___) => _sellerInitial(),
              )
            : _sellerInitial(),
      ),
      const SizedBox(width: 12),
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(p!.sellerName, style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 14),
          maxLines: 1, overflow: TextOverflow.ellipsis),
        const Text('Official Store', style: TextStyle(color: _textLight, fontSize: 11)),
      ])),
      _outlineBtn(Icons.store_outlined, 'View Shop', () {
        Navigator.push(context, MaterialPageRoute(
          builder: (_) => BuyerViewShopPage(
            userEmail: widget.userEmail,
            sellerEmail: p!.sellerEmail,
          ),
        ));
      }),
    ]),
  );

  Widget _sellerInitial() => Center(
    child: Text(
      p!.sellerName.isNotEmpty ? p!.sellerName[0].toUpperCase() : 'S',
      style: const TextStyle(color: _primary, fontWeight: FontWeight.w800, fontSize: 18),
    ),
  );

  String _resolveSellerPicture(String pic) {
    if (pic.startsWith('http://') || pic.startsWith('https://')) return pic;
    return '$kFlaskBaseUrl/static/uploads/$pic';
  }

  Widget _outlineBtn(IconData icon, String label, VoidCallback onTap) => GestureDetector(
    onTap: onTap,
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _border),
        color: _bg,
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 13, color: _accent),
        const SizedBox(width: 4),
        Text(label, style: const TextStyle(color: _accent, fontSize: 11, fontWeight: FontWeight.w600)),
      ]),
    ),
  );

  // ─── Reviews Section ──────────────────────────────────────────────────────
  Widget _reviewsSection() => Container(
    margin: const EdgeInsets.fromLTRB(12, 0, 12, 0),
    padding: const EdgeInsets.all(18),
    decoration: BoxDecoration(
      color: Colors.white, borderRadius: BorderRadius.circular(16),
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.06), blurRadius: 12, offset: const Offset(0, 3))],
    ),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        const Icon(Icons.star, color: _gold, size: 18),
        const SizedBox(width: 8),
        const Text('Customer Reviews', style: TextStyle(color: _accent, fontSize: 15, fontWeight: FontWeight.w800)),
      ]),
      const SizedBox(height: 4),
      Container(width: 36, height: 3, decoration: BoxDecoration(borderRadius: BorderRadius.circular(2), gradient: _goldGrad)),
      const SizedBox(height: 16),
      // Rating summary
      Row(children: [
        Column(children: [
          Text(p!.rating.toStringAsFixed(1),
            style: const TextStyle(color: _accent, fontSize: 40, fontWeight: FontWeight.w900)),
          Row(children: List.generate(5, (i) => Icon(
            i < p!.rating.floor() ? Icons.star : Icons.star_border, color: _gold, size: 14))),
          const SizedBox(height: 4),
          Text('${p!.reviewCount} reviews', style: const TextStyle(color: _textLight, fontSize: 11)),
        ]),
        const SizedBox(width: 20),
        Expanded(child: Column(
          children: [5, 4, 3, 2, 1].map((star) {
            final frac = p!.reviewCount > 0 ? (star == 5 ? 0.6 : star == 4 ? 0.25 : 0.1) : 0.0;
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(children: [
                Text('$star', style: const TextStyle(color: _textLight, fontSize: 11)),
                const SizedBox(width: 4),
                const Icon(Icons.star, color: _gold, size: 10),
                const SizedBox(width: 6),
                Expanded(child: ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                    value: frac, minHeight: 6,
                    backgroundColor: _border,
                    valueColor: const AlwaysStoppedAnimation<Color>(_gold),
                  ),
                )),
              ]),
            );
          }).toList(),
        )),
      ]),
      const Divider(height: 28),
      // Review list
      if (p!.reviews.isEmpty)
        const Center(child: Column(children: [
          Icon(Icons.chat_bubble_outline, size: 48, color: _border),
          SizedBox(height: 8),
          Text('No Reviews Yet', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 15)),
          SizedBox(height: 4),
          Text('Be the first to review this product!', style: TextStyle(color: _textLight, fontSize: 12)),
        ]))
      else
        ...p!.reviews.map((r) => _reviewTile(r)),
    ]),
  );

  Widget _reviewTile(ReviewItem r) => Padding(
    padding: const EdgeInsets.only(bottom: 16),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Container(
          width: 36, height: 36,
          decoration: BoxDecoration(shape: BoxShape.circle, gradient: _premiumGrad),
          child: Center(child: Text(r.reviewer[0].toUpperCase(),
            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 14))),
        ),
        const SizedBox(width: 10),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(r.reviewer, style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
          Text(r.date, style: const TextStyle(color: _textLight, fontSize: 11)),
        ])),
        Row(children: List.generate(5, (i) => Icon(
          i < r.rating ? Icons.star : Icons.star_border, color: _gold, size: 13))),
      ]),
      const SizedBox(height: 8),
      Text(r.text, style: const TextStyle(color: _textLight, fontSize: 13, height: 1.5)),
      if (r.sellerResponse != null) ...[
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: _gold.withOpacity(0.06), borderRadius: BorderRadius.circular(10),
            border: Border.all(color: _gold.withOpacity(0.2)),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Row(children: [
              Icon(Icons.store_outlined, size: 13, color: _gold),
              SizedBox(width: 5),
              Text('Seller Response', style: TextStyle(color: _gold, fontWeight: FontWeight.w700, fontSize: 12)),
            ]),
            const SizedBox(height: 4),
            Text(r.sellerResponse!, style: const TextStyle(color: _textLight, fontSize: 12, height: 1.4)),
          ]),
        ),
      ],
      const Divider(height: 20),
    ]),
  );

  // ─── Bottom Actions ───────────────────────────────────────────────────────
  Widget _bottomActions() => Container(
    padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
    decoration: BoxDecoration(
      color: Colors.white,
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.1), blurRadius: 16, offset: const Offset(0, -4))],
    ),
    child: SafeArea(
      child: Row(children: [
        // Add to Cart
        Expanded(child: GestureDetector(
          onTap: !_inStock ? null : () async {
            if (_selectedColor == null && p!.colors.isNotEmpty) { _snack('Please select a color'); return; }
            if (p!.sizes.isNotEmpty && _selectedSize == null) { _snack('Please select a size'); return; }
            // Require login
            if (widget.userEmail.isEmpty) {
              _snack('Please log in to add items to cart');
              return;
            }
            try {
              final result = await BuyerService.addToCart(
                email:       widget.userEmail,
                productId:   int.tryParse(p!.id) ?? 0,
                name:        p!.name,
                price:       p!.salePrice ?? p!.price,
                sellerEmail: p!.sellerEmail,
                color:       _selectedColor,
                size:        _selectedSize,
                quantity:    _quantity,
                image:       _selectedColor != null
                    ? (_colorImages[_selectedColor!.toLowerCase()] ?? _rawImage?.split(',').first.trim())
                    : _rawImage?.split(',').first.trim(),
              );
              if (mounted) {
                if (result.stockCapped && !result.added) {
                  _snack(result.message);
                } else {
                  _snack(result.stockCapped
                      ? '${result.message} — max stock reached'
                      : 'Added to cart!', success: true);
                  Future.delayed(const Duration(milliseconds: 800), () {
                    if (mounted) {
                      Navigator.push(context, MaterialPageRoute(
                        builder: (_) => BuyerCartPage(userEmail: widget.userEmail),
                      ));
                    }
                  });
                }
              }
            } catch (e) {
              _snack('Failed to add to cart');
            }
          },
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 14),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: _inStock ? _primary : _border, width: 2),
              color: _inStock ? Colors.white : _bg,
            ),
            child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              Icon(Icons.shopping_cart_outlined, color: _inStock ? _primary : _textLight, size: 16),
              const SizedBox(width: 6),
              Text('Add to Cart', style: TextStyle(
                color: _inStock ? _primary : _textLight, fontWeight: FontWeight.w700, fontSize: 13)),
            ]),
          ),
        )),
        const SizedBox(width: 12),
        // Buy Now
        Expanded(child: GestureDetector(
          onTap: !_inStock ? null : () {
            if (_selectedColor == null && p!.colors.isNotEmpty) { _snack('Please select a color'); return; }
            if (p!.sizes.isNotEmpty && _selectedSize == null) { _snack('Please select a size'); return; }
            Navigator.push(context, MaterialPageRoute(builder: (_) => BuyerCheckoutPage(
              userEmail: widget.userEmail,
              items: [CheckoutItem(
                id: p!.id, name: p!.name,
                price: p!.salePrice ?? p!.price,
                quantity: _quantity,
                color: _selectedColor,
                size: _selectedSize,
                productId: int.tryParse(p!.id),
                image: _selectedColor != null
                    ? (_colorImages[_selectedColor!.toLowerCase()] ?? _rawImage?.split(',').first.trim())
                    : _rawImage?.split(',').first.trim(),
              )],
            )));
          },
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 14),
            decoration: BoxDecoration(
              gradient: _inStock ? _premiumGrad : null,
              color: _inStock ? null : const Color(0xFFCED4DA),
              borderRadius: BorderRadius.circular(14),
              boxShadow: _inStock ? [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 10, offset: const Offset(0, 4))] : [],
            ),
            child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              Icon(Icons.bolt, color: _inStock ? _gold : Colors.white, size: 16),
              const SizedBox(width: 6),
              Text(_inStock ? 'Buy Now' : 'Out of Stock',
                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13)),
            ]),
          ),
        )),
      ]),
    ),
  );

  // ─── Shared ───────────────────────────────────────────────────────────────
  Widget _card({required Widget child}) => Container(
    margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: Colors.white, borderRadius: BorderRadius.circular(16),
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, 3))],
    ),
    child: child,
  );

  void _snack(String msg, {bool success = false}) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(msg), backgroundColor: success ? _primary : Colors.red.shade600,
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
    ));
  }
}
