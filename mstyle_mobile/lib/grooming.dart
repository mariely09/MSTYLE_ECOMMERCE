import 'package:flutter/material.dart';
import 'footer.dart';
import 'login.dart';
import 'buyer_scaffold.dart';
import 'buyer_viewproduct.dart';
import 'buyer_checkout.dart';
import 'buyer_service.dart';
import 'product_image_carousel.dart';
import 'product_card.dart';

const Color _primary   = Color(0xFF1a1a1a);
const Color _accent    = Color(0xFF2c3e50);
const Color _gold      = Color(0xFFd4af37);
const Color _goldLight = Color(0xFFF4D03F);
const Color _textLight = Color(0xFF6c757d);
const Color _bg        = Color(0xFFF8F9FA);
const Color _border    = Color(0xFFE9ECEF);

const _premiumGrad = LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [_primary, _accent]);
const _goldGrad    = LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [_gold, _goldLight]);

// Grooming has Sort By only (no Category filter — same as HTML)
const _categories  = ['All Categories', 'GROOMING'];
const _sortOptions = ['Default', 'Price: Low to High', 'Price: High to Low', 'Name: A to Z', 'Name: Z to A', 'Newest First'];

class GroomingPage extends StatefulWidget {
  final String? userEmail;
  const GroomingPage({super.key, this.userEmail});
  @override
  State<GroomingPage> createState() => _GroomingPageState();
}

class _GroomingPageState extends State<GroomingPage> {
  String _selectedCategory = 'All Categories';
  String _selectedSort     = 'Default';
  int    _heroSlide        = 0;

