import 'dart:math';
import 'package:flutter/material.dart';
import '../core/theme/jenny_colors.dart';

class AnimatedGradientBackground extends StatefulWidget {
  final Widget child;
  final List<Color>? colors;

  const AnimatedGradientBackground({super.key, required this.child, this.colors});

  @override
  State<AnimatedGradientBackground> createState() =>
      _AnimatedGradientBackgroundState();
}

class _AnimatedGradientBackgroundState extends State<AnimatedGradientBackground>
    with TickerProviderStateMixin {
  late final AnimationController _controller;
  late final AnimationController _blobController;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      duration: const Duration(seconds: 8),
      vsync: this,
    )..repeat(reverse: true);
    _blobController = AnimationController(
      duration: const Duration(seconds: 12),
      vsync: this,
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    _blobController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = widget.colors ??
        [
          JennyColors.background,
          JennyColors.primaryLight.withValues(alpha: 0.3),
          JennyColors.aiHighlight.withValues(alpha: 0.4),
          JennyColors.background,
        ];

    return AnimatedBuilder(
      animation: Listenable.merge([_controller, _blobController]),
      builder: (context, _) {
        return Stack(
          children: [
            Container(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment(
                    -1 + _controller.value * 2,
                    -1 + _controller.value,
                  ),
                  end: Alignment(
                    1 - _controller.value,
                    1 - _controller.value * 0.5,
                  ),
                  colors: colors,
                ),
              ),
            ),
            ..._buildBlobs(),
            widget.child,
          ],
        );
      },
    );
  }

  List<Widget> _buildBlobs() {
    return [
      _buildBlob(
        top: -60 + _blobController.value * 30,
        right: -40 + _blobController.value * 20,
        size: 200,
        color: JennyColors.primary.withValues(alpha: 0.08),
      ),
      _buildBlob(
        bottom: -80 + _blobController.value * 40,
        left: -60 + _blobController.value * 30,
        size: 250,
        color: JennyColors.aiHighlight.withValues(alpha: 0.15),
      ),
      _buildBlob(
        top: 200 + _blobController.value * 50,
        left: 100 - _blobController.value * 20,
        size: 150,
        color: JennyColors.primaryLight.withValues(alpha: 0.1),
      ),
    ];
  }

  Widget _buildBlob({
    double? top,
    double? bottom,
    double? left,
    double? right,
    required double size,
    required Color color,
  }) {
    return Positioned(
      top: top,
      bottom: bottom,
      left: left,
      right: right,
      child: Transform.rotate(
        angle: _blobController.value * pi * 0.3,
        child: Container(
          width: size,
          height: size,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: color,
          ),
        ),
      ),
    );
  }
}
