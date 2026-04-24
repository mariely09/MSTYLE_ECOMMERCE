import 'package:flutter/material.dart';
import 'buyer_homepage.dart';
import 'buyer_orders.dart';
import 'buyer_service.dart';
import 'product_card.dart';

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

class BuyerWishlistPage extends StatefulWidget {
  final String userEmail;
  const BuyerWishlistPage({super.key, required this.userEmail});
  @override
  State<BuyerWishlistPage> createState() => _BuyerWishlistPageState();
}

class _BuyerWishlistPageState extends State<BuyerWishlistPage> {
  bool _loading = true;
  List<Map<String, dynamic>> _items = [];

  @override
  void initState() {
    super.initState();
    _loadWishlist();
  }

  Future<void> _loadWishlist() async {
    setState(() => _loading = true);
    try {
      final data = await BuyerService.getWishlist(widget.userEmail);
      if (mounted) setState(() { _items = data; _loading = false; });
    } catch (e) {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Convert wishlist item to the flat product map that ProductCard expects.
  Map<String, dynamic> _toProductMap(Map<String, dynamic> item) {
    final p = item['products'] as Map<String, dynamic>? ?? {};
    return {
      'id':           item['product_id'],
      'name':         p['name'] ?? '',
      'price':        p['price'] ?? 0,
      'sale_price':   p['sale_price'],
      'image':        p['image'] ?? '',
      'seller_email': p['seller_email'] ?? '',
      'variations':   p['variations'] ?? '',
      'sizes':        p['sizes'] ?? '',
      'rating':       0,
      'sold':         0,
      'quantity':     1, // always in-stock in wishlist view
    };
  }

  Future<void> _removeItem(Map<String, dynamic> item) async {
    final productId = item['product_id'] as int?;
    if (productId == null) return;
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Remove from Wishlist',
          style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 16)),
        content: const Text('Remove this item from your wishlist?',
          style: TextStyle(color: _textLight, fontSize: 13)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          TextButton(
            onPressed: () async {
              Navigator.pop(context);
              await BuyerService.removeFromWishlist(widget.userEmail, productId);
              await _loadWishlist();
            },
            child: const Text('Remove', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      body: _loading
        ? const Center(child: CircularProgressIndicator(color: _gold))
        : CustomScrollView(
            slivers: [
              SliverAppBar(
                pinned: true,
                backgroundColor: _primary,
                elevation: 6,
                titleSpacing: 16,
                leading: IconButton(
                  icon: const Icon(Icons.arrow_back, color: Colors.white),
                  onPressed: () => Navigator.pop(context),
                ),
                title: const Text('My Wishlist',
                  style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w700)),
              ),
              if (_items.isEmpty)
                SliverFillRemaining(child: _emptyState())
              else
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
                  sliver: SliverGrid(
                    delegate: SliverChildBuilderDelegate(
                      (_, i) => ProductCard(
                        product: _toProductMap(_items[i]),
                        userEmail: widget.userEmail,
                        isInWishlist: true,
                        onWishlistToggle: () => _removeItem(_items[i]),
                      ),
                      childCount: _items.length,
                    ),
                    gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 2, crossAxisSpacing: 12, mainAxisSpacing: 12, childAspectRatio: 0.68,
                    ),
                  ),
                ),
              const SliverToBoxAdapter(child: SizedBox(height: 24)),
            ],
          ),
    );
  }

  // ─── Empty State ──────────────────────────────────────────────────────────
  Widget _emptyState() => Center(
    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
      const Icon(Icons.favorite_border, size: 80, color: _border),
      const SizedBox(height: 20),
      const Text('Your wishlist is empty',
        style: TextStyle(color: _accent, fontSize: 20, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      const Text("You haven't added any items yet.",
        style: TextStyle(color: _textLight, fontSize: 13)),
      const SizedBox(height: 24),
      GestureDetector(
        onTap: () => Navigator.pushAndRemoveUntil(context,
          MaterialPageRoute(builder: (_) => BuyerHomePage(userEmail: widget.userEmail)), (_) => false),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 13),
          decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(14),
            boxShadow: [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 12, offset: const Offset(0, 4))]),
          child: const Text('Continue Shopping',
            style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 14)),
        ),
      ),
    ]),
  );

}
