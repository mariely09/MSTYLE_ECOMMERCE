import 'package:flutter/material.dart';
import 'buyer_bottom_navbar.dart';
import 'buyer_service.dart';
import 'product_card.dart';
import 'supabase_client.dart';

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

class BuyerSearchResultsPage extends StatefulWidget {
  final String userEmail;

  /// Pre-filled query — pass from the search bar if available.
  final String initialQuery;

  const BuyerSearchResultsPage({
    super.key,
    required this.userEmail,
    this.initialQuery = '',
  });

  @override
  State<BuyerSearchResultsPage> createState() => _BuyerSearchResultsPageState();
}

class _BuyerSearchResultsPageState extends State<BuyerSearchResultsPage> {
  late final TextEditingController _searchCtrl;
  final FocusNode _focusNode = FocusNode();

  bool _loading = false;
  List<Map<String, dynamic>> _results = [];
  String _lastQuery = '';

  String _sortBy = 'newest';

  @override
  void initState() {
    super.initState();
    _searchCtrl = TextEditingController(text: widget.initialQuery);
    if (widget.initialQuery.isNotEmpty) {
      _search(widget.initialQuery);
    }
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  Future<void> _search(String query) async {
    final q = query.trim();
    if (q.isEmpty) {
      setState(() { _results = []; _lastQuery = ''; });
      return;
    }
    setState(() { _loading = true; _lastQuery = q; });
    try {
      final data = await supabase
          .from('products')
          .select('id, name, price, image, category, seller_email, quantity, sold, rating, variations, sizes')
          .or('quantity.gt.0,sold.gt.0')
          .ilike('name', '%$q%')
          .order('id', ascending: false);

      var list = List<Map<String, dynamic>>.from(data as List);
      list = list.where((p) {
        if (p['is_active'] == false) return false;
        final flaggedAt = p['flagged_at'];
        if (flaggedAt != null && flaggedAt.toString().isNotEmpty) return false;
        return true;
      }).toList();

      // ── Compute live ratings from reviews table ──
      if (list.isNotEmpty) {
        try {
          final productIds = list.map((p) => p['id']).whereType<int>().toList();
          if (productIds.isNotEmpty) {
            final reviewsRes = await supabase
                .from('reviews')
                .select('product_id, rating')
                .inFilter('product_id', productIds);

            final ratingMap = <int, List<double>>{};
            for (final r in (reviewsRes as List)) {
              final pid = r['product_id'] as int?;
              final rat = (r['rating'] as num?)?.toDouble();
              if (pid != null && rat != null) {
                ratingMap.putIfAbsent(pid, () => []).add(rat);
              }
            }
            for (final p in list) {
              final pid = p['id'] as int?;
              if (pid == null) continue;
              final ratings = ratingMap[pid];
              if (ratings != null && ratings.isNotEmpty) {
                final avg = ratings.reduce((a, b) => a + b) / ratings.length;
                p['rating'] = double.parse(avg.toStringAsFixed(1));
                p['review_count'] = ratings.length;
              } else {
                p['review_count'] = 0;
              }
            }
          }
        } catch (e) {
          debugPrint('Search rating fetch error: $e');
        }
      }

      // ── Enrich with active promotions ──
      if (list.isNotEmpty) {
        await _enrichWithPromotions(list);
      }

      // Sort after live ratings are attached
      if (_sortBy == 'price_low')  list.sort((a, b) => ((a['price'] as num?) ?? 0).compareTo((b['price'] as num?) ?? 0));
      if (_sortBy == 'price_high') list.sort((a, b) => ((b['price'] as num?) ?? 0).compareTo((a['price'] as num?) ?? 0));
      if (_sortBy == 'rating')     list.sort((a, b) => ((b['rating'] as num?) ?? 0).compareTo((a['rating'] as num?) ?? 0));

      if (mounted) setState(() { _results = list; _loading = false; });
    } catch (e) {
      debugPrint('Search error: $e');
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Fetches active promotions and enriches each product map with
  /// promotion_type, promotion_discount, promotion_code, and sale_price.
  Future<void> _enrichWithPromotions(List<Map<String, dynamic>> products) async {
    try {
      final today = DateTime.now().toIso8601String().split('T')[0];
      final promoRes = await supabase
          .from('promotions')
          .select('id, type, discount_value, code, product_scope, seller_email')
          .eq('is_active', true)
          .lte('start_date', today)
          .gte('end_date', today);

      final promos = List<Map<String, dynamic>>.from(promoRes as List);
      if (promos.isEmpty) return;

      // Fetch specific-scope product IDs
      final specificIds = promos
          .where((p) => (p['product_scope'] as String? ?? '') == 'specific')
          .map((p) => p['id'] as int)
          .toList();
      final Map<int, Set<int>> promoProductIds = {}; // promoId → productIds
      if (specificIds.isNotEmpty) {
        final ppRes = await supabase
            .from('promotion_products')
            .select('promotion_id, product_id')
            .inFilter('promotion_id', specificIds);
        for (final row in (ppRes as List)) {
          final pid = row['promotion_id'] as int?;
          final prodId = row['product_id'] as int?;
          if (pid != null && prodId != null) {
            promoProductIds.putIfAbsent(pid, () => {}).add(prodId);
          }
        }
      }

      // Fetch category-scope categories
      final categoryIds = promos
          .where((p) => (p['product_scope'] as String? ?? '') == 'category')
          .map((p) => p['id'] as int)
          .toList();
      final Map<int, Set<String>> promoCategoryNames = {};
      if (categoryIds.isNotEmpty) {
        final pcRes = await supabase
            .from('promotion_categories')
            .select('promotion_id, category')
            .inFilter('promotion_id', categoryIds);
        for (final row in (pcRes as List)) {
          final pid = row['promotion_id'] as int?;
          final cat = (row['category'] as String? ?? '').toUpperCase();
          if (pid != null && cat.isNotEmpty) {
            promoCategoryNames.putIfAbsent(pid, () => {}).add(cat);
          }
        }
      }

      // Match each product to its best promotion
      for (final product in products) {
        final productId = product['id'] as int?;
        if (productId == null) continue;
        final sellerEmail = product['seller_email'] as String? ?? '';
        final category = (product['category'] as String? ?? '').toUpperCase();
        final basePrice = (product['price'] as num?)?.toDouble() ?? 0;

        for (final promo in promos) {
          // Promo must belong to this product's seller
          if ((promo['seller_email'] as String? ?? '') != sellerEmail) continue;

          final scope = promo['product_scope'] as String? ?? 'all';
          bool qualifies = false;
          if (scope == 'all') {
            qualifies = true;
          } else if (scope == 'specific') {
            qualifies = promoProductIds[promo['id'] as int]?.contains(productId) ?? false;
          } else if (scope == 'category') {
            qualifies = promoCategoryNames[promo['id'] as int]?.contains(category) ?? false;
          }

          if (qualifies) {
            final promoType     = promo['type'] as String? ?? '';
            final promoDiscount = double.tryParse(promo['discount_value']?.toString() ?? '0') ?? 0;
            double? salePrice;
            if (promoType == 'percentage' && promoDiscount > 0) {
              salePrice = (basePrice * (1 - promoDiscount / 100)).clamp(0.01, double.infinity);
            } else if (promoType == 'fixed' && promoDiscount > 0) {
              salePrice = (basePrice - promoDiscount).clamp(0.01, double.infinity);
            }
            product['promotion_type']     = promoType;
            product['promotion_discount'] = promoDiscount;
            product['promotion_code']     = promo['code'] as String? ?? '';
            if (salePrice != null) product['sale_price'] = salePrice;
            break; // one promo per product
          }
        }
      }
    } catch (e) {
      debugPrint('_enrichWithPromotions error: $e');
    }
  }

  void _onSubmit(String value) => _search(value);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      bottomNavigationBar: widget.userEmail.isNotEmpty
          ? BuyerBottomNavBar(
              userEmail: widget.userEmail,
              currentPage: BuyerPage.search,
              onSearch: () => _focusNode.requestFocus(),
            )
          : null,
      body: CustomScrollView(slivers: [
        SliverAppBar(
          pinned: true,
          backgroundColor: _primary,
          automaticallyImplyLeading: false,
          leading: IconButton(
            icon: const Icon(Icons.arrow_back, color: Colors.white),
            onPressed: () => Navigator.pop(context),
          ),
          flexibleSpace: FlexibleSpaceBar(
            background: Container(
              color: _primary,
              padding: const EdgeInsets.fromLTRB(48, 0, 12, 8),
              alignment: Alignment.bottomCenter,
              child: _searchBar(),
            ),
          ),
          expandedHeight: 72,
          collapsedHeight: 72,
        ),
        if (_loading)
          const SliverFillRemaining(
            child: Center(child: CircularProgressIndicator(color: _gold)))
        else if (_lastQuery.isEmpty)
          SliverFillRemaining(child: _emptyPrompt())
        else if (_results.isEmpty)
          SliverFillRemaining(child: _noResults())
        else ...[
          SliverToBoxAdapter(child: _resultCount()),
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 80),
            sliver: SliverGrid(
              delegate: SliverChildBuilderDelegate(
                (_, i) => ProductCard(
                  product: _results[i],
                  userEmail: widget.userEmail,
                ),
                childCount: _results.length,
              ),
              gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: 2,
                crossAxisSpacing: 12,
                mainAxisSpacing: 12,
                childAspectRatio: 0.68,
              ),
            ),
          ),
        ],
      ]),
    );
  }

  Widget _searchBar() => Container(
    color: _primary,
    padding: const EdgeInsets.fromLTRB(12, 8, 12, 14),
    child: TextField(
      controller: _searchCtrl,
      focusNode: _focusNode,
      autofocus: widget.initialQuery.isEmpty,
      textInputAction: TextInputAction.search,
      onSubmitted: _onSubmit,
      style: const TextStyle(color: Colors.white, fontSize: 14),
      decoration: InputDecoration(
        hintText: 'Search for premium menswear...',
        hintStyle: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 14),
        prefixIcon: const Icon(Icons.search, color: _gold, size: 20),
        suffixIcon: _searchCtrl.text.isNotEmpty
          ? IconButton(
              icon: const Icon(Icons.close, color: Colors.white54, size: 18),
              onPressed: () {
                _searchCtrl.clear();
                setState(() { _results = []; _lastQuery = ''; });
              })
          : null,
        filled: true,
        fillColor: Colors.white.withOpacity(0.1),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(30),
          borderSide: BorderSide(color: _gold.withOpacity(0.4), width: 1.5),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(30),
          borderSide: const BorderSide(color: _gold, width: 2),
        ),
      ),
      onChanged: (v) => setState(() {}), // rebuild to show/hide clear button
    ),
  );

  Widget _resultCount() => Padding(
    padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
    child: Text(
      '${_results.length} result${_results.length == 1 ? '' : 's'} for "$_lastQuery"',
      style: const TextStyle(color: _textLight, fontSize: 12, fontWeight: FontWeight.w500),
    ),
  );

  Widget _emptyPrompt() => Center(
    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
      const Icon(Icons.search, size: 72, color: _border),
      const SizedBox(height: 16),
      const Text('Search for products', style: TextStyle(color: _accent, fontSize: 18, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      const Text('Type a product name or category above.',
        style: TextStyle(color: _textLight, fontSize: 13)),
    ]),
  );

  Widget _noResults() => Center(
    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
      const Icon(Icons.search_off_outlined, size: 72, color: _border),
      const SizedBox(height: 16),
      Text('No results for "$_lastQuery"',
        style: const TextStyle(color: _accent, fontSize: 17, fontWeight: FontWeight.w700),
        textAlign: TextAlign.center),
      const SizedBox(height: 8),
      const Text('Try a different keyword or category.',
        style: TextStyle(color: _textLight, fontSize: 13)),
    ]),
  );
}
