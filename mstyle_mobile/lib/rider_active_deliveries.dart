import 'package:flutter/material.dart';
import 'rider_dashboard.dart';
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

const _activeStatuses = [
  'For Pickup',
  'Heading to Seller',
  'In Transit',
  'Out for Delivery',
];

Color _statusColor(String status) {
  switch (status) {
    case 'For Pickup':        return Colors.orange;
    case 'Heading to Seller': return Colors.indigo;
    case 'In Transit':        return Colors.blue;
    case 'Out for Delivery':  return Colors.teal;
    default:                  return Colors.grey;
  }
}

IconData _statusIcon(String status) {
  switch (status) {
    case 'For Pickup':        return Icons.access_time;
    case 'Heading to Seller': return Icons.directions_bike_outlined;
    case 'In Transit':        return Icons.local_shipping_outlined;
    case 'Out for Delivery':  return Icons.local_shipping;
    default:                  return Icons.help_outline;
  }
}

String? _nextStatus(String status) {
  switch (status) {
    case 'For Pickup':        return 'Heading to Seller';
    case 'Heading to Seller': return 'In Transit';
    case 'In Transit':        return 'Out for Delivery';
    case 'Out for Delivery':  return 'Completed';
    default:                  return null;
  }
}

String _actionLabel(String status) {
  switch (status) {
    case 'For Pickup':        return 'Start Pickup';
    case 'Heading to Seller': return 'Mark Picked Up';
    case 'In Transit':        return 'Out for Delivery';
    case 'Out for Delivery':  return 'Mark Delivered';
    default:                  return 'Update';
  }
}

IconData _actionIcon(String status) {
  switch (status) {
    case 'For Pickup':        return Icons.play_circle_outline;
    case 'Heading to Seller': return Icons.check_circle_outline;
    case 'In Transit':        return Icons.local_shipping_outlined;
    case 'Out for Delivery':  return Icons.check_circle;
    default:                  return Icons.arrow_forward;
  }
}

class RiderActiveDeliveriesPage extends StatefulWidget {
  final String riderEmail;
  const RiderActiveDeliveriesPage({super.key, required this.riderEmail});
  @override
  State<RiderActiveDeliveriesPage> createState() => _RiderActiveDeliveriesPageState();
}

class _RiderActiveDeliveriesPageState extends State<RiderActiveDeliveriesPage> {
  String _filterStatus = 'all';
  String _sortBy = 'default';
  bool _loading = true;
  List<Map<String, dynamic>> _deliveries = [];

  @override
  void initState() {
    super.initState();
    _fetchActive();
  }

  // ── Fetch active orders directly from Supabase ──────────────────────────────
  Future<void> _fetchActive() async {
    setState(() => _loading = true);
    try {
      // 1. Fetch active orders for this rider
      final ordersRes = await supabase
          .from('orders')
          .select('*')
          .eq('rider_email', widget.riderEmail)
          .inFilter('status', _activeStatuses)
          .order('date', ascending: false);

      final orders = List<Map<String, dynamic>>.from(ordersRes as List);

      // 2. Collect unique seller emails
      final sellerEmails = orders
          .map((o) => o['seller_email'] as String?)
          .whereType<String>()
          .toSet()
          .toList();

      // 3. Fetch seller address fields using admin (bypasses RLS on users table)
      final sellerMap = <String, String>{};
      debugPrint('🏪 seller_emails to lookup: $sellerEmails');
      if (sellerEmails.isNotEmpty) {
        final sellersRes = await supabaseAdminSelectIn(
          table:  'users',
          select: 'email,house_street,barangay,city,province,region,zip_code',
          column: 'email',
          values: sellerEmails,
        ).catchError((e) {
          debugPrint('❌ supabaseAdminSelectIn error: $e');
          return <Map<String, dynamic>>[];
        });

        debugPrint('📦 sellers fetched: ${sellersRes.length} — $sellersRes');

        for (final s in sellersRes) {
          final parts = <String>[
            s['house_street'] as String? ?? '',
            s['barangay']    as String? ?? '',
            s['city']        as String? ?? '',
            s['province']    as String? ?? '',
            s['region']      as String? ?? '',
            s['zip_code']    as String? ?? '',
          ].where((p) => p.isNotEmpty).toList();
          sellerMap[s['email'] as String] = parts.join(', ');
        }
        debugPrint('🗺️ sellerMap: $sellerMap');
      }

      // 4. Attach seller_address to each order
      for (final o in orders) {
        o['seller_address'] = sellerMap[o['seller_email'] ?? ''] ?? '';
      }

      if (mounted) setState(() { _deliveries = orders; _loading = false; });
    } catch (e) {
      debugPrint('_fetchActive error: $e');
      if (mounted) setState(() => _loading = false);
    }
  }

