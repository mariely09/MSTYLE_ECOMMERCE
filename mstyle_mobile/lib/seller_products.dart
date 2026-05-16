import 'package:flutter/material.dart';
import 'seller_dashboard.dart';
import 'seller_add_product.dart';
import 'seller_orderlists.dart';
import 'seller_analytics.dart';
import 'seller_notifications.dart';
import 'profile.dart';
import 'product_image_carousel.dart';
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

// ─── Product model ────────────────────────────────────────────────────────────
class SellerProduct {
  final int id;
  final String name;
  final String category;
  final double price;
  final int stock;
  final int sold;
  final double rating;
  final bool isActive;
  final bool isFlagged;
  final bool isLowStock;
  final String? image; // raw comma-separated image string from DB

  const SellerProduct({
    required this.id,
    required this.name,
    required this.category,
    required this.price,
    required this.stock,
    required this.sold,
    required this.rating,
    this.isActive = true,
    this.isFlagged = false,
    this.isLowStock = false,
    this.image,
  });

  bool get isOutOfStock => stock <= 0;
}

class SellerProductsPage extends StatefulWidget {
  final String sellerEmail;
  const SellerProductsPage({super.key, required this.sellerEmail});
  @override
  State<SellerProductsPage> createState() => _SellerProductsPageState();
}

class _SellerProductsPageState extends State<SellerProductsPage> {
  final int _navIndex = 1;
  String _filterStatus = '';
  String _filterCategory = '';
  String _sortBy = 'newest';
  String _search = '';
  bool _tableView = false;
  String _businessName = '';
  List<SellerProduct> _products = [];
  bool _loadingProducts = true;

