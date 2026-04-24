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

const _premiumGrad = LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [_primary, _accent]);
const _goldGrad    = LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [_gold, _goldLight]);

class RiderHistoryDeliveriesPage extends StatefulWidget {
  final String riderEmail;
  const RiderHistoryDeliveriesPage({super.key, required this.riderEmail});
  @override
  State<RiderHistoryDeliveriesPage> createState() => _RiderHistoryDeliveriesPageState();
}

class _RiderHistoryDeliveriesPageState extends State<RiderHistoryDeliveriesPage> {
  bool _loading = true;
  List<Map<String, dynamic>> _history = [];

  @override
  void initState() {
    super.initState();
    _fetchHistory();
  }

  Future<void> _fetchHistory() async {
    setState(() => _loading = true);
    try {
      final data = await supabase
          .from('orders')
          .select()
          .eq('rider_email', widget.riderEmail)
          .eq('status', 'Completed')
          .order('date', ascending: false);
      if (mounted) setState(() { _history = List<Map<String, dynamic>>.from(data); _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      body: CustomScrollView(slivers: [
        SliverAppBar(
          pinned: true,
          backgroundColor: _primary,
          elevation: 6,
          leading: IconButton(
            icon: const Icon(Icons.arrow_back, color: Colors.white),
            onPressed: () => Navigator.pop(context),
          ),
          title: const Text('Delivery History',
            style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w700)),
        ),
        SliverToBoxAdapter(child: const SizedBox(height: 12)),
        if (_loading)
          const SliverFillRemaining(child: Center(child: CircularProgressIndicator(color: _gold)))
        else if (_history.isEmpty)
          SliverFillRemaining(child: _emptyState())
        else
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 32),
            sliver: SliverList(delegate: SliverChildBuilderDelegate(
              (_, i) => _historyCard(_history[i]), childCount: _history.length)),
          ),
      ]),
    );
  }

  Widget _historyCard(Map<String, dynamic> d) {
    final fee = (d['shipping_fee'] as num?)?.toDouble() ?? 0;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(14),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 8, offset: const Offset(0, 2))]),
      child: Row(children: [
        Container(width: 44, height: 44,
          decoration: BoxDecoration(color: Colors.green.shade50, shape: BoxShape.circle,
            border: Border.all(color: Colors.green.shade200)),
          child: Icon(Icons.check_circle_outline, color: Colors.green.shade600, size: 22)),
        const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Container(padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(6), border: Border.all(color: _border)),
              child: Text('#${d['id']}', style: const TextStyle(color: _textLight, fontSize: 10, fontWeight: FontWeight.w700))),
            const SizedBox(width: 6),
            Expanded(child: Text(d['name'] as String? ?? '',
              style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13),
              maxLines: 1, overflow: TextOverflow.ellipsis)),
          ]),
          const SizedBox(height: 4),
          Text(d['email'] as String? ?? '', style: const TextStyle(color: _textLight, fontSize: 11)),
          Text(d['date'] != null
            ? DateTime.tryParse(d['date'] as String)?.toLocal().toString().split(' ')[0] ?? ''
            : '', style: const TextStyle(color: _textLight, fontSize: 10)),
        ])),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(fee == 0 ? 'Free' : '₱${fee.toStringAsFixed(0)}',
            style: TextStyle(color: fee == 0 ? Colors.teal : Colors.green,
              fontWeight: FontWeight.w900, fontSize: 15)),
          Container(margin: const EdgeInsets.only(top: 4),
            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
            decoration: BoxDecoration(color: Colors.green.shade50, borderRadius: BorderRadius.circular(6)),
            child: Text(d['status'] as String? ?? 'Completed',
              style: TextStyle(color: Colors.green.shade700, fontSize: 9, fontWeight: FontWeight.w700))),
        ]),
      ]),
    );
  }

  Widget _emptyState() => Center(child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
    const Icon(Icons.history_outlined, size: 72, color: _border),
    const SizedBox(height: 16),
    const Text('No Delivery History', style: TextStyle(color: _accent, fontSize: 18, fontWeight: FontWeight.w700)),
    const SizedBox(height: 8),
    const Text('Your completed deliveries will appear here.',
      style: TextStyle(color: _textLight, fontSize: 13)),
  ]));

}
