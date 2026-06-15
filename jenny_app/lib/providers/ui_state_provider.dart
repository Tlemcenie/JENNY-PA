import 'package:flutter_riverpod/flutter_riverpod.dart';

class UiState {
  final bool sidebarExpanded;
  final int selectedNavIndex;
  final bool isSearchOpen;

  const UiState({
    this.sidebarExpanded = false,
    this.selectedNavIndex = 0,
    this.isSearchOpen = false,
  });

  UiState copyWith({
    bool? sidebarExpanded,
    int? selectedNavIndex,
    bool? isSearchOpen,
  }) =>
      UiState(
        sidebarExpanded: sidebarExpanded ?? this.sidebarExpanded,
        selectedNavIndex: selectedNavIndex ?? this.selectedNavIndex,
        isSearchOpen: isSearchOpen ?? this.isSearchOpen,
      );
}

class UiStateNotifier extends StateNotifier<UiState> {
  UiStateNotifier() : super(const UiState());

  void toggleSidebar() {
    state = state.copyWith(sidebarExpanded: !state.sidebarExpanded);
  }

  void setSidebarExpanded(bool expanded) {
    state = state.copyWith(sidebarExpanded: expanded);
  }

  void setNavIndex(int index) {
    state = state.copyWith(selectedNavIndex: index);
  }

  void toggleSearch() {
    state = state.copyWith(isSearchOpen: !state.isSearchOpen);
  }
}

final uiStateProvider = StateNotifierProvider<UiStateNotifier, UiState>((ref) {
  return UiStateNotifier();
});
