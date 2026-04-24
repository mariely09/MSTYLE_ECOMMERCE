import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'rider_active_deliveries.dart';
import 'rider_header.dart';
import 'rider_bottom_navbar.dart';
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

class RiderDashboardPage extends StatefulWidget {
  final String riderEmail;
  const RiderDashboardPage({super.key, required this.riderEmail});
  @override
  State<RiderDashboardPage> createState() => _RiderDashboardPageState();
}

class _RiderDashboardPageState extends State<RiderDashboardPage> {
  int    _availableCount = 0;
  int    _activeCount    = 0;
  bool   _loadingStats   = true;
  List<Map<String, dynamic>> _availableOrders = [];
  bool   _loadingAvailable = true;

  RealtimeChannel? _ordersChannel;

  @override
  void initState() {
    super.initState();
    _fetchStats();
    _fetchAvailableOrders();
    _subscribeRealtime();
  }

  @override
  void dispose() {
    _ordersChannel?.unsubscribe();
    super.dispose();
  }

  void _subscribeRealtime() {
    _ordersChannel = supabase
        .channel('rider_dashboard_orders')
        .onPostgresChanges(
          event: PostgresChangeEvent.all,
          schema: 'public',
          table: 'orders',
          callback: (_) {
            _fetchStats();
            _fetchAvailableOrders();
          },
        )
        .subscribe();
  }

  Future<void> _fetchStats() async {
    try {
      // Available: bypass RLS with admin
      final available = await supabaseAdminSelect(
        table: 'orders',
        select: 'id, rider_email',
        filters: {'status': 'Waiting for Pickup'},
      );
      final availableUnassigned = available.where((o) => o['rider_email'] == null).toList();
      debugPrint('📦 available total: ${available.length}, unassigned: ${availableUnassigned.length}');

      // Active: bypass RLS with admin, filter by rider_email then check statuses in Dart
      final allRiderOrders = await supabaseAdminSelect(
        table: 'orders',
        select: 'id, status',
        filters: {'rider_email': widget.riderEmail},
        limit: 200,
      );
      const activeStatuses = ['For Pickup', 'Heading to Seller', 'In Transit', 'Out for Delivery'];
      final activeOrders = allRiderOrders.where((o) => activeStatuses.contains(o['status'])).toList();
      debugPrint('🚚 rider orders total: ${allRiderOrders.length}, active: ${activeOrders.length}');
      debugPrint('🚚 statuses found: ${allRiderOrders.map((o) => o['status']).toSet()}');

      if (!mounted) return;

      setState(() {
        _availableCount = availableUnassigned.length;
        _activeCount    = activeOrders.length;
        _loadingStats   = false;
      });
    } catch (e) {
      debugPrint('_fetchStats error: $e');
      if (mounted) setState(() => _loadingStats = false);
    }
  }

