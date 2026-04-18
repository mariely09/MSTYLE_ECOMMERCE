import 'package:flutter/material.dart';
import 'supabase_client.dart' show supabase, supabaseAdminSelect;
import 'product_image_carousel.dart' show buildImageUrl, kFlaskBaseUrl;
import 'buyer_viewproduct.dart';

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

class BuyerViewShopPage extends StatefulWidget {
  final String userEmail;
  final String sellerEmail;

  const BuyerViewShopPage({
    super.key,
    required this.userEmail,
    required this.sellerEmail,
  });

  @override
  State<BuyerViewShopPage> createState() => _BuyerViewShopPageState();
}

class _BuyerViewShopPageState extends State<BuyerViewShopPage> {
  bool _loading = true;
  String? _error;

  // Seller info
  String _sellerName    = '';
  String? _sellerPicture;
  String _sellerPhone   = '';

  // Stats
  double _rating        = 0;
  int    _totalRatings  = 0;
  int    _totalProducts = 0;
  int    _totalSold     = 0;

  // Products
  List<Map<String, dynamic>> _products = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      // ── 1. Seller info (admin REST call bypasses RLS) ──────────────
      final sellerRows = await supabaseAdminSelect(
        table: 'users',
        select: 'business_name,first_name,last_name,profile_picture,phone',
        filters: {'email': widget.sellerEmail},
        limit: 1,
      );

      if (sellerRows.isEmpty) {
        setState(() { _loading = false; _error = 'Seller not found'; });
        return;
      }
      final s = sellerRows[0];
      final biz   = (s['business_name'] as String? ?? '').trim();
      final first = (s['first_name']    as String? ?? '').trim();
      final last  = (s['last_name']     as String? ?? '').trim();
      _sellerName    = biz.isNotEmpty ? biz : '$first $last'.trim().isNotEmpty ? '$first $last'.trim() : widget.sellerEmail;
      _sellerPicture = (s['profile_picture'] as String? ?? '').trim().isNotEmpty
          ? (s['profile_picture'] as String).trim()
          : null;
      _sellerPhone   = (s['phone'] as String? ?? '').trim();

      // ── 2. Products (admin call to get all seller products) ─────────
      final prodRows = await supabaseAdminSelect(
        table: 'products',
        select: 'id,name,category,description,price,image,quantity,sold,rating,seller_email,variations,sizes,image_colors',
        filters: {'seller_email': widget.sellerEmail},
      );

      _products = prodRows;
      _totalProducts = _products.length;
      _totalSold = _products.fold(0, (sum, p) => sum + ((p['sold'] as num?)?.toInt() ?? 0));

      // Sort by sold desc
      _products.sort((a, b) => ((b['sold'] as num?)?.toInt() ?? 0).compareTo((a['sold'] as num?)?.toInt() ?? 0));

      // ── 3. Seller rating from reviews ───────────────────────────────
      try {
        final reviewRows = await supabaseAdminSelect(
          table: 'reviews',
          select: 'rating',
          filters: {'seller_email': widget.sellerEmail},
        );
        if (reviewRows.isNotEmpty) {
          _totalRatings = reviewRows.length;
          _rating = reviewRows.fold(0.0, (sum, r) => sum + ((r['rating'] as num?)?.toDouble() ?? 0)) / _totalRatings;
        }
      } catch (_) {}

