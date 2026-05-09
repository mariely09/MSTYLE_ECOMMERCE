import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'login.dart';
import 'buyer_homepage.dart';
import 'buyer_orders.dart';
import 'buyer_checkout.dart';
import 'buyer_wishlist.dart';
import 'profile.dart';
import 'buyer_notifications.dart';
import 'buyer_service.dart';
import 'product_image_carousel.dart';
import 'buyer_viewproduct.dart';
import 'buyer_view_shop.dart';

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

// ─── Mock cart item model ─────────────────────────────────────────────────────
class CartItem {
  final String id;
  final String name;
  final double price;
  final String? color;
  final String? size;
  int quantity;
  bool selected;

  CartItem({
    required this.id,
    required this.name,
    required this.price,
    this.color,
    this.size,
    this.quantity = 1,
    this.selected = false,
  });
}

class BuyerCartPage extends StatefulWidget {
  final String userEmail;
  const BuyerCartPage({super.key, required this.userEmail});
  @override
  State<BuyerCartPage> createState() => _BuyerCartPageState();
}

class _BuyerCartPageState extends State<BuyerCartPage> {
  bool _loading = true;
  List<Map<String, dynamic>> _items = [];

  bool get _allSelected => _items.isNotEmpty && _items.every((i) => i['_selected'] == true);
  List<Map<String, dynamic>> get _selectedItems => _items.where((i) => i['_selected'] == true).toList();
  int get _totalItems => _selectedItems.fold(0, (s, i) => s + (i['quantity'] as int? ?? 1));
  double get _totalAmount => _selectedItems.fold(0.0, (s, i) =>
    s + (double.tryParse(i['price']?.toString() ?? '0') ?? 0) * (i['quantity'] as int? ?? 1));

  @override
  void initState() {
    super.initState();
    _loadCart();
  }

  Future<void> _loadCart() async {
    setState(() => _loading = true);
    try {
      final data = await BuyerService.getCartItems(widget.userEmail);
      // Add local selection flag
      for (final item in data) { item['_selected'] = false; }
      if (mounted) setState(() { _items = data; _loading = false; });
    } catch (e) {
      debugPrint('_loadCart error: $e');
      if (mounted) setState(() => _loading = false);
    }
  }

  void _toggleAll(bool? val) => setState(() {
    for (final item in _items) item['_selected'] = val ?? false;
  });

