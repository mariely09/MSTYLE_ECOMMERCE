import 'package:flutter/material.dart';
import 'buyer_service.dart';
import 'buyer_viewproduct.dart';
import 'product_image_carousel.dart';

// ─── Shared theme constants ───────────────────────────────────────────────────
const Color kPrimary   = Color(0xFF1a1a1a);
const Color kAccent    = Color(0xFF2c3e50);
const Color kGold      = Color(0xFFd4af37);
const Color kGoldLight = Color(0xFFF4D03F);
const Color kTextLight = Color(0xFF6c757d);
const Color kBg        = Color(0xFFF8F9FA);
const Color kBorder    = Color(0xFFE9ECEF);

const kPremiumGrad = LinearGradient(
  begin: Alignment.topLeft, end: Alignment.bottomRight,
  colors: [kPrimary, kAccent],
);
const kGoldGrad = LinearGradient(
  begin: Alignment.topLeft, end: Alignment.bottomRight,
  colors: [kGold, kGoldLight],
);

/// Shared product card used across home page, buyer homepage, and all category pages.
/// Pass [userEmail] as empty string for unauthenticated (guest) users.
/// [onLoginRequired] is called when an action needs auth but user is not logged in.
/// [isInWishlist] overrides the initial heart icon state (filled = true).
/// [onWishlistToggle] overrides the default wishlist add behavior (e.g. for remove).
class ProductCard extends StatefulWidget {
  final Map<String, dynamic> product;
  final String userEmail;
  final VoidCallback? onLoginRequired;
  final bool isInWishlist;
  final VoidCallback? onWishlistToggle;

  const ProductCard({
    super.key,
    required this.product,
    required this.userEmail,
    this.onLoginRequired,
    this.isInWishlist = false,
    this.onWishlistToggle,
  });

  @override
  State<ProductCard> createState() => _ProductCardState();
}

class _ProductCardState extends State<ProductCard> {
  late bool _inWishlist;
  bool _wishlistLoading = false;

  bool get _isGuest => widget.userEmail.isEmpty;

  @override
  void initState() {
    super.initState();
    _inWishlist = widget.isInWishlist;
    // Check actual wishlist status from Supabase (only for logged-in users)
    if (!_isGuest && !widget.isInWishlist) {
      _checkWishlist();
    }
  }

  Future<void> _checkWishlist() async {
    try {
      final id = widget.product['id'];
      final productId = id is int ? id : int.tryParse('$id');
      if (productId == null) return;
      final inWl = await BuyerService.isInWishlist(widget.userEmail, productId);
      if (mounted) setState(() => _inWishlist = inWl);
    } catch (_) {}
  }