  Future<void> _fetchAvailableOrders() async {
    setState(() => _loadingAvailable = true);
    try {
      final data = await supabaseAdminSelect(
        table: 'orders',
        select: 'id, name, email, address, date, shipping_fee, product_id, rider_email, status',
        filters: {'status': 'Waiting for Pickup'},
        limit: 10,
      );

      // Filter out already-assigned orders
      final unassigned = data.where((o) => o['rider_email'] == null).take(3).toList();

      debugPrint('_fetchAvailableOrders: found ${data.length} total, ${unassigned.length} unassigned');

      if (mounted) {
        setState(() {
          _availableOrders = unassigned;
          _loadingAvailable = false;
        });
      }
    } catch (e) {
      debugPrint('_fetchAvailableOrders error: $e');
      if (mounted) setState(() => _loadingAvailable = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      bottomNavigationBar: RiderBottomNavBar(riderEmail: widget.riderEmail, currentPage: RiderPage.dashboard),
      body: CustomScrollView(slivers: [
        RiderAppBar(riderEmail: widget.riderEmail),
        SliverToBoxAdapter(child: _pageHeader()),
        SliverToBoxAdapter(child: _statsGrid()),
        SliverToBoxAdapter(child: _availableSection()),
        const SliverToBoxAdapter(child: SizedBox(height: 32)),
      ]),
    );
  }

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
        child: const Icon(Icons.speed, color: _primary, size: 26),
      ),
      const SizedBox(height: 12),
      const Text('Rider Dashboard',
        style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w800)),
      const SizedBox(height: 4),
      Text('Track your deliveries and earnings',
        style: TextStyle(color: Colors.white.withOpacity(0.7), fontSize: 12)),
    ]),
  );

  // ─── Stats Grid ───────────────────────────────────────────────────────────
  Widget _statsGrid() => Padding(
    padding: const EdgeInsets.fromLTRB(12, 16, 12, 0),
    child: _loadingStats
      ? const SizedBox(height: 80, child: Center(child: CircularProgressIndicator(color: _gold)))
      : Row(children: [
          Expanded(child: _statCard('$_availableCount', 'Available\nDeliveries', Icons.list_alt_outlined, Colors.blue)),
          const SizedBox(width: 12),
          Expanded(child: _statCard('$_activeCount', 'Active\nDeliveries', Icons.local_shipping_outlined, Colors.orange)),
        ]),
  );

  Widget _statCard(String value, String label, IconData icon, Color color) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: Colors.white, borderRadius: BorderRadius.circular(14),
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.06), blurRadius: 10, offset: const Offset(0, 3))],
    ),
    child: Column(children: [
      Container(
        width: 40, height: 40,
        decoration: BoxDecoration(color: color.withOpacity(0.12), borderRadius: BorderRadius.circular(10)),
        child: Icon(icon, color: color, size: 20),
      ),
      const SizedBox(height: 8),
      Text(value, style: const TextStyle(color: _accent, fontWeight: FontWeight.w900, fontSize: 18)),
      const SizedBox(height: 3),
      Text(label, style: const TextStyle(color: _textLight, fontSize: 10, fontWeight: FontWeight.w500),
        textAlign: TextAlign.center),
    ]),
  );

  // ─── Available Section ────────────────────────────────────────────────────
  Widget _availableSection() => Padding(
    padding: const EdgeInsets.fromLTRB(12, 16, 12, 0),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        const Icon(Icons.list_alt_outlined, color: _gold, size: 16),
        const SizedBox(width: 6),
        const Text('Available Deliveries', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
        const Spacer(),
        GestureDetector(
          onTap: () => Navigator.push(context, MaterialPageRoute(
            builder: (_) => RiderActiveDeliveriesPage(riderEmail: widget.riderEmail))),
          child: const Text('See active', style: TextStyle(color: _gold, fontSize: 12, fontWeight: FontWeight.w600)),
        ),
      ]),
      const SizedBox(height: 12),
      if (_loadingAvailable)
        const Center(child: Padding(
          padding: EdgeInsets.symmetric(vertical: 16),
          child: CircularProgressIndicator(color: _gold, strokeWidth: 2),
        ))
      else if (_availableOrders.isEmpty)
        const Center(child: Padding(
          padding: EdgeInsets.symmetric(vertical: 16),
          child: Text('No available deliveries right now', style: TextStyle(color: _textLight, fontSize: 12)),
        ))
      else
        ..._availableOrders.map((d) => _availableTile(d)),
    ]),
  );

  Widget _availableTile(Map<String, dynamic> d) {
    final fee = (d['shipping_fee'] as num?)?.toDouble() ?? 0;
    final isFree = fee == 0;
    return GestureDetector(
      onTap: () => _acceptDelivery(d),
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          boxShadow: [
            BoxShadow(color: Colors.black.withOpacity(0.07), blurRadius: 12, offset: const Offset(0, 4)),
          ],
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          // ── Header strip ──────────────────────────────────────────────
          Container(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
            decoration: BoxDecoration(
              gradient: _premiumGrad,
              borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
            ),
            child: Row(children: [
              Container(
                width: 36, height: 36,
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.12),
                  shape: BoxShape.circle,
                  border: Border.all(color: _gold.withOpacity(0.5)),
                ),
                child: const Icon(Icons.local_shipping_outlined, color: _gold, size: 18),
              ),
              const SizedBox(width: 10),
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Order #${d['id']}',
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13)),
                const SizedBox(height: 2),
                Text(d['name'] as String? ?? '',
                  style: TextStyle(color: Colors.white.withOpacity(0.7), fontSize: 11),
                  maxLines: 1, overflow: TextOverflow.ellipsis),
              ])),
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Text(isFree ? 'Free' : '₱${fee.toStringAsFixed(0)}',
                  style: TextStyle(
                    color: isFree ? Colors.greenAccent.shade200 : _goldLight,
                    fontWeight: FontWeight.w900, fontSize: 16)),
                const SizedBox(height: 3),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                  decoration: BoxDecoration(
                    color: Colors.orange.withOpacity(0.2),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: Colors.orange.withOpacity(0.5)),
                  ),
                  child: const Text('Ready for Pickup',
                    style: TextStyle(color: Colors.orange, fontSize: 9, fontWeight: FontWeight.w700)),
                ),
              ]),
            ]),
          ),

          // ── Body ──────────────────────────────────────────────────────
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              // Customer
              Row(children: [
                Container(
                  width: 28, height: 28,
                  decoration: BoxDecoration(
                    color: _accent.withOpacity(0.08),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: const Icon(Icons.person_outline, size: 14, color: _accent),
                ),
                const SizedBox(width: 8),
                Expanded(child: Text(d['email'] as String? ?? '',
                  style: const TextStyle(color: _textLight, fontSize: 11),
                  maxLines: 1, overflow: TextOverflow.ellipsis)),
              ]),

              // Address
              if ((d['address'] as String?)?.isNotEmpty == true) ...[
                const SizedBox(height: 8),
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Container(
                    width: 28, height: 28,
                    decoration: BoxDecoration(
                      color: Colors.red.withOpacity(0.08),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Icon(Icons.location_on_outlined, size: 14, color: Colors.redAccent),
                  ),
                  const SizedBox(width: 8),
                  Expanded(child: Text(d['address'] as String,
                    style: const TextStyle(color: _textLight, fontSize: 11),
                    maxLines: 2, overflow: TextOverflow.ellipsis)),
                ]),
              ],

              // Date
              if (d['date'] != null) ...[
                const SizedBox(height: 8),
                Row(children: [
                  Container(
                    width: 28, height: 28,
                    decoration: BoxDecoration(
                      color: Colors.blue.withOpacity(0.08),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Icon(Icons.calendar_today_outlined, size: 13, color: Colors.blueAccent),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    DateTime.tryParse(d['date'] as String)?.toLocal().toString().split(' ')[0] ?? '',
                    style: const TextStyle(color: _textLight, fontSize: 11)),
                ]),
              ],

              const SizedBox(height: 14),

              // Accept button
              GestureDetector(
                onTap: () => _acceptDelivery(d),
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  decoration: BoxDecoration(
                    gradient: _premiumGrad,
                    borderRadius: BorderRadius.circular(12),
                    boxShadow: [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 8, offset: const Offset(0, 3))],
                  ),
                  child: const Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                    Icon(Icons.check_circle_outline, size: 16, color: _gold),
                    SizedBox(width: 7),
                    Text('Accept Delivery',
                      style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13)),
                  ]),
                ),
              ),
            ]),
          ),
        ]),
      ),
    );
  }

  Future<void> _acceptDelivery(Map<String, dynamic> order) async {
    final fee = (order['shipping_fee'] as num?)?.toDouble() ?? 0;
    final confirm = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Accept Delivery',
          style: TextStyle(color: _accent, fontWeight: FontWeight.w800, fontSize: 16)),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Order #${order['id']}',
            style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
          const SizedBox(height: 4),
          Text(order['name'] as String? ?? '',
            style: const TextStyle(color: _textLight, fontSize: 12),
            maxLines: 2, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 12),
          Row(children: [
            const Icon(Icons.person_outline, size: 14, color: _textLight),
            const SizedBox(width: 6),
            Expanded(child: Text(order['email'] as String? ?? '',
              style: const TextStyle(color: _textLight, fontSize: 12))),
          ]),
          if ((order['address'] as String?)?.isNotEmpty == true) ...[
            const SizedBox(height: 6),
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Icon(Icons.location_on_outlined, size: 14, color: _textLight),
              const SizedBox(width: 6),
              Expanded(child: Text(order['address'] as String,
                style: const TextStyle(color: _textLight, fontSize: 12),
                maxLines: 2, overflow: TextOverflow.ellipsis)),
            ]),
          ],
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: _gold.withOpacity(0.08),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: _gold.withOpacity(0.3)),
            ),
            child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              const Text('Delivery Fee', style: TextStyle(color: _accent, fontWeight: FontWeight.w600, fontSize: 13)),
              Text(fee == 0 ? 'Free' : '₱${fee.toStringAsFixed(0)}',
                style: TextStyle(
                  color: fee == 0 ? Colors.teal : _gold,
                  fontWeight: FontWeight.w900, fontSize: 15)),
            ]),
          ),
        ]),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel', style: TextStyle(color: _textLight))),
          GestureDetector(
            onTap: () => Navigator.pop(context, true),
            child: Container(
              margin: const EdgeInsets.only(right: 8, bottom: 4),
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
              decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(10)),
              child: const Text('Accept', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 13)),
            ),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    try {
      await supabase
          .from('orders')
          .update({
            'rider_email': widget.riderEmail,
            'status': 'Heading to Seller',
          })
          .eq('id', order['id']);

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Order #${order['id']} accepted!'),
        backgroundColor: Colors.green,
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ));
      Navigator.pushReplacement(context, MaterialPageRoute(
        builder: (_) => RiderActiveDeliveriesPage(riderEmail: widget.riderEmail)));
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Failed to accept delivery. Please try again.'),
          backgroundColor: Colors.red,
          behavior: SnackBarBehavior.floating,
        ));
      }
    }
  }

}
