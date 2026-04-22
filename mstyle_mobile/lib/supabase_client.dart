import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';

// ─── Supabase singleton ───────────────────────────────────────────────────────
const String supabaseUrl  = 'https://vydcnhmgqovketjqvpoe.supabase.co';
const String supabaseAnon = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ5ZGNuaG1ncW92a2V0anF2cG9lIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYyMjc4MDMsImV4cCI6MjA5MTgwMzgwM30.wMFqPcuq_l19zr61-BhRUtGWJyiKa0Rq5300tGntiyE';
const String supabaseServiceRole = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ5ZGNuaG1ncW92a2V0anF2cG9lIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NjIyNzgwMywiZXhwIjoyMDkxODAzODAzfQ.N7gBt1F2bLulJkD2Uh1nXaTvLkV2fiEAFvnN3qVLYAY';

// Access the client anywhere: supabase.auth, supabase.from(...)
final supabase = Supabase.instance.client;

// Admin helper — queries the Supabase REST API directly with the service role
// key, bypassing RLS. Returns the parsed JSON list or throws on error.
Future<List<Map<String, dynamic>>> supabaseAdminSelect({
  required String table,
  required String select,
  Map<String, String> filters = const {},
  int? limit,
}) async {
  final params = <String, String>{'select': select};
  filters.forEach((k, v) => params[k] = 'eq.$v');
  if (limit != null) params['limit'] = '$limit';

  final uri = Uri.parse('$supabaseUrl/rest/v1/$table').replace(queryParameters: params);
  final resp = await http.get(uri, headers: {
    'apikey':        supabaseServiceRole,
    'Authorization': 'Bearer $supabaseServiceRole',
    'Accept':        'application/json',
  });

  if (resp.statusCode != 200) {
    throw Exception('supabaseAdminSelect $table: ${resp.statusCode} ${resp.body}');
  }
  final decoded = jsonDecode(resp.body);
  if (decoded is List) {
    return List<Map<String, dynamic>>.from(decoded);
  }
  return [];
}

/// Admin upsert — inserts or updates a row, bypassing RLS.
Future<void> supabaseAdminUpsert({
  required String table,
  required Map<String, dynamic> data,
  String? onConflict,
}) async {
  final uri = Uri.parse('$supabaseUrl/rest/v1/$table');
  final headers = <String, String>{
    'apikey':        supabaseServiceRole,
    'Authorization': 'Bearer $supabaseServiceRole',
    'Content-Type':  'application/json',
    'Prefer':        onConflict != null
        ? 'resolution=merge-duplicates,return=minimal'
        : 'return=minimal',
  };
  if (onConflict != null) {
    headers['Prefer'] = 'resolution=merge-duplicates,return=minimal';
  }
  final resp = await http.post(uri,
    headers: headers,
    body: jsonEncode(data),
  );
  if (resp.statusCode != 200 && resp.statusCode != 201 && resp.statusCode != 204) {
    throw Exception('supabaseAdminUpsert $table: ${resp.statusCode} ${resp.body}');
  }
}

/// Admin delete — deletes rows matching filters, bypassing RLS.
Future<void> supabaseAdminDelete({
  required String table,
  required Map<String, String> filters,
}) async {
  final params = <String, String>{};
  filters.forEach((k, v) => params[k] = 'eq.$v');

  final uri = Uri.parse('$supabaseUrl/rest/v1/$table').replace(queryParameters: params);
  final resp = await http.delete(uri, headers: {
    'apikey':        supabaseServiceRole,
    'Authorization': 'Bearer $supabaseServiceRole',
    'Prefer':        'return=minimal',
  });
  if (resp.statusCode != 200 && resp.statusCode != 204) {
    throw Exception('supabaseAdminDelete $table: ${resp.statusCode} ${resp.body}');
  }
}
