import 'package:flutter_test/flutter_test.dart';
import 'package:jenny_app/app.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

void main() {
  testWidgets('Jenny app renders', (WidgetTester tester) async {
    await tester.pumpWidget(const ProviderScope(child: JennyApp()));
    expect(find.text('Jenny'), findsOneWidget);
  });
}
