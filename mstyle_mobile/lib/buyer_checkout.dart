import 'package:flutter/material.dart';
import 'login.dart';
import 'buyer_homepage.dart';
import 'buyer_cart.dart';
import 'buyer_orders.dart';
import 'buyer_service.dart';

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

class CheckoutItem {
  final String id;
  final String name;
  final double price;          // effective price (sale price if promo applies)
  final double? originalPrice; // original price before discount (null if no promo)
  final String? promoType;     // 'percentage', 'fixed', 'buy_one_get_one', 'free_shipping'
  final double? promoDiscount;
  final int quantity;
  final String? color;
  final String? size;
  final bool freeShipping;
  final String? image;
  final int? productId;

  const CheckoutItem({
    required this.id,
    required this.name,
    required this.price,
    this.originalPrice,
    this.promoType,
    this.promoDiscount,
    required this.quantity,
    this.color,
    this.size,
    this.freeShipping = false,
    this.image,
    this.productId,
  });

  double get subtotal => price * quantity;
  double get shippingFee => freeShipping ? 0 : 50;
  bool get hasPromo => promoType != null && promoType!.isNotEmpty;

  String get promoBadgeLabel {
    if (!hasPromo) return '';
    final d = promoDiscount?.toInt() ?? 0;
    switch (promoType) {
      case 'percentage':      return '$d% OFF';
      case 'fixed':           return '₱$d OFF';
      case 'buy_one_get_one': return 'BOGO';
      case 'free_shipping':   return 'FREE SHIP';
      default:                return 'SALE';
    }
  }
}

class BuyerCheckoutPage extends StatefulWidget {
  final String userEmail;
  final List<CheckoutItem> items;

  const BuyerCheckoutPage({
    super.key,
    required this.userEmail,
    required this.items,
  });

  @override
  State<BuyerCheckoutPage> createState() => _BuyerCheckoutPageState();
}

class _BuyerCheckoutPageState extends State<BuyerCheckoutPage> {
  String _paymentMethod = 'cod';
  String _address = '';
  bool _addressLoading = true;
  bool _placing = false;

  // Structured address fields
  String _houseStreet = '';
  String _barangay    = '';
  String _city        = '';
  String _province    = '';
  String _region      = '';
  String _zipCode     = '';

  double get _subtotal => widget.items.fold(0, (s, i) => s + i.subtotal);
  double get _shippingFee => widget.items.fold(0, (s, i) => s + i.shippingFee);
  double get _total => _subtotal + _shippingFee;

  @override
  void initState() {
    super.initState();
    _loadAddress();
  }

  Future<void> _loadAddress() async {
    final fields = await BuyerService.getUserAddressFields(widget.userEmail);
    if (mounted) {
      setState(() {
        _houseStreet = fields['house_street'] ?? '';
        _barangay    = fields['barangay']     ?? '';
        _city        = fields['city']         ?? '';
        _province    = fields['province']     ?? '';
        _region      = fields['region']       ?? '';
        _zipCode     = fields['zip_code']     ?? '';
        _address     = _buildAddress();
        _addressLoading = false;
      });
    }
  }

