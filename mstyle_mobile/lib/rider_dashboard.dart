import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
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
        select: 'id, name, email, address, date, shipping_fee, product_id, rider_email, status, seller_email',
        filters: {'status': 'Waiting for Pickup'},
        limit: 10,
      );

      final unassigned = data.where((o) => o['rider_email'] == null).take(3).toList();

      // Fetch buyer full name + phone using service role (bypasses RLS)
      for (final o in unassigned) {
        final buyerEmail = o['email'] as String? ?? '';
        if (buyerEmail.isEmpty) continue;
        try {
          final uri = Uri.parse(
            '$supabaseUrl/rest/v1/users?select=first_name,last_name,phone&email=eq.${Uri.encodeComponent(buyerEmail)}&limit=1',
          );
          final resp = await http.get(uri, headers: {
            'apikey':        supabaseServiceRole,
            'Authorization': 'Bearer $supabaseServiceRole',
            'Accept':        'application/json',
          });
          debugPrint('👤 lookup $buyerEmail → ${resp.statusCode} ${resp.body}');
          if (resp.statusCode == 200) {
            final rows = jsonDecode(resp.body) as List;
            if (rows.isNotEmpty) {
              final b  = rows.first as Map<String, dynamic>;
              final fn = (b['first_name'] as String? ?? '').trim();
              final ln = (b['last_name']  as String? ?? '').trim();
              o['buyer_full_name'] = [fn, ln].where((s) => s.isNotEmpty).join(' ');
              final rawPhone = (b['phone'] as String? ?? '').trim();
              o['buyer_phone'] = rawPhone.startsWith('0')
                  ? '+63${rawPhone.substring(1)}'
                  : rawPhone;
            } else {
              o['buyer_full_name'] = '';
              o['buyer_phone']     = '';
            }
          }
        } catch (e) {
          debugPrint('👤 user lookup error: $e');
          o['buyer_full_name'] = '';
          o['buyer_phone']     = '';
        }
      }

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
        SliverToBoxAdapter(child: _statsGrid()),
        SliverToBoxAdapter(child: _availableSection()),
        const SliverToBoxAdapter(child: SizedBox(height: 32)),
      ]),
    );
  }

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
    return Container(
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
            decoration: const BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
            ),
            child: Row(children: [
              Container(
                width: 36, height: 36,
                decoration: BoxDecoration(
                  color: _accent.withOpacity(0.08),
                  shape: BoxShape.circle,
                  border: Border.all(color: _border),
                ),
                child: const Icon(Icons.local_shipping_outlined, color: _accent, size: 18),
              ),
              const SizedBox(width: 10),
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Order #${d['id']}',
                  style: const TextStyle(color: _accent, fontWeight: FontWeight.w800, fontSize: 13)),
                const SizedBox(height: 2),
                Text(d['name'] as String? ?? '',
                  style: const TextStyle(color: _textLight, fontSize: 11),
                  maxLines: 1, overflow: TextOverflow.ellipsis),
              ])),
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Text(isFree ? 'Free' : '₱${fee.toStringAsFixed(0)}',
                  style: TextStyle(
                    color: isFree ? Colors.teal : _gold,
                    fontWeight: FontWeight.w900, fontSize: 16)),
                const SizedBox(height: 3),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                  decoration: BoxDecoration(
                    color: Colors.orange.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: Colors.orange.withOpacity(0.4)),
                  ),
                  child: const Text('Ready for Pickup',
                    style: TextStyle(color: Colors.orange, fontSize: 9, fontWeight: FontWeight.w700)),
                ),
              ]),
            ]),
          ),
          const Divider(height: 1, thickness: 1, color: Color(0xFFE9ECEF)),

          // ── Body ──────────────────────────────────────────────────────
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              // Full name
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
                Expanded(child: Text(
                  (d['buyer_full_name'] as String?)?.isNotEmpty == true
                      ? d['buyer_full_name'] as String
                      : (d['email'] as String? ?? ''),
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

              // Phone
              if ((d['buyer_phone'] as String?)?.isNotEmpty == true) ...[
                const SizedBox(height: 8),
                Row(children: [
                  Container(
                    width: 28, height: 28,
                    decoration: BoxDecoration(
                      color: Colors.green.withOpacity(0.08),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Icon(Icons.phone_outlined, size: 13, color: Colors.green),
                  ),
                  const SizedBox(width: 8),
                  Text(d['buyer_phone'] as String,
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
    );
  }

  Future<void> _acceptDelivery(Map<String, dynamic> order) async {
    final fee = (order['shipping_fee'] as num?)?.toDouble() ?? 0;
    final isFree = fee == 0;

    final confirm = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Accept Delivery',
          style: TextStyle(color: _accent, fontWeight: FontWeight.w800, fontSize: 16)),
        content: Text(
          'Accept Order #${order['id']} — ${order['name'] ?? ''}?',
          style: const TextStyle(color: _textLight, fontSize: 13),
        ),
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
      // Use service role to bypass RLS
      final updateUri = Uri.parse('$supabaseUrl/rest/v1/orders?id=eq.${order['id']}');
      final updateResp = await http.patch(updateUri,
        headers: {
          'apikey':        supabaseServiceRole,
          'Authorization': 'Bearer $supabaseServiceRole',
          'Content-Type':  'application/json',
          'Prefer':        'return=minimal',
        },
        body: jsonEncode({
          'rider_email': widget.riderEmail,
          'status':      'For Pickup',
        }),
      );
      debugPrint('✅ order update: ${updateResp.statusCode} ${updateResp.body}');
      if (updateResp.statusCode != 200 && updateResp.statusCode != 204) {
        throw Exception('Update failed: ${updateResp.statusCode}');
      }

      // Remove from available list immediately (optimistic)
      setState(() {
        _availableOrders.removeWhere((o) => o['id'] == order['id']);
        _availableCount = (_availableCount - 1).clamp(0, 999);
        _activeCount = _activeCount + 1;
      });

      // Notify the seller using service role to bypass RLS
      final sellerEmail = order['seller_email'] as String?;
      if (sellerEmail != null && sellerEmail.isNotEmpty) {
        try {
          final notifUri = Uri.parse('$supabaseUrl/rest/v1/notifications');
          await http.post(notifUri,
            headers: {
              'apikey':        supabaseServiceRole,
              'Authorization': 'Bearer $supabaseServiceRole',
              'Content-Type':  'application/json',
              'Prefer':        'return=minimal',
            },
            body: jsonEncode({
              'seller_email': sellerEmail,
              'message':      'A rider has accepted Order #${order['id']} and will head to pick it up soon.',
              'type':         'rider_assigned',
              'is_read':      false,
              'order_id':     order['id'],
              'created_at':   DateTime.now().toIso8601String(),
            }),
          );
          debugPrint('✅ seller notified: $sellerEmail');
        } catch (e) {
          debugPrint('seller notification error: $e');
        }
      }

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Order #${order['id']} accepted!'),
        backgroundColor: Colors.green,
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ));
      // Refresh dashboard data immediately so accepted order disappears
      _fetchStats();
      _fetchAvailableOrders();
      // Navigate to active deliveries and refresh on return
      await Navigator.push(context, MaterialPageRoute(
        builder: (_) => RiderActiveDeliveriesPage(riderEmail: widget.riderEmail)));
      // Refresh again when rider comes back from active deliveries
      _fetchStats();
      _fetchAvailableOrders();
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