  void _deleteSelected() {
    if (_selectedItems.isEmpty) return;
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Delete Items', style: TextStyle(color: _accent, fontWeight: FontWeight.w700)),
        content: Text('Remove ${_selectedItems.length} selected item(s)?', style: const TextStyle(color: _textLight)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          TextButton(
            onPressed: () async {
              Navigator.pop(context);
              for (final item in _selectedItems) {
                await BuyerService.removeFromCart(item['id'] as int);
              }
              await _loadCart();
            },
            child: const Text('Delete', style: TextStyle(color: Colors.red)),
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
        : Stack(
            children: [
              CustomScrollView(
                slivers: [
                  _appBar(),
                  if (_items.isEmpty)
                    SliverFillRemaining(child: _emptyCart())
                  else ...[
                    SliverToBoxAdapter(child: _controls()),
                    SliverList(
                      delegate: SliverChildBuilderDelegate(
                        (_, i) => _cartItemTile(_items[i]),
                        childCount: _items.length,
                      ),
                    ),
                    const SliverToBoxAdapter(child: SizedBox(height: 16)),
                  ],
                  SliverToBoxAdapter(child: _orderSummary()),
                  // padding so content isn't hidden behind the pinned button
                  const SliverToBoxAdapter(child: SizedBox(height: 88)),
                ],
              ),
              Positioned(
                left: 0, right: 0, bottom: 0,
                child: _checkoutButton(),
              ),
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
    leading: IconButton(
      icon: const Icon(Icons.arrow_back, color: Colors.white),
      onPressed: () => Navigator.pop(context),
    ),
    title: const Text('Shopping Cart',
      style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w700)),
  );

  // ─── Cart Header ──────────────────────────────────────────────────────────
  Widget _cartHeader() => Container(
    width: double.infinity,
    padding: const EdgeInsets.fromLTRB(20, 28, 20, 24),
    decoration: const BoxDecoration(gradient: _premiumGrad),
    child: Column(children: [
      Container(
        width: 64, height: 64,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: _goldGrad,
          boxShadow: [BoxShadow(color: _gold.withOpacity(0.4), blurRadius: 16)],
        ),
        child: const Icon(Icons.shopping_cart, color: _primary, size: 30),
      ),
      const SizedBox(height: 14),
      const Text('Shopping Cart',
        style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w800, letterSpacing: -0.5)),
      const SizedBox(height: 6),
      Text('Review and manage your items',
        style: TextStyle(color: Colors.white.withOpacity(0.7), fontSize: 13)),
    ]),
  );

  Widget _controls() => Container(
    color: Colors.white,
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
    child: Row(children: [
      GestureDetector(
        onTap: () => _toggleAll(!_allSelected),
        child: Row(children: [
          AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            width: 22, height: 22,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(6),
              color: _allSelected ? _gold : Colors.white,
              border: Border.all(color: _allSelected ? _gold : Colors.grey.shade300, width: 2),
            ),
            child: _allSelected ? const Icon(Icons.check, color: Colors.white, size: 14) : null,
          ),
          const SizedBox(width: 10),
          Text('Select All Items (${_items.length})',
            style: const TextStyle(color: _accent, fontWeight: FontWeight.w600, fontSize: 13)),
        ]),
      ),
      const Spacer(),
      GestureDetector(
        onTap: _deleteSelected,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: Colors.red.shade200),
            color: Colors.red.shade50,
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.delete_outline, color: Colors.red.shade400, size: 16),
            const SizedBox(width: 4),
            Text('Delete Selected', style: TextStyle(color: Colors.red.shade400, fontSize: 12, fontWeight: FontWeight.w600)),
          ]),
        ),
      ),
    ]),
  );

  Widget _cartItemTile(Map<String, dynamic> item) {
    final selected = item['_selected'] == true;
    final name       = item['name'] as String? ?? '';
    final price      = double.tryParse(item['price']?.toString() ?? '0') ?? 0;
    final color      = item['variations'] as String?;
    final size       = item['size'] as String?;
    final qty        = item['quantity'] as int? ?? 1;
    final imageRaw   = item['image'] as String?;
    final pid        = item['product_id'];
    final sellerEmail = item['seller_email'] as String? ?? '';
    final sellerName  = item['seller_name'] as String? ?? sellerEmail;
    final productId  = pid is int ? pid : int.tryParse('$pid');
    final imageUrl   = imageRaw != null && imageRaw.trim().isNotEmpty
        ? buildImageUrl(imageRaw.split(',').first.trim())
        : null;

    return Container(
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.06), blurRadius: 12, offset: const Offset(0, 3))],
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          GestureDetector(
            onTap: () => setState(() => item['_selected'] = !selected),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              width: 22, height: 22,
              margin: const EdgeInsets.only(top: 2),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(6),
                color: selected ? _gold : Colors.white,
                border: Border.all(color: selected ? _gold : Colors.grey.shade300, width: 2),
              ),
              child: selected ? const Icon(Icons.check, color: Colors.white, size: 14) : null,
            ),
          ),
          const SizedBox(width: 12),
          // ── Clickable product image ──────────────────────────────────
          GestureDetector(
            onTap: productId != null
                ? () => Navigator.push(context, MaterialPageRoute(
                    builder: (_) => BuyerViewProductPage(
                      userEmail: widget.userEmail,
                      productId: productId,
                    )))
                : null,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: imageUrl != null
                  ? Image.network(imageUrl, width: 72, height: 72, fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => _imagePlaceholder())
                  : _imagePlaceholder(),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              // ── Seller name (clickable) ────────────────────────────────
              if (sellerEmail.isNotEmpty)
                GestureDetector(
                  onTap: () => Navigator.push(context, MaterialPageRoute(
                      builder: (_) => BuyerViewShopPage(
                        userEmail: widget.userEmail,
                        sellerEmail: sellerEmail,
                      ))),
                  child: Text(
                    sellerName,
                    style: const TextStyle(
                      color: _textLight,
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              if (sellerEmail.isNotEmpty) const SizedBox(height: 2),
              // ── Clickable product name ─────────────────────────────────
              GestureDetector(
                onTap: productId != null
                    ? () => Navigator.push(context, MaterialPageRoute(
                        builder: (_) => BuyerViewProductPage(
                          userEmail: widget.userEmail,
                          productId: productId,
                        )))
                    : null,
                child: Text(name,
                  style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 14),
                  maxLines: 2, overflow: TextOverflow.ellipsis),
              ),
              const SizedBox(height: 4),
              Text('₱${price.toStringAsFixed(2)}',
                style: const TextStyle(color: _gold, fontWeight: FontWeight.w800, fontSize: 15)),
              const SizedBox(height: 6),
              if ((color != null && color.isNotEmpty) || (size != null && size.isNotEmpty))
                Wrap(spacing: 6, children: [
                  if (color != null && color.isNotEmpty)
                    _editableSpecChip(
                      icon: Icons.palette_outlined,
                      label: 'Color: $color',
                      onTap: () => _showEditSpecModal(item, 'color'),
                    ),
                  if (size != null && size.isNotEmpty)
                    _editableSpecChip(
                      icon: Icons.straighten_outlined,
                      label: 'Size: $size',
                      onTap: () => _showEditSpecModal(item, 'size'),
                    ),
                ]),
              const SizedBox(height: 10),
              _CartQtyRow(
                itemId: item['id'] as int,
                productId: productId,
                color: color ?? '',
                size: size ?? '',
                initialQty: qty,
                onChanged: (newQty) async {
                  await BuyerService.updateCartQuantity(item['id'] as int, newQty);
                  await _loadCart();
                },
              ),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _imagePlaceholder() => Container(
    width: 72, height: 72,
    decoration: const BoxDecoration(
      gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight,
        colors: [Color(0xFFECEFF1), Color(0xFFE9ECEF)]),
    ),
    child: const Center(child: Icon(Icons.image_outlined, color: Color(0xFFADB5BD), size: 30)),
  );

  Widget _specChip(IconData icon, String label) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
    decoration: BoxDecoration(
      color: _bg,
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: _border),
    ),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 11, color: _textLight),
      const SizedBox(width: 4),
      Text(label, style: const TextStyle(color: _textLight, fontSize: 11, fontWeight: FontWeight.w500)),
    ]),
  );

  Widget _editableSpecChip({
    required IconData icon,
    required String label,
    required VoidCallback onTap,
  }) => GestureDetector(
    onTap: onTap,
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        // Web: background rgba(212,175,55,0.08), border 1px solid rgba(212,175,55,0.25)
        color: const Color(0xFFd4af37).withOpacity(0.08),
        borderRadius: BorderRadius.circular(20), // pill — matches web's border-radius: 20px
        border: Border.all(color: const Color(0xFFd4af37).withOpacity(0.25)),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 12, color: _gold),           // web: color: var(--secondary-color)
        const SizedBox(width: 5),
        Text(label, style: const TextStyle(
          color: Color(0xFF333333),                   // web: color: var(--text-color) = #333
          fontSize: 12,
          fontWeight: FontWeight.w500,                // web: font-weight: 500
        )),
        const SizedBox(width: 5),
        Icon(Icons.edit_outlined, size: 10, color: _gold.withOpacity(0.6)), // web: edit-icon opacity 0.6
      ]),
    ),
  );

  // ─── Edit Color / Size Modal ──────────────────────────────────────────────
  void _showEditSpecModal(Map<String, dynamic> item, String type) {
    final pid = item['product_id'];
    final productId = pid is int ? pid : int.tryParse('$pid');
    if (productId == null) return;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => _SpecEditSheet(
        itemId: item['id'] as int,
        productId: productId,
        type: type,
        currentColor: (item['variations'] as String? ?? '').trim(),
        currentSize: (item['size'] as String? ?? '').trim(),
        onSaved: (newColor, newSize) async {
          await BuyerService.updateCartSpec(
            item['id'] as int,
            color: newColor,
            size: newSize,
          );
          await _loadCart();
        },
      ),
    );
  }

  Widget _qtyBtn(IconData icon, VoidCallback onTap) => GestureDetector(
    onTap: onTap,
    child: Container(
      width: 30, height: 30,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: _border),
        color: Colors.white,
      ),
      child: Icon(icon, size: 16, color: _accent),
    ),
  );

  // ─── Empty Cart ───────────────────────────────────────────────────────────
  Widget _emptyCart() => Center(
    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
      Container(
        width: 90, height: 90,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: _border,
          border: Border.all(color: _border, width: 2),
        ),
        child: const Icon(Icons.shopping_cart_outlined, size: 44, color: _textLight),
      ),
      const SizedBox(height: 20),
      const Text('Your cart is empty',
        style: TextStyle(color: _accent, fontSize: 20, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      const Text("Looks like you haven't added any items yet.",
        style: TextStyle(color: _textLight, fontSize: 13), textAlign: TextAlign.center),
      const SizedBox(height: 6),
      // Debug: show email being queried
      Text('(${widget.userEmail.isEmpty ? "no email" : widget.userEmail})',
        style: const TextStyle(color: _textLight, fontSize: 10)),
      const SizedBox(height: 24),
      GestureDetector(
        onTap: () => Navigator.pushAndRemoveUntil(context,
          MaterialPageRoute(builder: (_) => BuyerHomePage(userEmail: widget.userEmail)), (_) => false),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 13),
          decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(14),
            boxShadow: [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 12, offset: const Offset(0, 4))]),
          child: const Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.arrow_back, color: Colors.white, size: 16),
            SizedBox(width: 8),
            Text('Continue Shopping', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 14)),
          ]),
        ),
      ),
    ]),
  );

  // ─── Order Summary ────────────────────────────────────────────────────────
  Widget _orderSummary() => Container(
    margin: const EdgeInsets.fromLTRB(12, 8, 12, 0),
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(18),
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.07), blurRadius: 16, offset: const Offset(0, 4))],
    ),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text('Order Summary',
        style: TextStyle(color: _accent, fontSize: 16, fontWeight: FontWeight.w800, letterSpacing: -0.3)),
      const SizedBox(height: 4),
      Container(width: 40, height: 3, decoration: BoxDecoration(borderRadius: BorderRadius.circular(2), gradient: _goldGrad)),
      const SizedBox(height: 16),
      _summaryRow('Total Items:', '$_totalItems'),
      const Divider(height: 20),
      _summaryRow('Total Amount:', '₱${_totalAmount.toStringAsFixed(2)}', highlight: true),
    ]),
  );

  Widget _summaryRow(String label, String value, {bool highlight = false}) => Row(
    mainAxisAlignment: MainAxisAlignment.spaceBetween,
    children: [
      Text(label, style: const TextStyle(color: _textLight, fontSize: 14)),
      Text(value, style: TextStyle(
        color: highlight ? _accent : _accent,
        fontWeight: highlight ? FontWeight.w800 : FontWeight.w600,
        fontSize: highlight ? 17 : 14,
      )),
    ],
  );

  // ─── Checkout Button ──────────────────────────────────────────────────────
  Widget _checkoutButton() {
    final bottomPad = MediaQuery.of(context).padding.bottom;
    final enabled = _selectedItems.isNotEmpty;
    return Container(
      padding: EdgeInsets.fromLTRB(16, 12, 16, 12 + bottomPad),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: _border)),
      ),
      child: GestureDetector(
        onTap: enabled ? () {
          final checkoutItems = _selectedItems.map((item) => CheckoutItem(
            id:        '${item['id']}',
            name:      item['name'] as String? ?? '',
            price:     double.tryParse(item['price']?.toString() ?? '0') ?? 0,
            quantity:  item['quantity'] as int? ?? 1,
            color:     item['variations'] as String?,
            size:      item['size'] as String?,
            image:     item['image'] as String?,
            productId: item['product_id'] is int
                ? item['product_id'] as int
                : int.tryParse('${item['product_id']}'),
          )).toList();
          Navigator.push(context, MaterialPageRoute(
            builder: (_) => BuyerCheckoutPage(userEmail: widget.userEmail, items: checkoutItems),
          ));
        } : null,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(vertical: 16),
          decoration: BoxDecoration(
            gradient: enabled ? _premiumGrad : null,
            color: enabled ? null : const Color(0xFFCED4DA),
            borderRadius: BorderRadius.circular(14),
            boxShadow: enabled
                ? [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 12, offset: const Offset(0, 4))]
                : [],
          ),
          child: const Center(
            child: Text('Proceed to Checkout',
              style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 15, letterSpacing: 0.3)),
          ),
        ),
      ),
    );
  }

  void _showProfile() {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      builder: (_) => Container(
        padding: const EdgeInsets.fromLTRB(20, 20, 20, 32),
        decoration: const BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
        ),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Container(width: 40, height: 4, decoration: BoxDecoration(color: _border, borderRadius: BorderRadius.circular(2))),
          const SizedBox(height: 20),
          Container(
            width: 64, height: 64,
            decoration: const BoxDecoration(gradient: _premiumGrad, shape: BoxShape.circle),
            child: const Icon(Icons.person, color: Colors.white, size: 32),
          ),
          const SizedBox(height: 12),
          Text(widget.userEmail, style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 15)),
          const SizedBox(height: 20),
          _profileTile(Icons.person_outline, 'My Profile', () => Navigator.pop(context)),
          _profileTile(Icons.shopping_bag_outlined, 'My Orders', () => Navigator.pop(context)),
          _profileTile(Icons.favorite_border, 'Wishlist', () => Navigator.pop(context)),
          const Divider(height: 24),
          _profileTile(Icons.logout, 'Logout', () {
            Navigator.pop(context);
            Navigator.pushAndRemoveUntil(context,
              MaterialPageRoute(builder: (_) => const LoginPage()), (_) => false);
          }, color: Colors.red.shade400),
        ]),
      ),
    );
  }

  Widget _profileTile(IconData icon, String label, VoidCallback onTap, {Color? color}) => ListTile(
    leading: Icon(icon, color: color ?? _accent, size: 20),
    title: Text(label, style: TextStyle(color: color ?? _accent, fontWeight: FontWeight.w600, fontSize: 14)),
    trailing: Icon(Icons.chevron_right, color: color ?? _textLight, size: 18),
    contentPadding: const EdgeInsets.symmetric(horizontal: 4),
    onTap: onTap,
  );
}

