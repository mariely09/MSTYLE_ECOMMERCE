import 'package:flutter/material.dart';
import 'product_image_carousel.dart' show buildImageUrl;

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

class BuyerViewOrderDetails extends StatelessWidget {
  final Map<String, dynamic> order;

  const BuyerViewOrderDetails({super.key, required this.order});

  @override
  Widget build(BuildContext context) {
    final status     = order['status'] as String? ?? 'Pending';
    final name       = order['name'] as String? ?? '';
    final totalPrice = double.tryParse(order['total_price']?.toString() ?? '0') ?? 0;
    final date       = order['date'] as String? ?? '';
    final color      = order['variations'] as String?;
    final size       = order['size'] as String?;
    final quantity   = order['quantity'] as int? ?? 1;
    final orderId    = order['id'];
    final address    = order['address'] as String? ?? '';
    final email      = order['email'] as String? ?? '';
    final payment    = order['payment_method'] as String? ?? 'Cash on Delivery';
    final shipping   = double.tryParse(order['shipping_fee']?.toString() ?? '50') ?? 50;
    final imageRaw   = order['image'] as String?;
    final imageUrl   = buildImageUrl(imageRaw?.split(',').first.trim());
    final statusColor = _statusColor(status);

    return Scaffold(
      backgroundColor: _bg,
      body: CustomScrollView(
        slivers: [
          // ── App Bar ──────────────────────────────────────────────────────
          SliverAppBar(
            pinned: true,
            backgroundColor: _primary,
            leading: IconButton(
              icon: const Icon(Icons.arrow_back, color: Colors.white),
              onPressed: () => Navigator.pop(context),
            ),
            title: const Text('Order Details',
              style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700)),
            centerTitle: false,
          ),

          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [

                // ── Product Details ──────────────────────────────────────
                _sectionTitle('Product Details'),
                _card(children: [
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    ClipRRect(
                      borderRadius: BorderRadius.circular(10),
                      child: imageUrl != null
                        ? Image.network(imageUrl, width: 64, height: 64, fit: BoxFit.cover,
                            errorBuilder: (_, __, ___) => _imagePlaceholder(size: 64))
                        : _imagePlaceholder(size: 64),
                    ),
                    const SizedBox(width: 12),
                    Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(name, style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 14),
                        maxLines: 2, overflow: TextOverflow.ellipsis),
                      const SizedBox(height: 6),
                      Wrap(spacing: 6, runSpacing: 4, children: [
                        if (color != null && color.isNotEmpty) _specChip(Icons.palette_outlined, color),
                        if (size != null && size.isNotEmpty)   _specChip(Icons.straighten_outlined, size),
                        _specChip(Icons.inventory_2_outlined, 'Qty: $quantity'),
                      ]),
                    ])),
                  ]),
                ]),

                const SizedBox(height: 14),

                // ── Pricing ──────────────────────────────────────────────
                _sectionTitle('Pricing'),
                _card(children: [
                  _priceRow('Subtotal', '₱${totalPrice.toStringAsFixed(2)}'),
                  const Divider(height: 16),
                  _priceRow('Shipping Fee', '₱${shipping.toStringAsFixed(2)}'),
                  const Divider(height: 16),
                  _priceRow('Total', '₱${(totalPrice + shipping).toStringAsFixed(2)}',
                    highlight: true),
                ]),

                const SizedBox(height: 14),

                // ── Delivery Address ─────────────────────────────────────
                _sectionTitle('Delivery Address'),
                _card(children: [
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        color: _gold.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: const Icon(Icons.location_on_outlined, color: _gold, size: 18),
                    ),
                    const SizedBox(width: 12),
                    Expanded(child: Text(
                      address.isNotEmpty ? address : 'No address provided',
                      style: const TextStyle(color: _textLight, fontSize: 12, height: 1.5),
                    )),
                  ]),
                ]),

                const SizedBox(height: 14),

                // ── Order Status Timeline ────────────────────────────────
                _sectionTitle('Order Status'),
                _card(children: [_statusTimeline(status)]),

                const SizedBox(height: 14),

                // ── Action Buttons ───────────────────────────────────────
                Row(children: [
                  if (status == 'Pending') ...[
                    Expanded(
                      child: _actionButton(
                        label: 'Cancel Order',
                        icon: Icons.cancel_outlined,
                        color: Colors.red,
                        onTap: () => _showCancelDialog(context, orderId),
                      ),
                    ),
                    const SizedBox(width: 10),
                  ],
                  Expanded(
                    child: _actionButton(
                      label: 'Contact Seller',
                      icon: Icons.chat_bubble_outline,
                      color: _accent,
                      onTap: () {},
                    ),
                  ),
                ]),

                const SizedBox(height: 32),
              ]),
            ),
          ),
        ],
      ),
    );
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  Widget _imagePlaceholder({double size = 80}) => Container(
    width: size, height: size,
    decoration: const BoxDecoration(
      gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight,
        colors: [Color(0xFFECEFF1), Color(0xFFE9ECEF)]),
    ),
    child: const Center(child: Icon(Icons.image_outlined, color: Color(0xFFADB5BD), size: 28)),
  );

  Widget _statusPill(String status, Color color) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
    decoration: BoxDecoration(
      color: color.withOpacity(0.2),
      borderRadius: BorderRadius.circular(20),
      border: Border.all(color: color.withOpacity(0.4)),
    ),
    child: Text(status, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w700)),
  );

  Widget _sectionTitle(String title) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Text(title, style: const TextStyle(
      color: _accent, fontSize: 14, fontWeight: FontWeight.w700, letterSpacing: 0.2)),
  );

  Widget _card({required List<Widget> children}) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, 2))],
    ),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
  );

  Widget _row(IconData icon, String label, String value) => Row(children: [
    Container(
      padding: const EdgeInsets.all(7),
      decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(8)),
      child: Icon(icon, size: 15, color: _textLight),
    ),
    const SizedBox(width: 10),
    Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label, style: const TextStyle(color: _textLight, fontSize: 11)),
      Text(value, style: const TextStyle(color: _accent, fontWeight: FontWeight.w600, fontSize: 13)),
    ])),
  ]);

  Widget _priceRow(String label, String value, {bool highlight = false}) => Row(
    mainAxisAlignment: MainAxisAlignment.spaceBetween,
    children: [
      Text(label, style: TextStyle(
        color: highlight ? _accent : _textLight,
        fontSize: highlight ? 14 : 13,
        fontWeight: highlight ? FontWeight.w700 : FontWeight.w500,
      )),
      Text(value, style: TextStyle(
        color: highlight ? _gold : _accent,
        fontSize: highlight ? 16 : 13,
        fontWeight: FontWeight.w700,
      )),
    ],
  );

  Widget _specChip(IconData icon, String label) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
    decoration: BoxDecoration(
      color: _gold.withOpacity(0.08),
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: _gold.withOpacity(0.25)),
    ),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 11, color: _gold),
      const SizedBox(width: 4),
      Text(label, style: const TextStyle(color: _accent, fontSize: 11, fontWeight: FontWeight.w600)),
    ]),
  );

  Widget _statusTimeline(String currentStatus) {
    final steps = [
      ('Pending',   Icons.hourglass_empty,       'Order placed'),
      ('Confirmed', Icons.check_circle_outline,   'Order confirmed'),
      ('Preparing', Icons.construction_outlined,  'Being prepared'),
      ('Waiting for Pickup', Icons.inventory_2_outlined,  'Ready for pickup'),
      ('Shipped',   Icons.local_shipping_outlined,'On the way'),
      ('Delivered', Icons.check_circle,           'Delivered'),
      ('Completed', Icons.verified_outlined,      'Completed'),
    ];

    final statusOrder = steps.map((s) => s.$1.toLowerCase()).toList();
    final currentIdx  = statusOrder.indexOf(currentStatus.toLowerCase());

    return Column(children: List.generate(steps.length, (i) {
      final (label, icon, sub) = steps[i];
      final done   = i <= currentIdx;
      final active = i == currentIdx;
      final color  = active ? _gold : (done ? Colors.green : _border);

      return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Column(children: [
          Container(
            width: 32, height: 32,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: active ? _gold : (done ? Colors.green.withOpacity(0.15) : _bg),
              border: Border.all(color: color, width: active ? 2 : 1.5),
            ),
            child: Icon(icon, size: 15, color: active ? Colors.white : color),
          ),
          if (i < steps.length - 1)
            Container(width: 2, height: 28,
              color: i < currentIdx ? Colors.green.withOpacity(0.4) : _border),
        ]),
        const SizedBox(width: 12),
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label, style: TextStyle(
              color: active ? _gold : (done ? _accent : _textLight),
              fontSize: 13, fontWeight: active ? FontWeight.w700 : FontWeight.w500)),
            Text(sub, style: const TextStyle(color: _textLight, fontSize: 11)),
          ]),
        ),
      ]);
    }));
  }

  Color _statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'pending':   return Colors.orange;
      case 'confirmed': return Colors.blue.shade700;
      case 'preparing': return Colors.indigo;
      case 'waiting for pickup': return Colors.purple;
      case 'shipped':   return Colors.blue;
      case 'delivered': return Colors.teal;
      case 'completed': return Colors.green;
      case 'cancelled': return Colors.red;
      default:          return _textLight;
    }
  }

  Widget _actionButton({
    required String label,
    required IconData icon,
    required Color color,
    required VoidCallback onTap,
  }) =>
      GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 14),
          decoration: BoxDecoration(
            color: color.withOpacity(0.08),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: color.withOpacity(0.3)),
          ),
          child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            Icon(icon, size: 16, color: color),
            const SizedBox(width: 7),
            Text(label,
                style: TextStyle(
                    color: color, fontSize: 13, fontWeight: FontWeight.w700)),
          ]),
        ),
      );

  void _showCancelDialog(BuildContext context, dynamic orderId) {
    final reasonCtrl = TextEditingController();
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Row(children: [
          Icon(Icons.cancel_outlined, color: Colors.red),
          SizedBox(width: 8),
          Text('Cancel Order',
              style: TextStyle(
                  color: _accent, fontWeight: FontWeight.w700, fontSize: 18)),
        ]),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('Reason for cancellation:',
              style: TextStyle(color: _textLight, fontSize: 13)),
          const SizedBox(height: 10),
          TextField(
            controller: reasonCtrl,
            maxLines: 3,
            decoration: InputDecoration(
              hintText: 'Please let us know why...',
              hintStyle: const TextStyle(color: _textLight, fontSize: 13),
              filled: true,
              fillColor: _bg,
              border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: _border)),
              focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: _primary, width: 2)),
            ),
          ),
        ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Close')),
          ElevatedButton(
            onPressed: () => Navigator.pop(context),
            style: ElevatedButton.styleFrom(
                backgroundColor: Colors.red,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10))),
            child: const Text('Confirm Cancel'),
          ),
        ],
      ),
    );
  }
}
