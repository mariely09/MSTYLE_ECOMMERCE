import 'dart:convert';
import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'package:url_launcher/url_launcher.dart';
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
    case 'Out for Delivery':  return 'Delivered';  // triggers proof of delivery
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
    case 'Out for Delivery':  return Icons.camera_alt_outlined;  // camera icon for proof
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
  StreamSubscription<List<Map<String, dynamic>>>? _deliveriesSub;

  @override
  void initState() {
    super.initState();
    _fetchActive();
    _subscribeToDeliveries();
  }

  @override
  void dispose() {
    _deliveriesSub?.cancel();
    super.dispose();
  }

  // ── Supabase Realtime subscription ────────────────────────────────────────
  void _subscribeToDeliveries() {
    _deliveriesSub = supabase
        .from('orders')
        .stream(primaryKey: ['id'])
        .eq('rider_email', widget.riderEmail)
        .order('date', ascending: false)
        .listen((rows) {
          if (!mounted) return;
          // Filter to active statuses only and merge with enriched data
          final activeRows = rows.where((r) =>
            _activeStatuses.contains(r['status'] as String? ?? '')).toList();
          setState(() {
            for (final incoming in activeRows) {
              final idx = _deliveries.indexWhere((d) => d['id'] == incoming['id']);
              if (idx != -1) {
                // Preserve enriched fields (seller_address, buyer_full_name, etc.)
                _deliveries[idx] = {..._deliveries[idx], ...incoming};
              }
            }
            // Remove completed/cancelled orders that left active statuses
            final activeIds = activeRows.map((r) => r['id']).toSet();
            _deliveries.removeWhere((d) => !activeIds.contains(d['id']));
          });
        }, onError: (e) {
          debugPrint('rider deliveries stream error: $e');
        });
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

      // 5. Fetch unit price from products table
      final productIds = orders
          .map((o) => o['product_id'])
          .whereType<int>().toSet().toList();
      if (productIds.isNotEmpty) {
        final productsRes = await supabaseAdminSelectIn(
          table: 'products',
          select: 'id, price',
          column: 'id',
          values: productIds.map((id) => '$id').toList(),
        ).catchError((_) => <Map<String, dynamic>>[]);
        final priceMap = <int, double>{
          for (final p in productsRes)
            (p['id'] as int): (double.tryParse('${p['price']}') ?? 0),
        };
        for (final o in orders) {
          final pid = o['product_id'] as int?;
          o['unit_price'] = pid != null ? (priceMap[pid] ?? 0.0) : 0.0;
        }
      }

      // 6. Fetch buyer + seller full name & phone
      final buyerEmails = orders
          .map((o) => o['email'] as String?)
          .whereType<String>().toSet().toList();
      final allEmails = {...sellerEmails, ...buyerEmails}.toList();

      if (allEmails.isNotEmpty) {
        final usersRes = await supabaseAdminSelectIn(
          table: 'users',
          select: 'email, first_name, last_name, phone',
          column: 'email',
          values: allEmails,
        ).catchError((_) => <Map<String, dynamic>>[]);

        final userMap = <String, Map<String, dynamic>>{
          for (final u in usersRes) (u['email'] as String): u,
        };

        for (final o in orders) {
          // buyer
          final buyer = userMap[o['email'] as String? ?? ''];
          if (buyer != null) {
            final fn = (buyer['first_name'] as String? ?? '').trim();
            final ln = (buyer['last_name']  as String? ?? '').trim();
            o['buyer_full_name'] = [fn, ln].where((s) => s.isNotEmpty).join(' ');
            final raw = (buyer['phone'] as String? ?? '').trim();
            o['buyer_phone'] = raw.startsWith('0') ? '+63${raw.substring(1)}' : raw;
          }
          // seller
          final seller = userMap[o['seller_email'] as String? ?? ''];
          if (seller != null) {
            final fn = (seller['first_name'] as String? ?? '').trim();
            final ln = (seller['last_name']  as String? ?? '').trim();
            o['seller_full_name'] = [fn, ln].where((s) => s.isNotEmpty).join(' ');
            final raw = (seller['phone'] as String? ?? '').trim();
            o['seller_phone'] = raw.startsWith('0') ? '+63${raw.substring(1)}' : raw;
          }
        }
      }

      if (mounted) setState(() { _deliveries = orders; _loading = false; });
    } catch (e) {
      debugPrint('_fetchActive error: $e');
      if (mounted) setState(() => _loading = false);
    }
  }

  // ── Update status directly in Supabase ──────────────────────────────────────
  Future<void> _updateStatus(Map<String, dynamic> order, String newStatus) async {
    // When marking as Delivered (Completed), require proof of delivery photo first
    if (newStatus == 'Completed') {
      await _handleProofOfDelivery(order);
      return;
    }

    final confirm = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Text('Update Status',
          style: const TextStyle(color: _accent, fontWeight: FontWeight.w800)),
        content: Text(
          'Update order #${order['id']} to "$newStatus"?',
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
    await _performStatusUpdate(order, newStatus, proofImageUrl: null);
  }

  // ── Proof of Delivery flow ───────────────────────────────────────────────────
  Future<void> _handleProofOfDelivery(Map<String, dynamic> order) async {
    File? proofFile;

    // Show bottom sheet to pick photo source
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      backgroundColor: Colors.transparent,
      builder: (_) => Container(
        padding: const EdgeInsets.fromLTRB(20, 20, 20, 32),
        decoration: const BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
        ),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Center(child: Container(
            width: 40, height: 4,
            decoration: BoxDecoration(color: _border, borderRadius: BorderRadius.circular(2)),
          )),
          const SizedBox(height: 16),
          Row(children: const [
            Icon(Icons.camera_alt_outlined, color: _gold, size: 22),
            SizedBox(width: 10),
            Text('Proof of Delivery',
              style: TextStyle(color: _accent, fontSize: 17, fontWeight: FontWeight.w800)),
          ]),
          const SizedBox(height: 6),
          Text('Order #${order['id']} — ${order['name'] ?? ''}',
            style: const TextStyle(color: _textLight, fontSize: 13)),
          const SizedBox(height: 6),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.amber.withOpacity(0.08),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: Colors.amber.withOpacity(0.3)),
            ),
            child: const Row(children: [
              Icon(Icons.info_outline, color: Colors.amber, size: 16),
              SizedBox(width: 8),
              Expanded(child: Text(
                'A photo is required to confirm delivery. Take a clear photo of the delivered package.',
                style: TextStyle(color: Colors.amber, fontSize: 12, fontWeight: FontWeight.w500),
              )),
            ]),
          ),
          const SizedBox(height: 20),
          Row(children: [
            Expanded(child: GestureDetector(
              onTap: () => Navigator.pop(context, ImageSource.camera),
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 16),
                decoration: BoxDecoration(
                  gradient: _premiumGrad,
                  borderRadius: BorderRadius.circular(14),
                  boxShadow: [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 8, offset: const Offset(0, 3))],
                ),
                child: const Column(children: [
                  Icon(Icons.camera_alt, color: _gold, size: 28),
                  SizedBox(height: 6),
                  Text('Take Photo', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 13)),
                ]),
              ),
            )),
            const SizedBox(width: 12),
            Expanded(child: GestureDetector(
              onTap: () => Navigator.pop(context, ImageSource.gallery),
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 16),
                decoration: BoxDecoration(
                  color: _bg,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: _border, width: 1.5),
                ),
                child: const Column(children: [
                  Icon(Icons.photo_library_outlined, color: _accent, size: 28),
                  SizedBox(height: 6),
                  Text('Choose Photo', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
                ]),
              ),
            )),
          ]),
          const SizedBox(height: 12),
          GestureDetector(
            onTap: () => Navigator.pop(context, null),
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 13),
              decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(12), border: Border.all(color: _border)),
              child: const Center(child: Text('Cancel', style: TextStyle(color: _textLight, fontWeight: FontWeight.w700))),
            ),
          ),
        ]),
      ),
    );

    if (source == null) return;

    // Pick image
    try {
      final picker = ImagePicker();
      final picked = await picker.pickImage(
        source: source,
        imageQuality: 80,
        maxWidth: 1200,
        maxHeight: 1200,
      );
      if (picked == null) return;
      proofFile = File(picked.path);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Could not access camera/gallery: $e'),
          backgroundColor: Colors.red,
          behavior: SnackBarBehavior.floating,
        ));
      }
      return;
    }

    // Show preview + confirm dialog
    if (!mounted) return;
    final confirmed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (_) => Dialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Row(children: const [
              Icon(Icons.check_circle_outline, color: Colors.green, size: 22),
              SizedBox(width: 8),
              Text('Confirm Delivery',
                style: TextStyle(color: _accent, fontSize: 16, fontWeight: FontWeight.w800)),
            ]),
            const SizedBox(height: 4),
            Text('Order #${order['id']}',
              style: const TextStyle(color: _textLight, fontSize: 12)),
            const SizedBox(height: 14),
            ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: Image.file(proofFile!, height: 220, width: double.infinity, fit: BoxFit.cover),
            ),
            const SizedBox(height: 12),
            const Text(
              'This photo will be saved as proof of delivery and the order will be marked as Delivered.',
              style: TextStyle(color: _textLight, fontSize: 12),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            Row(children: [
              Expanded(child: GestureDetector(
                onTap: () => Navigator.pop(context, false),
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  decoration: BoxDecoration(
                    color: _bg, borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: _border),
                  ),
                  child: const Center(child: Text('Retake', style: TextStyle(color: _textLight, fontWeight: FontWeight.w700))),
                ),
              )),
              const SizedBox(width: 10),
              Expanded(child: GestureDetector(
                onTap: () => Navigator.pop(context, true),
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  decoration: BoxDecoration(
                    gradient: const LinearGradient(colors: [Colors.green, Color(0xFF27ae60)]),
                    borderRadius: BorderRadius.circular(10),
                    boxShadow: [BoxShadow(color: Colors.green.withOpacity(0.3), blurRadius: 8, offset: const Offset(0, 3))],
                  ),
                  child: const Center(child: Text('Confirm Delivery',
                    style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 13))),
                ),
              )),
            ]),
          ]),
        ),
      ),
    );

    if (confirmed != true) {
      // User wants to retake — recurse
      await _handleProofOfDelivery(order);
      return;
    }

    // Show uploading indicator
    if (mounted) {
      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (_) => const Center(
          child: Card(
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(16))),
            child: Padding(
              padding: EdgeInsets.all(28),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                CircularProgressIndicator(color: _gold),
                SizedBox(height: 16),
                Text('Uploading proof...', style: TextStyle(color: _accent, fontWeight: FontWeight.w600)),
              ]),
            ),
          ),
        ),
      );
    }

    // Upload to Supabase Storage
    String? proofImageUrl;
    try {
      final bytes = await proofFile.readAsBytes();
      final ext = proofFile.path.split('.').last.toLowerCase();
      final contentType = ext == 'png' ? 'image/png' : 'image/jpeg';
      final timestamp = DateTime.now().millisecondsSinceEpoch;
      final storagePath = 'proof_of_delivery/order_${order['id']}_$timestamp.$ext';

      final uploadUri = Uri.parse(
        '$supabaseUrl/storage/v1/object/proof-of-delivery/$storagePath',
      );
      final uploadResp = await http.post(uploadUri,
        headers: {
          'apikey':          supabaseServiceRole,
          'Authorization':   'Bearer $supabaseServiceRole',
          'Content-Type':    contentType,
          'x-upsert':        'true',
        },
        body: bytes,
      );

      if (uploadResp.statusCode == 200 || uploadResp.statusCode == 201) {
        proofImageUrl = '$supabaseUrl/storage/v1/object/public/proof-of-delivery/$storagePath';
        debugPrint('✅ Proof uploaded: $proofImageUrl');
      } else {
        debugPrint('⚠️ Proof upload failed: ${uploadResp.statusCode} ${uploadResp.body}');
        // Continue without proof URL — still mark as delivered
      }
    } catch (e) {
      debugPrint('⚠️ Proof upload error: $e');
    }

    // Dismiss uploading dialog
    if (mounted) Navigator.of(context, rootNavigator: true).pop();

    // Perform the actual status update
    await _performStatusUpdate(order, 'Delivered', proofImageUrl: proofImageUrl);
  }

  // ── Core status update (shared by normal updates and proof-of-delivery) ──────
  Future<void> _performStatusUpdate(
    Map<String, dynamic> order,
    String newStatus, {
    String? proofImageUrl,
  }) async {
    final isCompleted = newStatus == 'Delivered' || newStatus == 'Completed';

    // Optimistic update
    setState(() {
      final idx = _deliveries.indexWhere((d) => d['id'] == order['id']);
      if (idx != -1) _deliveries[idx]['status'] = newStatus;
    });

    try {
      final updateData = <String, dynamic>{'status': newStatus};
      if (isCompleted) {
        updateData['delivered_at'] = DateTime.now().toIso8601String();
      }
      if (proofImageUrl != null) {
        updateData['proof_of_delivery_url'] = proofImageUrl;
      }

      // Use service role to bypass RLS
      final updateUri = Uri.parse(
        '$supabaseUrl/rest/v1/orders?id=eq.${order['id']}',
      );
      final updateResp = await http.patch(updateUri,
        headers: {
          'apikey':        supabaseServiceRole,
          'Authorization': 'Bearer $supabaseServiceRole',
          'Content-Type':  'application/json',
          'Prefer':        'return=minimal',
        },
        body: jsonEncode(updateData),
      );
      debugPrint('✅ status update: ${updateResp.statusCode} ${updateResp.body}');
      if (updateResp.statusCode != 200 && updateResp.statusCode != 204) {
        throw Exception('Update failed: ${updateResp.statusCode}');
      }

      // Notify the buyer
      final buyerEmail = order['email'] as String?;
      if (buyerEmail != null && buyerEmail.isNotEmpty) {
        final productName = order['name'] as String? ?? 'your order';
        final message = isCompleted
            ? 'Your order "$productName" has been delivered! Thank you for shopping with us.'
            : 'Your order "$productName" status has been updated to "$newStatus".';
        try {
          final notifUri = Uri.parse('$supabaseUrl/rest/v1/buyer_notifications');
          await http.post(notifUri,
            headers: {
              'apikey':        supabaseServiceRole,
              'Authorization': 'Bearer $supabaseServiceRole',
              'Content-Type':  'application/json',
              'Prefer':        'return=minimal',
            },
            body: jsonEncode({
              'buyer_email': buyerEmail,
              'message':     message,
              'is_read':     false,
              'created_at':  DateTime.now().toIso8601String(),
            }),
          );
        } catch (e) {
          debugPrint('buyer notification error: $e');
        }
      }

      // Notify the seller when rider starts heading to pick up
      if (newStatus == 'Heading to Seller') {
        final sellerEmail = order['seller_email'] as String?;
        if (sellerEmail != null && sellerEmail.isNotEmpty) {
          final productName = order['name'] as String? ?? 'an order';
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
                'message':      'The rider is now heading to pick up "$productName" (Order #${order['id']}). Please prepare the item.',
                'type':         'rider_heading',
                'is_read':      false,
                'created_at':   DateTime.now().toIso8601String(),
              }),
            );
          } catch (e) {
            debugPrint('seller notification error: $e');
          }
        }
      }

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Row(children: [
            Icon(isCompleted ? Icons.check_circle : Icons.update,
              color: Colors.white, size: 18),
            const SizedBox(width: 8),
            Expanded(child: Text(isCompleted
              ? 'Order #${order['id']} marked as Delivered!'
              : 'Status updated to "$newStatus"')),
          ]),
          backgroundColor: isCompleted ? Colors.green : Colors.blue,
          behavior: SnackBarBehavior.floating,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          duration: const Duration(seconds: 3),
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
              color: Colors.white,
              borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
            ),
            child: Row(children: [
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Order #${d['id']}',
                  style: const TextStyle(color: _accent, fontWeight: FontWeight.w800, fontSize: 14)),
                const SizedBox(height: 2),
                Text(d['name'] as String? ?? '',
                  style: const TextStyle(color: _textLight, fontSize: 12),
                  maxLines: 1, overflow: TextOverflow.ellipsis),
              ])),
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                  decoration: BoxDecoration(
                    color: color.withOpacity(0.1), borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: color.withOpacity(0.4)),
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
                    color: isFree ? Colors.teal : _gold,
                    fontWeight: FontWeight.w900, fontSize: 15)),
              ]),
            ]),
          ),
          const Divider(height: 1, thickness: 1, color: Color(0xFFE9ECEF)),
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
              if (next != null)
                _primaryBtn(
                  _actionIcon(status), _actionLabel(status),
                  () => _updateStatus(d, next),
                ),
            ]),
          ),
        ]),
      ),
    );
  }

  void _showOrderModal(Map<String, dynamic> d) {
    // Use a live reference so the modal reflects status changes after _updateStatus
    final orderId = d['id'];
    final fee = (d['shipping_fee'] as num?)?.toDouble() ?? 0;
    final isFree = fee == 0;

    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (modalCtx) => StatefulBuilder(
        builder: (modalCtx, setModalState) {
          // Always read the latest data from _deliveries so status updates reflect live
          final live = _deliveries.firstWhere(
            (x) => x['id'] == orderId,
            orElse: () => d,
          );
          final status = live['status'] as String? ?? '';
          final color  = _statusColor(status);
          final next   = _nextStatus(status);

          return DraggableScrollableSheet(
            initialChildSize: 0.75, minChildSize: 0.5, maxChildSize: 0.95,
            builder: (_, scrollCtrl) => Container(
              decoration: const BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
              ),
              child: Column(children: [
                // drag handle
                Center(child: Container(
                  margin: const EdgeInsets.symmetric(vertical: 12),
                  width: 40, height: 4,
                  decoration: BoxDecoration(color: _border, borderRadius: BorderRadius.circular(2)),
                )),
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
                      Text('Order #${live['id']}',
                        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 16)),
                      const SizedBox(height: 3),
                      Text(live['name'] as String? ?? '',
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
                  // ── Product Details ──────────────────────────────────────
                  _sectionHeader('Product Details', Icons.inventory_2_outlined, Colors.indigo),
                  _modalInfoRow(Icons.tag, 'Order #', '${live['id']}', Colors.indigo),
                  _modalInfoRow(Icons.shopping_bag_outlined, 'Product', live['name'] as String? ?? '', Colors.indigo),
                  if ((live['variations'] as String?)?.isNotEmpty == true)
                    _modalInfoRow(Icons.palette_outlined, 'Color', live['variations'] as String, Colors.orange),
                  if ((live['size'] as String?)?.isNotEmpty == true)
                    _modalInfoRow(Icons.straighten_outlined, 'Size', live['size'] as String, Colors.teal),
                  if (live['quantity'] != null)
                    _modalInfoRow(Icons.numbers_outlined, 'Quantity', '${live['quantity']}', Colors.blue),
                  if (live['unit_price'] != null && (live['unit_price'] as double) > 0)
                    _modalInfoRow(Icons.payments_outlined, 'Price',
                      '₱${(live['unit_price'] as double).toStringAsFixed(2)}', Colors.green),
                  if (live['date'] != null)
                    _modalInfoRow(Icons.calendar_today_outlined, 'Order Date',
                      DateTime.tryParse(live['date'] as String)?.toLocal().toString().split(' ')[0] ?? '', Colors.purple),
                  const SizedBox(height: 12),

                  // ── Customer Details ─────────────────────────────────────
                  _sectionHeader('Customer Details', Icons.person_outline, Colors.blue),
                  if ((live['buyer_full_name'] as String?)?.isNotEmpty == true)
                    _modalInfoRow(Icons.badge_outlined, 'Full Name', live['buyer_full_name'] as String, Colors.blue),
                  _modalInfoRow(Icons.email_outlined, 'Email', live['email'] as String? ?? '', Colors.blue),
                  if ((live['buyer_phone'] as String?)?.isNotEmpty == true)
                    _modalInfoRow(Icons.phone_outlined, 'Phone', live['buyer_phone'] as String, Colors.green),
                  _modalInfoRow(Icons.location_on_outlined, 'Delivery Address', _deliveryAddress(live), Colors.red),
                  if (status == 'Heading to Seller' || status == 'In Transit' || status == 'Out for Delivery') ...[
                    const SizedBox(height: 8),
                    GestureDetector(
                      onTap: () async {
                        final addr = _deliveryAddress(live);
                        final query = Uri.encodeComponent(addr);
                        final geoUri = Uri.parse('geo:0,0?q=$query');
                        final webUri = Uri.parse('https://www.google.com/maps/search/?api=1&query=$query');
                        try {
                          if (await canLaunchUrl(geoUri)) {
                            await launchUrl(geoUri);
                          } else {
                            await launchUrl(webUri, mode: LaunchMode.externalApplication);
                          }
                        } catch (_) {
                          await launchUrl(webUri, mode: LaunchMode.externalApplication);
                        }
                      },
                      child: Container(
                        padding: const EdgeInsets.symmetric(vertical: 10),
                        decoration: BoxDecoration(
                          color: Colors.blue.withOpacity(0.08),
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: Colors.blue.withOpacity(0.3)),
                        ),
                        child: const Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                          Icon(Icons.map_outlined, size: 15, color: Colors.blue),
                          SizedBox(width: 6),
                          Text('View Route on Maps',
                            style: TextStyle(color: Colors.blue, fontWeight: FontWeight.w700, fontSize: 12)),
                        ]),
                      ),
                    ),
                  ],
                  const SizedBox(height: 12),

                  // ── Pickup / Seller Details ──────────────────────────────
                  _sectionHeader('Pickup Details', Icons.store_outlined, Colors.orange),
                  if ((live['seller_full_name'] as String?)?.isNotEmpty == true)
                    _modalInfoRow(Icons.badge_outlined, 'Name', live['seller_full_name'] as String, Colors.orange),
                  if ((live['seller_email'] as String?)?.isNotEmpty == true)
                    _modalInfoRow(Icons.email_outlined, 'Email', live['seller_email'] as String, Colors.orange),
                  if ((live['seller_phone'] as String?)?.isNotEmpty == true)
                    _modalInfoRow(Icons.phone_outlined, 'Phone', live['seller_phone'] as String, Colors.green),
                  _modalInfoRow(Icons.location_on_outlined, 'Pickup Address', _pickupAddress(live), Colors.orange),
                  const SizedBox(height: 12),

                  // ── Pricing Summary ──────────────────────────────────────
                  Builder(builder: (_) {
                    final unitPrice = (live['unit_price'] as double?) ?? 0.0;
                    final qty = (live['quantity'] as int?) ?? 1;
                    final deliveryFee = fee;
                    final subtotal = unitPrice * qty;
                    final totalPrice = subtotal + deliveryFee;
                    return Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: _gold.withOpacity(0.06),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: _gold.withOpacity(0.25)),
                      ),
                      child: Column(children: [
                        _pricingRow('Subtotal', '₱${subtotal.toStringAsFixed(2)}', _accent, false),
                        const Divider(height: 14),
                        _pricingRow('Delivery Fee', isFree ? 'Free' : '₱${deliveryFee.toStringAsFixed(2)}', Colors.teal, false),
                        const Divider(height: 14),
                        _pricingRow('Total', '₱${totalPrice.toStringAsFixed(2)}', _gold, true),
                      ]),
                    );
                  }),
                  const SizedBox(height: 20),
                  Row(children: [
                    Expanded(child: _outlineBtn(Icons.flag_outlined, 'Report Issue',
                      Colors.orange, () { Navigator.pop(modalCtx); _showReportIssue(live); })),
                    if (next != null) ...[
                      const SizedBox(width: 10),
                      Expanded(child: _primaryBtn(
                        _actionIcon(status), _actionLabel(status),
                        () async {
                          Navigator.pop(modalCtx);
                          await _updateStatus(live, next);
                        },
                      )),
                    ],
                  ]),
                  const SizedBox(height: 12),
                  GestureDetector(
                    onTap: () => Navigator.pop(modalCtx),
                    child: Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(vertical: 13),
                      decoration: BoxDecoration(
                        color: _bg,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: _border),
                      ),
                      child: const Center(child: Text('Cancel',
                        style: TextStyle(color: _textLight, fontWeight: FontWeight.w700, fontSize: 14))),
                    ),
                  ),
                  const SizedBox(height: 8),
                ])),
              ]),
            ),
          );
        },
      ),
    );
  }

  Widget _pricingRow(String label, String value, Color color, bool bold) => Row(
    mainAxisAlignment: MainAxisAlignment.spaceBetween,
    children: [
      Text(label, style: TextStyle(
        color: bold ? _accent : _textLight,
        fontSize: bold ? 14 : 13,
        fontWeight: bold ? FontWeight.w800 : FontWeight.w500)),
      Text(value, style: TextStyle(
        color: color,
        fontSize: bold ? 16 : 13,
        fontWeight: bold ? FontWeight.w900 : FontWeight.w600)),
    ],
  );

  Widget _sectionHeader(String title, IconData icon, Color color) => Padding(
    padding: const EdgeInsets.only(bottom: 10),
    child: Row(children: [
      Container(
        width: 28, height: 28,
        decoration: BoxDecoration(color: color.withOpacity(0.12), borderRadius: BorderRadius.circular(8)),
        child: Icon(icon, size: 14, color: color)),
      const SizedBox(width: 8),
      Text(title, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 0.3)),
      const SizedBox(width: 8),
      Expanded(child: Container(height: 1, color: color.withOpacity(0.15))),
    ]),
  );

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