// ─── Cart quantity row with stock cap ─────────────────────────────────────────
class _CartQtyRow extends StatefulWidget {
  final int itemId;
  final int? productId;
  final String color;
  final String size;
  final int initialQty;
  final Future<void> Function(int) onChanged;

  const _CartQtyRow({
    required this.itemId,
    required this.productId,
    required this.color,
    required this.size,
    required this.initialQty,
    required this.onChanged,
  });

  @override
  State<_CartQtyRow> createState() => _CartQtyRowState();
}

class _CartQtyRowState extends State<_CartQtyRow> {
  late final TextEditingController _ctrl;
  int _qty = 1;
  int? _maxQty;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _qty = widget.initialQty;
    _ctrl = TextEditingController(text: '$_qty');
    _loadStock();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  Future<void> _loadStock() async {
    if (widget.productId == null) return;
    try {
      final res = await BuyerService.getVariantStock(
        widget.productId!, widget.color, widget.size);
      if (mounted) setState(() => _maxQty = res);
    } catch (_) {}
  }

  Future<void> _save(int qty) async {
    if (_saving) return;
    setState(() { _saving = true; _qty = qty; });
    _ctrl.text = '$qty';
    try { await widget.onChanged(qty); } catch (_) {}
    if (mounted) setState(() => _saving = false);
  }

