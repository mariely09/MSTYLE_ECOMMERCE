import 'dart:async';
import 'package:flutter/material.dart';
import 'login.dart';
import 'register.dart';
import 'seller_register.dart';
import 'activewear.dart';
import 'casual.dart';
import 'suits.dart';
import 'outerwear.dart';
import 'shoes.dart';
import 'grooming.dart';
import 'footer.dart';
import 'buyer_service.dart';
import 'buyer_viewproduct.dart';
import 'buyer_search_results.dart';
import 'product_image_carousel.dart';
import 'product_card.dart';

// ─── Theme ───────────────────────────────────────────────────────────────────
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

// ─── Data ─────────────────────────────────────────────────────────────────────
const _heroSlides = [
  {'title': 'Craft Your', 'highlight': 'Signature Style'},
  {'title': 'Craft Your', 'highlight': 'Executive Look'},
  {'title': 'Craft Your', 'highlight': 'Premium Fashion'},
  {'title': 'Craft Your', 'highlight': 'Timeless Elegance'},
];

const _categories = [
  {'icon': Icons.person,          'label': 'Suits & Blazers',      'sub': 'Executive & Formal Wear'},
  {'icon': Icons.checkroom,       'label': 'Casual Wear',           'sub': 'Everyday Comfort'},
  {'icon': Icons.layers,          'label': 'Outerwear',             'sub': 'Stylish Protection'},
  {'icon': Icons.directions_run,  'label': 'Activewear',            'sub': 'Performance Gear'},
  {'icon': Icons.shopping_bag,    'label': 'Shoes & Accessories',   'sub': 'Premium Footwear'},
  {'icon': Icons.cut,             'label': 'Grooming',              'sub': 'Complete Care Collection'},
];

const _proofStats = [
  {'number': '10K+', 'label': 'Customers'},
  {'number': '500+', 'label': 'Products'},
  {'number': '4.9★', 'label': 'Rating'},
];

