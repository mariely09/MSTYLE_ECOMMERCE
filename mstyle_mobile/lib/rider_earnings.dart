import 'package:flutter/material.dart';
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

class RiderEarningsPage extends StatefulWidget {
  final String riderEmail;
  const RiderEarningsPage({super.key, required this.riderEmail});
  @override
  State<RiderEarningsPage> createState() => _RiderEarningsPageState();
}

class _RiderEarningsPageState extends State<RiderEarningsPage> {
  bool _loading = true;
  List<Map<String, dynamic>> _earnings = [];

  @override
  void initState() {
    super.initState();
    _fetchEarnings();
  }

  Future<void> _fetchEarnings() async {
    setState(() => _loading = true);
    try {
      final data = await supabase
          .from('orders')
          .select('id, name, shipping_fee, date')
          .eq('rider_email', widget.riderEmail)
          .eq('status', 'Completed')
          .order('date', ascending: false);
      if (mounted) setState(() { _earnings = List<Map<String, dynamic>>.from(data); _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  double get _total => _earnings.fold(0.0, (s, d) => s + ((d['shipping_fee'] as num?)?.toDouble() ?? 0));

  double get _today {
    final now = DateTime.now();
    return _earnings.where((d) {
      final date = d['date'] != null ? DateTime.tryParse(d['date'] as String) : null;
      return date != null && date.year == now.year && date.month == now.month && date.day == now.day;
    }).fold(0.0, (s, d) => s + ((d['shipping_fee'] as num?)?.toDouble() ?? 0));
  }

  double get _week {
    final now = DateTime.now();
    final weekStart = now.subtract(Duration(days: now.weekday - 1));
    return _earnings.where((d) {
      final date = d['date'] != null ? DateTime.tryParse(d['date'] as String) : null;
      return date != null && date.isAfter(weekStart.subtract(const Duration(days: 1)));
    }).fold(0.0, (s, d) => s + ((d['shipping_fee'] as num?)?.toDouble() ?? 0));
  }

  double get _month {
    final now = DateTime.now();
    return _earnings.where((d) {
      final date = d['date'] != null ? DateTime.tryParse(d['date'] as String) : null;
      return date != null && date.year == now.year && date.month == now.month;
    }).fold(0.0, (s, d) => s + ((d['shipping_fee'] as num?)?.toDouble() ?? 0));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      body: _loading
        ? const Center(child: CircularProgressIndicator(color: _gold))
        : CustomScrollView(slivers: [
            SliverAppBar(
              pinned: true,
              backgroundColor: _primary,
              elevation: 6,
              leading: IconButton(
                icon: const Icon(Icons.arrow_back, color: Colors.white),
                onPressed: () => Navigator.pop(context),
              ),
              title: const Text('Earnings',
                style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w700)),
            ),
            SliverToBoxAdapter(child: _totalCard()),
            SliverToBoxAdapter(child: _periodCards()),
            SliverToBoxAdapter(child: _breakdownSection()),
            const SliverToBoxAdapter(child: SizedBox(height: 32)),
          ]),
    );
  }

  Widget _totalCard() => Container(
    margin: const EdgeInsets.fromLTRB(12, 12, 12, 0),
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(16),
      boxShadow: [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 12, offset: const Offset(0, 4))]),
    child: Column(children: [
      const Text('Total Earnings', style: TextStyle(color: Colors.white70, fontSize: 13)),
      const SizedBox(height: 8),
      ShaderMask(shaderCallback: (b) => _goldGrad.createShader(b),
        child: Text('₱${_total.toStringAsFixed(2)}',
          style: const TextStyle(color: Colors.white, fontSize: 36, fontWeight: FontWeight.w900))),
      const SizedBox(height: 4),
      Text('${_earnings.length} completed deliveries',
        style: TextStyle(color: Colors.white.withOpacity(0.6), fontSize: 12)),
    ]),
  );

  Widget _periodCards() => Padding(
    padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
    child: Row(children: [
      Expanded(child: _periodCard('₱${_today.toStringAsFixed(0)}', 'Today', Icons.today_outlined, Colors.blue)),
      const SizedBox(width: 12),
      Expanded(child: _periodCard('₱${_week.toStringAsFixed(0)}', 'This Week', Icons.date_range_outlined, Colors.purple)),
      const SizedBox(width: 12),
      Expanded(child: _periodCard('₱${_month.toStringAsFixed(0)}', 'This Month', Icons.calendar_month_outlined, Colors.teal)),
    ]),
  );

  Widget _periodCard(String value, String label, IconData icon, Color color) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12),
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 8, offset: const Offset(0, 2))]),
    child: Column(children: [
      Icon(icon, color: color, size: 20),
      const SizedBox(height: 6),
      Text(value, style: const TextStyle(color: _accent, fontWeight: FontWeight.w900, fontSize: 16)),
      Text(label, style: const TextStyle(color: _textLight, fontSize: 10)),
    ]),
  );

  Widget _breakdownSection() => Container(
    margin: const EdgeInsets.fromLTRB(12, 12, 12, 0),
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16),
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, 3))]),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Row(children: [
        Icon(Icons.receipt_long_outlined, color: _gold, size: 16),
        SizedBox(width: 6),
        Text('Earnings Breakdown', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
      ]),
      const SizedBox(height: 4),
      Container(width: 36, height: 3, decoration: BoxDecoration(borderRadius: BorderRadius.circular(2), gradient: _goldGrad)),
      const SizedBox(height: 14),
      if (_earnings.isEmpty)
        const Center(child: Padding(
          padding: EdgeInsets.symmetric(vertical: 16),
          child: Text('No earnings yet', style: TextStyle(color: _textLight, fontSize: 13)),
        ))
      else
        ..._earnings.map((d) {
          final fee = (d['shipping_fee'] as num?)?.toDouble() ?? 0;
          final dateStr = d['date'] != null
              ? DateTime.tryParse(d['date'] as String)?.toLocal().toString().split(' ')[0] ?? ''
              : '';
          return Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Row(children: [
              Container(padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(6), border: Border.all(color: _border)),
                child: Text('#${d['id']}', style: const TextStyle(color: _textLight, fontSize: 10, fontWeight: FontWeight.w700))),
              const SizedBox(width: 8),
              Expanded(child: Text(d['name'] as String? ?? '',
                style: const TextStyle(color: _accent, fontSize: 12), maxLines: 1, overflow: TextOverflow.ellipsis)),
              Text(dateStr, style: const TextStyle(color: _textLight, fontSize: 10)),
              const SizedBox(width: 10),
              Text(fee == 0 ? 'Free' : '₱${fee.toStringAsFixed(0)}',
                style: TextStyle(color: fee == 0 ? Colors.teal : Colors.green,
                  fontWeight: FontWeight.w800, fontSize: 13)),
            ]),
          );
        }),
      const Divider(height: 16),
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        const Text('Total', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 14)),
        ShaderMask(shaderCallback: (b) => _goldGrad.createShader(b),
          child: Text('₱${_total.toStringAsFixed(2)}',
            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 16))),
      ]),
    ]),
  );

}
