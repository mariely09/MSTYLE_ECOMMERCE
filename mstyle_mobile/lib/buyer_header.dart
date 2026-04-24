import 'package:flutter/material.dart';
import 'buyer_notifications.dart';
import 'buyer_cart.dart';
import 'profile.dart';
import 'supabase_client.dart';

// ─── Theme constants ──────────────────────────────────────────────────────────
const Color _primary   = Color(0xFF1a1a1a);
const Color _gold      = Color(0xFFd4af37);
const Color _goldLight = Color(0xFFF4D03F);

const _goldGrad = LinearGradient(
  begin: Alignment.topLeft, end: Alignment.bottomRight,
  colors: [_gold, _goldLight],
);

// ─── BuyerAppBar ──────────────────────────────────────────────────────────────
/// Shared pinned SliverAppBar for all main buyer pages.
/// Fetches cart count (distinct items) and unread notification count
/// directly from Supabase so every page always shows live badges.
class BuyerAppBar extends StatefulWidget {
  final String userEmail;

  const BuyerAppBar({
    super.key,
    required this.userEmail,
  });

  @override
  State<BuyerAppBar> createState() => _BuyerAppBarState();
}

class _BuyerAppBarState extends State<BuyerAppBar> {
  int _cartCount  = 0;
  int _notifCount = 0;

  @override
  void initState() {
    super.initState();
    _fetchCounts();
  }

  Future<void> _fetchCounts() async {
    try {
      // Cart: count distinct rows (not sum of quantity)
      final cartRes = await supabase
          .from('cart')
          .select('id')
          .eq('email', widget.userEmail);
      final cartCount = (cartRes as List).length;

      // Notifications: count unread rows
      final notifRes = await supabase
          .from('buyer_notifications')
          .select('id')
          .eq('buyer_email', widget.userEmail)
          .eq('is_read', false);
      final notifCount = (notifRes as List).length;

      if (mounted) {
        setState(() {
          _cartCount  = cartCount;
          _notifCount = notifCount;
        });
      }
    } catch (e) {
      debugPrint('BuyerAppBar _fetchCounts error: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return SliverAppBar(
      pinned: true,
      backgroundColor: _primary,
      elevation: 6,
      shadowColor: Colors.black45,
      titleSpacing: 12,
      automaticallyImplyLeading: false,
      title: Row(children: [
        // ── Logo ──────────────────────────────────────────────────────────
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: Image.asset(
            'assets/images/MStyle Logos/MStyle_logo1.png',
            height: 30, width: 30, fit: BoxFit.contain,
            errorBuilder: (_, __, ___) =>
                const Icon(Icons.storefront, color: _gold, size: 26),
          ),
        ),
        const SizedBox(width: 8),
        // ── "Style" text ──────────────────────────────────────────────────
        ShaderMask(
          shaderCallback: (b) => _goldGrad.createShader(b),
          child: const Text(
            'Style',
            style: TextStyle(
              color: Colors.white,
              fontSize: 18,
              fontWeight: FontWeight.w900,
              letterSpacing: 2,
            ),
          ),
        ),
      ]),
      actions: [
        // ── Notifications with badge ───────────────────────────────────────
        Stack(clipBehavior: Clip.none, children: [
          IconButton(
            icon: const Icon(Icons.notifications_outlined,
                color: Colors.white, size: 22),
            onPressed: () async {
              await Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) =>
                      BuyerNotificationsPage(userEmail: widget.userEmail),
                ),
              );
              _fetchCounts(); // refresh after returning
            },
          ),
          if (_notifCount > 0)
            Positioned(
              top: 6, right: 6,
              child: Container(
                constraints: const BoxConstraints(minWidth: 16, minHeight: 16),
                padding: const EdgeInsets.symmetric(horizontal: 3),
                decoration: const BoxDecoration(
                    color: Colors.red, shape: BoxShape.circle),
                child: Center(
                  child: Text(
                    _notifCount > 99 ? '99+' : '$_notifCount',
                    style: const TextStyle(
                        color: Colors.white,
                        fontSize: 9,
                        fontWeight: FontWeight.w800),
                  ),
                ),
              ),
            ),
        ]),
        // ── Cart with badge ────────────────────────────────────────────────
        Stack(clipBehavior: Clip.none, children: [
          IconButton(
            icon: const Icon(Icons.shopping_cart_outlined,
                color: Colors.white, size: 22),
            onPressed: () async {
              await Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => BuyerCartPage(userEmail: widget.userEmail),
                ),
              );
              _fetchCounts(); // refresh after returning
            },
          ),
          if (_cartCount > 0)
            Positioned(
              top: 6, right: 6,
              child: Container(
                constraints: const BoxConstraints(minWidth: 16, minHeight: 16),
                padding: const EdgeInsets.symmetric(horizontal: 3),
                decoration: const BoxDecoration(
                    color: Colors.red, shape: BoxShape.circle),
                child: Center(
                  child: Text(
                    _cartCount > 99 ? '99+' : '$_cartCount',
                    style: const TextStyle(
                        color: Colors.white,
                        fontSize: 9,
                        fontWeight: FontWeight.w800),
                  ),
                ),
              ),
            ),
        ]),
        // ── Profile ────────────────────────────────────────────────────────
        IconButton(
          icon: const Icon(Icons.person_outline,
              color: Colors.white, size: 22),
          onPressed: () => Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => ProfilePage(userEmail: widget.userEmail),
            ),
          ),
        ),
      ],
    );
  }
}
