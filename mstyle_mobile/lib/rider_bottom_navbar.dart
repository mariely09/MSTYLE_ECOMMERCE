import 'package:flutter/material.dart';
import 'rider_dashboard.dart';
import 'rider_active_deliveries.dart';
import 'rider_history_deliveries.dart';
import 'rider_earnings.dart';
import 'rider_messages.dart';

// ─── Theme constants (shared) ─────────────────────────────────────────────────
const Color _primary = Color(0xFF1a1a1a);
const Color _gold    = Color(0xFFd4af37);

// ─── RiderBottomNavBar ────────────────────────────────────────────────────────
/// A reusable bottom navigation bar for all rider pages.
/// Usage:
///   Scaffold(
///     bottomNavigationBar: RiderBottomNavBar(
///       riderEmail: widget.riderEmail,
///       currentPage: RiderPage.dashboard,
///     ),
///   )
enum RiderPage { dashboard, active, history, earnings, messages }

class RiderBottomNavBar extends StatelessWidget {
  final String riderEmail;
  final RiderPage currentPage;

  const RiderBottomNavBar({
    super.key,
    required this.riderEmail,
    required this.currentPage,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: _primary,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.25),
            blurRadius: 20,
            offset: const Offset(0, -4),
          ),
        ],
      ),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _navItem(
                context,
                Icons.speed,
                'Dashboard',
                currentPage == RiderPage.dashboard,
                () => _navigateTo(context, RiderPage.dashboard),
              ),
              _navItem(
                context,
                Icons.local_shipping_outlined,
                'Active',
                currentPage == RiderPage.active,
                () => _navigateTo(context, RiderPage.active),
              ),
              _navItem(
                context,
                Icons.history_outlined,
                'History',
                currentPage == RiderPage.history,
                () => _navigateTo(context, RiderPage.history),
              ),
              _navItem(
                context,
                Icons.currency_exchange,
                'Earnings',
                currentPage == RiderPage.earnings,
                () => _navigateTo(context, RiderPage.earnings),
              ),
              _navItem(
                context,
                Icons.chat_bubble_outline,
                'Messages',
                currentPage == RiderPage.messages,
                () => _navigateTo(context, RiderPage.messages),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _navItem(
    BuildContext context,
    IconData icon,
    String label,
    bool active,
    VoidCallback onTap,
  ) {
    return GestureDetector(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              icon,
              color: active ? _gold : Colors.white54,
              size: 20,
            ),
            const SizedBox(height: 2),
            Text(
              label,
              style: TextStyle(
                color: active ? _gold : Colors.white54,
                fontSize: 9,
                fontWeight: active ? FontWeight.w700 : FontWeight.w400,
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _navigateTo(BuildContext context, RiderPage page) {
    if (page == currentPage) return;

    Widget destination;
    switch (page) {
      case RiderPage.dashboard:
        destination = RiderDashboardPage(riderEmail: riderEmail);
        break;
      case RiderPage.active:
        destination = RiderActiveDeliveriesPage(riderEmail: riderEmail);
        break;
      case RiderPage.history:
        destination = RiderHistoryDeliveriesPage(riderEmail: riderEmail);
        break;
      case RiderPage.earnings:
        destination = RiderEarningsPage(riderEmail: riderEmail);
        break;
      case RiderPage.messages:
        destination = RiderMessagesPage(riderEmail: riderEmail);
        break;
    }

    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => destination),
    );
  }
}
