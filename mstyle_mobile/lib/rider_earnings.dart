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

class _RiderEarningsPageState extends State<RiderEarningsPage>
    with SingleTickerProviderStateMixin {
  late final TabController _tabCtrl;
  bool _loading = true;
  List<Map<String, dynamic>> _earnings = [];
  List<Map<String, dynamic>> _withdrawals = [];

  @override
  void initState() {
    super.initState();
    _tabCtrl = TabController(length: 2, vsync: this);
    _fetchAll();
  }

  @override
  void dispose() {
    _tabCtrl.dispose();
    super.dispose();
  }

  Future<void> _fetchAll() async {
    setState(() => _loading = true);
    await Future.wait([_fetchEarnings(), _fetchWithdrawals()]);
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _fetchEarnings() async {
    try {
      final data = await supabase
          .from('orders')
          .select('id, name, shipping_fee, date')
          .eq('rider_email', widget.riderEmail)
          .eq('status', 'Completed')
          .order('date', ascending: false);
      if (mounted) _earnings = List<Map<String, dynamic>>.from(data);
    } catch (_) {}
  }

  Future<void> _fetchWithdrawals() async {
    try {
      final data = await supabase
          .from('rider_withdrawals')
          .select()
          .eq('rider_email', widget.riderEmail)
          .order('requested_at', ascending: false);
      if (mounted) _withdrawals = List<Map<String, dynamic>>.from(data);
    } catch (_) {}
  }

  // ── Computed totals ──────────────────────────────────────────────────────
  double get _totalEarned =>
      _earnings.fold(0.0, (s, d) => s + ((d['shipping_fee'] as num?)?.toDouble() ?? 0));

  double get _totalWithdrawn => _withdrawals
      .where((w) => w['status'] == 'approved')
      .fold(0.0, (s, w) => s + ((w['amount'] as num?)?.toDouble() ?? 0));

  double get _pendingWithdrawal => _withdrawals
      .where((w) => w['status'] == 'pending')
      .fold(0.0, (s, w) => s + ((w['amount'] as num?)?.toDouble() ?? 0));

  double get _availableBalance =>
      _totalEarned - _totalWithdrawn - _pendingWithdrawal;

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

  // ── Withdraw bottom sheet ────────────────────────────────────────────────
  void _showWithdrawSheet() {
    final amountCtrl  = TextEditingController();
    final nameCtrl    = TextEditingController();
    final numberCtrl  = TextEditingController();
    String method     = 'GCash';
    final formKey     = GlobalKey<FormState>();
    bool submitting   = false;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheet) => Padding(
          padding: EdgeInsets.only(bottom: MediaQuery.of(ctx).viewInsets.bottom),
          child: Container(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 32),
            decoration: const BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
            ),
            child: Form(
              key: formKey,
              child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                // Handle bar
                Center(child: Container(width: 40, height: 4,
                  decoration: BoxDecoration(color: _border, borderRadius: BorderRadius.circular(2)))),
                const SizedBox(height: 16),

                // Title
                Row(children: [
                  Container(width: 36, height: 36,
                    decoration: BoxDecoration(gradient: _goldGrad, borderRadius: BorderRadius.circular(10)),
                    child: const Icon(Icons.account_balance_wallet_outlined, color: _primary, size: 18)),
                  const SizedBox(width: 10),
                  const Text('Withdraw Earnings',
                    style: TextStyle(color: _accent, fontSize: 16, fontWeight: FontWeight.w800)),
                ]),
                const SizedBox(height: 4),
                Container(width: 36, height: 3,
                  decoration: BoxDecoration(borderRadius: BorderRadius.circular(2), gradient: _goldGrad)),
                const SizedBox(height: 6),

                // Available balance chip
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: _gold.withOpacity(0.08),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: _gold.withOpacity(0.3)),
                  ),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    const Icon(Icons.wallet, color: _gold, size: 14),
                    const SizedBox(width: 6),
                    Text('Available: ₱${_availableBalance.toStringAsFixed(2)}',
                      style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
                  ]),
                ),
                const SizedBox(height: 16),

                // Amount
                _sheetField(
                  ctrl: amountCtrl,
                  label: 'Amount to Withdraw (₱)',
                  icon: Icons.currency_exchange,
                  type: TextInputType.number,
                  validator: (v) {
                    final amt = double.tryParse(v ?? '');
                    if (amt == null || amt <= 0) return 'Enter a valid amount';
                    if (amt > _availableBalance) return 'Exceeds available balance';
                    if (amt < 50) return 'Minimum withdrawal is ₱50';
                    return null;
                  },
                ),
                const SizedBox(height: 12),

                // Method selector
                const Text('Payment Method',
                  style: TextStyle(color: _accent, fontWeight: FontWeight.w600, fontSize: 13)),
                const SizedBox(height: 8),
                Row(children: ['GCash', 'Maya', 'Bank Transfer'].map((m) {
                  final selected = method == m;
                  return Expanded(child: GestureDetector(
                    onTap: () => setSheet(() => method = m),
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 180),
                      margin: const EdgeInsets.only(right: 8),
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      decoration: BoxDecoration(
                        gradient: selected ? _goldGrad : null,
                        color: selected ? null : _bg,
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: selected ? _gold : _border),
                      ),
                      child: Center(child: Text(m,
                        style: TextStyle(
                          color: selected ? _primary : _textLight,
                          fontSize: 11, fontWeight: selected ? FontWeight.w800 : FontWeight.w500))),
                    ),
                  ));
                }).toList()),
                const SizedBox(height: 12),

                // Account name
                _sheetField(
                  ctrl: nameCtrl,
                  label: 'Account Name',
                  icon: Icons.person_outline,
                  validator: (v) => (v == null || v.trim().isEmpty) ? 'Enter account name' : null,
                ),
                const SizedBox(height: 12),

                // Account number
                _sheetField(
                  ctrl: numberCtrl,
                  label: method == 'Bank Transfer' ? 'Account Number' : '$method Number',
                  icon: Icons.numbers,
                  type: TextInputType.number,
                  validator: (v) => (v == null || v.trim().isEmpty) ? 'Enter account number' : null,
                ),
                const SizedBox(height: 20),

                // Submit button
                GestureDetector(
                  onTap: submitting ? null : () async {
                    if (!formKey.currentState!.validate()) return;
                    setSheet(() => submitting = true);
                    try {
                      await supabase.from('rider_withdrawals').insert({
                        'rider_email':    widget.riderEmail,
                        'amount':         double.parse(amountCtrl.text.trim()),
                        'method':         method,
                        'account_name':   nameCtrl.text.trim(),
                        'account_number': numberCtrl.text.trim(),
                        'status':         'pending',
                      });
                      if (!mounted) return;
                      Navigator.pop(ctx);
                      await _fetchWithdrawals();
                      setState(() {});
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                        content: const Text('Withdrawal request submitted! We\'ll process it within 1–2 business days.'),
                        backgroundColor: _primary,
                        behavior: SnackBarBehavior.floating,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      ));
                    } catch (e) {
                      setSheet(() => submitting = false);
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                        content: Text('Error: $e'),
                        backgroundColor: Colors.red.shade600,
                        behavior: SnackBarBehavior.floating,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      ));
                    }
                  },
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    width: double.infinity,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    decoration: BoxDecoration(
                      gradient: submitting ? null : _premiumGrad,
                      color: submitting ? _border : null,
                      borderRadius: BorderRadius.circular(14),
                      boxShadow: submitting ? [] : [
                        BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 10, offset: const Offset(0, 4))
                      ],
                    ),
                    child: Center(child: submitting
                      ? const SizedBox(width: 20, height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Text('Submit Withdrawal Request',
                          style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 14))),
                  ),
                ),
              ]),
            ),
          ),
        ),
      ),
    );
  }

  Widget _sheetField({
    required TextEditingController ctrl,
    required String label,
    required IconData icon,
    TextInputType type = TextInputType.text,
    String? Function(String?)? validator,
  }) => TextFormField(
    controller: ctrl,
    keyboardType: type,
    validator: validator,
    style: const TextStyle(color: _accent, fontSize: 14),
    decoration: InputDecoration(
      labelText: label,
      labelStyle: const TextStyle(color: _textLight, fontSize: 13),
      prefixIcon: Icon(icon, color: _gold, size: 18),
      filled: true, fillColor: _bg,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: _border)),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: _gold, width: 2)),
      errorBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: Colors.red)),
      focusedErrorBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: Colors.red, width: 2)),
    ),
  );

  // ── Build ────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      body: _loading
        ? const Center(child: CircularProgressIndicator(color: _gold))
        : NestedScrollView(
            headerSliverBuilder: (_, __) => [
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
                bottom: TabBar(
                  controller: _tabCtrl,
                  indicatorColor: _gold,
                  indicatorWeight: 3,
                  labelColor: _gold,
                  unselectedLabelColor: Colors.white54,
                  labelStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
                  tabs: const [
                    Tab(text: 'Overview'),
                    Tab(text: 'Withdrawals'),
                  ],
                ),
              ),
            ],
            body: TabBarView(
              controller: _tabCtrl,
              children: [
                _overviewTab(),
                _withdrawalsTab(),
              ],
            ),
          ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _availableBalance >= 50 ? _showWithdrawSheet : () {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Minimum withdrawal is ₱50'),
            behavior: SnackBarBehavior.floating,
          ));
        },
        backgroundColor: _availableBalance >= 50 ? _gold : Colors.grey.shade400,
        foregroundColor: _primary,
        icon: const Icon(Icons.account_balance_wallet_outlined),
        label: const Text('Withdraw', style: TextStyle(fontWeight: FontWeight.w800)),
      ),
    );
  }

  // ── Overview Tab ─────────────────────────────────────────────────────────
  Widget _overviewTab() => RefreshIndicator(
    color: _gold,
    onRefresh: _fetchAll,
    child: ListView(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 100),
      children: [
        _balanceCard(),
        const SizedBox(height: 12),
        _periodCards(),
        const SizedBox(height: 12),
        _earningsBreakdown(),
      ],
    ),
  );

  Widget _balanceCard() => Container(
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(16),
      boxShadow: [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 12, offset: const Offset(0, 4))]),
    child: Column(children: [
      // Total earned
      const Text('Total Earned', style: TextStyle(color: Colors.white70, fontSize: 12)),
      const SizedBox(height: 4),
      ShaderMask(shaderCallback: (b) => _goldGrad.createShader(b),
        child: Text('₱${_totalEarned.toStringAsFixed(2)}',
          style: const TextStyle(color: Colors.white, fontSize: 34, fontWeight: FontWeight.w900))),
      Text('${_earnings.length} completed deliveries',
        style: TextStyle(color: Colors.white.withOpacity(0.55), fontSize: 11)),
      const SizedBox(height: 16),
      // Balance breakdown row
      Row(children: [
        Expanded(child: _balanceChip('Available', _availableBalance, Colors.green.shade400)),
        const SizedBox(width: 8),
        Expanded(child: _balanceChip('Pending', _pendingWithdrawal, Colors.orange.shade400)),
        const SizedBox(width: 8),
        Expanded(child: _balanceChip('Withdrawn', _totalWithdrawn, Colors.blue.shade300)),
      ]),
    ]),
  );

  Widget _balanceChip(String label, double amount, Color color) => Container(
    padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
    decoration: BoxDecoration(
      color: Colors.white.withOpacity(0.1),
      borderRadius: BorderRadius.circular(10),
      border: Border.all(color: Colors.white.withOpacity(0.15)),
    ),
    child: Column(children: [
      Text('₱${amount.toStringAsFixed(0)}',
        style: TextStyle(color: color, fontWeight: FontWeight.w900, fontSize: 14)),
      const SizedBox(height: 2),
      Text(label, style: const TextStyle(color: Colors.white60, fontSize: 9)),
    ]),
  );

  Widget _periodCards() => Row(children: [
    Expanded(child: _periodCard('₱${_today.toStringAsFixed(0)}', 'Today', Icons.today_outlined, Colors.blue)),
    const SizedBox(width: 10),
    Expanded(child: _periodCard('₱${_week.toStringAsFixed(0)}', 'This Week', Icons.date_range_outlined, Colors.purple)),
    const SizedBox(width: 10),
    Expanded(child: _periodCard('₱${_month.toStringAsFixed(0)}', 'This Month', Icons.calendar_month_outlined, Colors.teal)),
  ]);

  Widget _periodCard(String value, String label, IconData icon, Color color) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12),
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 8, offset: const Offset(0, 2))]),
    child: Column(children: [
      Icon(icon, color: color, size: 20),
      const SizedBox(height: 6),
      Text(value, style: const TextStyle(color: _accent, fontWeight: FontWeight.w900, fontSize: 15)),
      Text(label, style: const TextStyle(color: _textLight, fontSize: 9)),
    ]),
  );

  Widget _earningsBreakdown() => Container(
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
          child: Text('₱${_totalEarned.toStringAsFixed(2)}',
            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 16))),
      ]),
    ]),
  );

  // ── Withdrawals Tab ───────────────────────────────────────────────────────
  Widget _withdrawalsTab() => RefreshIndicator(
    color: _gold,
    onRefresh: _fetchAll,
    child: _withdrawals.isEmpty
      ? ListView(children: const [
          SizedBox(height: 80),
          Center(child: Column(children: [
            Icon(Icons.account_balance_wallet_outlined, size: 64, color: _border),
            SizedBox(height: 12),
            Text('No withdrawal requests yet',
              style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 15)),
            SizedBox(height: 6),
            Text('Tap "Withdraw" to request a payout.',
              style: TextStyle(color: _textLight, fontSize: 12)),
          ])),
        ])
      : ListView.separated(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 100),
          itemCount: _withdrawals.length,
          separatorBuilder: (_, __) => const SizedBox(height: 10),
          itemBuilder: (_, i) => _withdrawalCard(_withdrawals[i]),
        ),
  );

  Widget _withdrawalCard(Map<String, dynamic> w) {
    final status  = w['status'] as String? ?? 'pending';
    final amount  = (w['amount'] as num?)?.toDouble() ?? 0;
    final method  = w['method'] as String? ?? '';
    final name    = w['account_name'] as String? ?? '';
    final number  = w['account_number'] as String? ?? '';
    final reqDate = w['requested_at'] != null
        ? DateTime.tryParse(w['requested_at'] as String)?.toLocal().toString().split(' ')[0] ?? ''
        : '';

    Color statusColor;
    IconData statusIcon;
    String statusLabel;
    switch (status) {
      case 'approved':
        statusColor = Colors.green; statusIcon = Icons.check_circle_outline; statusLabel = 'Approved'; break;
      case 'rejected':
        statusColor = Colors.red; statusIcon = Icons.cancel_outlined; statusLabel = 'Rejected'; break;
      default:
        statusColor = Colors.orange; statusIcon = Icons.hourglass_empty_outlined; statusLabel = 'Pending';
    }

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: statusColor.withOpacity(0.25)),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 8, offset: const Offset(0, 2))],
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          // Amount
          ShaderMask(shaderCallback: (b) => _goldGrad.createShader(b),
            child: Text('₱${amount.toStringAsFixed(2)}',
              style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 20))),
          const Spacer(),
          // Status badge
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              color: statusColor.withOpacity(0.1),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: statusColor.withOpacity(0.3)),
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(statusIcon, size: 12, color: statusColor),
              const SizedBox(width: 4),
              Text(statusLabel, style: TextStyle(color: statusColor, fontSize: 11, fontWeight: FontWeight.w700)),
            ]),
          ),
        ]),
        const SizedBox(height: 8),
        // Method + account
        Row(children: [
          _infoChip(Icons.payment_outlined, method),
          const SizedBox(width: 8),
          _infoChip(Icons.person_outline, name),
          const SizedBox(width: 8),
          _infoChip(Icons.numbers, number),
        ]),
        const SizedBox(height: 6),
        Row(children: [
          const Icon(Icons.calendar_today_outlined, size: 11, color: _textLight),
          const SizedBox(width: 4),
          Text('Requested: $reqDate', style: const TextStyle(color: _textLight, fontSize: 11)),
          if (w['note'] != null && (w['note'] as String).isNotEmpty) ...[
            const SizedBox(width: 12),
            Expanded(child: Text('Note: ${w['note']}',
              style: const TextStyle(color: _textLight, fontSize: 11),
              maxLines: 1, overflow: TextOverflow.ellipsis)),
          ],
        ]),
      ]),
    );
  }

  Widget _infoChip(IconData icon, String label) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
    decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(6), border: Border.all(color: _border)),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 10, color: _textLight),
      const SizedBox(width: 4),
      Text(label, style: const TextStyle(color: _textLight, fontSize: 10, fontWeight: FontWeight.w600),
        maxLines: 1, overflow: TextOverflow.ellipsis),
    ]),
  );
}
