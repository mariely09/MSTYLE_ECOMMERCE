import 'package:flutter/material.dart';
import 'login.dart';
import 'register.dart';
import 'buyer_homepage.dart';
import 'buyer_cart.dart';
import 'buyer_orders.dart';
import 'buyer_wishlist.dart';
import 'profile.dart';
import 'buyer_notifications.dart';
import 'buyer_header.dart';
import 'buyer_bottom_navbar.dart';
import 'buyer_search_results.dart';

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

/// Wraps a category page body with the buyer bottom nav + header.
/// Matches buyer_homepage.dart exactly.
/// If [userEmail] is null, shows Sign In / Sign Up buttons instead of user actions.
class BuyerCategoryScaffold extends StatefulWidget {
  final String title;
  final String? userEmail;
  final List<Widget> slivers;

  const BuyerCategoryScaffold({
    super.key,
    required this.title,
    this.userEmail,
    required this.slivers,
  });

  @override
  State<BuyerCategoryScaffold> createState() => _BuyerCategoryScaffoldState();
}

class _BuyerCategoryScaffoldState extends State<BuyerCategoryScaffold> {
  final _scrollCtrl = ScrollController();
  bool _navVisible = true;
  double _lastScrollOffset = 0;

  @override
  void initState() {
    super.initState();
    _scrollCtrl.addListener(_onScroll);
  }

  void _onScroll() {
    final offset = _scrollCtrl.offset;
    final diff = offset - _lastScrollOffset;
    if (diff > 6 && _navVisible) {
      setState(() => _navVisible = false);
    } else if (diff < -6 && !_navVisible) {
      setState(() => _navVisible = true);
    }
    _lastScrollOffset = offset;
  }

  @override
  void dispose() {
    _scrollCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      body: Stack(
        children: [
          CustomScrollView(
            controller: _scrollCtrl,
            slivers: [
              SliverAppBar(
                pinned: true,
                backgroundColor: _primary,
                elevation: 6,
                leading: IconButton(
                  icon: const Icon(Icons.arrow_back, color: Colors.white),
                  onPressed: () => Navigator.pop(context),
                ),
                title: ShaderMask(
                  shaderCallback: (b) => _goldGrad.createShader(b),
                  child: Text(widget.title,
                    style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w800)),
                ),
              ),
              ...widget.slivers,
              const SliverToBoxAdapter(child: SizedBox(height: 80)),
            ],
          ),
          Positioned(
            left: 0, right: 0, bottom: 0,
            child: AnimatedSlide(
              duration: const Duration(milliseconds: 250),
              curve: Curves.easeInOut,
              offset: _navVisible ? Offset.zero : const Offset(0, 1),
              child: BuyerBottomNavBar(
                userEmail: widget.userEmail ?? '',
                currentPage: BuyerPage.none,
                onSearch: _showSearch,
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _showSearch() {
    Navigator.push(context, MaterialPageRoute(
      builder: (_) => BuyerSearchResultsPage(userEmail: widget.userEmail ?? ''),
    ));
  }
}