  // ── Update status directly in Supabase ──────────────────────────────────────
  Future<void> _updateStatus(Map<String, dynamic> order, String newStatus) async {
    final isCompleted = newStatus == 'Completed';
    final confirm = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Text(isCompleted ? 'Mark as Delivered' : 'Update Status',
          style: const TextStyle(color: _accent, fontWeight: FontWeight.w800)),
        content: Text(
          isCompleted
            ? 'Confirm delivery of order #${order['id']} to ${order['name'] ?? 'customer'}?'
            : 'Update order #${order['id']} to "$newStatus"?',
          style: const TextStyle(color: _textLight, fontSize: 13),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel', style: TextStyle(color: _textLight))),
          GestureDetector(
            onTap: () => Navigator.pop(context, true),
            child: Container(
              margin: const EdgeInsets.only(right: 8, bottom: 4),
              padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
              decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(10)),
              child: const Text('Confirm', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 13)),
            ),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    // Optimistic update
    setState(() {
      final idx = _deliveries.indexWhere((d) => d['id'] == order['id']);
      if (idx != -1) _deliveries[idx]['status'] = newStatus;
    });

    try {
      final updateData = <String, dynamic>{'status': newStatus};
      if (isCompleted) updateData['delivered_at'] = DateTime.now().toIso8601String();

      await supabase
          .from('orders')
          .update(updateData)
          .eq('id', order['id'])
          .eq('rider_email', widget.riderEmail);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(isCompleted
            ? 'Order #${order['id']} delivered!'
            : 'Status updated to "$newStatus"'),
          backgroundColor: isCompleted ? Colors.green : Colors.blue,
          behavior: SnackBarBehavior.floating,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        ));
        if (isCompleted) {
          setState(() => _deliveries.removeWhere((d) => d['id'] == order['id']));
        }
      }
    } catch (e) {
      // Revert on failure
      setState(() {
        final idx = _deliveries.indexWhere((d) => d['id'] == order['id']);
        if (idx != -1) _deliveries[idx]['status'] = order['status'];
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Failed to update status. Please try again.'),
          backgroundColor: Colors.red,
          behavior: SnackBarBehavior.floating,
        ));
      }
    }
  }

  // ── Helpers ─────────────────────────────────────────────────────────────────
  String _pickupAddress(Map<String, dynamic> d) {
    final addr = (d['seller_address'] as String? ?? '').trim();
    return addr.isNotEmpty ? addr : 'Pickup address not available';
  }

  String _deliveryAddress(Map<String, dynamic> d) =>
      (d['address'] as String?)?.trim().isNotEmpty == true
          ? d['address'] as String
          : 'Delivery address not available';

  List<Map<String, dynamic>> get _filtered {
    var list = _deliveries.where((d) {
      if (_filterStatus != 'all' && (d['status'] as String? ?? '') != _filterStatus) return false;
      return true;
    }).toList();
    if (_sortBy == 'value_high') list.sort((a, b) => ((b['shipping_fee'] as num?) ?? 0).compareTo((a['shipping_fee'] as num?) ?? 0));
    if (_sortBy == 'value_low')  list.sort((a, b) => ((a['shipping_fee'] as num?) ?? 0).compareTo((b['shipping_fee'] as num?) ?? 0));
    return list;
  }

  int _countByStatus(String status) => _deliveries.where((d) => d['status'] == status).length;

  // ── Build ────────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      body: CustomScrollView(
        slivers: [
          SliverAppBar(
            pinned: true,
            backgroundColor: _primary,
            elevation: 6,
            leading: IconButton(
              icon: const Icon(Icons.arrow_back, color: Colors.white),
              onPressed: () => Navigator.pop(context),
            ),
            title: const Text('Active Deliveries',
              style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w700)),
          ),
          SliverToBoxAdapter(child: _statsRow()),
          SliverToBoxAdapter(child: _filterSection()),
          if (_loading)
            const SliverFillRemaining(child: Center(child: CircularProgressIndicator(color: _gold)))
          else if (_filtered.isEmpty)
            SliverFillRemaining(child: _emptyState())
          else
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 80),
              sliver: SliverList(
                delegate: SliverChildBuilderDelegate(
                  (_, i) => _deliveryCard(_filtered[i]),
                  childCount: _filtered.length,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _statsRow() => Container(
    color: Colors.white,
    padding: const EdgeInsets.fromLTRB(12, 14, 12, 14),
    child: Row(children: [
      Expanded(child: _miniStat('${_deliveries.length}', 'Active', Icons.list_alt_outlined, Colors.blue)),
      _divider(),
      Expanded(child: _miniStat('${_countByStatus('For Pickup')}', 'For\nPickup', Icons.access_time, Colors.orange)),
      _divider(),
      Expanded(child: _miniStat('${_countByStatus('Heading to Seller')}', 'Heading to\nSeller', Icons.directions_bike_outlined, Colors.indigo)),
      _divider(),
      Expanded(child: _miniStat('${_countByStatus('Out for Delivery')}', 'Out for\nDelivery', Icons.local_shipping, Colors.teal)),
    ]),
  );

  Widget _miniStat(String value, String label, IconData icon, Color color) => Column(children: [
    Icon(icon, color: color, size: 18),
    const SizedBox(height: 4),
    Text(value, style: TextStyle(color: color, fontWeight: FontWeight.w900, fontSize: 18)),
    Text(label, style: const TextStyle(color: _textLight, fontSize: 9, fontWeight: FontWeight.w500),
      textAlign: TextAlign.center),
  ]);

  Widget _divider() => Container(width: 1, height: 40, color: _border, margin: const EdgeInsets.symmetric(horizontal: 4));

  Widget _filterSection() => Container(
    color: Colors.white,
    padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
    child: Row(children: [
      Expanded(child: _dropdown('Status', _filterStatus, {
        'all': 'All Status',
        'For Pickup': 'For Pickup',
        'Heading to Seller': 'Heading to Seller',
        'In Transit': 'In Transit',
        'Out for Delivery': 'Out for Delivery',
      }, (v) => setState(() => _filterStatus = v ?? 'all'))),
      const SizedBox(width: 10),
      Expanded(child: _dropdown('Sort By', _sortBy, {
        'default': 'Default Order',
        'value_high': 'Fee: High to Low',
        'value_low': 'Fee: Low to High',
      }, (v) => setState(() => _sortBy = v ?? 'default'))),
      const SizedBox(width: 10),
      GestureDetector(
        onTap: () => setState(() { _filterStatus = 'all'; _sortBy = 'default'; }),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(10), border: Border.all(color: _border)),
          child: const Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.refresh, size: 14, color: _textLight),
            SizedBox(width: 4),
            Text('Reset', style: TextStyle(color: _textLight, fontSize: 12, fontWeight: FontWeight.w600)),
          ]),
        ),
      ),
    ]),
  );

  Widget _dropdown(String label, String value, Map<String, String> options, ValueChanged<String?> onChanged) =>
    DropdownButtonFormField<String>(
      value: value, isExpanded: true,
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

  Widget _deliveryCard(Map<String, dynamic> d) {
    final status = d['status'] as String? ?? '';
    final fee = (d['shipping_fee'] as num?)?.toDouble() ?? 0;
    final isFree = fee == 0;
    final color = _statusColor(status);
    final next = _nextStatus(status);

    return GestureDetector(
      onTap: () => _showOrderModal(d),
      child: Container(
        margin: const EdgeInsets.only(bottom: 14),
        decoration: BoxDecoration(
          color: Colors.white, borderRadius: BorderRadius.circular(16),
          boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.06), blurRadius: 12, offset: const Offset(0, 3))],
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
            decoration: const BoxDecoration(
              gradient: _premiumGrad,
              borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
            ),
            child: Row(children: [
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Order #${d['id']}',
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 14)),
                const SizedBox(height: 2),
                Text(d['name'] as String? ?? '',
                  style: TextStyle(color: Colors.white.withOpacity(0.7), fontSize: 12),
                  maxLines: 1, overflow: TextOverflow.ellipsis),
              ])),
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                  decoration: BoxDecoration(
                    color: color.withOpacity(0.2), borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: color.withOpacity(0.5)),
                  ),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(_statusIcon(status), size: 11, color: color),
                    const SizedBox(width: 4),
                    Text(status, style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 10)),
                  ]),
                ),
                const SizedBox(height: 4),
                Text(isFree ? 'Free' : '₱${fee.toStringAsFixed(0)}',
                  style: TextStyle(
                    color: isFree ? Colors.greenAccent.shade200 : _goldLight,
                    fontWeight: FontWeight.w900, fontSize: 15)),
              ]),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Container(width: 28, height: 28,
                  decoration: BoxDecoration(color: Colors.orange.withOpacity(0.1), borderRadius: BorderRadius.circular(8)),
                  child: const Icon(Icons.store_outlined, size: 14, color: Colors.orange)),
                const SizedBox(width: 8),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('Pickup', style: TextStyle(color: _textLight, fontSize: 10, fontWeight: FontWeight.w600)),
                  Text(_pickupAddress(d),
                    style: const TextStyle(color: _accent, fontSize: 12, fontWeight: FontWeight.w500),
                    maxLines: 2, overflow: TextOverflow.ellipsis),
                ])),
              ]),
              const SizedBox(height: 8),
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Container(width: 28, height: 28,
                  decoration: BoxDecoration(color: Colors.red.withOpacity(0.08), borderRadius: BorderRadius.circular(8)),
                  child: const Icon(Icons.location_on_outlined, size: 14, color: Colors.redAccent)),
                const SizedBox(width: 8),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('Deliver to', style: TextStyle(color: _textLight, fontSize: 10, fontWeight: FontWeight.w600)),
                  Text(_deliveryAddress(d),
                    style: const TextStyle(color: _accent, fontSize: 12, fontWeight: FontWeight.w500),
                    maxLines: 2, overflow: TextOverflow.ellipsis),
                ])),
              ]),
              const SizedBox(height: 12),
              Row(children: [
                Expanded(child: _outlineBtn(Icons.flag_outlined, 'Report Issue',
                  Colors.orange, () => _showReportIssue(d))),
                if (next != null) ...[
                  const SizedBox(width: 10),
                  Expanded(child: _primaryBtn(
                    _actionIcon(status), _actionLabel(status),
                    () => _updateStatus(d, next),
                  )),
                ],
              ]),
            ]),
          ),
        ]),
      ),
    );
  }

  void _showOrderModal(Map<String, dynamic> d) {
    final status = d['status'] as String? ?? '';
    final fee = (d['shipping_fee'] as num?)?.toDouble() ?? 0;
    final isFree = fee == 0;
    final color = _statusColor(status);
    final next = _nextStatus(status);

    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (_) => DraggableScrollableSheet(
        initialChildSize: 0.75, minChildSize: 0.5, maxChildSize: 0.95,
        builder: (_, scrollCtrl) => Container(
          decoration: const BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
          ),
          child: Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 8, 0),
              child: Row(children: [
                const Spacer(),
                Container(width: 40, height: 4,
                  decoration: BoxDecoration(color: _border, borderRadius: BorderRadius.circular(2))),
                const Spacer(),
                IconButton(
                  icon: const Icon(Icons.close, color: _textLight, size: 20),
                  onPressed: () => Navigator.pop(context),
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(),
                ),
              ]),
            ),
            Container(
              margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(16)),
              child: Row(children: [
                Container(width: 44, height: 44,
                  decoration: BoxDecoration(color: Colors.white.withOpacity(0.12), shape: BoxShape.circle,
                    border: Border.all(color: _gold.withOpacity(0.5))),
                  child: const Icon(Icons.local_shipping_outlined, color: _gold, size: 22)),
                const SizedBox(width: 12),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Order #${d['id']}',
                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 16)),
                  const SizedBox(height: 3),
                  Text(d['name'] as String? ?? '',
                    style: TextStyle(color: Colors.white.withOpacity(0.7), fontSize: 12),
                    maxLines: 1, overflow: TextOverflow.ellipsis),
                ])),
                Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text(isFree ? 'Free' : '₱${fee.toStringAsFixed(0)}',
                    style: TextStyle(
                      color: isFree ? Colors.greenAccent.shade200 : _goldLight,
                      fontWeight: FontWeight.w900, fontSize: 18)),
                  const SizedBox(height: 4),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: color.withOpacity(0.2), borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: color.withOpacity(0.5))),
                    child: Text(status, style: TextStyle(color: color, fontSize: 10, fontWeight: FontWeight.w700)),
                  ),
                ]),
              ]),
            ),
            Expanded(child: ListView(controller: scrollCtrl, padding: const EdgeInsets.all(16), children: [
              _modalInfoRow(Icons.person_outline, 'Customer', d['email'] as String? ?? '', Colors.blue),
              _modalInfoRow(Icons.store_outlined, 'Pickup Address', _pickupAddress(d), Colors.orange),
              _modalInfoRow(Icons.location_on_outlined, 'Delivery Address', _deliveryAddress(d), Colors.red),
              if (d['date'] != null)
                _modalInfoRow(Icons.calendar_today_outlined, 'Order Date',
                  DateTime.tryParse(d['date'] as String)?.toLocal().toString().split(' ')[0] ?? '', Colors.purple),
              if ((d['variations'] as String?)?.isNotEmpty == true)
                _modalInfoRow(Icons.palette_outlined, 'Color', d['variations'] as String, Colors.orange),
              if ((d['size'] as String?)?.isNotEmpty == true)
                _modalInfoRow(Icons.straighten_outlined, 'Size', d['size'] as String, Colors.teal),
              if (d['quantity'] != null)
                _modalInfoRow(Icons.inventory_2_outlined, 'Quantity', '${d['quantity']}', Colors.indigo),
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                decoration: BoxDecoration(
                  color: _gold.withOpacity(0.08),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: _gold.withOpacity(0.3)),
                ),
                child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                  const Text('Delivery Fee', style: TextStyle(color: _accent, fontWeight: FontWeight.w600, fontSize: 14)),
                  Text(isFree ? 'Free' : '₱${fee.toStringAsFixed(0)}',
                    style: TextStyle(color: isFree ? Colors.teal : _gold, fontWeight: FontWeight.w900, fontSize: 16)),
                ]),
              ),
              const SizedBox(height: 20),
              Row(children: [
                Expanded(child: _outlineBtn(Icons.flag_outlined, 'Report Issue',
                  Colors.orange, () { Navigator.pop(context); _showReportIssue(d); })),
                if (next != null) ...[
                  const SizedBox(width: 10),
                  Expanded(child: _primaryBtn(
                    _actionIcon(status), _actionLabel(status),
                    () { Navigator.pop(context); _updateStatus(d, next); },
                  )),
                ],
              ]),
              const SizedBox(height: 8),
            ])),
          ]),
        ),
      ),
    );
  }

  Widget _modalInfoRow(IconData icon, String label, String value, Color color) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Container(width: 36, height: 36,
        decoration: BoxDecoration(color: color.withOpacity(0.1), borderRadius: BorderRadius.circular(10)),
        child: Icon(icon, size: 16, color: color)),
      const SizedBox(width: 12),
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(color: _textLight, fontSize: 11, fontWeight: FontWeight.w500)),
        const SizedBox(height: 2),
        Text(value, style: const TextStyle(color: _accent, fontSize: 13, fontWeight: FontWeight.w600)),
      ])),
    ]),
  );

  Widget _outlineBtn(IconData icon, String label, Color color, VoidCallback onTap) => GestureDetector(
    onTap: onTap,
    child: Container(
      padding: const EdgeInsets.symmetric(vertical: 11),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withOpacity(0.4), width: 1.5),
        color: color.withOpacity(0.05),
      ),
      child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
        Icon(icon, size: 14, color: color),
        const SizedBox(width: 6),
        Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 12)),
      ]),
    ),
  );

  Widget _primaryBtn(IconData icon, String label, VoidCallback onTap) => GestureDetector(
    onTap: onTap,
    child: Container(
      padding: const EdgeInsets.symmetric(vertical: 11),
      decoration: BoxDecoration(
        gradient: _premiumGrad, borderRadius: BorderRadius.circular(12),
        boxShadow: [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 8, offset: const Offset(0, 3))],
      ),
      child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
        Icon(icon, size: 14, color: _gold),
        const SizedBox(width: 6),
        Text(label, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 12)),
      ]),
    ),
  );

  void _showReportIssue(Map<String, dynamic> order) {
    final ctrl = TextEditingController();
    showModalBottomSheet(
      context: context, backgroundColor: Colors.transparent, isScrollControlled: true,
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
            const Row(children: [
              Icon(Icons.flag_outlined, color: Colors.orange, size: 20),
              SizedBox(width: 8),
              Text('Report Issue', style: TextStyle(color: _accent, fontSize: 16, fontWeight: FontWeight.w800)),
            ]),
            const SizedBox(height: 8),
            Text('Order #${order['id']} — ${order['name'] ?? ''}',
              style: const TextStyle(color: _textLight, fontSize: 13)),
            const SizedBox(height: 14),
            TextField(
              controller: ctrl, maxLines: 4,
              decoration: InputDecoration(
                hintText: 'Describe the issue...',
                hintStyle: const TextStyle(color: _textLight, fontSize: 13),
                filled: true, fillColor: _bg,
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: _border)),
                focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: _gold, width: 2)),
              ),
            ),
            const SizedBox(height: 14),
            GestureDetector(
              onTap: () {
                Navigator.pop(context);
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                  content: Text('Issue reported successfully.'),
                  backgroundColor: Colors.orange,
                  behavior: SnackBarBehavior.floating));
              },
              child: Container(
                width: double.infinity, padding: const EdgeInsets.symmetric(vertical: 14),
                decoration: BoxDecoration(
                  color: Colors.orange, borderRadius: BorderRadius.circular(14),
                  boxShadow: [BoxShadow(color: Colors.orange.withOpacity(0.3), blurRadius: 10, offset: const Offset(0, 4))]),
                child: const Center(child: Text('Submit Report',
                  style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 14))),
              ),
            ),
          ]),
        ),
      ),
    );
  }

  Widget _emptyState() => Center(
    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
      const Icon(Icons.local_shipping_outlined, size: 72, color: _border),
      const SizedBox(height: 16),
      const Text('No Active Deliveries', style: TextStyle(color: _accent, fontSize: 18, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      const Text("You don't have any active deliveries at the moment.",
        style: TextStyle(color: _textLight, fontSize: 13), textAlign: TextAlign.center),
      const SizedBox(height: 20),
      GestureDetector(
        onTap: () => Navigator.pushReplacement(context,
          MaterialPageRoute(builder: (_) => RiderDashboardPage(riderEmail: widget.riderEmail))),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(12)),
          child: const Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.speed, color: Colors.white, size: 16),
            SizedBox(width: 6),
            Text('Go to Dashboard',
              style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 13)),
          ]),
        ),
      ),
    ]),
  );
}
