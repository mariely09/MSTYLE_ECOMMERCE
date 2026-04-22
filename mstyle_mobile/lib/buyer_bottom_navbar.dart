import 'package:flutter/material.dart';
import 'buyer_homepage.dart';
import 'buyer_orders.dart';
import 'buyer_wishlist.dart';
import 'buyer_search_results.dart';
import 'buyer_messages.dart';

// ─── Theme constants ──────────────────────────────────────────────────────────
const Color _primary = Color(0xFF1a1a1a);
const Color _gold    = Color(0xFFd4af37);

// ─── BuyerPage enum ───────────────────────────────────────────────────────────
enum BuyerPage { home, orders, search, wishlist, messages, none }

// ─── BuyerBottomNavBar ────────────────────────────────────────────────────────
/// Shared bottom navigation bar for all main buyer pages.
/// Usage:
///   bottomNavigationBar: BuyerBottomNavBar(
///     userEmail: widget.userEmail,
///     currentPage: BuyerPage.orders,
///     onSearch: _showSearch,   // optional — pass your search handler
///   )
class BuyerBottomNavBar extends StatelessWidget {
  final String userEmail;
  final BuyerPage currentPage;

  /// Optional callback for the Search center button.
  /// If null, the search button is a no-op.
  final VoidCallback? onSearch;

  const BuyerBottomNavBar({
    super.key,
    required this.userEmail,
    required this.currentPage,
    this.onSearch,
  });

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      bottom: true,
      child: Container(
        decoration: BoxDecoration(
          color: _primary,
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.25),
              blurRadius: 20,
              offset: const Offset(0, -4),
            ),
          ],
        ),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceAround,
          children: [
            _navItem(context, BuyerPage.home,     Icons.home_outlined,        Icons.home,        'Home'),
            _navItem(context, BuyerPage.orders,   Icons.shopping_bag_outlined, Icons.shopping_bag,'Orders'),
            _searchCenter(context),
            _navItem(context, BuyerPage.wishlist, Icons.favorite_border,       Icons.favorite,    'Wishlist'),
            _navItem(context, BuyerPage.messages, Icons.chat_bubble_outline,   Icons.chat_bubble, 'Messages'),
          ],
        ),
      ),
    );
  }

  Widget _navItem(
    BuildContext context,
    BuyerPage page,
    IconData icon,
    IconData activeIcon,
    String label,
  ) {
    final active = currentPage == page;
    return GestureDetector(
      onTap: () => _navigateTo(context, page),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(
            active ? activeIcon : icon,
            color: active ? _gold : Colors.white54,
            size: 22,
          ),
          const SizedBox(height: 3),
          Text(
            label,
            style: TextStyle(
              color: active ? _gold : Colors.white54,
              fontSize: 10,
              fontWeight: active ? FontWeight.w700 : FontWeight.w400,
            ),
          ),
        ]),
      ),
    );
  }

  Widget _searchCenter(BuildContext context) => GestureDetector(
    onTap: onSearch ?? () => Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => BuyerSearchResultsPage(userEmail: userEmail)),
    ),
    child: const Padding(
      padding: EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.search, color: Colors.white54, size: 22),
        SizedBox(height: 3),
        Text('Search',
          style: TextStyle(
            color: Colors.white54,
            fontSize: 10,
            fontWeight: FontWeight.w400,
          )),
      ]),
    ),
  );

  void _navigateTo(BuildContext context, BuyerPage page) {
    if (page == currentPage) return;

    switch (page) {
      case BuyerPage.home:
        Navigator.pushAndRemoveUntil(
          context,
          MaterialPageRoute(builder: (_) => BuyerHomePage(userEmail: userEmail)),
          (_) => false,
        );
        break;
      case BuyerPage.orders:
        Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => BuyerOrdersPage(userEmail: userEmail)),
        );
        break;
      case BuyerPage.wishlist:
        Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => BuyerWishlistPage(userEmail: userEmail)),
        );
        break;
      case BuyerPage.messages:
        Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => BuyerMessagesPage(userEmail: userEmail)),
        );
        break;
      case BuyerPage.search:
        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => BuyerSearchResultsPage(userEmail: userEmail)),
        );
        break;
      case BuyerPage.none:
        break;
    }
  }
}
