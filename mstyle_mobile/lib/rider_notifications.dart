import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'supabase_client.dart';

const Color _primary   = Color(0xFF1a1a1a);
const Color _accent    = Color(0xFF2c3e50);
const Color _gold      = Color(0xFFd4af37);
const Color _goldLight = Color(0xFFF4D03F);
const Color _textLight = Color(0xFF6c757d);
const Color _bg        = Color(0xFFF8F9FA);
const Color _border    = Color(0xFFE9ECEF);

const _goldGrad = LinearGradient(
  begin: Alignment.topLeft, end: Alignment.bottomRight,
  colors: [_gold, _goldLight],
);

class RiderNotificationsPage extends StatefulWidget {
  final String riderEmail;
  const RiderNotificationsPage({super.key, required this.riderEmail});
  @override
  State<RiderNotificationsPage> createState() => _RiderNotificationsPageState();
}

class _RiderNotificationsPageState extends State<RiderNotificationsPage> {
  String _filter = 'all';
  bool _loading = true;
  List<Map<String, dynamic>> _notifs = [];

  RealtimeChannel? _notifsChannel;

  @override
  void initState() {
    super.initState();
    _load();
    _subscribeRealtime();
  }

  @override
  void dispose() {
    _notifsChannel?.unsubscribe();
    super.dispose();
  }

