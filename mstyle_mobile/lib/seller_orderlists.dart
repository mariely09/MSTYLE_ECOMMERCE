import 'package:flutter/material.dart';
import 'dart:async';
import 'seller_dashboard.dart';
import 'seller_products.dart';
import 'seller_analytics.dart';
import 'seller_notifications.dart';
import 'profile.dart';
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

// ─── Order model ──────────────────────────────────────────────────────────────
class SellerOrder {
  final int id;
  final String customerName;
  final String customerEmail;
  final String address;
  final String productName;
  final String? variation;
  final String? size;
  final int quantity;
  final double originalPrice;
  final double totalPrice;
  final String? promotionType;
  final String date;
  final String status;
  final String? riderName;

  const SellerOrder({
    required this.id,
    required this.customerName,
    required this.customerEmail,
    required this.address,
    required this.productName,
    this.variation,
    this.size,
    required this.quantity,
    required this.originalPrice,
    required this.totalPrice,
    this.promotionType,
    required this.date,
    required this.status,
    this.riderName,
  });
}

// ─── Mock data ────────────────────────────────────────────────────────────────
final _mockOrders = [
  const SellerOrder(id: 1001, customerName: 'Juan Dela Cruz',  customerEmail: 'juan@email.com',  address: '123 Rizal St, Brgy. San Jose, Makati City', productName: 'Classic Black Suit',   variation: 'Black', size: 'L',  quantity: 1, originalPrice: 5999.0, totalPrice: 5099.0, promotionType: 'percentage', date: 'Mar 25, 2026', status: 'Pending'),
  const SellerOrder(id: 1002, customerName: 'Maria Santos',    customerEmail: 'maria@email.com', address: '456 Mabini Ave, Brgy. Poblacion, Quezon City', productName: 'Oxford Button-Down', variation: 'White', size: 'M',  quantity: 2, originalPrice: 1998.0, totalPrice: 1998.0, date: 'Mar 24, 2026', status: 'Confirmed'),
  const SellerOrder(id: 1003, customerName: 'Pedro Reyes',     customerEmail: 'pedro@email.com', address: '789 Luna Blvd, Brgy. Bagong Ilog, Pasig City', productName: 'Leather Biker Jacket', variation: 'Brown', size: 'XL', quantity: 1, originalPrice: 4999.0, totalPrice: 4999.0, date: 'Mar 23, 2026', status: 'Shipped', riderName: 'Carlos Rider'),
  const SellerOrder(id: 1004, customerName: 'Ana Gonzales',    customerEmail: 'ana@email.com',   address: '321 Bonifacio St, Brgy. Sto. Tomas, Taguig City', productName: 'Performance Tee',    variation: 'Gray',  size: 'S',  quantity: 3, originalPrice: 2697.0, totalPrice: 2427.0, promotionType: 'fixed', date: 'Mar 22, 2026', status: 'Delivered'),
  const SellerOrder(id: 1005, customerName: 'Jose Ramos',      customerEmail: 'jose@email.com',  address: '654 Aguinaldo Rd, Brgy. Bagumbayan, Mandaluyong', productName: 'Oxford Derby Shoes',  variation: 'Black', size: '42', quantity: 1, originalPrice: 3499.0, totalPrice: 3499.0, date: 'Mar 20, 2026', status: 'Completed'),
  const SellerOrder(id: 1006, customerName: 'Rosa Villanueva', customerEmail: 'rosa@email.com',  address: '987 Quezon Ave, Brgy. Pinyahan, Quezon City', productName: 'Premium Face Wash',   quantity: 2, originalPrice: 1198.0, totalPrice: 1198.0, promotionType: 'free_shipping', date: 'Mar 19, 2026', status: 'Rejected'),
];

class SellerOrderListsPage extends StatefulWidget {
  final String sellerEmail;
  const SellerOrderListsPage({super.key, required this.sellerEmail});
  @override
  State<SellerOrderListsPage> createState() => _SellerOrderListsPageState();
}