  final _searchCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    _fetchBusinessName();
    _fetchProducts();
  }

  Future<void> _fetchBusinessName() async {
    try {
      final res = await supabase
          .from('users')
          .select('business_name')
          .eq('email', widget.sellerEmail)
          .maybeSingle();
      if (mounted && res != null) {
        setState(() => _businessName = res['business_name'] as String? ?? '');
      }
    } catch (_) {}
  }

  Future<void> _fetchProducts() async {
    try {
      final data = await supabase
          .from('products')
          .select('id, name, category, price, quantity, sold, rating, is_active, is_flagged, low_stock_threshold, image')
          .eq('seller_email', widget.sellerEmail)
          .order('created_at', ascending: false);
      if (mounted) {
        setState(() {
          _products = (data as List).map((p) => SellerProduct(
            id:         p['id'] as int,
            name:       p['name'] as String? ?? '',
            category:   (p['category'] as String? ?? '').toUpperCase(),
            price:      (p['price'] as num?)?.toDouble() ?? 0,
            stock:      (p['quantity'] as num?)?.toInt() ?? 0,
            sold:       (p['sold'] as num?)?.toInt() ?? 0,
            rating:     (p['rating'] as num?)?.toDouble() ?? 0,
            isActive:   p['is_active'] as bool? ?? true,
            isFlagged:  p['is_flagged'] as bool? ?? false,
            isLowStock: ((p['quantity'] as num?)?.toInt() ?? 0) > 0 &&
                        ((p['quantity'] as num?)?.toInt() ?? 0) <=
                        ((p['low_stock_threshold'] as num?)?.toInt() ?? 5),
            image:      p['image'] as String?,
          )).toList();
          _loadingProducts = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loadingProducts = false);
    }
  }

  List<SellerProduct> get _filtered {
    var list = _products.where((p) {
      if (_search.isNotEmpty && !p.name.toLowerCase().contains(_search.toLowerCase())) return false;
      if (_filterCategory.isNotEmpty && p.category != _filterCategory) return false;
      if (_filterStatus == 'active' && !p.isActive) return false;
      if (_filterStatus == 'inactive' && p.isActive) return false;
      if (_filterStatus == 'flagged' && !p.isFlagged) return false;
      if (_filterStatus == 'out_of_stock' && !p.isOutOfStock) return false;
      if (_filterStatus == 'low_stock' && !p.isLowStock) return false;
      return true;
    }).toList();

    switch (_sortBy) {
      case 'price_low':  list.sort((a, b) => a.price.compareTo(b.price)); break;
      case 'price_high': list.sort((a, b) => b.price.compareTo(a.price)); break;
      case 'name_asc':   list.sort((a, b) => a.name.compareTo(b.name)); break;
      case 'name_desc':  list.sort((a, b) => b.name.compareTo(a.name)); break;
      case 'sold_high':  list.sort((a, b) => b.sold.compareTo(a.sold)); break;
      case 'rating_high':list.sort((a, b) => b.rating.compareTo(a.rating)); break;
      case 'stock_high': list.sort((a, b) => b.stock.compareTo(a.stock)); break;
      case 'stock_low':  list.sort((a, b) => a.stock.compareTo(b.stock)); break;
    }
    return list;
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      bottomNavigationBar: _bottomNav(),
      floatingActionButton: FloatingActionButton(
        onPressed: () async {
          await Navigator.push(context,
            MaterialPageRoute(builder: (_) => SellerAddProductPage(sellerEmail: widget.sellerEmail)));
          _fetchProducts();
        },
        backgroundColor: _gold,
        child: const Icon(Icons.add, color: _primary),
      ),
      body: _loadingProducts
        ? const Center(child: CircularProgressIndicator(color: _gold))
        : CustomScrollView(
          slivers: [
            _appBar(),
            SliverToBoxAdapter(child: _pageHeader()),
            SliverToBoxAdapter(child: _filterSection()),
            SliverToBoxAdapter(child: _viewToggle()),
            if (_tableView)
              SliverToBoxAdapter(child: _tableViewWidget())
            else
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(12, 0, 12, 80),
                sliver: SliverGrid(
                  delegate: SliverChildBuilderDelegate(
                    (_, i) => _productCard(_filtered[i]),
                    childCount: _filtered.length,
                  ),
                  gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: 2, crossAxisSpacing: 12, mainAxisSpacing: 12,
                    childAspectRatio: 0.72,
                  ),
                ),
              ),
            if (_filtered.isEmpty)
              SliverFillRemaining(child: _emptyState()),
            const SliverToBoxAdapter(child: SizedBox(height: 16)),
          ],
        ),
    );
  }

  // ─── App Bar ──────────────────────────────────────────────────────────────
  SliverAppBar _appBar() => SliverAppBar(
    pinned: true,
    backgroundColor: _primary,
    elevation: 6,
    titleSpacing: 16,
    automaticallyImplyLeading: false,
    title: Row(children: [
      Container(
        width: 32, height: 32,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: _goldGrad,
          boxShadow: [BoxShadow(color: _gold.withOpacity(0.3), blurRadius: 6)],
        ),
        child: const Icon(Icons.store, color: _primary, size: 18),
      ),
      const SizedBox(width: 8),
      Flexible(
        child: ShaderMask(
          shaderCallback: (b) => _goldGrad.createShader(b),
          child: Text(
            _businessName.isNotEmpty ? _businessName : widget.sellerEmail.split('@').first,
            style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800, letterSpacing: 0.5),
            maxLines: 1, overflow: TextOverflow.ellipsis,
          ),
        ),
      ),
    ]),
    actions: [
      IconButton(
        icon: const Icon(Icons.notifications_outlined, color: Colors.white, size: 22),
        onPressed: () => Navigator.push(context,
          MaterialPageRoute(builder: (_) => SellerNotificationsPage(sellerEmail: widget.sellerEmail))),
      ),
      IconButton(
        icon: const Icon(Icons.chat_bubble_outline, color: Colors.white, size: 22),
        onPressed: () => ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Messages coming soon'), behavior: SnackBarBehavior.floating)),
      ),
      IconButton(
        icon: const Icon(Icons.person_outline, color: Colors.white, size: 22),
        onPressed: () => Navigator.push(context,
          MaterialPageRoute(builder: (_) => ProfilePage(userEmail: widget.sellerEmail))),
      ),
    ],
  );

  // ─── Page Header ──────────────────────────────────────────────────────────
  Widget _pageHeader() => Container(
    width: double.infinity,
    padding: const EdgeInsets.fromLTRB(20, 24, 20, 20),
    decoration: const BoxDecoration(gradient: _premiumGrad),
    child: Column(children: [
      Container(
        width: 56, height: 56,
        decoration: BoxDecoration(shape: BoxShape.circle, gradient: _goldGrad,
          boxShadow: [BoxShadow(color: _gold.withOpacity(0.4), blurRadius: 12)]),
        child: const Icon(Icons.inventory_2_outlined, color: _primary, size: 26),
      ),
      const SizedBox(height: 12),
      const Text('My Products',
        style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w800)),
      const SizedBox(height: 4),
      Text('Manage and showcase your product inventory',
        style: TextStyle(color: Colors.white.withOpacity(0.7), fontSize: 12)),
    ]),
  );

  // ─── Filter Section ───────────────────────────────────────────────────────
  Widget _filterSection() => Container(
    color: Colors.white,
    padding: const EdgeInsets.all(14),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        const Icon(Icons.tune, color: _gold, size: 16),
        const SizedBox(width: 6),
        const Text('Filter & Search', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
        const Spacer(),
        if (_filterStatus.isNotEmpty || _filterCategory.isNotEmpty || _search.isNotEmpty)
          GestureDetector(
            onTap: () => setState(() { _filterStatus = ''; _filterCategory = ''; _search = ''; _searchCtrl.clear(); }),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(color: Colors.red.shade50, borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.red.shade200)),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(Icons.close, size: 12, color: Colors.red.shade400),
                const SizedBox(width: 4),
                Text('Clear', style: TextStyle(color: Colors.red.shade400, fontSize: 11, fontWeight: FontWeight.w600)),
              ]),
            ),
          ),
      ]),
      const SizedBox(height: 12),
      // Search
      TextField(
        controller: _searchCtrl,
        style: const TextStyle(color: _accent, fontSize: 13),
        onChanged: (v) => setState(() => _search = v),
        decoration: InputDecoration(
          hintText: 'Search by product name...',
          hintStyle: const TextStyle(color: _textLight, fontSize: 13),
          prefixIcon: const Icon(Icons.search, color: _textLight, size: 18),
          filled: true, fillColor: _bg,
          contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: _border)),
          focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: _gold, width: 2)),
        ),
      ),
      const SizedBox(height: 10),
      Row(children: [
        Expanded(child: _dropdown('Status', _filterStatus, {
          '': 'All Status', 'active': 'Active', 'inactive': 'Inactive',
          'flagged': 'Flagged', 'out_of_stock': 'Out of Stock', 'low_stock': 'Low Stock',
        }, (v) => setState(() => _filterStatus = v ?? ''))),
        const SizedBox(width: 10),
        Expanded(child: _dropdown('Category', _filterCategory, {
          '': 'All Categories', 'SUITS': 'Suits', 'SHIRTS': 'Shirts', 'PANTS': 'Pants',
          'JACKETS': 'Jackets', 'OUTERWEAR': 'Outerwear', 'ACTIVEWEAR': 'Activewear',
          'SHOES': 'Shoes', 'GROOMING': 'Grooming',
        }, (v) => setState(() => _filterCategory = v ?? ''))),
      ]),
      const SizedBox(height: 10),
      _dropdown('Sort By', _sortBy, {
        'newest': 'Newest First', 'oldest': 'Oldest First',
        'price_low': 'Price: Low to High', 'price_high': 'Price: High to Low',
        'name_asc': 'Name: A to Z', 'name_desc': 'Name: Z to A',
        'stock_high': 'Stock: High to Low', 'stock_low': 'Stock: Low to High',
        'sold_high': 'Most Sold', 'rating_high': 'Highest Rated',
      }, (v) => setState(() => _sortBy = v ?? 'newest')),
      const SizedBox(height: 8),
      Row(children: [
        const Icon(Icons.inventory_2_outlined, color: _textLight, size: 13),
        const SizedBox(width: 5),
        Text('Showing ${_filtered.length} product${_filtered.length != 1 ? 's' : ''}',
          style: const TextStyle(color: _textLight, fontSize: 12)),
      ]),
    ]),
  );

  Widget _dropdown(String label, String value, Map<String, String> options, ValueChanged<String?> onChanged) =>
    DropdownButtonFormField<String>(
      value: value,
      isExpanded: true,
      style: const TextStyle(color: _accent, fontSize: 12, fontWeight: FontWeight.w600),
      decoration: InputDecoration(
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        filled: true, fillColor: _bg,
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: _border)),
        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: _gold, width: 2)),
      ),
      items: options.entries.map((e) => DropdownMenuItem(value: e.key,
        child: Text(e.value, overflow: TextOverflow.ellipsis))).toList(),
      onChanged: onChanged,
    );

  // ─── View Toggle ──────────────────────────────────────────────────────────
  Widget _viewToggle() => Container(
    color: Colors.white,
    padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
    child: Row(children: [
      _toggleBtn(Icons.grid_view_rounded, 'Card View', !_tableView, () => setState(() => _tableView = false)),
      const SizedBox(width: 8),
      _toggleBtn(Icons.table_rows_outlined, 'Table View', _tableView, () => setState(() => _tableView = true)),
    ]),
  );

  Widget _toggleBtn(IconData icon, String label, bool active, VoidCallback onTap) => GestureDetector(
    onTap: onTap,
    child: AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      decoration: BoxDecoration(
        gradient: active ? _goldGrad : null,
        color: active ? null : _bg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: active ? _gold : _border),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 14, color: active ? _primary : _textLight),
        const SizedBox(width: 5),
        Text(label, style: TextStyle(color: active ? _primary : _textLight,
          fontSize: 12, fontWeight: active ? FontWeight.w700 : FontWeight.w500)),
      ]),
    ),
  );

  // ─── Product Card ─────────────────────────────────────────────────────────
  Widget _productCard(SellerProduct p) => Container(
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      border: p.isFlagged ? Border.all(color: Colors.orange.shade300, width: 2) : null,
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.06), blurRadius: 12, offset: const Offset(0, 3))],
    ),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      // Image area
      Expanded(
        child: Stack(children: [
          // Actual product image via carousel
          ClipRRect(
            borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
            child: ProductImageCarousel(
              imageString: p.image,
              height: double.infinity,
              borderRadius: 16,
              placeholder: Icons.inventory_2_outlined,
            ),
          ),
          // Inactive overlay
          if (!p.isActive)
            Positioned.fill(
              child: ClipRRect(
                borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
                child: Container(color: Colors.black.withOpacity(0.35)),
              ),
            ),
          // Status badges
          Positioned(top: 8, left: 8,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (p.isFlagged) _badge('Flagged', Colors.orange),
              if (!p.isActive) _badge('Inactive', Colors.grey),
              if (p.isOutOfStock) _badge('Out of Stock', Colors.red),
              if (p.isLowStock && !p.isOutOfStock) _badge('Low Stock', Colors.amber.shade700),
            ]),
          ),
          // Action buttons
          Positioned(top: 8, right: 8,
            child: Column(children: [
              _overlayBtn(Icons.edit_outlined, () => _showEditSheet(p)),
              const SizedBox(height: 6),
              _overlayBtn(Icons.delete_outline, () => _confirmDelete(p), color: Colors.red.shade400),
            ]),
          ),
        ]),
      ),
      // Info
      Padding(
        padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(p.name, style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 12),
            maxLines: 1, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 3),
          Row(children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(6),
                border: Border.all(color: _border)),
              child: Text(p.category, style: const TextStyle(color: _textLight, fontSize: 9, fontWeight: FontWeight.w600)),
            ),
          ]),
          const SizedBox(height: 5),
          Text('₱${p.price.toStringAsFixed(2)}',
            style: const TextStyle(color: _accent, fontWeight: FontWeight.w900, fontSize: 14)),
          const SizedBox(height: 5),
          Row(children: [
            _statChip(Icons.inventory_2_outlined, '${p.stock}', p.isOutOfStock ? Colors.red : p.isLowStock ? Colors.orange : Colors.green),
            const SizedBox(width: 5),
            _statChip(Icons.trending_up, '${p.sold}', Colors.blue),
            const SizedBox(width: 5),
            _statChip(Icons.star, p.rating.toStringAsFixed(1), _gold),
          ]),
        ]),
      ),
    ]),
  );

  Widget _badge(String label, Color color) => Container(
    margin: const EdgeInsets.only(bottom: 3),
    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
    decoration: BoxDecoration(color: color.withOpacity(0.9), borderRadius: BorderRadius.circular(6)),
    child: Text(label, style: const TextStyle(color: Colors.white, fontSize: 9, fontWeight: FontWeight.w700)),
  );

  Widget _overlayBtn(IconData icon, VoidCallback onTap, {Color? color}) => GestureDetector(
    onTap: onTap,
    child: Container(
      width: 28, height: 28,
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.92), shape: BoxShape.circle,
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.12), blurRadius: 4)],
      ),
      child: Icon(icon, size: 13, color: color ?? _accent),
    ),
  );

  Widget _statChip(IconData icon, String value, Color color) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 3),
    decoration: BoxDecoration(color: color.withOpacity(0.1), borderRadius: BorderRadius.circular(6)),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 9, color: color),
      const SizedBox(width: 3),
      Text(value, style: TextStyle(color: color, fontSize: 9, fontWeight: FontWeight.w700)),
    ]),
  );

  // ─── Table View ───────────────────────────────────────────────────────────
  Widget _tableViewWidget() => Container(
    margin: const EdgeInsets.fromLTRB(12, 0, 12, 80),
    decoration: BoxDecoration(
      color: Colors.white, borderRadius: BorderRadius.circular(16),
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.06), blurRadius: 12, offset: const Offset(0, 3))],
    ),
    child: SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowColor: WidgetStateProperty.all(_bg),
        headingTextStyle: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 12),
        dataTextStyle: const TextStyle(color: _accent, fontSize: 12),
        columnSpacing: 16,
        columns: const [
          DataColumn(label: Text('#')),
          DataColumn(label: Text('Product Name')),
          DataColumn(label: Text('Category')),
          DataColumn(label: Text('Price')),
          DataColumn(label: Text('Stock')),
          DataColumn(label: Text('Sold')),
          DataColumn(label: Text('Rating')),
          DataColumn(label: Text('Actions')),
        ],
        rows: _filtered.asMap().entries.map((entry) {
          final i = entry.key;
          final p = entry.value;
          return DataRow(cells: [
            DataCell(Text('${i + 1}')),
            DataCell(Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.center, children: [
              Text(p.name, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 12), overflow: TextOverflow.ellipsis),
              if (p.isFlagged) const Text('Flagged', style: TextStyle(color: Colors.orange, fontSize: 10)),
              if (!p.isActive) const Text('Inactive', style: TextStyle(color: Colors.grey, fontSize: 10)),
            ])),
            DataCell(Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
              decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(6), border: Border.all(color: _border)),
              child: Text(p.category, style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w600, color: _textLight)),
            )),
            DataCell(Text('₱${p.price.toStringAsFixed(2)}', style: const TextStyle(fontWeight: FontWeight.w700))),
            DataCell(Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: (p.isOutOfStock ? Colors.red : p.isLowStock ? Colors.orange : Colors.green).withOpacity(0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text('${p.stock}', style: TextStyle(
                color: p.isOutOfStock ? Colors.red : p.isLowStock ? Colors.orange : Colors.green,
                fontWeight: FontWeight.w700, fontSize: 12)),
            )),
            DataCell(Text('${p.sold}')),
            DataCell(Row(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.star, color: _gold, size: 12),
              const SizedBox(width: 3),
              Text(p.rating.toStringAsFixed(1), style: const TextStyle(fontWeight: FontWeight.w700)),
            ])),
            DataCell(Row(children: [
              _overlayBtn(Icons.edit_outlined, () => _showEditSheet(p)),
              const SizedBox(width: 6),
              _overlayBtn(Icons.delete_outline, () => _confirmDelete(p), color: Colors.red.shade400),
            ])),
          ]);
        }).toList(),
      ),
    ),
  );

  // ─── Empty State ──────────────────────────────────────────────────────────
  Widget _emptyState() => Center(
    child: SingleChildScrollView(
      padding: const EdgeInsets.symmetric(vertical: 24),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        const Icon(Icons.inventory_2_outlined, size: 72, color: _border),
        const SizedBox(height: 16),
        const Text('No Products Found', style: TextStyle(color: _accent, fontSize: 18, fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        const Text("You haven't added any products yet.", style: TextStyle(color: _textLight, fontSize: 13)),
        const SizedBox(height: 20),
        GestureDetector(
          onTap: _showAddProductSheet,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
            decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(12)),
            child: const Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.add, color: Colors.white, size: 16),
              SizedBox(width: 6),
              Text('Add Your First Product', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 13)),
            ]),
          ),
        ),
      ]),
    ),
  );

  // ─── Add / Edit Sheets ────────────────────────────────────────────────────
  void _showAddProductSheet() async {
    await Navigator.push(context,
      MaterialPageRoute(builder: (_) => SellerAddProductPage(sellerEmail: widget.sellerEmail)));
    _fetchProducts();
  }

  void _showEditSheet(SellerProduct p) => _showProductSheet(p);

  void _showProductSheet(SellerProduct? existing) {
    final nameCtrl = TextEditingController(text: existing?.name ?? '');
    final priceCtrl = TextEditingController(text: existing != null ? existing.price.toStringAsFixed(2) : '');
    final stockCtrl = TextEditingController(text: existing != null ? '${existing.stock}' : '');
    String category = existing?.category ?? '';
    final List<String> selectedSizes = [];

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
        child: Container(
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 32),
          decoration: const BoxDecoration(color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Center(child: Container(width: 40, height: 4,
              decoration: BoxDecoration(color: _border, borderRadius: BorderRadius.circular(2)))),
            const SizedBox(height: 16),
            Row(children: [
              Icon(existing == null ? Icons.add_box_outlined : Icons.edit_outlined, color: _gold, size: 20),
              const SizedBox(width: 8),
              Text(existing == null ? 'Add New Product' : 'Edit Product',
                style: const TextStyle(color: _accent, fontSize: 16, fontWeight: FontWeight.w800)),
            ]),
            const SizedBox(height: 4),
            Container(width: 36, height: 3, decoration: BoxDecoration(borderRadius: BorderRadius.circular(2), gradient: _goldGrad)),
            const SizedBox(height: 16),
            _sheetField('Product Name', nameCtrl, Icons.inventory_2_outlined),
            const SizedBox(height: 12),
            _sheetField('Price (₱)', priceCtrl, Icons.currency_exchange, type: TextInputType.number),
            const SizedBox(height: 12),
            _sheetField('Stock Quantity', stockCtrl, Icons.numbers, type: TextInputType.number),
            const SizedBox(height: 20),
            GestureDetector(
              onTap: () async {
                final name  = nameCtrl.text.trim();
                final price = double.tryParse(priceCtrl.text.trim()) ?? 0;
                final stock = int.tryParse(stockCtrl.text.trim()) ?? 0;
                if (name.isEmpty) return;
                Navigator.pop(context);
                try {
                  if (existing == null) {
                    await supabase.from('products').insert({
                      'name':         name,
                      'price':        price,
                      'quantity':     stock,
                      'seller_email': widget.sellerEmail,
                      'category':     category.isEmpty ? 'OTHER' : category,
                      'is_active':    true,
                    });
                  } else {
                    await supabase.from('products').update({
                      'name':     name,
                      'price':    price,
                      'quantity': stock,
                    }).eq('id', existing.id);
                  }
                  _fetchProducts();
                  if (!mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                    content: Text(existing == null ? 'Product added successfully!' : 'Product updated successfully!'),
                    backgroundColor: _primary, behavior: SnackBarBehavior.floating,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ));
                } catch (e) {
                  if (!mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                    content: Text('Error: $e'),
                    backgroundColor: Colors.red.shade600, behavior: SnackBarBehavior.floating,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ));
                }
              },
              child: Container(
                width: double.infinity, padding: const EdgeInsets.symmetric(vertical: 14),
                decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(14),
                  boxShadow: [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 10, offset: const Offset(0, 4))]),
                child: Center(child: Text(existing == null ? 'Add Product' : 'Update Product',
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 14))),
              ),
            ),
          ]),
        ),
      ),
    );
  }

  Widget _sheetField(String label, TextEditingController ctrl, IconData icon,
      {TextInputType type = TextInputType.text}) =>
    TextField(
      controller: ctrl, keyboardType: type,
      style: const TextStyle(color: _accent, fontSize: 14),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: _textLight, fontSize: 13),
        prefixIcon: Icon(icon, color: _gold, size: 18),
        filled: true, fillColor: _bg,
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: _border)),
        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: _gold, width: 2)),
      ),
    );

  void _confirmDelete(SellerProduct p) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Row(children: [
          Icon(Icons.delete_outline, color: Colors.red),
          SizedBox(width: 8),
          Text('Delete Product', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 16)),
        ]),
        content: Text('Are you sure you want to delete "${p.name}"? This action cannot be undone.',
          style: const TextStyle(color: _textLight, fontSize: 13)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          ElevatedButton(
            onPressed: () async {
              Navigator.pop(context);
              try {
                await supabase.from('products').delete().eq('id', p.id);
                _fetchProducts();
                if (!mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                  content: Text('"${p.name}" deleted.'),
                  backgroundColor: Colors.red.shade600, behavior: SnackBarBehavior.floating,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ));
              } catch (e) {
                if (!mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                  content: Text('Error: $e'),
                  backgroundColor: Colors.red.shade600, behavior: SnackBarBehavior.floating,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ));
              }
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
  }

  // ─── Bottom Nav ───────────────────────────────────────────────────────────
  Widget _bottomNav() => Container(
    decoration: BoxDecoration(
      color: _primary,
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.25), blurRadius: 20, offset: const Offset(0, -4))],
    ),
    child: SafeArea(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
        child: Row(children: [
          _navItem(0, Icons.speed, Icons.speed, 'Dashboard'),
          _navItem(1, Icons.inventory_2_outlined, Icons.inventory_2, 'Products'),
          _navItem(2, Icons.list_alt_outlined, Icons.list_alt, 'Orders'),
          _navItem(3, Icons.bar_chart_outlined, Icons.bar_chart, 'Analytics'),
        ]),
      ),
    ),
  );

  Widget _navItem(int index, IconData icon, IconData activeIcon, String label) {
    final active = _navIndex == index;
    return Expanded(
      child: GestureDetector(
      onTap: () {
        if (index == 0) Navigator.pushReplacement(context,
          MaterialPageRoute(builder: (_) => SellerDashboardPage(sellerEmail: widget.sellerEmail)));
        if (index == 2) Navigator.pushReplacement(context,
          MaterialPageRoute(builder: (_) => SellerOrderListsPage(sellerEmail: widget.sellerEmail)));
        if (index == 3) Navigator.pushReplacement(context,
          MaterialPageRoute(builder: (_) => SellerAnalyticsPage(sellerEmail: widget.sellerEmail)));
      },
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(active ? activeIcon : icon, color: active ? _gold : Colors.white54, size: 22),
          const SizedBox(height: 3),
          Text(label, style: TextStyle(
            color: active ? _gold : Colors.white54,
            fontSize: 10, fontWeight: active ? FontWeight.w700 : FontWeight.w400)),
        ]),
      ),
    ),
  );
  }
}