  void _subscribeRealtime() {
    _notifsChannel = supabase
        .channel('rider_notifications_${widget.riderEmail}')
        .onPostgresChanges(
          event: PostgresChangeEvent.insert,
          schema: 'public',
          table: 'rider_notifications',
          filter: PostgresChangeFilter(
            type: PostgresChangeFilterType.eq,
            column: 'rider_email',
            value: widget.riderEmail,
          ),
          callback: (payload) {
            final newRow = payload.newRecord;
            if (mounted && newRow.isNotEmpty) {
              setState(() => _notifs.insert(0, Map<String, dynamic>.from(newRow)));
            }
          },
        )
        .subscribe();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final data = await supabase
          .from('rider_notifications')
          .select()
          .eq('rider_email', widget.riderEmail)
          .order('created_at', ascending: false)
          .limit(50);
      if (mounted) setState(() { _notifs = List<Map<String, dynamic>>.from(data); _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<Map<String, dynamic>> get _filtered {
    if (_filter == 'all') return _notifs;
    if (_filter == 'unread') return _notifs.where((n) => n['is_read'] == false).toList();
    return _notifs;
  }

  int get _unreadCount => _notifs.where((n) => n['is_read'] == false).length;

  Future<void> _markAllRead() async {
    try {
      await supabase
          .from('rider_notifications')
          .update({'is_read': true})
          .eq('rider_email', widget.riderEmail)
          .eq('is_read', false);
      await _load();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: const Text('All notifications marked as read'),
        backgroundColor: _primary, behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ));
    } catch (_) {}
  }

  Future<void> _markRead(Map<String, dynamic> n) async {
    if (n['is_read'] == true) return;
    try {
      await supabase.from('rider_notifications').update({'is_read': true}).eq('id', n['id']);
      setState(() => n['is_read'] = true);
    } catch (_) {}
  }

  Future<void> _delete(Map<String, dynamic> n) async {
    try {
      await supabase.from('rider_notifications').delete().eq('id', n['id']);
      setState(() => _notifs.remove(n));
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: const Text('Notification removed'),
        backgroundColor: _primary, behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ));
    } catch (_) {}
  }

  String _timeAgo(String? createdAt) {
    if (createdAt == null) return '';
    final date = DateTime.tryParse(createdAt);
    if (date == null) return '';
    final diff = DateTime.now().difference(date);
    if (diff.inMinutes < 1) return 'Just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    return '${diff.inDays}d ago';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      body: _loading
        ? const Center(child: CircularProgressIndicator(color: _gold))
        : CustomScrollView(slivers: [
            _appBar(),
            SliverToBoxAdapter(child: _filterRow()),
            if (_filtered.isEmpty)
              SliverFillRemaining(child: _emptyState())
            else
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(12, 0, 12, 32),
                sliver: SliverList(delegate: SliverChildBuilderDelegate(
                  (_, i) => _notifCard(_filtered[i]),
                  childCount: _filtered.length,
                )),
              ),
          ]),
    );
  }

  SliverAppBar _appBar() => SliverAppBar(
    pinned: true,
    backgroundColor: _primary,
    elevation: 6,
    leading: IconButton(
      icon: const Icon(Icons.arrow_back, color: Colors.white),
      onPressed: () => Navigator.pop(context),
    ),
    title: const Text('Notifications',
      style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w700)),
    actions: [
      if (_unreadCount > 0)
        TextButton(
          onPressed: _markAllRead,
          child: const Text('Mark all read',
            style: TextStyle(color: _gold, fontSize: 12, fontWeight: FontWeight.w600)),
        ),
    ],
  );

  Widget _filterRow() => Container(
    color: Colors.white,
    padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
    child: SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(children: [
        _chip('all', 'All'),
        const SizedBox(width: 8),
        _chip('unread', 'Unread${_unreadCount > 0 ? ' ($_unreadCount)' : ''}'),
      ]),
    ),
  );

  Widget _chip(String value, String label) {
    final active = _filter == value;
    return GestureDetector(
      onTap: () => setState(() => _filter = value),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          gradient: active ? _goldGrad : null,
          color: active ? null : _bg,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: active ? _gold : _border),
        ),
        child: Text(label, style: TextStyle(
          color: active ? _primary : _textLight,
          fontSize: 12, fontWeight: active ? FontWeight.w700 : FontWeight.w500)),
      ),
    );
  }

  Widget _notifCard(Map<String, dynamic> n) {
    final isRead = n['is_read'] == true;
    final time   = _timeAgo(n['created_at'] as String?);
    final msg    = n['message'] as String? ?? '';

    return Dismissible(
      key: Key('${n['id']}'),
      direction: DismissDirection.endToStart,
      background: Container(
        margin: const EdgeInsets.only(bottom: 10),
        decoration: BoxDecoration(color: Colors.red.shade400, borderRadius: BorderRadius.circular(14)),
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 20),
        child: const Icon(Icons.delete_outline, color: Colors.white, size: 22),
      ),
      onDismissed: (_) => _delete(n),
      child: GestureDetector(
        onTap: () => _markRead(n),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: isRead ? Colors.white : Colors.blue.withOpacity(0.04),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: isRead ? _border : Colors.blue.withOpacity(0.25),
              width: isRead ? 1 : 1.5),
            boxShadow: [BoxShadow(
              color: Colors.black.withOpacity(isRead ? 0.04 : 0.07),
              blurRadius: 10, offset: const Offset(0, 2))],
          ),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              width: 44, height: 44,
              decoration: BoxDecoration(
                color: Colors.blue.withOpacity(0.12), shape: BoxShape.circle,
                border: Border.all(color: Colors.blue.withOpacity(0.2))),
              child: const Icon(Icons.local_shipping_outlined, color: Colors.blue, size: 20),
            ),
            const SizedBox(width: 12),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: Colors.blue.withOpacity(0.1), borderRadius: BorderRadius.circular(6)),
                  child: const Text('Delivery', style: TextStyle(color: Colors.blue, fontSize: 9, fontWeight: FontWeight.w700)),
                ),
                const Spacer(),
                Text(time, style: const TextStyle(color: _textLight, fontSize: 10)),
                if (!isRead) ...[
                  const SizedBox(width: 6),
                  Container(width: 8, height: 8,
                    decoration: const BoxDecoration(color: Colors.blue, shape: BoxShape.circle)),
                ],
              ]),
              const SizedBox(height: 6),
              Text(msg, style: TextStyle(
                color: _accent,
                fontWeight: isRead ? FontWeight.w600 : FontWeight.w800,
                fontSize: 13)),
            ])),
          ]),
        ),
      ),
    );
  }

  Widget _emptyState() => Center(
    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
      Container(
        width: 80, height: 80,
        decoration: BoxDecoration(color: _bg, shape: BoxShape.circle, border: Border.all(color: _border, width: 2)),
        child: const Icon(Icons.notifications_off_outlined, size: 36, color: _border),
      ),
      const SizedBox(height: 16),
      const Text('No Notifications', style: TextStyle(color: _accent, fontSize: 18, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      Text(
        _filter == 'unread' ? 'No unread notifications.' : 'Nothing here yet.',
        style: const TextStyle(color: _textLight, fontSize: 13)),
    ]),
  );
}