// ─── Page ─────────────────────────────────────────────────────────────────────
class HomePage extends StatefulWidget {
  const HomePage({super.key});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> with TickerProviderStateMixin {
  final _searchCtrl = TextEditingController();
  final _scrollCtrl = ScrollController();
  int _heroSlide = 0;
  Timer? _heroTimer;

  late final AnimationController _fadeCtrl;
  late final Animation<double> _fadeAnim;

  List<Map<String, dynamic>> _featuredProducts = [];
  List<Map<String, dynamic>> _promoProducts = [];
  bool _productsLoading = true;
  String? _productsError;
  int _productsPage = 1;
  static const int _perPage = 12;
  bool _hasMoreProducts = true;
  bool _loadingMore = false;

  @override
  void initState() {
    super.initState();
    _fadeCtrl = AnimationController(vsync: this, duration: const Duration(milliseconds: 800));
    _fadeAnim = CurvedAnimation(parent: _fadeCtrl, curve: Curves.easeOut);
    _fadeCtrl.forward();
    _heroTimer = Timer.periodic(const Duration(seconds: 4), (_) {
      setState(() => _heroSlide = (_heroSlide + 1) % _heroSlides.length);
    });
    _loadFeaturedProducts();
  }

  Future<void> _loadFeaturedProducts() async {
    if (mounted) setState(() { _productsLoading = true; _productsError = null; _productsPage = 1; _hasMoreProducts = true; });
    try {
      final results = await Future.wait([
        BuyerService.getProducts(limit: _perPage, offset: 0),
        BuyerService.getPromotionalProducts(limit: 4),
      ]);
      if (mounted) setState(() {
        _featuredProducts = results[0];
        _promoProducts    = results[1];
        _productsLoading  = false;
        _hasMoreProducts  = results[0].length >= _perPage;
      });
    } catch (e) {
      debugPrint('_loadFeaturedProducts error: $e');
      if (mounted) setState(() { _productsLoading = false; _productsError = e.toString(); });
    }
  }

  Future<void> _loadMoreProducts() async {
    if (_loadingMore || !_hasMoreProducts) return;
    setState(() => _loadingMore = true);
    try {
      final nextPage = _productsPage + 1;
      final data = await BuyerService.getProducts(limit: _perPage, offset: (nextPage - 1) * _perPage);
      if (mounted) setState(() {
        _featuredProducts.addAll(data);
        _productsPage = nextPage;
        _hasMoreProducts = data.length >= _perPage;
        _loadingMore = false;
      });
    } catch (e) {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    _scrollCtrl.dispose();
    _heroTimer?.cancel();
    _fadeCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      body: FadeTransition(
        opacity: _fadeAnim,
        child: CustomScrollView(
          controller: _scrollCtrl,
          slivers: [
            _appBar(),
            SliverToBoxAdapter(child: _heroSection()),
            SliverToBoxAdapter(child: _categoriesSection()),
            SliverToBoxAdapter(child: _productsSection()),
            SliverToBoxAdapter(child: _sellerSection()),
            const SliverToBoxAdapter(child: AppFooter()),
            const SliverToBoxAdapter(child: SizedBox(height: 0)),
          ],
        ),
      ),
    );
  }

  // ─── App Bar ──────────────────────────────────────────────────────────────
  SliverAppBar _appBar() => SliverAppBar(
    pinned: true,
    backgroundColor: _primary,
    elevation: 6,
    shadowColor: Colors.black45,
    titleSpacing: 12,
    automaticallyImplyLeading: false,
    title: Row(mainAxisSize: MainAxisSize.min, children: [
      ClipRRect(
        borderRadius: BorderRadius.circular(6),
        child: Image.asset(
          'assets/images/MStyle Logos/MStyle_logo1.png',
          height: 30, width: 30, fit: BoxFit.contain,
          errorBuilder: (_, __, ___) => const Icon(Icons.storefront, color: _gold, size: 26),
        ),
      ),
      const SizedBox(width: 6),
      Flexible(
        child: ShaderMask(
          shaderCallback: (b) => _goldGrad.createShader(b),
          child: const Text('Style',
            style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w900, letterSpacing: 2),
            overflow: TextOverflow.visible,
            softWrap: false),
        ),
      ),
    ]),
    actions: [
      IconButton(icon: const Icon(Icons.search, color: Colors.white, size: 22), onPressed: _showSearch),
      // Sign In — bordered with icon (matches website auth-btn login-btn)
      GestureDetector(
        onTap: () => _pushLogin(),
        child: Container(
          margin: const EdgeInsets.only(left: 4),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: _gold, width: 1.5),
          ),
          child: const Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.login, color: _gold, size: 13),
            SizedBox(width: 5),
            Text('Sign In', style: TextStyle(color: _gold, fontWeight: FontWeight.w700, fontSize: 11)),
          ]),
        ),
      ),
      // Sign Up — accent blue (color theme)
      GestureDetector(
        onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const RegisterPage())),
        child: Container(
          margin: const EdgeInsets.only(right: 10, left: 6),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
          decoration: BoxDecoration(
            color: _accent,
            borderRadius: BorderRadius.circular(20),
            boxShadow: [BoxShadow(color: _accent.withOpacity(0.35), blurRadius: 8, offset: const Offset(0, 3))],
          ),
          child: const Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.person_add, color: Colors.white, size: 13),
            SizedBox(width: 5),
            Text('Sign Up', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 11)),
          ]),
        ),
      ),
    ],
  );

  void _showSearch() {
    Navigator.push(context, MaterialPageRoute(
      builder: (_) => const BuyerSearchResultsPage(userEmail: ''),
    ));
  }

  void _pushLogin() => Navigator.push(context, MaterialPageRoute(builder: (_) => const LoginPage()));

  // ─── Hero Section ─────────────────────────────────────────────────────────
  Widget _heroSection() {
    final slide = _heroSlides[_heroSlide];
    return SizedBox(
      height: 420,
      child: Stack(fit: StackFit.expand, children: [
        // ── Background: product image carousel or gradient fallback ──────
        _promoProducts.isEmpty
          ? Container(decoration: const BoxDecoration(gradient: _premiumGrad))
          : _PromoCarousel(products: _promoProducts, heroSlide: _heroSlide),

        // ── Dark gradient overlay (left-heavy, like website) ─────────────
        Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.centerLeft,
              end: Alignment.centerRight,
              stops: [0.0, 0.55, 0.85, 1.0],
              colors: [
                Color(0xEE1a1a1a),
                Color(0xCC1a1a1a),
                Color(0x661a1a1a),
                Color(0x001a1a1a),
              ],
            ),
          ),
        ),

        // ── Text content ─────────────────────────────────────────────────
        Positioned(
          left: 0, top: 0, bottom: 0,
          width: MediaQuery.of(context).size.width * 0.62,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 28, 12, 40),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // NEW COLLECTION badge
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    gradient: _goldGrad,
                    borderRadius: BorderRadius.circular(20),
                    boxShadow: [BoxShadow(color: _gold.withOpacity(0.4), blurRadius: 10, offset: const Offset(0, 3))],
                  ),
                  child: const Text('NEW COLLECTION',
                    style: TextStyle(color: _primary, fontWeight: FontWeight.w900, fontSize: 9, letterSpacing: 1.5)),
                ),
                const SizedBox(height: 12),
                Text(slide['title']!,
                  style: const TextStyle(color: Colors.white70, fontSize: 13, fontWeight: FontWeight.w400, letterSpacing: 0.3)),
                const SizedBox(height: 4),
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 500),
                  transitionBuilder: (child, anim) => FadeTransition(
                    opacity: anim,
                    child: SlideTransition(
                      position: Tween(begin: const Offset(0, 0.25), end: Offset.zero).animate(anim),
                      child: child)),
                  child: ShaderMask(
                    key: ValueKey(_heroSlide),
                    shaderCallback: (b) => _goldGrad.createShader(b),
                    child: Text(slide['highlight']!,
                      style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w900, letterSpacing: -0.5, height: 1.1)),
                  ),
                ),
                const SizedBox(height: 10),
                Container(width: 44, height: 3,
                  decoration: BoxDecoration(borderRadius: BorderRadius.circular(2), gradient: _goldGrad)),
                const SizedBox(height: 10),
                const Text('Premium menswear for the modern man.',
                  style: TextStyle(color: Colors.white60, fontSize: 11, height: 1.5),
                  maxLines: 2, overflow: TextOverflow.ellipsis),
                const SizedBox(height: 18),
                _heroBtn('Shop Now', primary: true, onTap: () {
                  // Scroll past hero + features + categories to products section
                  _scrollCtrl.animateTo(
                    700,
                    duration: const Duration(milliseconds: 600),
                    curve: Curves.easeInOut,
                  );
                }),
              ],
            ),
          ),
        ),

        // ── Slide indicators ─────────────────────────────────────────────
        Positioned(
          bottom: 14, left: 0, right: 0,
          child: Row(mainAxisAlignment: MainAxisAlignment.center,
            children: List.generate(
              _promoProducts.isNotEmpty ? _promoProducts.length : _heroSlides.length,
              (i) => GestureDetector(
                onTap: () => setState(() => _heroSlide = i),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 300),
                  margin: const EdgeInsets.symmetric(horizontal: 3),
                  width: _heroSlide % (_promoProducts.isNotEmpty ? _promoProducts.length : _heroSlides.length) == i ? 24 : 8,
                  height: 8,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(4),
                    color: _heroSlide % (_promoProducts.isNotEmpty ? _promoProducts.length : _heroSlides.length) == i
                        ? _gold : Colors.white38,
                    boxShadow: _heroSlide % (_promoProducts.isNotEmpty ? _promoProducts.length : _heroSlides.length) == i
                        ? [BoxShadow(color: _gold.withOpacity(0.6), blurRadius: 8)]
                        : [],
                  ),
                ),
              ),
            ),
          ),
        ),
      ]),
    );
  }

  Widget _heroBtn(String label, {required bool primary, required VoidCallback onTap}) => GestureDetector(
    onTap: onTap,
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(30),
        gradient: primary ? _goldGrad : null,
        border: primary ? null : Border.all(color: Colors.white38, width: 1.5),
        boxShadow: primary ? [BoxShadow(color: _gold.withOpacity(0.35), blurRadius: 12, offset: const Offset(0, 4))] : [],
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Text(label, style: TextStyle(color: primary ? _primary : Colors.white, fontWeight: FontWeight.w800, fontSize: 12, letterSpacing: 0.5)),
        const SizedBox(width: 6),
        Icon(primary ? Icons.arrow_forward : Icons.explore_outlined, color: primary ? _primary : Colors.white, size: 14),
      ]),
    ),
  );

  // ─── Features Strip ───────────────────────────────────────────────────────
  Widget _featuresStrip() => Container(
    color: Colors.white,
    padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 12),
    child: SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(children: [
        _featureChip(Icons.local_shipping_outlined, 'Free Shipping'),
        _featureChip(Icons.verified_outlined, 'Premium Quality'),
        _featureChip(Icons.replay_outlined, 'Easy Returns'),
        _featureChip(Icons.lock_outlined, 'Secure Payment'),
      ]),
    ),
  );

  Widget _featureChip(IconData icon, String label) => Container(
    margin: const EdgeInsets.only(right: 10),
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
    decoration: BoxDecoration(
      color: _bg,
      borderRadius: BorderRadius.circular(25),
      border: Border.all(color: _border),
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.04), blurRadius: 8, offset: const Offset(0, 2))],
    ),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Container(
        width: 30, height: 30,
        decoration: BoxDecoration(gradient: _goldGrad, shape: BoxShape.circle,
          boxShadow: [BoxShadow(color: _gold.withOpacity(0.3), blurRadius: 6)]),
        child: Icon(icon, color: _primary, size: 15),
      ),
      const SizedBox(width: 8),
      Text(label, style: const TextStyle(color: _accent, fontWeight: FontWeight.w600, fontSize: 12)),
    ]),
  );

  // ─── Categories Section ───────────────────────────────────────────────────
  Widget _categoriesSection() => Container(
    color: Colors.white,
    padding: const EdgeInsets.symmetric(vertical: 32),
    child: Column(children: [
      _sectionTitle("Premium Men's Categories"),
      const SizedBox(height: 24),
      SizedBox(
        height: 140,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 16),
          itemCount: _categories.length,
          separatorBuilder: (_, __) => const SizedBox(width: 12),
          itemBuilder: (_, i) {
            final cat = _categories[i];
            return GestureDetector(
              onTap: () {
                final label = cat['label'] as String;
                if (label == 'Activewear') {
                  Navigator.push(context, MaterialPageRoute(builder: (_) => const ActivewearPage()));
                } else if (label == 'Casual Wear') {
                  Navigator.push(context, MaterialPageRoute(builder: (_) => const CasualPage()));
                } else if (label == 'Suits & Blazers') {
                  Navigator.push(context, MaterialPageRoute(builder: (_) => const SuitsPage()));
                } else if (label == 'Outerwear') {
                  Navigator.push(context, MaterialPageRoute(builder: (_) => const OuterwearPage()));
                } else if (label == 'Shoes & Accessories') {
                  Navigator.push(context, MaterialPageRoute(builder: (_) => const ShoesPage()));
                } else if (label == 'Grooming') {
                  Navigator.push(context, MaterialPageRoute(builder: (_) => const GroomingPage()));
                }
              },
              child: Container(
                width: 108,
                decoration: BoxDecoration(
                  color: _bg,
                  borderRadius: BorderRadius.circular(18),
                  border: Border.all(color: _border),
                  boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, 4))],
                ),
                child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Container(
                    width: 52, height: 52,
                    decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(16),
                      boxShadow: [BoxShadow(color: _primary.withOpacity(0.25), blurRadius: 8, offset: const Offset(0, 3))]),
                    child: Icon(cat['icon'] as IconData, color: Colors.white, size: 24),
                  ),
                  const SizedBox(height: 10),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 6),
                    child: Text(cat['label'] as String,
                      style: const TextStyle(color: _accent, fontSize: 10.5, fontWeight: FontWeight.w700, letterSpacing: 0.2),
                      textAlign: TextAlign.center, maxLines: 2, overflow: TextOverflow.ellipsis),
                  ),
                  const SizedBox(height: 4),
                  const Text('→', style: TextStyle(color: _gold, fontSize: 12, fontWeight: FontWeight.w700)),
                ]),
              ),
            );
          },
        ),
      ),
    ]),
  );

  // ─── Featured Products ────────────────────────────────────────────────────
  Widget _productsSection() => Container(
    color: _bg,
    padding: const EdgeInsets.symmetric(vertical: 32),
    child: Column(children: [
      _sectionTitle('Featured Products'),
      const SizedBox(height: 24),
      if (_productsLoading)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 32),
          child: CircularProgressIndicator(color: _gold),
        )
      else if (_productsError != null)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 20),
          child: Column(children: [
            const Icon(Icons.wifi_off_rounded, size: 48, color: _textLight),
            const SizedBox(height: 12),
            const Text('Could not load products', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 15)),
            const SizedBox(height: 6),
            Text(_productsError!, style: const TextStyle(color: _textLight, fontSize: 11), textAlign: TextAlign.center, maxLines: 3, overflow: TextOverflow.ellipsis),
            const SizedBox(height: 16),
            GestureDetector(
              onTap: _loadFeaturedProducts,
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
      else if (_featuredProducts.isEmpty)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 32),
          child: Text('No products available yet.', style: TextStyle(color: _textLight, fontSize: 14)),
        )
      else
        GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          padding: const EdgeInsets.symmetric(horizontal: 14),
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 2, crossAxisSpacing: 14, mainAxisSpacing: 14, childAspectRatio: 0.68,
          ),
          itemCount: _featuredProducts.length,
          itemBuilder: (_, i) => ProductCard(
            product: _featuredProducts[i],
            userEmail: '',
            onLoginRequired: _pushLogin,
          ),
        ),
      if (_hasMoreProducts)
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 16, 14, 0),
          child: GestureDetector(
            onTap: _loadMoreProducts,
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 14),
              decoration: BoxDecoration(
                gradient: _premiumGrad,
                borderRadius: BorderRadius.circular(14),
                boxShadow: [BoxShadow(color: _primary.withOpacity(0.2), blurRadius: 8, offset: const Offset(0, 3))],
              ),
              child: _loadingMore
                  ? const Center(child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: _gold, strokeWidth: 2)))
                  : const Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                      Text('Load More Products', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 14)),
                      SizedBox(width: 8),
                      Icon(Icons.expand_more, color: _gold, size: 18),
                    ]),
            ),
          ),
        ),
    ]),
  );

  // ─── Seller Section ───────────────────────────────────────────────────────
  Widget _sellerSection() => Container(
    decoration: const BoxDecoration(
      gradient: _premiumGrad,
    ),
    child: Stack(children: [
      // Decorative circles
      Positioned(top: -30, right: -30,
        child: Container(width: 120, height: 120, decoration: BoxDecoration(shape: BoxShape.circle, color: _gold.withOpacity(0.07)))),
      Positioned(bottom: -20, left: -20,
        child: Container(width: 90, height: 90, decoration: BoxDecoration(shape: BoxShape.circle, color: Colors.white.withOpacity(0.04)))),
      Padding(
        padding: const EdgeInsets.all(28),
        child: Column(children: [
          // Badge
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            decoration: BoxDecoration(
              color: _gold.withOpacity(0.12),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: _gold.withOpacity(0.3)),
            ),
            child: const Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.store, color: _gold, size: 15),
              SizedBox(width: 6),
              Text('Become a Seller', style: TextStyle(color: _gold, fontWeight: FontWeight.w700, fontSize: 12, letterSpacing: 0.3)),
            ]),
          ),
          const SizedBox(height: 18),
          const Text('Start Your Premium\nFashion Business',
            style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w800, letterSpacing: -0.3, height: 1.2),
            textAlign: TextAlign.center),
          const SizedBox(height: 10),
          const Text('Join our exclusive network of premium fashion sellers. Access our curated marketplace and grow your business.',
            style: TextStyle(color: Colors.white60, fontSize: 12.5, height: 1.6), textAlign: TextAlign.center),
          const SizedBox(height: 22),
          // Benefits
          Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
            _benefitItem(Icons.bar_chart, 'Growth\nAnalytics'),
            _benefitItem(Icons.people_outline, 'Premium\nCustomers'),
            _benefitItem(Icons.handshake_outlined, 'Business\nSupport'),
          ]),
          const SizedBox(height: 26),
          // CTA button
          GestureDetector(
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SellerRegisterPage())),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 36, vertical: 15),
              decoration: BoxDecoration(
                gradient: _goldGrad,
                borderRadius: BorderRadius.circular(30),
                boxShadow: [BoxShadow(color: _gold.withOpacity(0.45), blurRadius: 18, offset: const Offset(0, 6))],
              ),
              child: const Row(mainAxisSize: MainAxisSize.min, children: [
                Text('Start Selling Today',
                  style: TextStyle(color: _primary, fontWeight: FontWeight.w800, fontSize: 14, letterSpacing: 0.3)),
                SizedBox(width: 10),
                Icon(Icons.arrow_forward, color: _primary, size: 16),
              ]),
            ),
          ),
          const SizedBox(height: 14),
          const Text('Quick approval • Professional guidance • Marketing support',
            style: TextStyle(color: Colors.white38, fontSize: 10.5, letterSpacing: 0.2), textAlign: TextAlign.center),
        ]),
      ),
    ]),
  );

  Widget _benefitItem(IconData icon, String label) => Column(children: [
    Container(
      width: 50, height: 50,
      decoration: BoxDecoration(
        color: _gold.withOpacity(0.12),
        shape: BoxShape.circle,
        border: Border.all(color: _gold.withOpacity(0.25)),
      ),
      child: Icon(icon, color: _gold, size: 22),
    ),
    const SizedBox(height: 8),
    Text(label, style: const TextStyle(color: Colors.white60, fontSize: 10.5, fontWeight: FontWeight.w500, height: 1.4), textAlign: TextAlign.center),
  ]);

  // ─── Shared helpers ───────────────────────────────────────────────────────
  Widget _sectionTitle(String text) => Column(children: [
    Text(text,
      style: const TextStyle(color: _accent, fontSize: 22, fontWeight: FontWeight.w800, letterSpacing: -0.5),
      textAlign: TextAlign.center),
    const SizedBox(height: 10),
    Container(
      width: 72, height: 4,
      decoration: BoxDecoration(borderRadius: BorderRadius.circular(2), gradient: _goldGrad,
        boxShadow: [BoxShadow(color: _gold.withOpacity(0.35), blurRadius: 8)]),
    ),
  ]);
}

