import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:supabase_flutter/supabase_flutter.dart' show FileOptions;
import 'buyer_service.dart';
import 'supabase_client.dart' show supabase, supabaseUrl, supabaseServiceRole;
import 'package:http/http.dart' as http;

const Color _primary   = Color(0xFF1a1a1a);
const Color _accent    = Color(0xFF2c3e50);
const Color _gold      = Color(0xFFd4af37);
const Color _goldLight = Color(0xFFF4D03F);
const Color _textLight = Color(0xFF6c757d);
const Color _bg        = Color(0xFFF8F9FA);
const Color _border    = Color(0xFFE9ECEF);

/// Shows the review bottom sheet. Call this from anywhere.
Future<void> showReviewBottomSheet(
  BuildContext context, {
  required Map<String, dynamic> order,
  required String userEmail,
  VoidCallback? onSubmitted,
}) {
  return showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (_) => _ReviewBottomSheet(
      order: order,
      userEmail: userEmail,
      onSubmitted: onSubmitted,
    ),
  );
}

// ─── Bottom Sheet Widget ──────────────────────────────────────────────────────
class _ReviewBottomSheet extends StatefulWidget {
  final Map<String, dynamic> order;
  final String userEmail;
  final VoidCallback? onSubmitted;

  const _ReviewBottomSheet({
    required this.order,
    required this.userEmail,
    this.onSubmitted,
  });

  @override
  State<_ReviewBottomSheet> createState() => _ReviewBottomSheetState();
}

class _ReviewBottomSheetState extends State<_ReviewBottomSheet> {
  int _rating = 0;
  final _reviewCtrl = TextEditingController();
  final _picker = ImagePicker();
  // Each entry holds the XFile and its pre-loaded bytes (works on web + mobile)
  final List<({XFile xfile, Uint8List bytes})> _images = [];
  bool _submitting = false;

  static const int _maxImages = 5;

  @override
  void dispose() {
    _reviewCtrl.dispose();
    super.dispose();
  }

  String get _orderName => widget.order['name'] as String? ?? 'Product';
  int get _orderId      => widget.order['id'] as int? ?? 0;
  int get _productId    => widget.order['product_id'] as int? ?? 0;
  String get _sellerEmail => widget.order['seller_email'] as String? ?? '';

  // ── Image Picker ────────────────────────────────────────────────────────
  Future<void> _pickImages() async {
    final remaining = _maxImages - _images.length;
    if (remaining <= 0) return;

    final picked = await _picker.pickMultiImage(imageQuality: 80, limit: remaining);
    if (picked.isNotEmpty) {
      for (final xfile in picked) {
        final bytes = await xfile.readAsBytes();
        setState(() => _images.add((xfile: xfile, bytes: bytes)));
      }
    }
  }

  Future<void> _pickFromCamera() async {
    if (_images.length >= _maxImages) return;
    final photo = await _picker.pickImage(source: ImageSource.camera, imageQuality: 80);
    if (photo != null) {
      final bytes = await photo.readAsBytes();
      setState(() => _images.add((xfile: photo, bytes: bytes)));
    }
  }

  void _removeImage(int index) => setState(() => _images.removeAt(index));