  void _setQty(int qty) {
    final max = _maxQty;
    final clamped = qty.clamp(1, max != null && max > 0 ? max : 9999);
    if (clamped == _qty) return;
    _save(clamped);
  }

  @override
  Widget build(BuildContext context) {
    const accent = Color(0xFF2c3e50);
    const gold = Color(0xFFd4af37);
    const textLight = Color(0xFF6c757d);
    const border = Color(0xFFE9ECEF);

    final max = _maxQty;
    final atMin = _qty <= 1;
    final atMax = max != null && max > 0 && _qty >= max;
    final noStock = max != null && max <= 0;

    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        // Minus
        GestureDetector(
          onTap: (atMin || _saving) ? null : () => _setQty(_qty - 1),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 150),
            width: 30, height: 30,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: atMin ? border.withOpacity(0.4) : border),
              color: atMin ? const Color(0xFFF5F5F5) : Colors.white,
            ),
            child: Icon(Icons.remove, size: 15,
              color: atMin ? textLight.withOpacity(0.4) : accent),
          ),
        ),
        const SizedBox(width: 4),
        // Typeable input
        SizedBox(
          width: 48,
          child: TextField(
            controller: _ctrl,
            keyboardType: TextInputType.number,
            textAlign: TextAlign.center,
            enabled: !noStock && !_saving,
            style: TextStyle(
              color: noStock ? textLight : accent,
              fontWeight: FontWeight.w700, fontSize: 14),
            decoration: InputDecoration(
              contentPadding: const EdgeInsets.symmetric(vertical: 6),
              isDense: true,
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(8),
                borderSide: BorderSide(color: border)),
              enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8),
                borderSide: BorderSide(color: atMax ? gold.withOpacity(0.6) : border)),
              focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8),
                borderSide: const BorderSide(color: gold, width: 1.5)),
              disabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8),
                borderSide: BorderSide(color: border.withOpacity(0.5))),
              filled: true,
              fillColor: noStock ? const Color(0xFFF5F5F5) : Colors.white,
            ),
            onChanged: (val) {
              final parsed = int.tryParse(val);
              if (parsed == null) return;
              final clamped = parsed.clamp(1, max != null && max > 0 ? max : 9999);
              if (clamped != parsed) {
                _ctrl.text = '$clamped';
                _ctrl.selection = TextSelection.collapsed(offset: _ctrl.text.length);
              }
              if (clamped != _qty) setState(() => _qty = clamped);
            },
            onSubmitted: (val) {
              final parsed = int.tryParse(val) ?? 1;
              _setQty(parsed);
            },
          ),
        ),
        const SizedBox(width: 4),
        // Plus
        GestureDetector(
          onTap: (atMax || noStock || _saving) ? null : () => _setQty(_qty + 1),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 150),
            width: 30, height: 30,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: (atMax || noStock) ? border.withOpacity(0.4) : border),
              color: (atMax || noStock) ? const Color(0xFFF5F5F5) : Colors.white,
            ),
            child: Icon(Icons.add, size: 15,
              color: (atMax || noStock) ? textLight.withOpacity(0.4) : accent),
          ),
        ),
        const SizedBox(width: 8),
        // Stock label
        if (max != null)
          Text(
            noStock ? 'Out of stock' : (atMax ? 'Max' : '/$max'),
            style: TextStyle(
              fontSize: 10,
              color: noStock ? Colors.red : (atMax ? gold : textLight),
              fontWeight: FontWeight.w600,
            ),
          ),
        if (_saving)
          const Padding(
            padding: EdgeInsets.only(left: 6),
            child: SizedBox(width: 12, height: 12,
              child: CircularProgressIndicator(strokeWidth: 1.5, color: gold)),
          ),
      ]),
    ]);
  }
}

