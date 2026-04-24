import 'dart:convert';
import 'package:http/http.dart' as http;

class PsgcService {
  static const _base = 'https://psgc.cloud/api';

  static Future<List<String>> getRegions() async {
    final res = await http.get(Uri.parse('$_base/regions'));
    if (res.statusCode != 200) return [];
    final List data = jsonDecode(res.body);
    data.sort((a, b) => (a['name'] as String).toLowerCase().compareTo((b['name'] as String).toLowerCase()));
    return data.map<String>((e) => e['name'] as String).toList();
  }

  static Future<List<Map<String, String>>> getRegionsWithCode() async {
    final res = await http.get(Uri.parse('$_base/regions'));
    if (res.statusCode != 200) return [];
    final List data = jsonDecode(res.body);
    data.sort((a, b) => (a['name'] as String).toLowerCase().compareTo((b['name'] as String).toLowerCase()));
    return data.map<Map<String, String>>((e) => {
      'code': e['code'].toString(),
      'name': e['name'] as String,
    }).toList();
  }

  static Future<List<Map<String, String>>> getProvinces(String regionCode) async {
    final res = await http.get(Uri.parse('$_base/regions/$regionCode/provinces'));
    if (res.statusCode != 200) return [];
    final List data = jsonDecode(res.body);
    data.sort((a, b) => (a['name'] as String).toLowerCase().compareTo((b['name'] as String).toLowerCase()));
    return data.map<Map<String, String>>((e) => {
      'code': e['code'].toString(),
      'name': e['name'] as String,
    }).toList();
  }

  static Future<List<Map<String, String>>> getCities(String provinceCode) async {
    final res = await http.get(Uri.parse('$_base/provinces/$provinceCode/cities-municipalities'));
    if (res.statusCode != 200) return [];
    final List data = jsonDecode(res.body);
    data.sort((a, b) => (a['name'] as String).toLowerCase().compareTo((b['name'] as String).toLowerCase()));
    return data.map<Map<String, String>>((e) => {
      'code': e['code'].toString(),
      'name': e['name'] as String,
    }).toList();
  }

  static Future<List<String>> getBarangays(String cityCode) async {
    final res = await http.get(Uri.parse('$_base/cities-municipalities/$cityCode/barangays'));
    if (res.statusCode != 200) return [];
    final List data = jsonDecode(res.body);
    data.sort((a, b) => (a['name'] as String).toLowerCase().compareTo((b['name'] as String).toLowerCase()));
    return data.map<String>((e) => e['name'] as String).toList();
  }
}