      setState(() => _loading = false);
    } catch (e) {
      setState(() { _loading = false; _error = e.toString(); });
    }
  }

  String _resolveImage(String? pic) {
    if (pic == null || pic.isEmpty) return '';
    if (pic.startsWith('http://') || pic.startsWith('https://')) return pic;
    return '$kFlaskBaseUrl/static/uploads/$pic';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: _gold))
          : _error != null
              ? _errorState()
              : CustomScrollView(
                  slivers: [
                    _appBar(),
                    SliverToBoxAdapter(child: _shopHeader()),
                    SliverToBoxAdapter(child: _statsRow()),
                    SliverToBoxAdapter(child: _sectionTitle('Products')),
                    _productGrid(),
                    const SliverToBoxAdapter(child: SizedBox(height: 32)),
                  ],
                ),
    );
  }

  // ── App Bar ────────────────────────────────────────────────────────────────
  SliverAppBar _appBar() => SliverAppBar(
    pinned: true,
    backgroundColor: _primary,
    leading: IconButton(
      icon: const Icon(Icons.arrow_back, color: Colors.white),
      onPressed: () => Navigator.pop(context),
    ),
    title: Text(_sellerName,
      style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700),
      maxLines: 1, overflow: TextOverflow.ellipsis),
  );

  // ── Shop Header ────────────────────────────────────────────────────────────
  Widget _shopHeader() => Container(
    width: double.infinity,
    padding: const EdgeInsets.fromLTRB(20, 28, 20, 24),
    decoration: const BoxDecoration(gradient: _premiumGrad),
    child: Column(children: [
      // Avatar
      Container(
        width: 80, height: 80,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: _sellerPicture == null ? _goldGrad : null,
          boxShadow: [BoxShadow(color: _gold.withOpacity(0.4), blurRadius: 16)],
        ),
        clipBehavior: Clip.antiAlias,
        child: _sellerPicture != null
            ? Image.network(
                _resolveImage(_sellerPicture),
                fit: BoxFit.cover,
                errorBuilder: (_, __, ___) => _avatarInitial(size: 80),
              )
            : _avatarInitial(size: 80),
      ),
      const SizedBox(height: 14),
      Text(_sellerName,
        style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w800, letterSpacing: -0.5),
        textAlign: TextAlign.center),
      const SizedBox(height: 4),
      Text('Official Store',
        style: TextStyle(color: Colors.white.withOpacity(0.65), fontSize: 13)),
      if (_sellerPhone.isNotEmpty) ...[
        const SizedBox(height: 6),
        Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          Icon(Icons.phone_outlined, color: Colors.white.withOpacity(0.6), size: 13),
          const SizedBox(width: 5),
          Text(_sellerPhone, style: TextStyle(color: Colors.white.withOpacity(0.7), fontSize: 12)),
        ]),
      ],
      // Rating stars
      if (_rating > 0) ...[
        const SizedBox(height: 10),
        Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          ...List.generate(5, (i) => Icon(
            i < _rating.floor() ? Icons.star : (i < _rating ? Icons.star_half : Icons.star_border),
            color: _gold, size: 16)),
          const SizedBox(width: 6),
          Text('${_rating.toStringAsFixed(1)} ($_totalRatings reviews)',
            style: TextStyle(color: Colors.white.withOpacity(0.8), fontSize: 12)),
        ]),
      ],
    ]),
  );

  Widget _avatarInitial({double size = 44}) => Container(
    width: size, height: size,
    decoration: const BoxDecoration(shape: BoxShape.circle, gradient: _goldGrad),
    child: Center(child: Text(
      _sellerName.isNotEmpty ? _sellerName[0].toUpperCase() : 'S',
      style: TextStyle(color: _primary, fontWeight: FontWeight.w800, fontSize: size * 0.4),
    )),
  );

  // ── Stats Row ──────────────────────────────────────────────────────────────
  Widget _statsRow() => Container(
    color: Colors.white,
    padding: const EdgeInsets.symmetric(vertical: 16),
    child: Row(children: [
      _statItem('$_totalProducts', 'Products'),
      _divider(),
      _statItem('$_totalSold', 'Sold'),
      _divider(),
      _statItem(_rating > 0 ? _rating.toStringAsFixed(1) : '—', 'Rating'),
    ]),
  );

  Widget _statItem(String value, String label) => Expanded(
    child: Column(children: [
      Text(value, style: const TextStyle(color: _accent, fontSize: 18, fontWeight: FontWeight.w800)),
      const SizedBox(height: 2),
      Text(label, style: const TextStyle(color: _textLight, fontSize: 11)),
    ]),
  );

  Widget _divider() => Container(width: 1, height: 32, color: _border);

  // ── Section Title ──────────────────────────────────────────────────────────
  Widget _sectionTitle(String title) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 20, 16, 10),
    child: Row(children: [
      Container(width: 4, height: 18, decoration: BoxDecoration(gradient: _goldGrad, borderRadius: BorderRadius.circular(2))),
      const SizedBox(width: 8),
      Text(title, style: const TextStyle(color: _accent, fontSize: 15, fontWeight: FontWeight.w800)),
    ]),
  );

  // ── Product Grid ───────────────────────────────────────────────────────────
  Widget _productGrid() {
    if (_products.isEmpty) {
      return SliverToBoxAdapter(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(40),
            child: Column(children: [
              const Icon(Icons.inventory_2_outlined, size: 48, color: _border),
              const SizedBox(height: 12),
              const Text('No products yet', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 15)),
              const SizedBox(height: 4),
              Text('This shop has no products listed.', style: const TextStyle(color: _textLight, fontSize: 12)),
            ]),
          ),
        ),
      );
    }

    return SliverPadding(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      sliver: SliverGrid(
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: 2,
          mainAxisSpacing: 12,
          crossAxisSpacing: 12,
          childAspectRatio: 0.72,
        ),
        delegate: SliverChildBuilderDelegate(
          (_, i) => _productCard(_products[i]),
          childCount: _products.length,
        ),
      ),
    );
  }

  Widget _productCard(Map<String, dynamic> product) {
    final id       = product['id'];
    final name     = product['name'] as String? ?? '';
    final price    = (product['price'] as num?)?.toDouble() ?? 0;
    final rating   = (product['rating'] as num?)?.toDouble() ?? 0;
    final sold     = (product['sold'] as num?)?.toInt() ?? 0;
    final imageRaw = product['image'] as String?;
    final imageUrl = buildImageUrl(imageRaw?.split(',').first.trim());
    final inStock  = ((product['quantity'] as num?)?.toInt() ?? 0) > 0;

    return GestureDetector(
      onTap: () => Navigator.push(context, MaterialPageRoute(
        builder: (_) => BuyerViewProductPage(
          userEmail: widget.userEmail,
          productId: id is int ? id : int.tryParse('$id'),
        ),
      )),
      child: Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(14),
          boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.06), blurRadius: 10, offset: const Offset(0, 3))],
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          // Image
          ClipRRect(
            borderRadius: const BorderRadius.vertical(top: Radius.circular(14)),
            child: Stack(children: [
              imageUrl != null
                  ? Image.network(imageUrl,
                      height: 140, width: double.infinity, fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => _imagePlaceholder())
                  : _imagePlaceholder(),
              if (!inStock)
                Positioned.fill(child: Container(
                  color: Colors.black.withOpacity(0.45),
                  child: const Center(child: Text('OUT OF STOCK',
                    style: TextStyle(color: Colors.white, fontSize: 9, fontWeight: FontWeight.w800, letterSpacing: 1))),
                )),
            ]),
          ),
          // Info
          Padding(
            padding: const EdgeInsets.all(10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(name,
                style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 12),
                maxLines: 2, overflow: TextOverflow.ellipsis),
              const SizedBox(height: 5),
              Text('₱${price.toStringAsFixed(2)}',
                style: const TextStyle(color: _gold, fontWeight: FontWeight.w800, fontSize: 14)),
              const SizedBox(height: 4),
              Row(children: [
                Icon(Icons.star, color: _gold, size: 11),
                const SizedBox(width: 3),
                Text(rating > 0 ? rating.toStringAsFixed(1) : '—',
                  style: const TextStyle(color: _textLight, fontSize: 10)),
                const SizedBox(width: 6),
                Text('$sold sold', style: const TextStyle(color: _textLight, fontSize: 10)),
              ]),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _imagePlaceholder() => Container(
    height: 140, width: double.infinity,
    color: const Color(0xFFECEFF1),
    child: const Center(child: Icon(Icons.image_outlined, color: Color(0xFFADB5BD), size: 32)),
  );

  Widget _errorState() => Center(
    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
      const Icon(Icons.error_outline, size: 48, color: _textLight),
      const SizedBox(height: 12),
      Text(_error ?? 'Something went wrong', style: const TextStyle(color: _textLight)),
      const SizedBox(height: 16),
      GestureDetector(
        onTap: _load,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(10)),
          child: const Text('Retry', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
        ),
      ),
    ]),
  );
}
