import 'package:flutter/material.dart';
import 'dart:async';
import 'buyer_homepage.dart';
import 'buyer_service.dart';
import 'product_image_carousel.dart' show buildImageUrl;
import 'supabase_client.dart' show supabase;
import 'buyer_vieworder_details.dart';
import 'buyer_reviews.dart' show showReviewBottomSheet;

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
enum OrderStatus { all, pending, shipped, delivered, completed, cancelled }

class Order {
  final String id;
  final String name;
  final double totalPrice;
  final String date;
  final String status;
  final String? color;
  final String? size;
  final int quantity;

  const Order({
    required this.id,
    required this.name,
    required this.totalPrice,
    required this.date,
    required this.status,
    this.color,
    this.size,
    required this.quantity,
  });
}

// ─── Mock data ────────────────────────────────────────────────────────────────
final _mockOrders = [
  const Order(id: '1001', name: 'Oxford Button-Down', totalPrice: 1099.0, date: 'March 20, 2026', status: 'Pending',   color: 'White', size: 'M',  quantity: 1),
  const Order(id: '1002', name: 'Slim Chino Pants',   totalPrice: 2748.0, date: 'March 18, 2026', status: 'Shipped',   color: 'Navy',  size: '32', quantity: 2),
  const Order(id: '1003', name: 'Sports Hoodie',      totalPrice: 1999.0, date: 'March 10, 2026', status: 'Delivered', color: 'Black', size: 'L',  quantity: 1),
  const Order(id: '1004', name: 'Leather Biker Jacket', totalPrice: 5249.0, date: 'March 5, 2026', status: 'Completed', color: 'Brown', size: 'XL', quantity: 1),
  const Order(id: '1005', name: 'Running Shorts',     totalPrice: 1049.0, date: 'Feb 28, 2026',   status: 'Cancelled', color: 'Gray',  size: 'M',  quantity: 1),
];

class BuyerOrdersPage extends StatefulWidget {
  final String userEmail;
  const BuyerOrdersPage({super.key, required this.userEmail});
  @override
  State<BuyerOrdersPage> createState() => _BuyerOrdersPageState();
}

class _BuyerOrdersPageState extends State<BuyerOrdersPage> {
  OrderStatus _filter = OrderStatus.all;
  bool _loading = true;
  List<Map<String, dynamic>> _orders = [];
  StreamSubscription<List<Map<String, dynamic>>>? _ordersSub;
  // Tracks which order IDs already have a review submitted
  final Set<dynamic> _reviewedOrderIds = {};

  @override
  void initState() {
    super.initState();
    _loadOrders();
    _subscribeToOrders();
  }

  @override
  void dispose() {
    _ordersSub?.cancel();
    super.dispose();
  }

  // ── Supabase Realtime subscription ────────────────────────────────────────
  void _subscribeToOrders() {
    _ordersSub = supabase
        .from('orders')
        .stream(primaryKey: ['id'])
        .eq('email', widget.userEmail)
        .order('date', ascending: false)
        .listen((rows) {
          if (!mounted) return;
          // Merge incoming status updates into existing _orders list
          // (preserves enriched image/price data already loaded)
          final updated = List<Map<String, dynamic>>.from(rows);
          setState(() {
            // Update status of existing orders in-place; add new ones
            for (final incoming in updated) {
              final idx = _orders.indexWhere((o) => o['id'] == incoming['id']);
              if (idx != -1) {
                // Only update mutable fields from realtime — keep enriched data
                _orders[idx] = {..._orders[idx], ...incoming};
              } else {
                _orders.insert(0, incoming);
              }
            }
            // Remove orders that no longer exist
            final incomingIds = updated.map((o) => o['id']).toSet();
            _orders.removeWhere((o) => !incomingIds.contains(o['id']));
          });
        }, onError: (e) {
          debugPrint('buyer orders stream error: $e');
        });
  }

