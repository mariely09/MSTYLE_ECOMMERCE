import 'package:flutter/material.dart';
import 'buyer_bottom_navbar.dart';
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

      if (_sortBy == 'price_low')  list.sort((a, b) => ((a['price'] as num?) ?? 0).compareTo((b['price'] as num?) ?? 0));
      if (_sortBy == 'price_high') list.sort((a, b) => ((b['price'] as num?) ?? 0).compareTo((a['price'] as num?) ?? 0));
      if (_sortBy == 'rating')     list.sort((a, b) => ((b['rating'] as num?) ?? 0).compareTo((a['rating'] as num?) ?? 0));

      if (mounted) setState(() { _results = list; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
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