// ─── Promotional Products Carousel (hero right panel) ────────────────────────
class _PromoCarousel extends StatefulWidget {
  final List<Map<String, dynamic>> products;
  final int heroSlide;
  const _PromoCarousel({required this.products, required this.heroSlide});
  @override
  State<_PromoCarousel> createState() => _PromoCarouselState();
}

class _PromoCarouselState extends State<_PromoCarousel> {
  late PageController _ctrl;
  late int _current;

  @override
  void initState() {
    super.initState();
    _current = 0;
    _ctrl = PageController();
  }

  @override
  void didUpdateWidget(_PromoCarousel old) {
    super.didUpdateWidget(old);
    // Sync with hero slide timer
    if (widget.heroSlide != old.heroSlide && widget.products.isNotEmpty) {
      final next = widget.heroSlide % widget.products.length;
      _ctrl.animateToPage(next, duration: const Duration(milliseconds: 500), curve: Curves.easeInOut);
      _current = next;
    }
  }

  @override
  void dispose() { _ctrl.dispose(); super.dispose(); }

  String _promoBadge(Map<String, dynamic> p) {
    final t = p['promotion_type'] as String? ?? '';
    final d = (p['promotion_discount'] as num?)?.toDouble() ?? 0;
    if (t == 'percentage') return '${d.toInt()}% OFF';
    if (t == 'fixed')      return '₱${d.toInt()} OFF';
    if (t == 'buy_one_get_one') return 'BOGO';
    if (t == 'free_shipping')   return 'FREE SHIP';
    return 'SALE';
  }