  List<Map<String, dynamic>> _products = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadProducts();
  }

  Future<void> _loadProducts() async {
    try {
      final data = await BuyerService.getProducts(
        categories: ['GROOMING'],
        limit: 50,
      );
      if (mounted) setState(() { _products = data; _loading = false; });
    } catch (e) {
      debugPrint('_loadProducts error: $e');
      if (mounted) setState(() { _loading = false; _error = e.toString(); });
    }
  }

  List<Map<String, dynamic>> get _filteredProducts {
    var list = List<Map<String, dynamic>>.from(_products);
    if (_selectedCategory != 'All Categories') {
      list = list.where((p) => (p['category'] as String?) == _selectedCategory).toList();
    }
    switch (_selectedSort) {
      case 'Price: Low to High':  list.sort((a, b) => ((a['price'] as num?) ?? 0).compareTo((b['price'] as num?) ?? 0)); break;
      case 'Price: High to Low':  list.sort((a, b) => ((b['price'] as num?) ?? 0).compareTo((a['price'] as num?) ?? 0)); break;
      case 'Name: A to Z':        list.sort((a, b) => (a['name'] as String).compareTo(b['name'] as String)); break;
      case 'Name: Z to A':        list.sort((a, b) => (b['name'] as String).compareTo(a['name'] as String)); break;
      case 'Newest First':        list.sort((a, b) => ((b['id'] as num?) ?? 0).compareTo((a['id'] as num?) ?? 0)); break;
    }
    return list;
  }

  void _pushLogin() => Navigator.push(context, MaterialPageRoute(builder: (_) => const LoginPage()));

  @override
  Widget build(BuildContext context) {
    return BuyerCategoryScaffold(
      title: 'Grooming Essentials',
      userEmail: widget.userEmail,
      slivers: [
        SliverToBoxAdapter(child: _heroSection()),
        SliverToBoxAdapter(child: _filterSection()),
        SliverToBoxAdapter(child: _productGrid()),
        const SliverToBoxAdapter(child: AppFooter()),
      ],
    );
  }

  SliverAppBar _appBar() => SliverAppBar(
    pinned: true, backgroundColor: _primary, elevation: 6,
    leading: IconButton(icon: const Icon(Icons.arrow_back, color: Colors.white), onPressed: () => Navigator.pop(context)),
    title: ShaderMask(
      shaderCallback: (b) => _goldGrad.createShader(b),
      child: const Text('Grooming Essentials', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w800, letterSpacing: 0.5)),
    ),
    actions: [
      IconButton(icon: const Icon(Icons.search, color: Colors.white, size: 22), onPressed: () {}),
      const SizedBox(width: 4),
    ],
  );

  Widget _heroSection() {
    final slides = [
      {'title': "Men's", 'highlight': 'Grooming Essentials', 'sub': 'Elevate your grooming routine with premium care products.'},
      {'title': 'Care &', 'highlight': 'Style', 'sub': 'Crafted for the modern gentleman.'},
    ];
    final slide = slides[_heroSlide % slides.length];
    return SizedBox(
      height: 380,
      child: Stack(children: [
        Row(children: [
          Expanded(
            flex: 55,
            child: Container(
              decoration: const BoxDecoration(gradient: _premiumGrad),
              padding: const EdgeInsets.fromLTRB(20, 28, 14, 28),
              child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                  decoration: BoxDecoration(gradient: _goldGrad, borderRadius: BorderRadius.circular(20),
                    boxShadow: [BoxShadow(color: _gold.withOpacity(0.35), blurRadius: 10, offset: const Offset(0, 3))]),
                  child: Row(mainAxisSize: MainAxisSize.min, children: const [
                    Icon(Icons.cut, color: _primary, size: 10),
                    SizedBox(width: 4),
                    Text('Premium Grooming Collection', style: TextStyle(color: _primary, fontWeight: FontWeight.w800, fontSize: 8, letterSpacing: 0.8)),
                  ]),
                ),
                const SizedBox(height: 12),
                Text(slide['title']!, style: const TextStyle(color: Colors.white70, fontSize: 14, fontWeight: FontWeight.w400)),
                const SizedBox(height: 3),
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 500),
                  child: ShaderMask(
                    key: ValueKey(_heroSlide),
                    shaderCallback: (b) => _goldGrad.createShader(b),
                    child: Text(slide['highlight']!, style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w900, letterSpacing: -0.5, height: 1.1)),
                  ),
                ),
                const SizedBox(height: 8),
                Container(width: 40, height: 3, decoration: BoxDecoration(borderRadius: BorderRadius.circular(2), gradient: _goldGrad)),
                const SizedBox(height: 10),
                Text(slide['sub']!, style: const TextStyle(color: Colors.white60, fontSize: 10.5, height: 1.5), maxLines: 2, overflow: TextOverflow.ellipsis),
                const SizedBox(height: 16),
                GestureDetector(
                  onTap: () {},
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
                    decoration: BoxDecoration(gradient: _goldGrad, borderRadius: BorderRadius.circular(30),
                      boxShadow: [BoxShadow(color: _gold.withOpacity(0.4), blurRadius: 12, offset: const Offset(0, 4))]),
                    child: Row(mainAxisSize: MainAxisSize.min, children: const [
                      Text('Shop Now', style: TextStyle(color: _primary, fontWeight: FontWeight.w800, fontSize: 12)),
                      SizedBox(width: 6),
                      Icon(Icons.arrow_forward, color: _primary, size: 13),
                    ]),
                  ),
                ),
              ]),
            ),
          ),
          Expanded(
            flex: 45,
            child: Container(
              decoration: const BoxDecoration(
                gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color(0xFF0a1a1a), Color(0xFF1a2d2d)]),
              ),
              child: Stack(alignment: Alignment.center, children: [
                Container(width: 130, height: 130, decoration: BoxDecoration(shape: BoxShape.circle,
                  gradient: RadialGradient(colors: [_gold.withOpacity(0.15), Colors.transparent]))),
                const Icon(Icons.cut, size: 64, color: Color(0xFF2a5a5a)),
                Positioned(top: 16, right: 10,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(gradient: _goldGrad, borderRadius: BorderRadius.circular(14),
                      boxShadow: [BoxShadow(color: _gold.withOpacity(0.4), blurRadius: 8)]),
                    child: const Text('NEW', style: TextStyle(color: _primary, fontWeight: FontWeight.w800, fontSize: 9, letterSpacing: 0.8)),
                  ),
                ),
                Positioned(bottom: 24, left: 10,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    decoration: BoxDecoration(color: _primary.withOpacity(0.85), borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: _gold.withOpacity(0.3))),
                    child: const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('Grooming Essentials', style: TextStyle(color: Colors.white70, fontSize: 8)),
                      Text('From ₱499.00', style: TextStyle(color: _gold, fontWeight: FontWeight.w800, fontSize: 12)),
                    ]),
                  ),
                ),
              ]),
            ),
          ),
        ]),
        Positioned(bottom: 10, left: 0, right: 0,
          child: Row(mainAxisAlignment: MainAxisAlignment.center,
            children: List.generate(slides.length, (i) => GestureDetector(
              onTap: () => setState(() => _heroSlide = i),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 300),
                margin: const EdgeInsets.symmetric(horizontal: 3),
                width: _heroSlide == i ? 20 : 7, height: 7,
                decoration: BoxDecoration(borderRadius: BorderRadius.circular(4),
                  color: _heroSlide == i ? _gold : Colors.white38),
              ),
            )),
          ),
        ),
      ]),
    );
  }

  Widget _filterSection() => Container(
    color: Colors.white,
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    child: Column(children: [
      Row(children: [
        Expanded(child: _filterDropdown(label: 'Sort By', value: _selectedSort, items: _sortOptions,
          onChanged: (v) => setState(() => _selectedSort = v!))),
        const Spacer(),
      ]),
      const SizedBox(height: 10),
      Row(children: [
        const Icon(Icons.inventory_2_outlined, color: _textLight, size: 14),
        const SizedBox(width: 6),
        Text('Showing ${_filteredProducts.length} products', style: const TextStyle(color: _textLight, fontSize: 12)),
      ]),
    ]),
  );

  Widget _filterDropdown({required String label, required String value, required List<String> items, required ValueChanged<String?> onChanged}) =>
    Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label, style: const TextStyle(color: _textLight, fontSize: 10, fontWeight: FontWeight.w600, letterSpacing: 0.3)),
      const SizedBox(height: 4),
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
        decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(10), border: Border.all(color: _border)),
        child: DropdownButtonHideUnderline(
          child: DropdownButton<String>(
            value: value, isExpanded: true,
            icon: const Icon(Icons.keyboard_arrow_down, color: _textLight, size: 18),
            style: const TextStyle(color: _accent, fontSize: 12, fontWeight: FontWeight.w600),
            items: items.map((e) => DropdownMenuItem(value: e, child: Text(e, overflow: TextOverflow.ellipsis))).toList(),
            onChanged: onChanged,
          ),
        ),
      ),
    ]);

  Widget _productGrid() => Container(
    color: _bg,
    padding: const EdgeInsets.fromLTRB(14, 20, 14, 20),
    child: Column(children: [
      const Text('Grooming Essentials', style: TextStyle(color: _accent, fontSize: 20, fontWeight: FontWeight.w800, letterSpacing: -0.5)),
      const SizedBox(height: 8),
      Container(width: 60, height: 4, decoration: BoxDecoration(borderRadius: BorderRadius.circular(2), gradient: _goldGrad,
        boxShadow: [BoxShadow(color: _gold.withOpacity(0.35), blurRadius: 8)])),
      const SizedBox(height: 20),
      if (_loading)
        const Padding(padding: EdgeInsets.symmetric(vertical: 32), child: CircularProgressIndicator(color: _gold))
      else if (_error != null)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 20),
          child: Column(children: [
            const Icon(Icons.wifi_off_rounded, size: 48, color: _textLight),
            const SizedBox(height: 12),
            const Text('Could not load products', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 15)),
            const SizedBox(height: 6),
            Text(_error!, style: const TextStyle(color: _textLight, fontSize: 11), textAlign: TextAlign.center, maxLines: 3, overflow: TextOverflow.ellipsis),
            const SizedBox(height: 16),
            GestureDetector(
              onTap: _loadProducts,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(12),
                  boxShadow: [BoxShadow(color: _primary.withOpacity(0.25), blurRadius: 8, offset: const Offset(0, 3))]),
                child: const Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(Icons.refresh, color: _gold, size: 16),
                  SizedBox(width: 8),
                  Text('Retry', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 13)),
                ]),
              ),
            ),
          ]),
        )
      else if (_filteredProducts.isEmpty)
        const Padding(padding: EdgeInsets.symmetric(vertical: 32),
          child: Text('No products available', style: TextStyle(color: _textLight, fontSize: 14)))
      else
        GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 2, crossAxisSpacing: 14, mainAxisSpacing: 14, childAspectRatio: 0.68),
          itemCount: _filteredProducts.length,
          itemBuilder: (_, i) => ProductCard(
            product: _filteredProducts[i],
            userEmail: widget.userEmail ?? '',
          ),
        ),
    ]),
  );

  Widget _productCard(Map<String, dynamic> p) {
    final name    = p['name'] as String? ?? '';
    final price   = (p['price'] as num?)?.toDouble() ?? 0;
    final rating  = (p['rating'] as num?)?.toDouble() ?? 0;
    final sold    = (p['sold'] as num?)?.toInt() ?? 0;
    final qty     = (p['quantity'] as num?)?.toInt() ?? 0;
    final id      = p['id'];
    final inStock = qty > 0;
    final variations = p['variations'] as String? ?? '';
    final sizes      = p['sizes'] as String? ?? '';
    final colorList  = variations.split(',').map((e) => e.trim()).where((e) => e.isNotEmpty).toList();
    final sizeList   = sizes.split(',').map((e) => e.trim()).where((e) => e.isNotEmpty).toList();
    return Container(
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(18),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.07), blurRadius: 16, offset: const Offset(0, 5))]),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: Stack(children: [
            Positioned.fill(
              child: LayoutBuilder(
                builder: (_, constraints) => ProductImageCarousel(
                  imageString: p['image'] as String?,
                  height: constraints.maxHeight.isInfinite ? 200 : constraints.maxHeight,
                  borderRadius: 18,
                ),
              ),
            ),
            if (!inStock)
              Positioned.fill(child: Container(
                decoration: BoxDecoration(color: Colors.black.withOpacity(0.45),
                  borderRadius: const BorderRadius.vertical(top: Radius.circular(18))),
                child: const Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Icon(Icons.cancel_outlined, color: Colors.white70, size: 26),
                  SizedBox(height: 4),
                  Text('OUT OF STOCK', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 9, letterSpacing: 1)),
                ])),
              )),
            if (inStock)
              Positioned(bottom: 8, right: 8,
                child: Row(children: [
                  _iconBtn(Icons.favorite_border, onTap: () async {
                    final email = widget.userEmail;
                    if (email == null) { _pushLogin(); return; }
                    try {
                      await BuyerService.addToWishlist(email, id is int ? id : int.tryParse('$id') ?? 0);
                      if (mounted) ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('Added to wishlist'), backgroundColor: _primary, behavior: SnackBarBehavior.floating));
                    } catch (_) {}
                  }),
                  const SizedBox(width: 6),
                  _iconBtn(Icons.shopping_cart_outlined, onTap: () async {
                    final email = widget.userEmail;
                    if (email == null) { _pushLogin(); return; }
                    try {
                      await BuyerService.addToCart(
                        email: email,
                        productId: id is int ? id : int.tryParse('$id') ?? 0,
                        name: name, price: price,
                        sellerEmail: p['seller_email'] as String? ?? '',
                        quantity: 1,
                      );
                      if (mounted) ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('Added to cart!'), backgroundColor: _primary, behavior: SnackBarBehavior.floating));
                    } catch (_) {}
                  }),
                ])),
            Positioned(bottom: 8, left: 8,
              child: GestureDetector(
                onTap: () {
                  final email = widget.userEmail;
                  if (email != null) {
                    Navigator.push(context, MaterialPageRoute(builder: (_) => BuyerViewProductPage(
                      userEmail: email,
                      productId: id is int ? id : int.tryParse('$id'),
                    )));
                  } else { _pushLogin(); }
                },
                child: Container(
                  width: 30, height: 30,
                  decoration: BoxDecoration(gradient: _premiumGrad, shape: BoxShape.circle,
                    boxShadow: [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 6)]),
                  child: const Icon(Icons.visibility_outlined, color: Colors.white, size: 14),
                ),
              ),
            ),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(name, style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13),
              maxLines: 1, overflow: TextOverflow.ellipsis),
            const SizedBox(height: 4),
            Row(children: [
              ...List.generate(5, (s) => Icon(
                s < rating.floor() ? Icons.star : (s < rating ? Icons.star_half : Icons.star_border),
                color: _gold, size: 11)),
              const SizedBox(width: 4),
              Text('(${rating.toStringAsFixed(1)})', style: const TextStyle(color: _textLight, fontSize: 10)),
              const Spacer(),
              Text('$sold sold', style: const TextStyle(color: _textLight, fontSize: 10)),
            ]),
            const SizedBox(height: 6),
            Text('₱${price.toStringAsFixed(2)}', style: const TextStyle(color: _accent, fontWeight: FontWeight.w800, fontSize: 15)),
            const SizedBox(height: 8),
            inStock
              ? GestureDetector(
                  onTap: () {
                    final email = widget.userEmail;
                    if (email != null) {
                      _showBuyNowModal(email: email, name: name, price: price, colors: colorList, sizes: sizeList);
                    } else { _pushLogin(); }
                  },
                  child: Container(
                    width: double.infinity, padding: const EdgeInsets.symmetric(vertical: 9),
                    decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(12),
                      boxShadow: [BoxShadow(color: _primary.withOpacity(0.25), blurRadius: 8, offset: const Offset(0, 3))]),
                    child: const Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                      Icon(Icons.bolt, color: _gold, size: 14),
                      SizedBox(width: 4),
                      Text('Buy Now', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 12)),
                    ]),
                  ))
              : Container(
                  width: double.infinity, padding: const EdgeInsets.symmetric(vertical: 9),
                  decoration: BoxDecoration(color: const Color(0xFFCED4DA), borderRadius: BorderRadius.circular(12)),
                  child: const Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                    Icon(Icons.cancel_outlined, color: Colors.white, size: 14),
                    SizedBox(width: 4),
                    Text('Out of Stock', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 12)),
                  ])),
          ]),
        ),
      ]),
    );
  }

  void _showBuyNowModal({required String email, required String name, required double price, required List<String> colors, required List<String> sizes}) {
    String? selectedColor; String? selectedSize; int qty = 1;
    showModalBottomSheet(context: context, isScrollControlled: true, backgroundColor: Colors.transparent, builder: (_) => StatefulBuilder(builder: (ctx, setS) => Padding(padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom), child: Container(padding: const EdgeInsets.fromLTRB(20, 20, 20, 32), decoration: const BoxDecoration(color: Colors.white, borderRadius: BorderRadius.vertical(top: Radius.circular(24))), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: _border, borderRadius: BorderRadius.circular(2)))), const SizedBox(height: 16), Row(children: [const Icon(Icons.bolt, color: _gold, size: 18), const SizedBox(width: 8), Expanded(child: Text(name, style: const TextStyle(color: _accent, fontSize: 15, fontWeight: FontWeight.w800), maxLines: 1, overflow: TextOverflow.ellipsis)), Text('₱${price.toStringAsFixed(2)}', style: const TextStyle(color: _gold, fontSize: 15, fontWeight: FontWeight.w900))]), const SizedBox(height: 14), if (colors.isNotEmpty) ...[const Text('Color', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)), const SizedBox(height: 8), Wrap(spacing: 8, runSpacing: 8, children: colors.map((c) { final sel = selectedColor == c; return GestureDetector(onTap: () => setS(() => selectedColor = c), child: AnimatedContainer(duration: const Duration(milliseconds: 150), padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8), decoration: BoxDecoration(gradient: sel ? _goldGrad : null, color: sel ? null : _bg, borderRadius: BorderRadius.circular(10), border: Border.all(color: sel ? _gold : _border, width: sel ? 2 : 1.5)), child: Text(c, style: TextStyle(color: sel ? _primary : _accent, fontWeight: sel ? FontWeight.w800 : FontWeight.w600, fontSize: 12)))); }).toList()), const SizedBox(height: 12)], if (sizes.isNotEmpty) ...[const Text('Size', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)), const SizedBox(height: 8), Wrap(spacing: 8, runSpacing: 8, children: sizes.map((s) { final sel = selectedSize == s; return GestureDetector(onTap: () => setS(() => selectedSize = s), child: AnimatedContainer(duration: const Duration(milliseconds: 150), padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 9), decoration: BoxDecoration(gradient: sel ? _goldGrad : null, color: sel ? null : _bg, borderRadius: BorderRadius.circular(10), border: Border.all(color: sel ? _gold : _border, width: sel ? 2 : 1.5)), child: Text(s, style: TextStyle(color: sel ? _primary : _accent, fontWeight: sel ? FontWeight.w800 : FontWeight.w600, fontSize: 13)))); }).toList()), const SizedBox(height: 12)], const Text('Quantity', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)), const SizedBox(height: 8), Row(children: [_qtyModalBtn(Icons.remove, () { if (qty > 1) setS(() => qty--); }), Container(width: 48, alignment: Alignment.center, child: Text('$qty', style: const TextStyle(color: _accent, fontWeight: FontWeight.w800, fontSize: 16))), _qtyModalBtn(Icons.add, () => setS(() => qty++))]), const SizedBox(height: 20), GestureDetector(onTap: () { if (colors.isNotEmpty && selectedColor == null) { ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Please select a color'), backgroundColor: Colors.red, behavior: SnackBarBehavior.floating)); return; } if (sizes.isNotEmpty && selectedSize == null) { ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Please select a size'), backgroundColor: Colors.red, behavior: SnackBarBehavior.floating)); return; } Navigator.pop(context); Navigator.push(context, MaterialPageRoute(builder: (_) => BuyerCheckoutPage(userEmail: email, items: [CheckoutItem(id: name, name: name, price: price, quantity: qty, color: selectedColor, size: selectedSize)]))); }, child: Container(width: double.infinity, padding: const EdgeInsets.symmetric(vertical: 15), decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(14), boxShadow: [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 12, offset: const Offset(0, 4))]), child: const Row(mainAxisAlignment: MainAxisAlignment.center, children: [Icon(Icons.bolt, color: _gold, size: 16), SizedBox(width: 8), Text('Proceed to Checkout', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 14))]))),])))));
  }
  Widget _qtyModalBtn(IconData icon, VoidCallback onTap) => GestureDetector(onTap: onTap, child: Container(width: 34, height: 34, decoration: BoxDecoration(borderRadius: BorderRadius.circular(10), border: Border.all(color: _border), color: Colors.white), child: Icon(icon, size: 18, color: _accent)));

  Widget _iconBtn(IconData icon, {required VoidCallback onTap}) => GestureDetector(
    onTap: onTap,
    child: Container(
      width: 30, height: 30,
      decoration: BoxDecoration(color: Colors.white.withOpacity(0.92), shape: BoxShape.circle,
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.12), blurRadius: 6)]),
      child: Icon(icon, size: 14, color: _accent),
    ),
  );
}