class _SellerOrderListsPageState extends State<SellerOrderListsPage> {
  final int _navIndex = 2;
  String _filterStatus = '';
  String _sortBy = 'date-desc';
  String _search = '';
  String _businessName = '';
  List<SellerOrder> _orders = [];
  bool _loadingOrders = true;
  final _searchCtrl = TextEditingController();
  StreamSubscription<List<Map<String, dynamic>>>? _ordersSub;

  @override
  void initState() {
    super.initState();
    _fetchBusinessName();
    _fetchOrders();
    _subscribeToOrders();
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    _ordersSub?.cancel();
    super.dispose();
  }

  // ── Supabase Realtime subscription ────────────────────────────────────────
  void _subscribeToOrders() {
    _ordersSub = supabase
        .from('orders')
        .stream(primaryKey: ['id'])
        .eq('seller_email', widget.sellerEmail)
        .order('date', ascending: false)
        .listen((rows) {
          if (!mounted) return;
          setState(() {
            _orders = rows.map((o) => SellerOrder(
              id:            (o['id'] as num).toInt(),
              customerName:  o['email'] as String? ?? '',
              customerEmail: o['email'] as String? ?? '',
              address:       o['address'] as String? ?? '',
              productName:   o['name'] as String? ?? '',
              variation:     o['variations'] as String?,
              size:          o['size'] as String?,
              quantity:      (o['quantity'] as num?)?.toInt() ?? 1,
              originalPrice: (o['total_price'] as num?)?.toDouble() ?? 0,
              totalPrice:    (o['total_price'] as num?)?.toDouble() ?? 0,
              date:          o['date'] != null
                  ? DateTime.parse(o['date']).toLocal().toString().split(' ')[0]
                  : '',
              status:        o['status'] as String? ?? 'Pending',
            )).toList();
            _loadingOrders = false;
          });
        }, onError: (e) {
          debugPrint('seller orders stream error: $e');
        });
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

  Future<void> _fetchOrders() async {
    try {
      final data = await supabase
          .from('orders')
          .select()
          .eq('seller_email', widget.sellerEmail)
          .order('date', ascending: false);
      if (mounted) {
        setState(() {
          _orders = (data as List).map((o) => SellerOrder(
            id:            (o['id'] as num).toInt(),
            customerName:  o['email'] as String? ?? '',
            customerEmail: o['email'] as String? ?? '',
            address:       o['address'] as String? ?? '',
            productName:   o['name'] as String? ?? '',
            variation:     o['variations'] as String?,
            size:          o['size'] as String?,
            quantity:      (o['quantity'] as num?)?.toInt() ?? 1,
            originalPrice: (o['total_price'] as num?)?.toDouble() ?? 0,
            totalPrice:    (o['total_price'] as num?)?.toDouble() ?? 0,
            date:          o['date'] != null
                ? DateTime.parse(o['date']).toLocal().toString().split(' ')[0]
                : '',
            status:        o['status'] as String? ?? 'Pending',
          )).toList();
          _loadingOrders = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loadingOrders = false);
    }
  }

  List<SellerOrder> get _filtered {
    var list = _orders.where((o) {
      if (_search.isNotEmpty &&
          !o.customerName.toLowerCase().contains(_search.toLowerCase()) &&
          !o.productName.toLowerCase().contains(_search.toLowerCase())) return false;
      if (_filterStatus.isNotEmpty && o.status.toLowerCase() != _filterStatus.toLowerCase()) return false;
      return true;
    }).toList();

    switch (_sortBy) {
      case 'date-asc':      list.sort((a, b) => a.date.compareTo(b.date)); break;
      case 'customer-asc':  list.sort((a, b) => a.customerName.compareTo(b.customerName)); break;
      case 'customer-desc': list.sort((a, b) => b.customerName.compareTo(a.customerName)); break;
      case 'price-desc':    list.sort((a, b) => b.totalPrice.compareTo(a.totalPrice)); break;
      case 'price-asc':     list.sort((a, b) => a.totalPrice.compareTo(b.totalPrice)); break;
      default: list.sort((a, b) => b.date.compareTo(a.date));
    }
    return list;
  }

  // _fetchOrders is kept as a fallback for the initial load before the stream fires

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      bottomNavigationBar: _bottomNav(),
      body: _loadingOrders
        ? const Center(child: CircularProgressIndicator(color: _gold))
        : CustomScrollView(
          slivers: [
            _appBar(),
            SliverToBoxAdapter(child: _pageHeader()),
            SliverToBoxAdapter(child: _filterSection()),
            if (_filtered.isEmpty)
              SliverFillRemaining(child: _emptyState())
            else
              SliverList(
                delegate: SliverChildBuilderDelegate(
                  (_, i) => _orderCard(_filtered[i], i + 1),
                  childCount: _filtered.length,
                ),
              ),
            const SliverToBoxAdapter(child: SizedBox(height: 24)),
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
      IconButton(icon: const Icon(Icons.notifications_outlined, color: Colors.white, size: 22),
        onPressed: () => Navigator.push(context,
          MaterialPageRoute(builder: (_) => SellerNotificationsPage(sellerEmail: widget.sellerEmail)))),
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
        child: const Icon(Icons.list_alt_outlined, color: _primary, size: 26),
      ),
      const SizedBox(height: 12),
      const Text('Order List', style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w800)),
      const SizedBox(height: 4),
      Text('Manage and track all customer orders',
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
        const Text('Filter & Search Orders', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
        const Spacer(),
        if (_filterStatus.isNotEmpty || _search.isNotEmpty)
          GestureDetector(
            onTap: () => setState(() { _filterStatus = ''; _search = ''; _searchCtrl.clear(); }),
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
      TextField(
        controller: _searchCtrl,
        style: const TextStyle(color: _accent, fontSize: 13),
        onChanged: (v) => setState(() => _search = v),
        decoration: InputDecoration(
          hintText: 'Search by customer or product...',
          hintStyle: const TextStyle(color: _textLight, fontSize: 13),
          prefixIcon: const Icon(Icons.search, color: _textLight, size: 18),
          suffixIcon: _search.isNotEmpty
            ? IconButton(icon: const Icon(Icons.close, size: 16, color: _textLight),
                onPressed: () => setState(() { _search = ''; _searchCtrl.clear(); }))
            : null,
          filled: true, fillColor: _bg,
          contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: _border)),
          focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: _gold, width: 2)),
        ),
      ),
      const SizedBox(height: 10),
      Row(children: [
        Expanded(child: _dropdown('Status', _filterStatus, {
          '': 'All Status', 'pending': 'Pending', 'confirmed': 'Confirmed',
          'for pickup': 'For Pickup', 'heading to seller': 'Heading to Seller',
          'shipped': 'Shipped', 'delivered': 'Delivered',
          'completed': 'Completed', 'rejected': 'Rejected',
        }, (v) => setState(() => _filterStatus = v ?? ''))),
        const SizedBox(width: 10),
        Expanded(child: _dropdown('Sort By', _sortBy, {
          'date-desc': 'Newest First', 'date-asc': 'Oldest First',
          'customer-asc': 'Customer A-Z', 'customer-desc': 'Customer Z-A',
          'price-desc': 'Price: High to Low', 'price-asc': 'Price: Low to High',
        }, (v) => setState(() => _sortBy = v ?? 'date-desc'))),
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

  // ─── Order Card ───────────────────────────────────────────────────────────
  Widget _orderCard(SellerOrder order, int seq) => Container(
    margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.06), blurRadius: 12, offset: const Offset(0, 3))],
    ),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      // Header row
      Container(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
        decoration: BoxDecoration(
          color: _bg,
          borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
          border: Border(bottom: BorderSide(color: _border)),
        ),
        child: Row(children: [
          Container(
            width: 28, height: 28,
            decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(8)),
            child: Center(child: Text('$seq', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 11))),
          ),
          const SizedBox(width: 10),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(order.customerName, style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
            Text(order.customerEmail, style: const TextStyle(color: _textLight, fontSize: 11)),
          ])),
          _statusBadge(order.status),
        ]),
      ),
      // Body
      Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          // Product row
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              width: 52, height: 52,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(10),
                gradient: const LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight,
                  colors: [Color(0xFFECEFF1), Color(0xFFE9ECEF)]),
              ),
              child: const Center(child: Icon(Icons.image_outlined, color: Color(0xFFADB5BD), size: 24)),
            ),
            const SizedBox(width: 12),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(order.productName, style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13),
                maxLines: 2, overflow: TextOverflow.ellipsis),
              const SizedBox(height: 4),
              Wrap(spacing: 6, children: [
                if (order.variation != null) _specChip(Icons.palette_outlined, order.variation!),
                if (order.size != null) _specChip(Icons.straighten_outlined, order.size!),
                _specChip(Icons.inventory_2_outlined, 'Qty: ${order.quantity}'),
              ]),
            ])),
          ]),
          const SizedBox(height: 10),
          // Address
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Icon(Icons.location_on_outlined, size: 13, color: _textLight),
            const SizedBox(width: 5),
            Expanded(child: Text(order.address,
              style: const TextStyle(color: _textLight, fontSize: 11), maxLines: 2, overflow: TextOverflow.ellipsis)),
          ]),
          const SizedBox(height: 10),
          // Price row
          Row(children: [
            // Promotion badge
            if (order.promotionType != null) _promoBadge(order.promotionType!),
            const Spacer(),
            Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              if (order.originalPrice != order.totalPrice)
                Text('₱${order.originalPrice.toStringAsFixed(2)}',
                  style: TextStyle(color: _textLight.withOpacity(0.7), fontSize: 11,
                    decoration: TextDecoration.lineThrough)),
              Text('₱${order.totalPrice.toStringAsFixed(2)}',
                style: const TextStyle(color: _accent, fontWeight: FontWeight.w900, fontSize: 15)),
            ]),
          ]),
          const SizedBox(height: 4),
          Row(children: [
            const Icon(Icons.calendar_today_outlined, size: 11, color: _textLight),
            const SizedBox(width: 4),
            Text(order.date, style: const TextStyle(color: _textLight, fontSize: 11)),
          ]),
          const SizedBox(height: 12),
          // Action buttons
          _actionButtons(order),
        ]),
      ),
    ]),
  );

  Widget _specChip(IconData icon, String label) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
    decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(8), border: Border.all(color: _border)),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 10, color: _textLight),
      const SizedBox(width: 3),
      Text(label, style: const TextStyle(color: _textLight, fontSize: 10, fontWeight: FontWeight.w500)),
    ]),
  );

  Widget _promoBadge(String type) {
    String label; Color color; IconData icon;
    switch (type) {
      case 'free_shipping': label = 'Free Shipping'; color = Colors.teal; icon = Icons.local_shipping_outlined; break;
      case 'buy_one_get_one': label = 'BOGO'; color = Colors.purple; icon = Icons.add_circle_outline; break;
      case 'percentage': label = '% OFF'; color = Colors.orange; icon = Icons.percent; break;
      case 'fixed': label = '₱ OFF'; color = Colors.blue; icon = Icons.remove_circle_outline; break;
      default: label = 'Promo'; color = _gold; icon = Icons.local_offer_outlined;
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(color: color.withOpacity(0.1), borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withOpacity(0.3))),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 11, color: color),
        const SizedBox(width: 4),
        Text(label, style: TextStyle(color: color, fontSize: 10, fontWeight: FontWeight.w700)),
      ]),
    );
  }

  Widget _statusBadge(String status) {
    Color color;
    switch (status.toLowerCase()) {
      case 'pending':           color = Colors.orange; break;
      case 'confirmed':         color = Colors.blue; break;
      case 'for pickup':        color = Colors.purple; break;
      case 'heading to seller': color = Colors.indigo; break;
      case 'shipped':           color = Colors.teal; break;
      case 'delivered':         color = Colors.green.shade600; break;
      case 'completed':         color = Colors.green; break;
      case 'rejected':          color = Colors.red; break;
      default:                  color = _textLight;
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(color: color.withOpacity(0.1), borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.3))),
      child: Text(status, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700)),
    );
  }

  Widget _actionButtons(SellerOrder order) {
    return Wrap(spacing: 8, runSpacing: 8, children: [
      // Status-specific actions
      if (order.status == 'Pending') ...[
        _actionBtn('Confirm', Icons.check_circle_outline, Colors.green,
          () => _updateStatus(order, 'Confirmed')),
        _actionBtn('Reject', Icons.cancel_outlined, Colors.red,
          () => _updateStatus(order, 'Rejected')),
      ],
      if (order.status == 'Confirmed')
        _infoChip(Icons.access_time, 'Waiting for Rider', Colors.blue),
      if (order.status == 'For Pickup')
        _infoChip(Icons.person_pin_circle_outlined, 'Rider Assigned', Colors.purple),
      if (order.status == 'Heading to Seller')
        _infoChip(Icons.directions_bike_outlined, 'Rider on the Way', Colors.indigo),
      if (order.status == 'Shipped')
        _infoChip(Icons.local_shipping_outlined, 'Out for Delivery', Colors.teal),
      if (order.status == 'Delivered')
        _infoChip(Icons.check_circle_outline, 'Awaiting Buyer Confirmation', Colors.green.shade600),
      if (order.status == 'Completed')
        _infoChip(Icons.check_circle, 'Order Complete', Colors.green),
      if (order.status == 'Rejected')
        _infoChip(Icons.cancel, 'Order Rejected', Colors.red),
      // Always visible
      _actionBtn('View Details', Icons.visibility_outlined, _accent,
        () => _showOrderDetails(order)),
    ]);
  }

  Widget _actionBtn(String label, IconData icon, Color color, VoidCallback onTap) => GestureDetector(
    onTap: onTap,
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: color.withOpacity(0.08), borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 13, color: color),
        const SizedBox(width: 5),
        Text(label, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600)),
      ]),
    ),
  );

  Widget _infoChip(IconData icon, String label, Color color) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
    decoration: BoxDecoration(color: color.withOpacity(0.06), borderRadius: BorderRadius.circular(10),
      border: Border.all(color: color.withOpacity(0.2))),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 13, color: color),
      const SizedBox(width: 5),
      Text(label, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600)),
    ]),
  );

  void _updateStatus(SellerOrder order, String newStatus) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(children: [
          Icon(newStatus == 'Confirmed' ? Icons.check_circle_outline : Icons.cancel_outlined,
            color: newStatus == 'Confirmed' ? Colors.green : Colors.red),
          const SizedBox(width: 8),
          Text('$newStatus Order', style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 16)),
        ]),
        content: Text('Are you sure you want to $newStatus order #${order.id} for ${order.customerName}?',
          style: const TextStyle(color: _textLight, fontSize: 13)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          ElevatedButton(
            onPressed: () async {
              Navigator.pop(context);
              try {
                await supabase.from('orders').update({'status': newStatus}).eq('id', order.id);
                _fetchOrders();
                if (!mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                  content: Text('Order #${order.id} $newStatus successfully!'),
                  backgroundColor: newStatus == 'Confirmed' ? Colors.green : Colors.red,
                  behavior: SnackBarBehavior.floating,
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
            style: ElevatedButton.styleFrom(
              backgroundColor: newStatus == 'Confirmed' ? Colors.green : Colors.red,
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
            child: Text(newStatus),
          ),
        ],
      ),
    );
  }

  void _showOrderDetails(SellerOrder order) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => DraggableScrollableSheet(
        initialChildSize: 0.85,
        maxChildSize: 0.95,
        minChildSize: 0.5,
        builder: (_, ctrl) => Container(
          decoration: const BoxDecoration(color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
          child: Column(children: [
            // Handle
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Center(child: Container(width: 40, height: 4,
                decoration: BoxDecoration(color: _border, borderRadius: BorderRadius.circular(2)))),
            ),
            // Header
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
              child: Row(children: [
                const Icon(Icons.receipt_long_outlined, color: _gold, size: 20),
                const SizedBox(width: 8),
                const Text('Order Details', style: TextStyle(color: _accent, fontSize: 16, fontWeight: FontWeight.w800)),
                const Spacer(),
                GestureDetector(onTap: () => Navigator.pop(context),
                  child: const Icon(Icons.close, color: _textLight, size: 20)),
              ]),
            ),
            const Divider(height: 20),
            // Content
            Expanded(child: ListView(controller: ctrl, padding: const EdgeInsets.fromLTRB(20, 0, 20, 20), children: [
              _detailSection('Customer Information', Icons.person_outline, [
                _detailRow('Name', order.customerName),
                _detailRow('Email', order.customerEmail),
                _detailRow('Address', order.address),
              ]),
              const SizedBox(height: 14),
              _detailSection('Order Information', Icons.assignment_outlined, [
                _detailRow('Order ID', '#${order.id}'),
                _detailRow('Date', order.date),
                _detailRow('Status', order.status, statusColor: _statusColor(order.status)),
                _detailRow('Quantity', '${order.quantity}'),
              ]),
              const SizedBox(height: 14),
              _detailSection('Product Information', Icons.inventory_2_outlined, [
                _detailRow('Product', order.productName),
                if (order.variation != null) _detailRow('Color/Variation', order.variation!),
                if (order.size != null) _detailRow('Size', order.size!),
              ]),
              const SizedBox(height: 14),
              _detailSection('Pricing Information', Icons.currency_exchange, [
                _detailRow('Original Price', '₱${order.originalPrice.toStringAsFixed(2)}'),
                _detailRow('Promotion', order.promotionType ?? 'No Promotion'),
                _detailRow('Total Price', '₱${order.totalPrice.toStringAsFixed(2)}', highlight: true),
              ]),
              const SizedBox(height: 20),
              // Footer actions
              Wrap(spacing: 10, runSpacing: 10, children: [
                _actionBtn('Contact Buyer', Icons.chat_bubble_outline, _accent, () {}),
                if (order.riderName != null)
                  _actionBtn('Contact Rider', Icons.directions_bike_outlined, Colors.teal, () {}),
                _actionBtn('Report Issue', Icons.flag_outlined, Colors.orange, () {}),
              ]),
            ])),
          ]),
        ),
      ),
    );
  }

  Widget _detailSection(String title, IconData icon, List<Widget> rows) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(12), border: Border.all(color: _border)),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Icon(icon, color: _gold, size: 15),
        const SizedBox(width: 6),
        Text(title, style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
      ]),
      const SizedBox(height: 10),
      ...rows,
    ]),
  );

  Widget _detailRow(String label, String value, {Color? statusColor, bool highlight = false}) => Padding(
    padding: const EdgeInsets.only(bottom: 6),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SizedBox(width: 110, child: Text(label, style: const TextStyle(color: _textLight, fontSize: 12))),
      Expanded(child: Text(value, style: TextStyle(
        color: statusColor ?? (highlight ? _accent : _accent),
        fontWeight: highlight ? FontWeight.w900 : FontWeight.w600,
        fontSize: highlight ? 14 : 12,
      ))),
    ]),
  );

  Color _statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'pending': return Colors.orange;
      case 'confirmed': return Colors.blue;
      case 'shipped': return Colors.teal;
      case 'delivered': return Colors.green.shade600;
      case 'completed': return Colors.green;
      case 'rejected': return Colors.red;
      default: return _textLight;
    }
  }

  // ─── Empty State ──────────────────────────────────────────────────────────
  Widget _emptyState() => Center(
    child: SingleChildScrollView(
      padding: const EdgeInsets.symmetric(vertical: 24),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        const Icon(Icons.inbox_outlined, size: 72, color: _border),
        const SizedBox(height: 16),
        const Text('No Orders Yet', style: TextStyle(color: _accent, fontSize: 18, fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        const Text("Orders will appear here once customers start purchasing.",
          style: TextStyle(color: _textLight, fontSize: 13), textAlign: TextAlign.center),
      ]),
    ),
  );

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
          if (index == 1) Navigator.pushReplacement(context,
            MaterialPageRoute(builder: (_) => SellerProductsPage(sellerEmail: widget.sellerEmail)));
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