  Future<void> _toggleWishlist(BuildContext context) async {
    if (_isGuest) { widget.onLoginRequired?.call(); return; }

    // If caller provided a custom toggle (e.g. wishlist page remove), use it
    if (widget.onWishlistToggle != null) {
      widget.onWishlistToggle!();
      return;
    }

    final id = widget.product['id'];
    final productId = id is int ? id : int.tryParse('$id');
    if (productId == null) return;

    setState(() => _wishlistLoading = true);
    try {
      if (_inWishlist) {
        await BuyerService.removeFromWishlist(widget.userEmail, productId);
        if (mounted) setState(() => _inWishlist = false);
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Removed from wishlist'),
            backgroundColor: kPrimary, behavior: SnackBarBehavior.floating));
        }
      } else {
        await BuyerService.addToWishlist(widget.userEmail, productId);
        if (mounted) setState(() => _inWishlist = true);
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Added to wishlist'),
            backgroundColor: kPrimary, behavior: SnackBarBehavior.floating));
        }
      }
    } catch (_) {}
    if (mounted) setState(() => _wishlistLoading = false);
  }

  void _doLogin(BuildContext context) => widget.onLoginRequired?.call();

  @override
  Widget build(BuildContext context) {
    final name      = widget.product['name'] as String? ?? '';
    final price     = (widget.product['price'] as num?)?.toDouble() ?? 0;
    final rating    = (widget.product['rating'] as num?)?.toDouble() ?? 0;
    final sold      = (widget.product['sold'] as num?)?.toInt() ?? 0;
    final qty       = (widget.product['quantity'] as num?)?.toInt() ?? 0;
    final id        = widget.product['id'];
    final inStock   = qty > 0;
    final productId = id is int ? id : int.tryParse('$id');

    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.07), blurRadius: 16, offset: const Offset(0, 5))],
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        // ── Image area ──────────────────────────────────────────────────────
        Expanded(
          child: Stack(children: [
            Positioned.fill(
              child: LayoutBuilder(
                builder: (_, c) => ProductImageCarousel(
                  imageString: widget.product['image'] as String?,
                  height: c.maxHeight.isInfinite ? 200 : c.maxHeight,
                  borderRadius: 18,
                ),
              ),
            ),
            // Out of stock overlay
            if (!inStock)
              Positioned.fill(child: Container(
                decoration: BoxDecoration(
                  color: Colors.black.withOpacity(0.45),
                  borderRadius: const BorderRadius.vertical(top: Radius.circular(18)),
                ),
                child: const Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Icon(Icons.cancel_outlined, color: Colors.white70, size: 26),
                  SizedBox(height: 4),
                  Text('OUT OF STOCK',
                    style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 9, letterSpacing: 1)),
                ])),
              )),
            // Wishlist + Cart buttons
            if (inStock)
              Positioned(bottom: 8, right: 8,
                child: Row(children: [
                  _wishlistLoading
                    ? const SizedBox(width: 30, height: 30,
                        child: Center(child: SizedBox(width: 14, height: 14,
                          child: CircularProgressIndicator(strokeWidth: 2, color: kPrimary))))
                    : _iconBtn(
                        _inWishlist ? Icons.favorite : Icons.favorite_border,
                        color: _inWishlist ? Colors.red.shade400 : kAccent,
                        onTap: () => _toggleWishlist(context),
                      ),
                  const SizedBox(width: 6),
                  _iconBtn(Icons.shopping_cart_outlined, onTap: () async {
                    if (_isGuest) { _doLogin(context); return; }
                    try {
                      await BuyerService.addToCart(
                        email: widget.userEmail,
                        productId: productId ?? 0,
                        name: name, price: price,
                        sellerEmail: widget.product['seller_email'] as String? ?? '',
                        quantity: 1,
                      );
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                          content: Text('Added to cart!'),
                          backgroundColor: kPrimary, behavior: SnackBarBehavior.floating));
                      }
                    } catch (_) {}
                  }),
                ]),
              ),
            // View button
            Positioned(bottom: 8, left: 8,
              child: GestureDetector(
                onTap: () {
                  if (_isGuest) { _doLogin(context); return; }
                  Navigator.push(context, MaterialPageRoute(
                    builder: (_) => BuyerViewProductPage(
                      userEmail: widget.userEmail,
                      productId: productId,
                    ),
                  )).then((_) => _checkWishlist()); // re-check on return
                },
                child: Container(
                  width: 30, height: 30,
                  decoration: BoxDecoration(
                    gradient: kPremiumGrad, shape: BoxShape.circle,
                    boxShadow: [BoxShadow(color: kPrimary.withOpacity(0.3), blurRadius: 6)],
                  ),
                  child: const Icon(Icons.visibility_outlined, color: Colors.white, size: 14),
                ),
              ),
            ),
          ]),
        ),

        // ── Info ────────────────────────────────────────────────────────────
        Padding(
          padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(name,
              style: const TextStyle(color: kAccent, fontWeight: FontWeight.w700, fontSize: 13),
              maxLines: 1, overflow: TextOverflow.ellipsis),
            const SizedBox(height: 4),
            Row(children: [
              ...List.generate(5, (s) => Icon(
                s < rating.floor() ? Icons.star : (s < rating ? Icons.star_half : Icons.star_border),
                color: kGold, size: 11)),
              const SizedBox(width: 4),
              Builder(builder: (_) {
                final reviewCount = (widget.product['review_count'] as num?)?.toInt();
                if (reviewCount != null && reviewCount > 0) {
                  return Text('${rating.toStringAsFixed(1)} ($reviewCount)',
                    style: const TextStyle(color: kTextLight, fontSize: 10));
                }
                if (rating > 0) {
                  return Text(rating.toStringAsFixed(1),
                    style: const TextStyle(color: kTextLight, fontSize: 10));
                }
                return const Text('No reviews',
                  style: TextStyle(color: kTextLight, fontSize: 10));
              }),
              const Spacer(),
              Text('$sold sold', style: const TextStyle(color: kTextLight, fontSize: 10)),
            ]),
            const SizedBox(height: 6),
            // Sale price support
            Builder(builder: (_) {
              final salePrice = (widget.product['sale_price'] as num?)?.toDouble();
              if (salePrice != null && salePrice < price) {
                return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('₱${price.toStringAsFixed(2)}',
                    style: const TextStyle(color: kTextLight, fontSize: 11,
                      decoration: TextDecoration.lineThrough)),
                  Text('₱${salePrice.toStringAsFixed(2)}',
                    style: const TextStyle(color: Color(0xFFE74C3C),
                      fontWeight: FontWeight.w800, fontSize: 15)),
                ]);
              }
              return Text('₱${price.toStringAsFixed(2)}',
                style: const TextStyle(color: kAccent, fontWeight: FontWeight.w800, fontSize: 15));
            }),
          ]),
        ),
      ]),
    );
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  Widget _iconBtn(IconData icon, {required VoidCallback onTap, Color? color}) => GestureDetector(
    onTap: onTap,
    child: Container(
      width: 30, height: 30,
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.92), shape: BoxShape.circle,
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.12), blurRadius: 6)],
      ),
      child: Icon(icon, size: 14, color: color ?? kAccent),
    ),
  );
}