  @override
  Widget build(BuildContext context) {
    return Stack(children: [
      PageView.builder(
        controller: _ctrl,
        itemCount: widget.products.length,
        onPageChanged: (i) => setState(() => _current = i),
        itemBuilder: (_, i) {
          final p = widget.products[i];
          final imageStr = p['image'] as String? ?? '';
          final firstImg = imageStr.split(',').first.trim();
          final imageUrl = buildImageUrl(firstImg.isNotEmpty ? firstImg : null);
          final hasPromo  = (p['promotion_type'] as String? ?? '').isNotEmpty;

          return Stack(fit: StackFit.expand, children: [
            // Full-width product image
            imageUrl != null
              ? Image.network(imageUrl, fit: BoxFit.cover,
                  loadingBuilder: (_, child, progress) => progress == null
                    ? child
                    : Container(color: const Color(0xFF1a1a1a),
                        child: const Center(child: CircularProgressIndicator(color: _gold, strokeWidth: 2))),
                  errorBuilder: (_, __, ___) => Container(
                    decoration: const BoxDecoration(gradient: _premiumGrad)))
              : Container(decoration: const BoxDecoration(gradient: _premiumGrad)),

            // Promo badge only — top right, pill style
            if (hasPromo)
              Positioned(top: 14, right: 14,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    gradient: const LinearGradient(colors: [Color(0xFFE74C3C), Color(0xFFc0392b)]),
                    borderRadius: BorderRadius.circular(20),
                    boxShadow: [BoxShadow(color: Colors.red.withOpacity(0.5), blurRadius: 10, offset: const Offset(0, 3))],
                  ),
                  child: Text(_promoBadge(p),
                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 11, letterSpacing: 0.8)),
                ),
              ),
          ]);
        },
      ),
    ]);
  }
}