  Future<void> _loadOrders() async {
    setState(() => _loading = true);
    try {
      final data = await BuyerService.getOrders(widget.userEmail);

      // Enrich each order with a color-specific image from the product's image_colors
      for (final order in data) {
        final pid = order['product_id'];
        final selectedColor = (order['variations'] as String? ?? '').trim();
        final storedImage = (order['image'] as String? ?? '').trim();

        // If image is already a full URL, keep it
        if (storedImage.startsWith('http://') || storedImage.startsWith('https://')) {
          continue;
        }

        // Try to get color-specific image from product
        if (pid != null && selectedColor.isNotEmpty) {
          try {
            final prodRes = await supabase
                .from('products')
                .select('image, image_colors')
                .eq('id', pid)
                .limit(1)
                .maybeSingle();
            if (prodRes != null) {
              final colorMap = BuyerService.parseColorImages(
                prodRes['image_colors'] as String?,
                prodRes['image'] as String?,
              );
              final colorImg = colorMap[selectedColor.toLowerCase()];
              if (colorImg != null && colorImg.isNotEmpty) {
                order['image'] = colorImg;
              } else if (storedImage.isEmpty) {
                // Fallback to first product image
                final allImages = (prodRes['image'] as String? ?? '');
                final first = allImages.split(',').map((e) => e.trim()).firstWhere(
                  (e) => e.isNotEmpty, orElse: () => '');
                if (first.isNotEmpty) order['image'] = first;
              }
            }
          } catch (_) {}
        }
      }

      if (mounted) setState(() { _orders = data; _loading = false; });

      // Fetch which completed orders already have a review
      _loadReviewedOrders();
    } catch (e) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadReviewedOrders() async {
    try {
      // Check all completed orders (case-insensitive)
      final completedIds = _orders
          .where((o) => (o['status'] as String? ?? '').toLowerCase() == 'completed')
          .map((o) => o['id'])
          .where((id) => id != null)
          .toList();
      if (completedIds.isEmpty) return;

      final res = await supabase
          .from('reviews')
          .select('order_id')
          .eq('customer_email', widget.userEmail)
          .inFilter('order_id', completedIds);

      final ids = (res as List).map((r) => r['order_id']).toSet();
      if (mounted) setState(() => _reviewedOrderIds.addAll(ids));
    } catch (e) {
      debugPrint('_loadReviewedOrders error: $e');
    }
  }

  List<Map<String, dynamic>> get _filtered {
    if (_filter == OrderStatus.all) return _orders;
    if (_filter == OrderStatus.shipped) {
      // "Shipped" covers all in-transit statuses
      const transitStatuses = [
        'shipped', 'heading to seller', 'for pickup',
        'in transit', 'out for delivery', 'waiting for pickup',
      ];
      return _orders.where((o) =>
        transitStatuses.contains((o['status'] as String? ?? '').toLowerCase())
      ).toList();
    }
    final statusName = _filter.name.toLowerCase();
    return _orders.where((o) =>
      (o['status'] as String? ?? '').toLowerCase() == statusName
    ).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      body: _loading
        ? const Center(child: CircularProgressIndicator(color: _gold))
        : CustomScrollView(
            slivers: [
              SliverAppBar(
                pinned: true,
                backgroundColor: _primary,
                elevation: 6,
                titleSpacing: 16,
                leading: IconButton(
                  icon: const Icon(Icons.arrow_back, color: Colors.white),
                  onPressed: () => Navigator.pop(context),
                ),
                title: const Text('My Orders',
                  style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w700)),
              ),
              SliverToBoxAdapter(child: _filterTabs()),
              if (_filtered.isEmpty)
                SliverFillRemaining(child: _emptyState())
              else
                SliverList(
                  delegate: SliverChildBuilderDelegate(
                    (_, i) => _orderCard(_filtered[i]),
                    childCount: _filtered.length,
                  ),
                ),
              const SliverToBoxAdapter(child: SizedBox(height: 24)),
            ],
          ),
    );
  }

  // ─── Filter Tabs ──────────────────────────────────────────────────────────
  Widget _filterTabs() => Container(
    color: Colors.white,
    padding: const EdgeInsets.symmetric(vertical: 12),
    child: SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Row(
        children: OrderStatus.values.map((s) {
          final active = _filter == s;
          return GestureDetector(
            onTap: () => setState(() => _filter = s),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              margin: const EdgeInsets.only(right: 8),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              decoration: BoxDecoration(
                gradient: active ? _goldGrad : null,
                color: active ? null : _bg,
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: active ? _gold : _border),
              ),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(_statusIcon(s), size: 13, color: active ? _primary : _textLight),
                const SizedBox(width: 5),
                Text(_statusLabel(s), style: TextStyle(
                  color: active ? _primary : _textLight,
                  fontSize: 12, fontWeight: active ? FontWeight.w700 : FontWeight.w500,
                )),
              ]),
            ),
          );
        }).toList(),
      ),
    ),
  );

  IconData _statusIcon(OrderStatus s) {
    switch (s) {
      case OrderStatus.all:       return Icons.grid_view_rounded;
      case OrderStatus.pending:   return Icons.hourglass_empty;
      case OrderStatus.shipped:   return Icons.local_shipping_outlined;
      case OrderStatus.delivered: return Icons.check_circle_outline;
      case OrderStatus.completed: return Icons.check_circle;
      case OrderStatus.cancelled: return Icons.cancel_outlined;
    }
  }

  String _statusLabel(OrderStatus s) {
    switch (s) {
      case OrderStatus.all:       return 'All Orders';
      case OrderStatus.pending:   return 'Pending';
      case OrderStatus.shipped:   return 'Shipped';
      case OrderStatus.delivered: return 'Delivered';
      case OrderStatus.completed: return 'Completed';
      case OrderStatus.cancelled: return 'Cancelled';
    }
  }

  // ─── Order Card ───────────────────────────────────────────────────────────
  Widget _orderCard(Map<String, dynamic> order) {
    final status      = order['status'] as String? ?? 'Pending';
    final statusColor = _statusColor(status);
    final name        = order['name'] as String? ?? 'Order';
    final totalPrice  = double.tryParse(order['total_price']?.toString() ?? '0') ?? 0;
    final date        = order['date'] as String? ?? '';
    final color       = order['variations'] as String?;
    final size        = order['size'] as String?;
    final quantity    = order['quantity'] as int? ?? 1;
    final orderId     = order['id'];
    final imageRaw    = order['image'] as String?;
    final imageUrl    = buildImageUrl(imageRaw?.split(',').first.trim());

    return GestureDetector(
      onTap: () => Navigator.push(context,
        MaterialPageRoute(builder: (_) => BuyerViewOrderDetails(order: order))),
      child: Container(
        margin: const EdgeInsets.fromLTRB(14, 0, 14, 14),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(18),
          boxShadow: [
            BoxShadow(color: Colors.black.withOpacity(0.07), blurRadius: 14, offset: const Offset(0, 4)),
          ],
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          // ── Top: image + info ──────────────────────────────────────────
          Padding(
            padding: const EdgeInsets.all(14),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              // Product image with status indicator dot
              Stack(children: [
                Container(
                  width: 76, height: 76,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(14),
                    gradient: const LinearGradient(
                      begin: Alignment.topLeft, end: Alignment.bottomRight,
                      colors: [Color(0xFFECEFF1), Color(0xFFE9ECEF)]),
                  ),
                  child: imageUrl != null
                    ? ClipRRect(
                        borderRadius: BorderRadius.circular(14),
                        child: Image.network(imageUrl, width: 76, height: 76, fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) => const Center(
                            child: Icon(Icons.image_outlined, color: Color(0xFFADB5BD), size: 30))),
                      )
                    : const Center(child: Icon(Icons.image_outlined, color: Color(0xFFADB5BD), size: 30)),
                ),
                Positioned(
                  bottom: 4, right: 4,
                  child: Container(
                    width: 12, height: 12,
                    decoration: BoxDecoration(
                      color: statusColor,
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 2),
                    ),
                  ),
                ),
              ]),
              const SizedBox(width: 12),
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                // Status badge top-right
                Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                  Expanded(
                    child: Text(name,
                      style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 14),
                      maxLines: 2, overflow: TextOverflow.ellipsis),
                  ),
                  const SizedBox(width: 8),
                  _statusBadge(status, statusColor),
                ]),
                const SizedBox(height: 6),
                // Date
                Row(children: [
                  const Icon(Icons.calendar_today_outlined, size: 11, color: _textLight),
                  const SizedBox(width: 4),
                  Text(date.length > 10 ? date.substring(0, 10) : date,
                    style: const TextStyle(color: _textLight, fontSize: 11)),
                ]),
                const SizedBox(height: 6),
                // Specs chips
                Wrap(spacing: 5, runSpacing: 4, children: [
                  if (color != null && color.isNotEmpty) _chip(Icons.palette_outlined, color),
                  if (size != null && size.isNotEmpty)   _chip(Icons.straighten_outlined, size),
                  _chip(Icons.inventory_2_outlined, 'Qty: $quantity'),
                ]),
              ])),
            ]),
          ),

          // ── Bottom: price + cancel/arrow ──────────────────────────────
          Container(
            padding: const EdgeInsets.fromLTRB(14, 10, 14, 14),
            decoration: BoxDecoration(
              color: _bg,
              borderRadius: const BorderRadius.vertical(bottom: Radius.circular(18)),
            ),
            child: Row(children: [
              // Price
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('Total', style: TextStyle(color: _textLight, fontSize: 10)),
                Text('₱${totalPrice.toStringAsFixed(2)}',
                  style: const TextStyle(color: _accent, fontWeight: FontWeight.w800, fontSize: 16)),
              ]),
              const Spacer(),
              // Action buttons
              if (status == 'Pending')
                GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () => _showCancelDialog(orderId),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                    decoration: BoxDecoration(
                      color: Colors.red.withOpacity(0.08),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: Colors.red.withOpacity(0.3)),
                    ),
                    child: const Row(mainAxisSize: MainAxisSize.min, children: [
                      Icon(Icons.cancel_outlined, size: 13, color: Colors.red),
                      SizedBox(width: 5),
                      Text('Cancel', style: TextStyle(color: Colors.red, fontSize: 12, fontWeight: FontWeight.w700)),
                    ]),
                  ),
                )
              else if (status == 'Delivered')
                GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () => _showConfirmDialog(order),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                    decoration: BoxDecoration(
                      color: Colors.green.withOpacity(0.08),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: Colors.green.withOpacity(0.3)),
                    ),
                    child: const Row(mainAxisSize: MainAxisSize.min, children: [
                      Icon(Icons.check_circle_outline, size: 13, color: Colors.green),
                      SizedBox(width: 5),
                      Text('Confirm Receipt', style: TextStyle(color: Colors.green, fontSize: 12, fontWeight: FontWeight.w700)),
                    ]),
                  ),
                )
              else if (status == 'Completed')
                _reviewedOrderIds.contains(orderId)
                  ? Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                      decoration: BoxDecoration(
                        color: Colors.green.withOpacity(0.08),
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: Colors.green.withOpacity(0.3)),
                      ),
                      child: const Row(mainAxisSize: MainAxisSize.min, children: [
                        Icon(Icons.check_circle, size: 13, color: Colors.green),
                        SizedBox(width: 5),
                        Text('Reviewed', style: TextStyle(color: Colors.green, fontSize: 12, fontWeight: FontWeight.w700)),
                      ]),
                    )
                  : GestureDetector(
                      behavior: HitTestBehavior.opaque,
                      onTap: () => _showReviewDialog(order),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                        decoration: BoxDecoration(
                          color: _gold.withOpacity(0.08),
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: _gold.withOpacity(0.3)),
                        ),
                        child: const Row(mainAxisSize: MainAxisSize.min, children: [
                          Icon(Icons.star_outline, size: 13, color: _gold),
                          SizedBox(width: 5),
                          Text('Leave Review', style: TextStyle(color: _gold, fontSize: 12, fontWeight: FontWeight.w700)),
                        ]),
                      ),
                    )
              else
                const SizedBox.shrink(),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _chip(IconData icon, String label) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
    decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(8), border: Border.all(color: _border)),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 10, color: _textLight),
      const SizedBox(width: 3),
      Text(label, style: const TextStyle(color: _textLight, fontSize: 10, fontWeight: FontWeight.w500)),
    ]),
  );

  Widget _statusBadge(String status, Color color) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
    decoration: BoxDecoration(
      color: color.withOpacity(0.12),
      borderRadius: BorderRadius.circular(20),
      border: Border.all(color: color.withOpacity(0.3)),
    ),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(_statusIconFromString(status), size: 11, color: color),
      const SizedBox(width: 4),
      Text(status, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700)),
    ]),
  );

  Color _statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'pending':            return Colors.orange;
      case 'confirmed':          return Colors.blue.shade300;
      case 'preparing':          return Colors.purple;
      case 'waiting for pickup': return Colors.amber.shade700;
      case 'heading to seller':  return Colors.indigo;
      case 'for pickup':         return Colors.orange;
      case 'in transit':         return Colors.blue;
      case 'out for delivery':   return Colors.teal;
      case 'shipped':            return Colors.blue;
      case 'delivered':          return Colors.teal;
      case 'completed':          return Colors.green;
      case 'cancelled':          return Colors.red;
      default:                   return _textLight;
    }
  }

  IconData _statusIconFromString(String status) {
    switch (status.toLowerCase()) {
      case 'pending':            return Icons.hourglass_empty;
      case 'confirmed':          return Icons.check_circle_outline;
      case 'preparing':          return Icons.build_outlined;
      case 'waiting for pickup': return Icons.inventory_2_outlined;
      case 'heading to seller':  return Icons.directions_bike_outlined;
      case 'for pickup':         return Icons.access_time;
      case 'in transit':         return Icons.local_shipping_outlined;
      case 'out for delivery':   return Icons.local_shipping;
      case 'shipped':            return Icons.local_shipping_outlined;
      case 'delivered':          return Icons.check_circle_outline;
      case 'completed':          return Icons.check_circle;
      case 'cancelled':          return Icons.cancel_outlined;
      default:                   return Icons.help_outline;
    }
  }

  Widget _actionButtons(String status, int orderId, String orderName) {
    return Wrap(spacing: 8, runSpacing: 8, children: [
      if (status == 'Pending')
        _actionBtn('Cancel Order', Icons.cancel_outlined, Colors.red,
          () => _showCancelDialog(orderId)),
      if (status == 'Shipped')
        _actionBtn('Contact Rider', Icons.chat_outlined, Colors.blue, () {}),
      if (status == 'Delivered' || status == 'Completed')
        _actionBtn('Report Issue', Icons.flag_outlined, Colors.orange, () {}),
      _actionBtn('Contact Seller', Icons.chat_bubble_outline, _accent, () {}),
    ]);
  }

  Widget _actionBtn(String label, IconData icon, Color color, VoidCallback onTap) => GestureDetector(
    onTap: onTap,
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: color.withOpacity(0.08),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 13, color: color),
        const SizedBox(width: 5),
        Text(label, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600)),
      ]),
    ),
  );

  // ─── Dialogs ──────────────────────────────────────────────────────────────
  void _showCancelDialog(int orderId) {
    final reasonCtrl = TextEditingController();
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Row(children: [
          Icon(Icons.cancel_outlined, color: Colors.red),
          SizedBox(width: 8),
          Text('Cancel Order', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 18)),
        ]),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('Reason for cancellation:', style: TextStyle(color: _textLight, fontSize: 13)),
          const SizedBox(height: 10),
          TextField(
            controller: reasonCtrl,
            maxLines: 3,
            decoration: InputDecoration(
              hintText: 'Please let us know why...',
              hintStyle: const TextStyle(color: _textLight, fontSize: 13),
              filled: true, fillColor: _bg,
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: _border)),
              focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: _primary, width: 2)),
            ),
          ),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close')),
          ElevatedButton(
            onPressed: () async {
              Navigator.pop(context);
              await BuyerService.cancelOrder(orderId, reasonCtrl.text.trim());
              await _loadOrders();
              _showSuccessSnack('Order cancelled successfully.');
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
            child: const Text('Confirm Cancel'),
          ),
        ],
      ),
    );
  }

  void _showConfirmDialog(Map<String, dynamic> order) {
    final orderId = order['id'] as int;
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Row(children: [
          Icon(Icons.check_circle_outline, color: Colors.green),
          SizedBox(width: 8),
          Text('Confirm Receipt', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 18)),
        ]),
        content: const Text('Confirm that you have received this order?', style: TextStyle(color: _textLight)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          ElevatedButton(
            onPressed: () async {
              Navigator.pop(context);
              // Mark as Completed in Supabase
              await BuyerService.confirmReceipt(orderId);
              // Reload orders so status updates to Completed
              await _loadOrders();
              _showSuccessSnack('Receipt confirmed! Order is now Completed.');
              // Auto-open review dialog — only if not already reviewed
              if (mounted && !_reviewedOrderIds.contains(orderId)) {
                // Update the order map with new status for the review dialog
                final updatedOrder = Map<String, dynamic>.from(order)
                  ..['status'] = 'Completed';
                _showReviewDialog(updatedOrder);
              }
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.green, foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
            child: const Text('Confirm'),
          ),
        ],
      ),
    );
  }

  void _showReviewDialog(Map<String, dynamic> order) {
    final orderId = order['id'];
    // Guard: don't open if already reviewed
    if (_reviewedOrderIds.contains(orderId)) return;
    showReviewBottomSheet(
      context,
      order: order,
      userEmail: widget.userEmail,
      onSubmitted: () {
        // Mark this order as reviewed so the button changes to "Reviewed" immediately
        if (mounted) setState(() => _reviewedOrderIds.add(orderId));
        _showSuccessSnack('Review submitted! Thank you.');
      },
    );
  }

  void _showSuccessSnack(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: _primary, behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
    );
  }

  // ─── Empty State ──────────────────────────────────────────────────────────
  Widget _emptyState() => Center(
    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
      Container(
        width: 90, height: 90,
        decoration: BoxDecoration(shape: BoxShape.circle, color: _border),
        child: const Icon(Icons.shopping_bag_outlined, size: 44, color: _textLight),
      ),
      const SizedBox(height: 20),
      const Text('No Orders Yet', style: TextStyle(color: _accent, fontSize: 20, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      const Text("You haven't placed any orders yet.",
        style: TextStyle(color: _textLight, fontSize: 13), textAlign: TextAlign.center),
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

}
