import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'product_image_carousel.dart' show kFlaskBaseUrl;

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

class RiderMessagesPage extends StatefulWidget {
  final String riderEmail;
  const RiderMessagesPage({super.key, required this.riderEmail});
  @override
  State<RiderMessagesPage> createState() => _RiderMessagesPageState();
}

class _RiderMessagesPageState extends State<RiderMessagesPage> {
  bool _loading = true;
  List<Map<String, dynamic>> _conversations = [];

  @override
  void initState() {
    super.initState();
    _fetchConversations();
  }

  Future<void> _fetchConversations() async {
    setState(() => _loading = true);
    try {
      final uri = Uri.parse(
          '$kFlaskBaseUrl/api/mobile/rider/messages?rider_email=${Uri.encodeComponent(widget.riderEmail)}');
      final res = await http.get(uri).timeout(const Duration(seconds: 15));
      final body = jsonDecode(res.body) as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          _conversations = body['success'] == true
              ? List<Map<String, dynamic>>.from(body['conversations'] as List)
              : [];
          _loading = false;
        });
      }
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
          title: const Text('Messages',
            style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w700)),
        ),
        if (_loading)
          const SliverFillRemaining(
              child: Center(child: CircularProgressIndicator(color: _gold)))
        else if (_conversations.isEmpty)
          SliverFillRemaining(child: _emptyState())
        else
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 80),
            sliver: SliverList(
              delegate: SliverChildBuilderDelegate(
                (_, i) => _conversationTile(_conversations[i]),
                childCount: _conversations.length,
              ),
            ),
          ),
      ]),
    );
  }

  Widget _conversationTile(Map<String, dynamic> c) {
    final unread = (c['unread_count'] as int? ?? 0) > 0;
    final type   = c['conversation_type'] as String? ?? 'buyer';
    final isSeller = type == 'seller';
    final color  = isSeller ? Colors.indigo : Colors.blue;
    final icon   = isSeller ? Icons.store_outlined : Icons.person_outline;

    return GestureDetector(
      onTap: () {
        // TODO: navigate to chat detail page
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Chat with ${c['contact_name']} — Order #${c['order_id']}'),
          behavior: SnackBarBehavior.floating,
          backgroundColor: _accent,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        ));
      },
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(14),
          border: unread ? Border.all(color: _gold.withOpacity(0.4), width: 1.5) : null,
          boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 8, offset: const Offset(0, 2))],
        ),
        child: Row(children: [
          // Avatar
          Container(
            width: 46, height: 46,
            decoration: BoxDecoration(
              color: color.withOpacity(0.1),
              shape: BoxShape.circle,
              border: Border.all(color: color.withOpacity(0.3)),
            ),
            child: Icon(icon, color: color, size: 22),
          ),
          const SizedBox(width: 12),
          // Content
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(child: Text(c['contact_name'] as String? ?? '',
                style: TextStyle(
                  color: _accent, fontWeight: unread ? FontWeight.w800 : FontWeight.w600,
                  fontSize: 13),
                maxLines: 1, overflow: TextOverflow.ellipsis)),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: color.withOpacity(0.1), borderRadius: BorderRadius.circular(6)),
                child: Text(isSeller ? 'Seller' : 'Buyer',
                  style: TextStyle(color: color, fontSize: 9, fontWeight: FontWeight.w700)),
              ),
            ]),
            const SizedBox(height: 3),
            Text('Order #${c['order_id']}',
              style: const TextStyle(color: _textLight, fontSize: 10)),
            const SizedBox(height: 4),
            Text(c['last_message'] as String? ?? 'No messages yet',
              style: TextStyle(
                color: unread ? _accent : _textLight,
                fontSize: 12,
                fontWeight: unread ? FontWeight.w600 : FontWeight.w400),
              maxLines: 1, overflow: TextOverflow.ellipsis),
          ])),
          const SizedBox(width: 8),
          // Unread badge
          if (unread)
            Container(
              width: 20, height: 20,
              decoration: BoxDecoration(
                gradient: _goldGrad, shape: BoxShape.circle),
              child: Center(
                child: Text('${c['unread_count']}',
                  style: const TextStyle(color: _primary, fontSize: 10, fontWeight: FontWeight.w900)),
              ),
            ),
        ]),
      ),
    );
  }

  Widget _emptyState() => Center(
    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
      const Icon(Icons.chat_bubble_outline, size: 72, color: _border),
      const SizedBox(height: 16),
      const Text('No Messages Yet',
          style: TextStyle(color: _accent, fontSize: 18, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      const Text('Your conversations will appear here.',
          style: TextStyle(color: _textLight, fontSize: 13)),
    ]),
  );
}