  String _buildAddress() {
    return [_houseStreet, _barangay, _city, _province, _region, _zipCode]
        .where((p) => p.trim().isNotEmpty)
        .join(', ');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      appBar: _appBar(),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _orderSummaryCard(),
          const SizedBox(height: 16),
          _addressCard(),
          const SizedBox(height: 16),
          _paymentCard(),
          const SizedBox(height: 24),
          _actionButtons(),
          const SizedBox(height: 32),
        ]),
      ),
    );
  }

  // ─── App Bar ──────────────────────────────────────────────────────────────
  PreferredSizeWidget _appBar() => AppBar(
    backgroundColor: _primary,
    elevation: 6,
    titleSpacing: 16,
    leading: IconButton(
      icon: const Icon(Icons.arrow_back, color: Colors.white),
      onPressed: () => Navigator.pop(context),
    ),
    title: ShaderMask(
      shaderCallback: (b) => _goldGrad.createShader(b),
      child: const Text('Checkout',
        style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w800, letterSpacing: 0.5)),
    ),
  );

  // ─── Hero Header ──────────────────────────────────────────────────────────
  Widget _heroHeader() => Container(
    width: double.infinity,
    padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 20),
    decoration: BoxDecoration(
      gradient: _premiumGrad,
      borderRadius: BorderRadius.circular(16),
      boxShadow: [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 12, offset: const Offset(0, 4))],
    ),
    child: Row(children: [
      Container(
        width: 52, height: 52,
        decoration: BoxDecoration(
          shape: BoxShape.circle, gradient: _goldGrad,
          boxShadow: [BoxShadow(color: _gold.withOpacity(0.4), blurRadius: 12)],
        ),
        child: const Icon(Icons.shopping_bag_outlined, color: _primary, size: 26),
      ),
      const SizedBox(width: 14),
      const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Checkout', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w800)),
        SizedBox(height: 3),
        Text('Review your order and place it', style: TextStyle(color: Colors.white60, fontSize: 12)),
      ]),
    ]),
  );

  // ─── Order Summary Card ───────────────────────────────────────────────────
  Widget _orderSummaryCard() => _card(
    title: 'Order Summary',
    icon: Icons.receipt_long_outlined,
    child: Column(children: [
      ...widget.items.map((item) => _itemRow(item)),
      const Divider(height: 24),
      _totalRow('Subtotal', '₱${_subtotal.toStringAsFixed(2)}'),
      const SizedBox(height: 6),
      _totalRow('Shipping Fee',
        _shippingFee == 0 ? 'Free' : '₱${_shippingFee.toStringAsFixed(2)}'),
      const Divider(height: 20),
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        const Text('Total Amount', style: TextStyle(color: _accent, fontWeight: FontWeight.w800, fontSize: 16)),
        ShaderMask(
          shaderCallback: (b) => _goldGrad.createShader(b),
          child: Text('₱${_total.toStringAsFixed(2)}',
            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 18)),
        ),
      ]),
    ]),
  );

  Widget _itemRow(CheckoutItem item) => Padding(
    padding: const EdgeInsets.only(bottom: 14),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      // Product image
      Stack(children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: item.image != null && item.image!.isNotEmpty
            ? Image.network(
                item.image!,
                width: 60, height: 60, fit: BoxFit.cover,
                errorBuilder: (_, __, ___) => _imagePlaceholder(),
              )
            : _imagePlaceholder(),
        ),
        // Promo badge on image
        if (item.hasPromo)
          Positioned(
            top: 0, left: 0,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 3),
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  colors: [Color(0xFFE74C3C), Color(0xFFc0392b)],
                  begin: Alignment.topLeft, end: Alignment.bottomRight,
                ),
                borderRadius: BorderRadius.only(
                  topLeft: Radius.circular(10),
                  bottomRight: Radius.circular(7),
                ),
              ),
              child: Text(item.promoBadgeLabel,
                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 8, letterSpacing: 0.4)),
            ),
          ),
      ]),
      const SizedBox(width: 12),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(item.name,
            style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13),
            maxLines: 2, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 4),
          // Price row — show sale + strikethrough original if promo
          if (item.hasPromo && item.originalPrice != null &&
              (item.promoType == 'percentage' || item.promoType == 'fixed'))
            Row(children: [
              Text('₱${item.price.toStringAsFixed(2)}',
                style: const TextStyle(color: Color(0xFFE74C3C), fontWeight: FontWeight.w800, fontSize: 13)),
              const SizedBox(width: 6),
              Text('₱${item.originalPrice!.toStringAsFixed(2)}',
                style: const TextStyle(
                  color: _textLight, fontSize: 11,
                  decoration: TextDecoration.lineThrough,
                  decorationColor: _textLight)),
            ])
          else if (item.freeShipping)
            Row(children: [
              Text('₱${item.price.toStringAsFixed(2)}',
                style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
              const SizedBox(width: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: Colors.green.shade50,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: Colors.green.shade200),
                ),
                child: const Text('Free Shipping', style: TextStyle(color: Colors.green, fontSize: 10, fontWeight: FontWeight.w600)),
              ),
            ])
          else if (item.hasPromo && item.promoType == 'buy_one_get_one')
            Row(children: [
              Text('₱${item.price.toStringAsFixed(2)}',
                style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
              const SizedBox(width: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: Colors.orange.shade50,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: Colors.orange.shade200),
                ),
                child: const Text('BOGO', style: TextStyle(color: Colors.orange, fontSize: 10, fontWeight: FontWeight.w600)),
              ),
            ])
          else
            Text('₱${item.price.toStringAsFixed(2)}',
              style: const TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
          const SizedBox(height: 4),
          // Specs
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(children: [
              if (item.color != null) ...[
                _specChip(Icons.palette_outlined, 'Color: ${item.color}'),
                const SizedBox(width: 6),
              ],
              if (item.size != null) ...[
                _specChip(Icons.straighten_outlined, 'Size: ${item.size}'),
                const SizedBox(width: 6),
              ],
              _specChip(Icons.inventory_2_outlined, 'Qty: ${item.quantity}'),
            ]),
          ),
        ]),
      ),
      Text('₱${item.subtotal.toStringAsFixed(2)}',
        style: const TextStyle(color: _accent, fontWeight: FontWeight.w800, fontSize: 13)),
    ]),
  );

  Widget _imagePlaceholder() => Container(
    width: 60, height: 60,
    decoration: BoxDecoration(
      borderRadius: BorderRadius.circular(10),
      gradient: const LinearGradient(
        begin: Alignment.topLeft, end: Alignment.bottomRight,
        colors: [Color(0xFFECEFF1), Color(0xFFE9ECEF)],
      ),
    ),
    child: const Center(child: Icon(Icons.image_outlined, color: Color(0xFFADB5BD), size: 26)),
  );

  Widget _specChip(IconData icon, String label) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
    decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(6), border: Border.all(color: _border)),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 10, color: _textLight),
      const SizedBox(width: 3),
      Text(label, style: const TextStyle(color: _textLight, fontSize: 10, fontWeight: FontWeight.w500)),
    ]),
  );

  Widget _totalRow(String label, String value) => Row(
    mainAxisAlignment: MainAxisAlignment.spaceBetween,
    children: [
      Text(label, style: const TextStyle(color: _textLight, fontSize: 13)),
      Text(value, style: const TextStyle(color: _accent, fontWeight: FontWeight.w600, fontSize: 13)),
    ],
  );

  // ─── Address Card ─────────────────────────────────────────────────────────
  Widget _addressCard() => _card(
    title: 'Delivery Address',
    icon: Icons.location_on_outlined,
    trailing: GestureDetector(
      onTap: _showAddressModal,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: _gold.withOpacity(0.4)),
          color: _gold.withOpacity(0.08),
        ),
        child: const Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.edit_outlined, size: 13, color: _gold),
          SizedBox(width: 4),
          Text('Change', style: TextStyle(color: _gold, fontSize: 12, fontWeight: FontWeight.w600)),
        ]),
      ),
    ),
    child: _addressLoading
      ? const Center(child: Padding(
          padding: EdgeInsets.symmetric(vertical: 12),
          child: CircularProgressIndicator(color: _gold, strokeWidth: 2),
        ))
      : Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: _bg,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: _address.isEmpty ? Colors.orange.shade200 : _border),
          ),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(Icons.home_outlined, color: _address.isEmpty ? Colors.orange : _gold, size: 18),
            const SizedBox(width: 10),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(
                _address.isEmpty ? 'No address saved — tap Change to add one' : _address,
                style: TextStyle(
                  color: _address.isEmpty ? Colors.orange.shade700 : _accent,
                  fontSize: 13, fontWeight: FontWeight.w500, height: 1.4),
              ),
              const SizedBox(height: 4),
              const Text('Ensure your address is complete for on-time delivery',
                style: TextStyle(color: _textLight, fontSize: 11)),
            ])),
          ]),
        ),
  );

  // ─── Payment Card ─────────────────────────────────────────────────────────
  Widget _paymentCard() => _card(
    title: 'Payment Method',
    icon: Icons.credit_card_outlined,
    child: Column(children: [
      Row(children: [
        const Icon(Icons.lock_outline, size: 13, color: _textLight),
        const SizedBox(width: 5),
        const Text('Payments are secured and encrypted',
          style: TextStyle(color: _textLight, fontSize: 11)),
      ]),
      const SizedBox(height: 14),
      GestureDetector(
        onTap: () => setState(() => _paymentMethod = 'cod'),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: _paymentMethod == 'cod' ? _gold : _border,
              width: _paymentMethod == 'cod' ? 2 : 1,
            ),
            color: _paymentMethod == 'cod' ? _gold.withOpacity(0.06) : Colors.white,
          ),
          child: Row(children: [
            Container(
              width: 40, height: 40,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: _paymentMethod == 'cod' ? _gold.withOpacity(0.15) : _bg,
              ),
              child: Icon(Icons.payments_outlined,
                color: _paymentMethod == 'cod' ? _gold : _textLight, size: 20),
            ),
            const SizedBox(width: 12),
            const Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Cash on Delivery', style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 14)),
              SizedBox(height: 2),
              Text('Pay when you receive your items', style: TextStyle(color: _textLight, fontSize: 12)),
            ])),
            if (_paymentMethod == 'cod')
              Container(
                width: 20, height: 20,
                decoration: const BoxDecoration(gradient: _goldGrad, shape: BoxShape.circle),
                child: const Icon(Icons.check, color: _primary, size: 13),
              ),
          ]),
        ),
      ),
    ]),
  );

  // ─── Action Buttons ───────────────────────────────────────────────────────
  Widget _actionButtons() => Column(children: [
    // Place Order
    GestureDetector(
      onTap: _placing ? null : _placeOrder,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        width: double.infinity,
        padding: const EdgeInsets.symmetric(vertical: 16),
        decoration: BoxDecoration(
          gradient: _placing ? null : _premiumGrad,
          color: _placing ? const Color(0xFFCED4DA) : null,
          borderRadius: BorderRadius.circular(14),
          boxShadow: _placing ? [] : [BoxShadow(color: _primary.withOpacity(0.3), blurRadius: 12, offset: const Offset(0, 4))],
        ),
        child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          if (_placing)
            const SizedBox(width: 18, height: 18,
              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
          else
            const Icon(Icons.check, color: Colors.white, size: 18),
          const SizedBox(width: 8),
          Text(_placing ? 'Processing...' : 'Place Order',
            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 15, letterSpacing: 0.3)),
        ]),
      ),
    ),
  ]);

  // ─── Shared card wrapper ──────────────────────────────────────────────────
  Widget _card({required String title, required IconData icon, required Widget child, Widget? trailing}) => Container(
    padding: const EdgeInsets.all(18),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.06), blurRadius: 12, offset: const Offset(0, 3))],
    ),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Icon(icon, color: _gold, size: 18),
        const SizedBox(width: 8),
        Text(title, style: const TextStyle(color: _accent, fontSize: 15, fontWeight: FontWeight.w800)),
        const Spacer(),
        if (trailing != null) trailing,
      ]),
      const SizedBox(height: 4),
      Container(width: 36, height: 3, decoration: BoxDecoration(borderRadius: BorderRadius.circular(2), gradient: _goldGrad)),
      const SizedBox(height: 16),
      child,
    ]),
  );

  // ─── Address Modal ────────────────────────────────────────────────────────
  void _showAddressModal() {
    final houseCtrl    = TextEditingController(text: _houseStreet);
    final barangayCtrl = TextEditingController(text: _barangay);
    final cityCtrl     = TextEditingController(text: _city);
    final provinceCtrl = TextEditingController(text: _province);
    final regionCtrl   = TextEditingController(text: _region);
    final zipCtrl      = TextEditingController(text: _zipCode);

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
        child: Container(
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 32),
          decoration: const BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
          ),
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Center(child: Container(width: 40, height: 4,
                decoration: BoxDecoration(color: _border, borderRadius: BorderRadius.circular(2)))),
              const SizedBox(height: 16),
              const Row(children: [
                Icon(Icons.location_on_outlined, color: _gold),
                SizedBox(width: 8),
                Text('Delivery Address', style: TextStyle(color: _accent, fontSize: 16, fontWeight: FontWeight.w700)),
              ]),
              const SizedBox(height: 4),
              const Text('This will be saved to your profile',
                style: TextStyle(color: _textLight, fontSize: 11)),
              const SizedBox(height: 16),
              _addressField('House No. / Street', houseCtrl, Icons.home_outlined),
              const SizedBox(height: 10),
              _addressField('Barangay', barangayCtrl, Icons.location_city_outlined),
              const SizedBox(height: 10),
              _addressField('City / Municipality', cityCtrl, Icons.apartment_outlined),
              const SizedBox(height: 10),
              _addressField('Province', provinceCtrl, Icons.map_outlined),
              const SizedBox(height: 10),
              _addressField('Region', regionCtrl, Icons.public_outlined),
              const SizedBox(height: 10),
              _addressField('ZIP Code', zipCtrl, Icons.markunread_mailbox_outlined,
                keyboardType: TextInputType.number),
              const SizedBox(height: 20),
              Row(children: [
                Expanded(child: GestureDetector(
                  onTap: () => Navigator.pop(context),
                  child: Container(
                    padding: const EdgeInsets.symmetric(vertical: 13),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: _border), color: Colors.white),
                    child: const Center(child: Text('Cancel',
                      style: TextStyle(color: _textLight, fontWeight: FontWeight.w600))),
                  ),
                )),
                const SizedBox(width: 12),
                Expanded(child: GestureDetector(
                  onTap: () async {
                    final hs  = houseCtrl.text.trim();
                    final br  = barangayCtrl.text.trim();
                    final ct  = cityCtrl.text.trim();
                    final pr  = provinceCtrl.text.trim();
                    final rg  = regionCtrl.text.trim();
                    final zp  = zipCtrl.text.trim();
                    // At least city must be filled
                    if (ct.isEmpty) return;
                    setState(() {
                      _houseStreet = hs;
                      _barangay    = br;
                      _city        = ct;
                      _province    = pr;
                      _region      = rg;
                      _zipCode     = zp;
                      _address     = _buildAddress();
                    });
                    Navigator.pop(context);
                    // Save to Supabase in background
                    try {
                      await BuyerService.updateUserAddress(
                        widget.userEmail,
                        houseStreet: hs,
                        barangay:    br,
                        city:        ct,
                        province:    pr,
                        region:      rg,
                        zipCode:     zp,
                      );
                    } catch (_) {}
                  },
                  child: Container(
                    padding: const EdgeInsets.symmetric(vertical: 13),
                    decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(12)),
                    child: const Center(child: Text('Save Address',
                      style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700))),
                  ),
                )),
              ]),
            ]),
          ),
        ),
      ),
    );
  }

  Widget _addressField(String label, TextEditingController ctrl, IconData icon,
      {TextInputType keyboardType = TextInputType.text}) =>
    TextField(
      controller: ctrl,
      keyboardType: keyboardType,
      style: const TextStyle(color: _accent, fontSize: 13),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: _textLight, fontSize: 12),
        prefixIcon: Icon(icon, size: 16, color: _textLight),
        filled: true, fillColor: _bg,
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        isDense: true,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide(color: _border)),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide(color: _border)),
        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: _gold, width: 1.5)),
      ),
    );

  // ─── Place Order ──────────────────────────────────────────────────────────
  void _placeOrder() {
    if (_paymentMethod.isEmpty) return;
    setState(() => _placing = true);
    _doPlaceOrder();
  }

  Future<void> _doPlaceOrder() async {
    if (_address.trim().isEmpty) {
      setState(() => _placing = false);
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Please add a delivery address before placing your order.'),
        backgroundColor: Colors.orange,
        behavior: SnackBarBehavior.floating,
      ));
      return;
    }
    try {
      for (final item in widget.items) {
        // Resolve productId — try numeric id first, then look up by name
        int resolvedProductId = item.productId ?? int.tryParse(item.id) ?? 0;
        String resolvedSellerEmail = '';

        if (resolvedProductId == 0) {
          // Look up product by name to get real id + seller_email
          try {
            final res = await BuyerService.findProductByName(item.name);
            if (res != null) {
              resolvedProductId = res['id'] as int? ?? 0;
              resolvedSellerEmail = res['seller_email'] as String? ?? '';
            }
          } catch (_) {}
        }

        await BuyerService.placeOrder(
          email:         widget.userEmail,
          name:          item.name,
          productId:     resolvedProductId,
          totalPrice:    item.subtotal + item.shippingFee,
          quantity:      item.quantity,
          address:       _address,
          sellerEmail:   resolvedSellerEmail,
          paymentMethod: _paymentMethod,
          color:         item.color,
          size:          item.size,
          image:         item.image,
          shippingFee:   item.shippingFee,
        );
      }
      if (!mounted) return;
      setState(() => _placing = false);
      _showSuccessDialog();
    } catch (e) {
      if (!mounted) return;
      setState(() => _placing = false);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Failed to place order: $e'),
        backgroundColor: Colors.red.shade600,
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ));
    }
  }

  void _showSuccessDialog() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => Dialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Container(
              width: 72, height: 72,
              decoration: BoxDecoration(gradient: _goldGrad, shape: BoxShape.circle,
                boxShadow: [BoxShadow(color: _gold.withOpacity(0.4), blurRadius: 16)]),
              child: const Icon(Icons.check, color: _primary, size: 36),
            ),
            const SizedBox(height: 18),
            const Text('Order Placed!',
              style: TextStyle(color: _accent, fontSize: 22, fontWeight: FontWeight.w800)),
            const SizedBox(height: 8),
            const Text('Your order has been placed successfully.',
              style: TextStyle(color: _textLight, fontSize: 13), textAlign: TextAlign.center),
            const SizedBox(height: 24),
            // Go to Orders
            GestureDetector(
              onTap: () {
                Navigator.pop(context);
                Navigator.pushAndRemoveUntil(context,
                  MaterialPageRoute(builder: (_) => BuyerOrdersPage(userEmail: widget.userEmail)),
                  (_) => false);
              },
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(vertical: 14),
                decoration: BoxDecoration(gradient: _premiumGrad, borderRadius: BorderRadius.circular(12)),
                child: const Center(child: Text('View My Orders',
                  style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 14))),
              ),
            ),
            const SizedBox(height: 10),
            // Continue Shopping
            GestureDetector(
              onTap: () {
                Navigator.pop(context);
                Navigator.pushAndRemoveUntil(context,
                  MaterialPageRoute(builder: (_) => BuyerHomePage(userEmail: widget.userEmail)),
                  (_) => false);
              },
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(vertical: 14),
                decoration: BoxDecoration(borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: _border), color: Colors.white),
                child: const Center(child: Text('Continue Shopping',
                  style: TextStyle(color: _accent, fontWeight: FontWeight.w600, fontSize: 14))),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}