// ─── Spec Edit Bottom Sheet ───────────────────────────────────────────────────
class _SpecEditSheet extends StatefulWidget {
  final int itemId;
  final int productId;
  final String type; // 'color' or 'size'
  final String currentColor;
  final String currentSize;
  final Future<void> Function(String? color, String? size) onSaved;

  const _SpecEditSheet({
    required this.itemId,
    required this.productId,
    required this.type,
    required this.currentColor,
    required this.currentSize,
    required this.onSaved,
  });

  @override
  State<_SpecEditSheet> createState() => _SpecEditSheetState();
}

class _SpecEditSheetState extends State<_SpecEditSheet> {
  bool _loading = true;
  bool _saving = false;

  List<String> _colors = [];
  List<String> _sizes = [];
  Map<String, String> _imageColors = {}; // colorName → imageUrl

  late String _selectedColor;
  late String _selectedSize;

  @override
  void initState() {
    super.initState();
    _selectedColor = widget.currentColor;
    _selectedSize = widget.currentSize;
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() => _loading = true);
    try {
      final results = await Future.wait([
        BuyerService.getProductColors(widget.productId),
        BuyerService.getProductSizes(widget.productId, widget.currentColor),
        BuyerService.getProductImageColors(widget.productId),
      ]);
      if (mounted) {
        setState(() {
          _colors = results[0] as List<String>;
          _sizes = results[1] as List<String>;
          _imageColors = results[2] as Map<String, String>;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _reloadSizes(String color) async {
    setState(() => _loading = true);
    try {
      final sizes = await BuyerService.getProductSizes(widget.productId, color);
      if (mounted) {
        setState(() {
          _sizes = sizes;
          // Reset size selection if current size not available for new color
          if (!sizes.contains(_selectedSize)) _selectedSize = sizes.isNotEmpty ? sizes.first : '';
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      final newColor = widget.type == 'color' ? _selectedColor : null;
      final newSize  = widget.type == 'size'  ? _selectedSize  : null;

      // If color changed, also update the cart image to the color-matched image
      if (newColor != null && newColor.isNotEmpty) {
        final imgUrl = _resolveColorImage(newColor);
        await BuyerService.updateCartSpec(
          widget.itemId,
          color: newColor,
          image: imgUrl,
        );
      } else {
        await BuyerService.updateCartSpec(
          widget.itemId,
          size: newSize,
        );
      }

      await widget.onSaved(newColor, newSize);
      if (mounted) Navigator.pop(context);
    } catch (_) {
      if (mounted) {
        setState(() => _saving = false);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Failed to save. Please try again.')),
        );
      }
    }
  }

  String? _resolveColorImage(String color) {
    final key = color.toLowerCase();
    return _imageColors[key] ?? _imageColors[color];
  }

  @override
  Widget build(BuildContext context) {
    final isColor = widget.type == 'color';
    final title = isColor ? 'Change Color' : 'Change Size';
    final bottomPad = MediaQuery.of(context).viewInsets.bottom;

    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        // ── Header — dark gradient matching web ──────────────────────────
        Container(
          padding: const EdgeInsets.fromLTRB(20, 16, 16, 16),
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topLeft, end: Alignment.bottomRight,
              colors: [Color(0xFF2c3e50), Color(0xFF34495e)],
            ),
            borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
          ),
          child: Row(children: [
            Icon(
              isColor ? Icons.palette_outlined : Icons.straighten_outlined,
              color: Colors.white, size: 20,
            ),
            const SizedBox(width: 10),
            Text(title,
              style: const TextStyle(
                color: Colors.white, fontSize: 16,
                fontWeight: FontWeight.w600, letterSpacing: 0.2)),
            const Spacer(),
            GestureDetector(
              onTap: () => Navigator.pop(context),
              child: Container(
                width: 30, height: 30,
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: const Icon(Icons.close, size: 16, color: Colors.white),
              ),
            ),
          ]),
        ),

        // ── Body ─────────────────────────────────────────────────────────
        Flexible(
          child: SingleChildScrollView(
            padding: EdgeInsets.fromLTRB(20, 20, 20, 8 + bottomPad),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(
                isColor ? 'Select Color:' : 'Select Size:',
                style: const TextStyle(
                  color: Color(0xFF2c3e50), fontSize: 14,
                  fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 12),
              if (_loading)
                const Center(
                  child: Padding(
                    padding: EdgeInsets.symmetric(vertical: 32),
                    child: CircularProgressIndicator(color: _gold),
                  ),
                )
              else if (isColor)
                _colorGrid()
              else
                _sizeGrid(),
            ]),
          ),
        ),

        // ── Footer — #f8f9fa bg matching web ─────────────────────────────
        Container(
          padding: EdgeInsets.fromLTRB(20, 14, 20, 14 + bottomPad),
          decoration: const BoxDecoration(
            color: Color(0xFFF8F9FA),
            border: Border(top: BorderSide(color: Color(0xFFE9ECEF))),
          ),
          child: Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            // Cancel — #6c757d
            GestureDetector(
              onTap: () => Navigator.pop(context),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 11),
                decoration: BoxDecoration(
                  color: const Color(0xFF6c757d),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: const Text('Cancel',
                  style: TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 13)),
              ),
            ),
            const SizedBox(width: 12),
            // Save — #2c3e50
            GestureDetector(
              onTap: _saving ? null : _save,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 11),
                decoration: BoxDecoration(
                  color: _saving ? const Color(0xFFCED4DA) : const Color(0xFF2c3e50),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: _saving
                  ? const SizedBox(width: 16, height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Text('Save Changes',
                      style: TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 13)),
              ),
            ),
          ]),
        ),
      ]),
    );
  }

  Widget _colorGrid() {
    if (_colors.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 24),
        child: Text('No color options available.',
          style: TextStyle(color: _textLight, fontSize: 13), textAlign: TextAlign.center),
      );
    }
    return Container(
      // Web: background: #fafafa; border: 1px solid #f0f0f0; border-radius: 8px
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: const Color(0xFFFAFAFA),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFF0F0F0)),
      ),
      constraints: const BoxConstraints(maxHeight: 300),
      child: SingleChildScrollView(
        child: Wrap(
          spacing: 12,
          runSpacing: 12,
          children: _colors.map((color) {
            final isSelected = color == _selectedColor;
            final imgUrl = _resolveColorImage(color);
            return GestureDetector(
              onTap: () {
                setState(() => _selectedColor = color);
                if (widget.type == 'color') _reloadSizes(color);
              },
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                width: 72, height: 80,
                decoration: BoxDecoration(
                  // Web: background: #f8f9fa; border: 2px solid #e5e5e5 (unselected)
                  //      border: 2px solid #d4af37 + gold shadow (selected)
                  color: const Color(0xFFF8F9FA),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(
                    color: isSelected ? _gold : const Color(0xFFE5E5E5),
                    width: 2,
                  ),
                  boxShadow: isSelected ? [
                    BoxShadow(color: _gold.withOpacity(0.4), blurRadius: 15, offset: const Offset(0, 4)),
                    BoxShadow(color: _gold.withOpacity(0.2), blurRadius: 0, spreadRadius: 2),
                  ] : [
                    BoxShadow(color: Colors.black.withOpacity(0.1), blurRadius: 8, offset: const Offset(0, 2)),
                  ],
                ),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: Stack(children: [
                    // Image or color swatch
                    if (imgUrl != null)
                      Image.network(
                        imgUrl,
                        width: 72, height: 80,
                        fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => _colorSwatch(color),
                      )
                    else
                      _colorSwatch(color),
                    // Color name overlay — always visible on selected, hover-like on others
                    // Web: gradient overlay at bottom, opacity 0 → 1 on hover/selected
                    Positioned(
                      bottom: 0, left: 0, right: 0,
                      child: AnimatedOpacity(
                        duration: const Duration(milliseconds: 200),
                        opacity: isSelected ? 1.0 : 0.85,
                        child: Container(
                          padding: const EdgeInsets.fromLTRB(4, 6, 4, 3),
                          decoration: const BoxDecoration(
                            gradient: LinearGradient(
                              begin: Alignment.topCenter, end: Alignment.bottomCenter,
                              colors: [Colors.transparent, Color(0xCC000000)],
                            ),
                            borderRadius: BorderRadius.vertical(bottom: Radius.circular(4)),
                          ),
                          child: Text(color,
                            textAlign: TextAlign.center,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              color: Colors.white, fontSize: 9,
                              fontWeight: FontWeight.w600,
                              letterSpacing: 0.2,
                            )),
                        ),
                      ),
                    ),
                    // Selected checkmark — web: gold circle top-right with ✓
                    if (isSelected)
                      Positioned(
                        top: 4, right: 4,
                        child: Container(
                          width: 18, height: 18,
                          decoration: BoxDecoration(
                            color: _gold,
                            shape: BoxShape.circle,
                            boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.2), blurRadius: 4)],
                          ),
                          child: const Icon(Icons.check, color: Colors.white, size: 11),
                        ),
                      ),
                  ]),
                ),
              ),
            );
          }).toList(),
        ),
      ),
    );
  }

  Widget _colorSwatch(String color) {
    final colorMap = <String, Color>{
      'red': const Color(0xFFdc3545), 'blue': const Color(0xFF0d6efd),
      'green': const Color(0xFF198754), 'black': const Color(0xFF212529),
      'white': const Color(0xFFF8F9FA), 'gray': const Color(0xFF6c757d),
      'grey': const Color(0xFF6c757d), 'yellow': const Color(0xFFffc107),
      'orange': const Color(0xFFfd7e14), 'purple': const Color(0xFF6f42c1),
      'pink': const Color(0xFFd63384), 'brown': const Color(0xFF8b4513),
      'navy': const Color(0xFF000080), 'maroon': const Color(0xFF800000),
      'beige': const Color(0xFFf5f5dc), 'coral': const Color(0xFFff7f50),
      'gold': const Color(0xFFffd700), 'silver': const Color(0xFFc0c0c0),
      'lime': const Color(0xFF32cd32), 'teal': const Color(0xFF008080),
    };
    final bg = colorMap[color.toLowerCase()] ?? const Color(0xFF6c757d);
    return Container(width: 72, height: 80, color: bg);
  }

  Widget _sizeGrid() {
    if (_sizes.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 24),
        child: Text('No size options available.',
          style: TextStyle(color: _textLight, fontSize: 13), textAlign: TextAlign.center),
      );
    }
    return ConstrainedBox(
      constraints: const BoxConstraints(maxHeight: 200),
      child: SingleChildScrollView(
        child: Wrap(
          spacing: 10,
          runSpacing: 10,
          children: _sizes.map((size) {
            final isSelected = size == _selectedSize;
            return GestureDetector(
              onTap: () => setState(() => _selectedSize = size),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                decoration: BoxDecoration(
                  // Web: white bg unselected → #d4af37 bg selected
                  //      #E9ECEF border unselected → #d4af37 border selected
                  color: isSelected ? _gold : Colors.white,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: isSelected ? _gold : const Color(0xFFE9ECEF),
                    width: 2,
                  ),
                ),
                child: Text(size,
                  style: TextStyle(
                    // Web: white text selected, #333 text unselected
                    color: isSelected ? Colors.white : const Color(0xFF333333),
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  )),
              ),
            );
          }).toList(),
        ),
      ),
    );
  }
}