  // ── Upload images to Supabase Storage ───────────────────────────────────
  // Uses the service-role key via REST to bypass storage RLS policies.
  // Each image gets a unique path: reviews/<orderId>_<index>_<timestamp>.<ext>
  Future<List<String>> _uploadImages() async {
    final urls = <String>[];
    final bucket = 'review-images';

    for (int i = 0; i < _images.length; i++) {
      final entry = _images[i];
      try {
        final rawExt = entry.xfile.name.contains('.')
            ? entry.xfile.name.split('.').last.toLowerCase()
            : 'jpg';
        final ext = ['jpg', 'jpeg', 'png', 'webp', 'gif'].contains(rawExt) ? rawExt : 'jpg';
        final ts  = DateTime.now().millisecondsSinceEpoch + i; // unique per iteration
        final path = 'reviews/${_orderId}_${i}_$ts.$ext';

        debugPrint('Uploading image $i → bucket=$bucket path=$path size=${entry.bytes.length}B');

        // Upload via REST with service-role key (bypasses storage RLS)
        final uploadUri = Uri.parse(
          '$supabaseUrl/storage/v1/object/$bucket/$path',
        );
        final uploadResp = await http.post(
          uploadUri,
          headers: {
            'Authorization': 'Bearer $supabaseServiceRole',
            'apikey':        supabaseServiceRole,
            'Content-Type':  'image/$ext',
            'x-upsert':      'true',
          },
          body: entry.bytes,
        );

        debugPrint('Upload response [${uploadResp.statusCode}]: ${uploadResp.body}');

        if (uploadResp.statusCode == 200 || uploadResp.statusCode == 201) {
          // Build public URL
          final publicUrl = '$supabaseUrl/storage/v1/object/public/$bucket/$path';
          urls.add(publicUrl);
          debugPrint('✅ Review image uploaded: $publicUrl');
        } else {
          debugPrint('❌ Review image upload failed [${uploadResp.statusCode}]: ${uploadResp.body}');
          // Surface the error so the user knows something went wrong
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text('Photo ${i + 1} upload failed (${uploadResp.statusCode}): ${uploadResp.body}'),
                backgroundColor: Colors.orange.shade700,
                behavior: SnackBarBehavior.floating,
              ),
            );
          }
        }
      } catch (e, st) {
        debugPrint('❌ Review image upload error (index $i): $e\n$st');
      }
    }

    debugPrint('_uploadImages done — ${urls.length}/${_images.length} uploaded');
    return urls;
  }

  // ── Submit ───────────────────────────────────────────────────────────────
  Future<void> _submit() async {
    if (_rating == 0) return;
    setState(() => _submitting = true);

    try {
      final imageUrls = await _uploadImages();

      // Warn if some images failed to upload but don't block submission
      if (_images.isNotEmpty && imageUrls.isEmpty) {
        debugPrint('Warning: all image uploads failed — submitting review without images');
      }

      await BuyerService.submitReview(
        orderId:       _orderId,
        productId:     _productId,
        customerEmail: widget.userEmail,
        sellerEmail:   _sellerEmail,
        rating:        _rating,
        reviewText:    _reviewCtrl.text.trim(),
        reviewImages:  imageUrls,
      );

      if (mounted) {
        Navigator.pop(context);
        widget.onSubmitted?.call();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(imageUrls.length < _images.length && _images.isNotEmpty
                ? 'Review submitted! (${imageUrls.length}/${_images.length} photos uploaded)'
                : 'Review submitted! Thank you.'),
            backgroundColor: _primary,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          ),
        );
      }
    } catch (e) {
      debugPrint('Review submit error: $e');
      setState(() => _submitting = false);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('Failed to submit review. Please try again.'),
            backgroundColor: Colors.red.shade700,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          ),
        );
      }
    }
  }

  // ── Build ────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.of(context).viewInsets.bottom;

    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      padding: EdgeInsets.fromLTRB(20, 0, 20, 20 + bottomInset),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // ── Handle bar ──────────────────────────────────────────────
            Center(
              child: Container(
                margin: const EdgeInsets.only(top: 12, bottom: 16),
                width: 40, height: 4,
                decoration: BoxDecoration(
                  color: _border,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),

            // ── Header ──────────────────────────────────────────────────
            Row(children: [
              Container(
                width: 40, height: 40,
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [_gold, _goldLight],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Icon(Icons.star_rounded, color: Colors.white, size: 22),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('Leave a Review',
                    style: TextStyle(color: _accent, fontWeight: FontWeight.w800, fontSize: 17)),
                  Text(_orderName,
                    style: const TextStyle(color: _textLight, fontSize: 12),
                    maxLines: 1, overflow: TextOverflow.ellipsis),
                ]),
              ),
              IconButton(
                onPressed: () => Navigator.pop(context),
                icon: const Icon(Icons.close, color: _textLight),
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints(),
              ),
            ]),

            const SizedBox(height: 24),

            // ── Star Rating ──────────────────────────────────────────────
            Center(
              child: Column(children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: List.generate(5, (i) => GestureDetector(
                    onTap: () => setState(() => _rating = i + 1),
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 150),
                      padding: const EdgeInsets.symmetric(horizontal: 5),
                      child: Icon(
                        i < _rating ? Icons.star_rounded : Icons.star_outline_rounded,
                        color: i < _rating ? _gold : _border,
                        size: 42,
                      ),
                    ),
                  )),
                ),
                const SizedBox(height: 6),
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 200),
                  child: Text(
                    _rating == 0 ? 'Tap a star to rate' : _ratingLabel(_rating),
                    key: ValueKey(_rating),
                    style: TextStyle(
                      color: _rating == 0 ? _textLight : _gold,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ]),
            ),

            const SizedBox(height: 20),

            // ── Review Text ──────────────────────────────────────────────
            const Text('Your Review',
              style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
            const SizedBox(height: 8),
            TextField(
              controller: _reviewCtrl,
              maxLines: 4,
              maxLength: 500,
              style: const TextStyle(fontSize: 14, color: _accent),
              decoration: InputDecoration(
                hintText: 'Share your experience with this product...',
                hintStyle: const TextStyle(color: _textLight, fontSize: 13),
                filled: true,
                fillColor: _bg,
                counterStyle: const TextStyle(color: _textLight, fontSize: 11),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(14),
                  borderSide: const BorderSide(color: _border),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(14),
                  borderSide: const BorderSide(color: _border),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(14),
                  borderSide: const BorderSide(color: _gold, width: 2),
                ),
              ),
            ),

            const SizedBox(height: 16),

            // ── Photo Upload ─────────────────────────────────────────────
            Row(children: [
              const Text('Add Photos',
                style: TextStyle(color: _accent, fontWeight: FontWeight.w700, fontSize: 13)),
              const SizedBox(width: 6),
              Text('(${_images.length}/$_maxImages)',
                style: const TextStyle(color: _textLight, fontSize: 12)),
            ]),
            const SizedBox(height: 8),

            SizedBox(
              height: 90,
              child: ListView(
                scrollDirection: Axis.horizontal,
                children: [
                  // Existing images
                  ..._images.asMap().entries.map((entry) => _imageThumbnail(entry.key, entry.value.bytes)),

                  // Add buttons (only if under limit)
                  if (_images.length < _maxImages) ...[
                    _addImageButton(
                      icon: Icons.photo_library_outlined,
                      label: 'Gallery',
                      onTap: _pickImages,
                    ),
                    const SizedBox(width: 8),
                    _addImageButton(
                      icon: Icons.camera_alt_outlined,
                      label: 'Camera',
                      onTap: _pickFromCamera,
                    ),
                  ],
                ],
              ),
            ),

            const SizedBox(height: 24),

            // ── Submit Button ────────────────────────────────────────────
            SizedBox(
              width: double.infinity,
              height: 52,
              child: ElevatedButton(
                onPressed: (_submitting || _rating == 0) ? null : _submit,
                style: ElevatedButton.styleFrom(
                  backgroundColor: _rating == 0 ? _border : _primary,
                  foregroundColor: Colors.white,
                  disabledBackgroundColor: _border,
                  elevation: _rating == 0 ? 0 : 4,
                  shadowColor: _primary.withOpacity(0.3),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                ),
                child: _submitting
                  ? const SizedBox(
                      width: 20, height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                      const Icon(Icons.send_rounded, size: 18),
                      const SizedBox(width: 8),
                      Text(
                        _rating == 0 ? 'Select a rating first' : 'Submit Review',
                        style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
                      ),
                    ]),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── Helpers ──────────────────────────────────────────────────────────────
  Widget _imageThumbnail(int index, Uint8List bytes) => Container(
    margin: const EdgeInsets.only(right: 8),
    child: Stack(children: [
      ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: Image.memory(
          bytes,
          width: 80, height: 80,
          fit: BoxFit.cover,
        ),
      ),
      Positioned(
        top: 4, right: 4,
        child: GestureDetector(
          onTap: () => _removeImage(index),
          child: Container(
            width: 22, height: 22,
            decoration: const BoxDecoration(
              color: Colors.black54,
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.close, color: Colors.white, size: 13),
          ),
        ),
      ),
    ]),
  );

  Widget _addImageButton({
    required IconData icon,
    required String label,
    required VoidCallback onTap,
  }) => GestureDetector(
    onTap: onTap,
    child: Container(
      width: 80, height: 80,
      margin: const EdgeInsets.only(right: 8),
      decoration: BoxDecoration(
        color: _bg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _border, width: 1.5),
      ),
      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        Icon(icon, color: _textLight, size: 24),
        const SizedBox(height: 4),
        Text(label, style: const TextStyle(color: _textLight, fontSize: 10, fontWeight: FontWeight.w500)),
      ]),
    ),
  );

  String _ratingLabel(int r) {
    switch (r) {
      case 1: return 'Poor';
      case 2: return 'Fair';
      case 3: return 'Good';
      case 4: return 'Very Good';
      case 5: return 'Excellent!';
      default: return '';
    }
  }
}
